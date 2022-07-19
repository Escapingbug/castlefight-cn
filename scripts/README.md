# 翻译脚本

- `auto_translate.py`: 基础翻译，给出 `map_data` 目录（默认为 `scripts/../map_data`），搜索所有 `*strings.txt` 并使用谷歌翻译
- `result_rewrite.py`: 经过基础翻译之后，由于翻译可能效果不好，所以可利用该脚本进行部分调整。
调整过程依赖 `template.toml` （包含用于调整的配置）

首先使用 `auto_translate.py` 利用谷歌 web api 进行翻译，再通过 `result_rewrite.py` 进行修正。