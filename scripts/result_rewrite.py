from glob import glob
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent))
from auto_translate import TemplateBasedMixin, IniLikeStrings
from pathlib import Path
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)


class TemplateRewritter(TemplateBasedMixin):
    def __init__(self) -> None:
        super().__init__("rewrite")

    def rewrite(self, string: str, belongs: str) -> str:
        return super().rewrite(string, belongs)


class RewriteDir:
    def __init__(self, dirname: Path):
        self.txt_files = glob(f"{dirname}/*.txt")
        self.rewritter = TemplateRewritter()

    def rewrite(self):
        for f in self.txt_files:
            logger.debug(f"f: {f}")
            strings = IniLikeStrings(Path(f))
            procedure = strings.translate()
            try:
                req = next(procedure)
                while True:
                    res = self.rewritter.rewrite(req.text, req.belongs)
                    req = procedure.send(res)
            except StopIteration:
                pass
            strings.save(
                out_path=Path(__file__)
                .parent.parent.joinpath("translate_out")
                .joinpath(Path(f).name)
            )


def main():
    RewriteDir(Path(__file__).parent.parent.joinpath("translate_out")).rewrite()


if __name__ == "__main__":
    main()
