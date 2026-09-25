from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

from PIL import Image


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "rouman-chapter-download"
    / "scripts"
    / "rouman_downloader.py"
)
SPEC = importlib.util.spec_from_file_location("rouman_downloader", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT}")
downloader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(downloader)


class ChapterCatalogTests(unittest.TestCase):
    def test_parse_original_titles_only_from_chapter_links(self) -> None:
        book_id = "demo-book"
        html = f"""
        <a href="/books/{book_id}/0"><span>start</span></a>
        <div class="site-chapters">
          <a href="/books/{book_id}/0" class="site-chapter-link active">
            <span title="第1話-原始 &amp; 標題">ignored text</span><small>舊</small>
          </a>
          <a class="site-chapter-link" href="/books/{book_id}/1">
            <span>最終話-完整標題</span><small>NEW</small>
          </a>
        </div>
        """
        self.assertEqual(
            downloader.parse_chapter_catalog(html, book_id),
            {0: "第1話-原始 & 標題", 1: "最終話-完整標題"},
        )

    def test_titles_are_saved_and_loaded_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "book"
            source = "https://rouman5.com/books/demo-book"
            titles = {0: "第1話-標題", 1: "第2話-標題"}
            path = downloader.save_chapter_titles(root, source, titles)
            self.assertEqual(path, root / "chapters" / "chapter_titles.json")
            self.assertEqual(downloader.load_chapter_titles(root, source), titles)
            self.assertEqual(downloader.load_chapter_titles(root, source + "-other"), {})


class BookIndexTests(unittest.TestCase):
    def test_index_uses_one_titled_link_per_chapter_in_a_grid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "離線示例"
            source = "https://rouman5.com/books/demo-book"
            readers = [root / "chapters" / f"chapter_{number:03d}.html" for number in (1, 2)]
            for position, reader in enumerate(readers):
                image_path = root / "images" / f"chapter_{position + 1:03d}" / "0001.png"
                image_path.parent.mkdir(parents=True)
                Image.new("RGB", (4, 6), color=(position * 40, 20, 30)).save(image_path)
                downloader.make_html_reader(
                    [image_path],
                    reader,
                    readers[position - 1] if position else None,
                    readers[position + 1] if position + 1 < len(readers) else None,
                )
            titles = {0: "第1話-原始標題", 1: "最終話-另一標題"}
            downloader.save_chapter_titles(root, source, titles)

            index_path = downloader.make_book_index(root, source)

            self.assertEqual(index_path, root / "index.html")
            markup = index_path.read_text(encoding="utf-8")
            self.assertIn('class="chapter-grid"', markup)
            self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", markup)
            self.assertIn('href="chapters/chapter_001.html"', markup)
            self.assertIn('href="chapters/chapter_002.html"', markup)
            self.assertIn("第1話-原始標題", markup)
            self.assertIn("最終話-另一標題", markup)
            self.assertEqual(markup.count('class="chapter-link"'), 2)
            self.assertNotIn("<table", markup)
            self.assertNotIn("打开阅读页", markup)


if __name__ == "__main__":
    unittest.main()
