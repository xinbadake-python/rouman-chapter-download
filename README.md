# rouman-chapter-download

一个用于 Rouman 漫画的 Codex skill：下载用户指定的章节图片，按页面顺序编号，并生成无间距的离线 HTML 阅读页和整本目录。默认不生成 PDF。

## 安装

需要 Python 3.9 或更新版本。安装图片处理依赖：

```sh
python -m pip install -r requirements.txt
```

在 Codex 中，从本仓库的 `skills/rouman-chapter-download` 目录安装 skill。已安装版本与仓库源码是两份文件；更新仓库后，需要重新安装或同步 skill。

## 使用

```sh
python skills/rouman-chapter-download/scripts/rouman_downloader.py https://rouman5.com/books/BOOK_ID --list
python skills/rouman-chapter-download/scripts/rouman_downloader.py https://rouman5.com/books/BOOK_ID --chapter 0
python skills/rouman-chapter-download/scripts/rouman_downloader.py https://rouman5.com/books/BOOK_ID --all
```

章节 URL 的 `/0` 对应本地 `chapter_001`。默认将每本漫画存放在运行命令时所在目录的 `downloads/` 下；使用 `--out <目录>` 可自行选择保存位置。章节阅读页直接读取本地图片，整本目录为 `index.html`。

只有明确需要 PDF 时才使用 `--pdf` 或 `--continuous-pdf`，并另行安装 `reportlab`。

## 仓库结构

```text
skills/rouman-chapter-download/
├── SKILL.md
└── scripts/rouman_downloader.py
requirements.txt
```
