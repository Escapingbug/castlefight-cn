from abc import ABC, abstractmethod
import asyncio
import configparser
import logging
import re
from typing import Any, Callable, Coroutine, Dict, Iterable, List, Tuple, cast
import tomli
from pathlib import Path
from glob import glob
from configparser import ConfigParser
import concurrent.futures

# must use v2, or else we will get pretty bad result
from translatepy.translators.google import GoogleTranslateV2

# see: https://github.com/encode/httpx/issues/914
import platform

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

with open(Path(__file__).parent.joinpath("template.toml"), "rb") as f:
    TEMPLATE: Dict[str, List[Dict[str, str]]] = tomli.load(f)

F_SID_KEY_RE = re.compile('FdrFJe":"(.*?)"')
BL_KEY_RE = re.compile('cfb2h":"(.*?)"')


class PartTranslator(ABC):
    @abstractmethod
    async def translate(self, text: str) -> str | None:
        pass


class GooglePartTranslator(PartTranslator):
    def __init__(self, max_workers: int = 8):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.translator = GoogleTranslateV2()

    async def translate(self, text: str) -> str:
        def do_translate():
            return self.translator.translate(text, "zh-CN", "en").result

        return await asyncio.get_running_loop().run_in_executor(
            self.executor, do_translate
        )


class TemplateBasedMixin:
    def __init__(self, template_key: str, max_workers: int = 8):
        self.translations: List[Tuple[re.Pattern, str]] = []
        self.executor = concurrent.futures.ProcessPoolExecutor(max_workers=max_workers)
        self.setup_translations(template_key=template_key)

    def setup_translations(self, template_key: str):
        for trans in TEMPLATE.get(template_key) or []:
            self.translations.append(
                (re.compile(trans["regex"]), trans["content"])
            )

    @staticmethod
    def translate_zipped(zipped: Tuple[Tuple[re.Pattern, str], str]) -> str | None:
        regex = zipped[0][0]
        content = zipped[0][1]
        text = zipped[1]
        if regex.fullmatch(text):
            return regex.sub(content, text)

    async def translate(self, text: str) -> str | None:
        results = self.executor.map(TemplateBasedMixin.translate_zipped, zip(self.translations, text))
        for result in results:
            if result is not None:
                return result

    def rewrite(self, text: str) -> str:
        # rewrite can only be sequential
        for regex, content in self.translations:
            text = regex.sub(content, text)
        return text
    

class TemplatePartTranslator(PartTranslator, TemplateBasedMixin):
    def __init__(self, max_workers: int = 8):
        TemplateBasedMixin.__init__(self, "translate", max_workers=max_workers)

    async def translate(self, text: str) -> str | None:
        return await TemplateBasedMixin.translate(self, text)


class TemplatePreRewritter(TemplateBasedMixin):
    """
    Rewrite but works on direct source language, based
    on template patterns.

    This should work for known property and pattern such as
    armor or attack type.
    """

    def __init__(self):
        super().__init__("pre_rewrite")

    def rewrite(self, text: str) -> str:
        """
        :param text: the raw input text (escape strings inside)
        :returns: rewritten result
        """
        return super().rewrite(text)


class MultiPartTranslator:
    translation_providers: List[PartTranslator] = [
        TemplatePartTranslator(),
        GooglePartTranslator(),
    ]

    @staticmethod
    async def translation_task(text_input: str, escape_strings: List[str]) -> str:
        """
        translates the text_input which contains escape_string to the final result
        :param text_input: the input to translate, should contain "|" s as separators,
            such as: AAAA|BBBB
        :param escape_strings: the escape strings that behind each "|" separator,
            an example would be ["|c0000ffff"]
        :returns: the translated string with correct escape strings inserted,
            like AAAA|c0000ffffBBBB
        """
        logger.debug(f"translating task translating {text_input}")
        if len(text_input) > 0:
            # We can make this concurrent as well. But in that case, API call cannot
            # be avoided. Since we are using public API, maybe we should not do that?
            result = None
            for translator in MultiPartTranslator.translation_providers:
                result = await translator.translate(text_input)
                if result is not None:
                    break
            result = cast(str, result)
        else:
            result = ""
        translation_result = result.split("|")
        assert (
            len(translation_result) == len(escape_strings) + 1
        ), f"incorrect translation result: {translation_result} escape string {escape_strings} {text_input}"
        # merge escape_strings back
        final_result = [translation_result[0]]
        for i in range(1, len(translation_result)):
            final_result.append(escape_strings[i - 1])
            final_result.append(translation_result[i])
        return "".join(final_result)

    @staticmethod
    async def translate(string: str) -> str:
        """
        A single line might contain several escape chars such as |n or |cXXXX that could
        interfere the translation.
        This function splits those parts and translate each parts then merge them together
        to achieve better translation result.

        :param string: a single string that is to be translated, might contain escape characters
        :returns: a translated string, with escape characters merged
        """
        escapes = "|"
        parts = string.split(escapes)

        # only supported escapes:
        # 1. |n ==> this should separate sentences
        # 2. |r or |cXXXXXXXX: this should not separate sentence, but add "|".

        # According to my experiment with Google Translate, "|" character is a
        # less semantic-influencing separator.

        result_tasks: List[asyncio.Task[Any]] = []
        escape_strings = (
            []
        )  # for |r and |c, record the exact escape string of each inserted "|"
        texts_to_translate = [parts[0]]
        i = 1
        while i < len(parts):
            part = parts[i]
            if part[0] == "n":
                text_input = "|".join(texts_to_translate)
                result_tasks.append(
                    asyncio.create_task(
                        MultiPartTranslator.translation_task(
                            text_input=text_input, escape_strings=escape_strings
                        )
                    )
                )

                texts_to_translate = [part[1:]]
                escape_strings: List[str] = []
            elif part[0] == "c" or part[0] == "r":
                start_idx = 1 if part[0] == "r" else 9
                texts_to_translate.append(part[start_idx:])
                escape_strings.append("|" + part[:start_idx])
            else:
                raise Exception(f"unsupported escape string found: {'|' + part} whole sentence {string}")
            i += 1
        if len(texts_to_translate) > 0:
            text_input = "|".join(texts_to_translate)
            result_tasks.append(
                asyncio.create_task(MultiPartTranslator.translation_task(text_input, escape_strings))
            )
        result: List[str] = [await task for task in result_tasks]
        return "|n".join(result)


class ShortcutAdjust:
    """
    Adjusts the shortcut hint format.

    Some of the descriptions in English might use the colored letter
    to tell one the shortcut of such item/spell, etc.

    Such as, **B**uild (** means colored).
    In this case, during the translation, it should be re-formatted into
    Build (**B**) to allow automatic translation work properly.

    To check if this case happans, we use two rules:

    1. the colored letter is a single letter
    2. the colored letter is not a single token (no space wrapping it)
    """

    shortcut_hint_regex = re.compile("\\|c[0-9a-f]{8}([a-zA-Z0-9])\\|r")

    @staticmethod
    def not_wrapped_by_space(string: str, start: int, end: int):
        return (
            start >= 1
            and end < len(string) - 1
            and (string[start] != " " or string[end] != " ")
        )

    @staticmethod
    def find_shortcut_hints(string: str) -> List[re.Match]:
        returns = []
        for possible_hint in ShortcutAdjust.shortcut_hint_regex.finditer(string):
            if ShortcutAdjust.not_wrapped_by_space(
                string, possible_hint.start(), possible_hint.end()
            ):
                returns.append(possible_hint)
        return returns

    @staticmethod
    def adjust(string: str) -> str:
        matched = ShortcutAdjust.find_shortcut_hints(string)
        if len(matched) == 0:
            return string

        for each_match in matched:
            clean_word_pieces = []
            original_word_pieces = []
            if each_match.start() > 1 and string[each_match.start() - 1] != " ":
                pre_piece = string[: each_match.start()].rsplit(maxsplit=1)[-1]
                clean_word_pieces.append(pre_piece)
                original_word_pieces.append(pre_piece)
            clean_word_pieces.append(each_match.group(1))
            original_word_pieces.append(each_match.group(0))
            if each_match.end() < len(string) - 1 and string[each_match.end() + 1] != " ":
                post_piece = string[each_match.end() :].split(maxsplit=1)[0]
                clean_word_pieces.append(post_piece)
                original_word_pieces.append(post_piece)

            original_word = "".join(original_word_pieces)
            clean_word = "".join(clean_word_pieces)

        # "[]" gives much better result in google translation (avoid semantic problem)
            string = string.replace(original_word, f"[{each_match.group(0)}] {clean_word} ")
        return string


class TemplateRewritter(TemplateBasedMixin):
    def __init__(self) -> None:
        super().__init__("rewrite")

    def rewrite(self, string: str) -> str:
        return super().rewrite(string)


class TranslationPipeline:
    def __init__(self) -> None:
        self.shortcut_adjust = ShortcutAdjust
        self.translator = MultiPartTranslator
        self.template_pre_rewritter = TemplatePreRewritter()
        self.template_rewritter = TemplateRewritter()

    async def translate(self, string: str) -> str:
        # Interestingly, the exported ini file got some fields wrapped
        # with quotes but some not.
        # During translation, the quotes are being respected,
        # so we deal with that by stripping then adding in the end.
        quoting: Callable[[str], str] = (
            (lambda x: f'"{x}"') if string[0] == '"' else lambda x: x
        )
        string = string.strip('"')
        string = self.template_pre_rewritter.rewrite(string)
        string = self.shortcut_adjust.adjust(string)
        string = await self.translator.translate(string)
        string = self.template_rewritter.rewrite(string)
        return quoting(string)


TRANSLATION_PIPELINE = TranslationPipeline()


class StringsFile:
    def __init__(
        self, path: Path | str, out_dir: Path | str, translation_keys: Iterable[str]
    ) -> None:
        self.path: Path = path if type(path) is Path else Path(path)
        out_d: Path = out_dir if type(out_dir) is Path else Path(out_dir)
        self.out_path = out_d.joinpath(self.path.name)
        self.parser = ConfigParser(interpolation=None)
        self.parser.optionxform = lambda option: option  # type: ignore
        self.errored = False
        try:
            self.parser.read(path, encoding="utf8")
        except configparser.DuplicateSectionError:
            self.errored = True
        self.translation_keys = set(translation_keys)

    async def translate(self):
        if self.errored:
            return
        logger.debug(f"begin translating {self.path}")
        set_task: List[
            Tuple[str, str, asyncio.Task[str]]
        ] = []  # (section_name, key, task)
        for section_name in self.parser.sections():
            section = self.parser[section_name]
            for key in section.keys():
                if key in self.translation_keys:
                    logger.debug(
                        f"pending translation({section}[{key}]): {section[key]}"
                    )
                    set_task.append(
                        (
                            section_name,
                            key,
                            asyncio.create_task(
                                TRANSLATION_PIPELINE.translate(section[key])
                            ),
                        )
                    )
        for section_name, key, task in set_task:
            result = await task
            logger.debug(f"translation {section_name}[{key}] result {result}")
            self.parser[section_name][key] = result

    def save(self):
        if self.errored:
            logger.error(f"{self.path} is errored, ignoring...")
            return
        with open(self.out_path, "w", encoding="utf8") as f:
            self.parser.write(f)


class MapDir:
    def __init__(self, path: Path, out_dir: Path) -> None:
        self.txt_files = glob(f"{path}/**/*strings.txt")
        self.out_dir = out_dir

    async def translate(self):
        tasks: List[Tuple[StringsFile, asyncio.Task]] = []
        for file_path_str in self.txt_files:
            logger.info(f"Translating {file_path_str}")
            stringsfile = StringsFile(file_path_str, self.out_dir, ["Name", "Tip", "Ubertip"])
            tasks.append((stringsfile, asyncio.create_task(stringsfile.translate())))
        for stringsfile, task in tasks:
            await task
            stringsfile.save()


mapdir = MapDir(
    Path(__file__).parent.parent.joinpath("map_data"),
    Path(__file__).parent.parent.joinpath("translate_out")
)


def main():
    asyncio.run(mapdir.translate())


if __name__ == "__main__":
    main()
