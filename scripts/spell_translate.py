import asyncio
import logging
import re
from typing import Any, Iterable, List, Tuple
import tomli
from pathlib import Path
from glob import glob
from configparser import ConfigParser
import concurrent.futures
import httpx
import json

# must use v2, or else we will get pretty bad result
from translatepy.translators.google import GoogleTranslateV2

# see: https://github.com/encode/httpx/issues/914
import platform

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

F_SID_KEY_RE = re.compile('FdrFJe":"(.*?)"')
BL_KEY_RE = re.compile('cfb2h":"(.*?)"')


class AsyncTranslator:
    def __init__(self, max_workers: int = 8):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.translator = GoogleTranslateV2()

    async def translate(self, text: str) -> str:
        def do_translate():
            return self.translator.translate(text, "zh-CN", "en").result

        return await asyncio.get_running_loop().run_in_executor(
            self.executor, do_translate
        )


translator = AsyncTranslator()


class Template:
    def __init__(self, path: Path) -> None:
        with open(path, "rb") as f:
            self.data = tomli.load(f)


class StringsFile:
    def __init__(self, path: Path | str, translation_keys: Iterable[str]) -> None:
        self.path = path
        self.parser = ConfigParser(interpolation=None)
        self.parser.optionxform = lambda option: option  # type: ignore
        self.parser.read(path, encoding="utf8")
        self.translation_keys = set(translation_keys)

    async def translate_by_parts(self, string: str) -> str:
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
                result = await translator.translate(text_input)
            else:
                result = ""
            translation_result = result.split("|")
            assert (
                len(translation_result) == len(escape_strings) + 1
            ), f"incorrect translation result: {translation_result} escape string {escape_strings}"
            # merge escape_strings back
            final_result = [translation_result[0]]
            for i in range(1, len(translation_result)):
                final_result.append(escape_strings[i - 1])
                final_result.append(translation_result[i])
            return "".join(final_result)

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
                        translation_task(
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
                raise Exception(f"unsupported escape string found: {'|' + part}")
            i += 1
        if len(texts_to_translate) > 0:
            text_input = "|".join(texts_to_translate)
            result_tasks.append(
                asyncio.create_task(translation_task(text_input, escape_strings))
            )
        result: List[str] = [await task for task in result_tasks]
        return "|n".join(result)

    async def translate(self):
        logger.debug(f"begin translating {self.path}")
        set_task: List[
            Tuple[str, str, asyncio.Task[str]]
        ] = []  # (section_name, key, task)
        for section_name in self.parser.sections():
            logger.debug(f"section {section_name}")
            section = self.parser[section_name]
            for key in section.keys():
                logger.debug(f"key {key}")
                if key in self.translation_keys:
                    logger.debug(
                        f"pending translation({section}[{key}]): {section[key]}"
                    )
                    set_task.append(
                        (
                            section_name,
                            key,
                            asyncio.create_task(self.translate_by_parts(section[key])),
                        )
                    )
            break
        for section_name, key, task in set_task:
            result = await task
            logger.debug(f"translation {section_name}[{key}] result {result}")
            self.parser[section_name][key] = result


class MapDir:
    def __init__(self, path: Path) -> None:
        self.txt_files = glob(f"{path}/**/*.txt")


template = Template(Path(__file__).parent.joinpath("template.toml"))
mapdir = MapDir(Path(__file__).parent.parent.joinpath("map_data"))


def main():
    test = StringsFile("./map_data/units/humanunitstrings.txt", ["Name", "Ubertip"])
    asyncio.run(test.translate())
    """
    for sec in test.parser.sections():
        section = test.parser[sec]
        print(dict(section.items()))
    """


if __name__ == "__main__":
    main()
