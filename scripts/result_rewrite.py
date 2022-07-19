from glob import glob
from .auto_translate import TemplateBasedMixin, IniLikeStrings 
from pathlib import Path


class TemplateRewritter(TemplateBasedMixin):
    def __init__(self) -> None:
        super().__init__("rewrite")

    def rewrite(self, string: str) -> str:
        return super().rewrite(string)


class RewriteDir:
    def __init__(self, dirname: Path):
        self.txt_files = glob(f"{dirname}/*.txt")
        self.rewritter = TemplateRewritter()

    def rewrite(self):
        for f in self.txt_files:
            strings = IniLikeStrings(Path(f))
            procedure = strings.translate()
            try:
                while True:
                    value = next(procedure)
                    procedure.send(self.rewritter.rewrite(value))
            except StopIteration:
                pass


def main():
    RewriteDir(Path(__file__).parent.parent.joinpath("translate_out")).rewrite()


if __name__ == "__main__":
    main()
