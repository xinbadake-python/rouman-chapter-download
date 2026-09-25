#!/usr/bin/env python3
"""Download publicly viewable Rouman comic chapters as numbered images.

Examples:
  python rouman_downloader.py URL --list
  python rouman_downloader.py URL --chapter 0 --limit 3
  python rouman_downloader.py URL --all

Image reconstruction needs Pillow; optional PDF export also needs ReportLab:
  python -m pip install pillow
"""

from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from html import escape, unescape
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
IMAGE_EXTENSIONS = ("webp", "jpg", "png", "gif")
CHAPTER_PATHS = re.compile(r"imagePaths:\$R\[\d+\]=")
DEFAULT_LIBRARY_ROOT = Path("downloads")


def parse_book_url(raw_url: str) -> tuple[str, int | None, str]:
    parsed = urlsplit(raw_url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "rouman5.com",
        "www.rouman5.com",
    }:
        raise ValueError("Expected an https://rouman5.com/books/... URL")
    match = re.fullmatch(r"/books/([A-Za-z0-9-]+)(?:/(\d+))?/?", parsed.path)
    if not match:
        raise ValueError("Expected a book or chapter URL under /books/")
    book_id = match.group(1)
    initial_chapter = int(match.group(2)) if match.group(2) is not None else None
    return book_id, initial_chapter, f"https://rouman5.com/books/{book_id}"


def book_output_root(parent: Path, book_id: str, book_url: str) -> Path:
    """Reuse a previously named book folder when its index records this URL."""
    default = parent / book_id
    if default.is_dir() or not parent.is_dir():
        return default
    for folder in parent.iterdir():
        if not folder.is_dir():
            continue
        index = folder / "index.html"
        try:
            if index.is_file() and book_url in index.read_text(encoding="utf-8"):
                return folder
        except (OSError, UnicodeError):
            continue
    return default


def request_bytes(url: str, *, referer: str | None = None) -> tuple[bytes, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
        headers["Accept"] = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
    else:
        headers["Accept"] = "text/html,application/xhtml+xml,*/*;q=0.8"

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                content_type = response.headers.get("Content-Type", "")
                return response.read(), content_type
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
            last_error = exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(2**attempt)
    raise RuntimeError(f"Request failed after 3 attempts: {url}") from last_error


def get_chapters(book_id: str, book_url: str) -> list[int]:
    data, content_type = request_bytes(book_url)
    if "text/html" not in content_type:
        raise ValueError(f"Unexpected book page content type: {content_type}")
    html = data.decode("utf-8")
    pattern = re.compile(rf'href="/books/{re.escape(book_id)}/(\d+)"')
    indices = sorted({int(value) for value in pattern.findall(html)})
    if not indices:
        raise ValueError("No chapter links found in the book page")
    return indices


def get_image_urls(chapter_url: str) -> list[str]:
    data, content_type = request_bytes(chapter_url)
    if "text/html" not in content_type:
        raise ValueError(f"Unexpected chapter page content type: {content_type}")
    html = data.decode("utf-8")
    match = CHAPTER_PATHS.search(html)
    if not match:
        raise ValueError("The chapter page did not expose imagePaths")
    urls, _ = json.JSONDecoder().raw_decode(html[match.end() :])
    if not isinstance(urls, list) or not urls:
        raise ValueError("The chapter has no image URLs")
    for url in urls:
        if not isinstance(url, str):
            raise ValueError("Unexpected image URL type")
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not (
            host == "kelv47.xyz"
            or host.endswith(".kelv47.xyz")
            or re.fullmatch(r"v[1-5]\.towm85\.xyz", host)
        ):
            raise ValueError(f"Unexpected image host: {host}")
    return urls


def detect_image_extension(data: bytes) -> str:
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    raise ValueError("The response is not a supported image")


def is_scrambled(url: str) -> bool:
    return "/sr:1/" in urlsplit(url).path


def reconstruct_image(data: bytes, url: str) -> bytes:
    """Reverse the horizontal-strip order used by the site's canvas reader."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Image reconstruction needs Pillow") from exc

    filename = urlsplit(url).path.rsplit("/", 1)[-1]
    encoded_source = filename.rsplit(".", 1)[0]
    source_path = base64.b64decode(encoded_source + "=" * (-len(encoded_source) % 4))
    strip_count = int(hashlib.md5(source_path).hexdigest()[-2:], 16) % 10 + 5

    with Image.open(BytesIO(data)) as source:
        source = source.convert("RGB")
        width, height = source.size
        base_height, remainder = divmod(height, strip_count)
        corrected = Image.new("RGB", (width, height))
        for index in range(strip_count):
            strip_height = base_height + (remainder if index == 0 else 0)
            source_y = height - base_height * (index + 1) - remainder
            target_y = base_height * index + (0 if index == 0 else remainder)
            strip = source.crop((0, source_y, width, source_y + strip_height))
            corrected.paste(strip, (0, target_y))
        buffer = BytesIO()
        corrected.save(buffer, format="PNG")
        return buffer.getvalue()


def existing_image(directory: Path, index: int, scrambled: bool) -> Path | None:
    extensions = ("png",) if scrambled else IMAGE_EXTENSIONS
    for extension in extensions:
        path = directory / f"{index:04d}.{extension}"
        if not path.is_file() or path.stat().st_size == 0:
            continue
        try:
            if detect_image_extension(path.read_bytes()) == extension:
                return path
        except ValueError:
            pass  # Replace an incomplete or invalid file on this run.
    return None


def download_image(url: str, chapter_url: str, directory: Path, index: int) -> Path:
    scrambled = is_scrambled(url)
    previous = existing_image(directory, index, scrambled)
    if previous:
        return previous
    data, content_type = request_bytes(url, referer=chapter_url)
    extension = detect_image_extension(data)
    media_type = content_type.split(";", 1)[0].strip().lower()
    if not (media_type.startswith("image/") or media_type in {"bytes", "application/octet-stream"}):
        raise ValueError(f"Unexpected image response content type: {content_type}")
    if scrambled:
        data = reconstruct_image(data, url)
        extension = "png"
    path = directory / f"{index:04d}.{extension}"
    temp_path = directory / f"{index:04d}.{extension}.part"
    try:
        temp_path.write_bytes(data)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return path


def make_pdf(image_paths: list[Path], pdf_path: Path, overwrite: bool) -> None:
    if pdf_path.exists() and not overwrite:
        print(f"PDF exists; skipped: {pdf_path}")
        return
    try:
        from PIL import Image
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("PDF export needs Pillow and ReportLab") from exc

    temp_path = pdf_path.with_suffix(".part.pdf")
    try:
        pdf = canvas.Canvas(str(temp_path), pageCompression=1)
        pdf.setTitle(pdf_path.stem)
        for path in image_paths:
            with Image.open(path) as source:
                image = source.convert("RGB")
                width, height = image.size
                if width <= 0 or height <= 0 or max(width, height) > 14400:
                    raise ValueError(f"Unsupported PDF page dimensions: {path}")
                pdf.setPageSize((width, height))
                pdf.drawImage(ImageReader(image), 0, 0, width=width, height=height)
                pdf.showPage()
        pdf.save()
        os.replace(temp_path, pdf_path)
    finally:
        temp_path.unlink(missing_ok=True)


def make_continuous_pdf(image_paths: list[Path], pdf_path: Path, overwrite: bool) -> None:
    """Join neighboring tiles with no gap, grouping them into manageable PDF pages."""
    if pdf_path.exists() and not overwrite:
        print(f"PDF exists; skipped: {pdf_path}")
        return
    try:
        from PIL import Image
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("Continuous PDF export needs Pillow and ReportLab") from exc

    max_page_height = 12000
    groups: list[list[tuple[Path, int, int]]] = []
    group: list[tuple[Path, int, int]] = []
    group_width = 0
    group_height = 0
    for path in image_paths:
        with Image.open(path) as source:
            width, height = source.size
        if width <= 0 or height <= 0 or height > max_page_height:
            raise ValueError(f"Unsupported continuous PDF tile dimensions: {path}")
        if group and (width != group_width or group_height + height > max_page_height):
            groups.append(group)
            group = []
            group_height = 0
        if not group:
            group_width = width
        group.append((path, width, height))
        group_height += height
    if group:
        groups.append(group)

    temp_path = pdf_path.with_suffix(".part.pdf")
    try:
        pdf = canvas.Canvas(str(temp_path), pageCompression=1)
        pdf.setTitle(pdf_path.stem)
        for tiles in groups:
            width = tiles[0][1]
            page_height = sum(height for _, _, height in tiles)
            joined = Image.new("RGB", (width, page_height))
            y = 0
            for path, _, height in tiles:
                with Image.open(path) as source:
                    joined.paste(source.convert("RGB"), (0, y))
                y += height
            pdf.setPageSize((width, page_height))
            pdf.drawImage(ImageReader(joined), 0, 0, width=width, height=page_height)
            pdf.showPage()
            joined.close()
        pdf.save()
        os.replace(temp_path, pdf_path)
    finally:
        temp_path.unlink(missing_ok=True)


def make_html_reader(image_paths: list[Path], html_path: Path) -> None:
    """Create a local chapter reader with no spacing between image tiles."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("HTML reader export needs Pillow") from exc
    title = html_path.stem.replace("_", " ")
    tags = []
    for path in image_paths:
        with Image.open(path) as source:
            width, height = source.size
        src = escape(f"{path.parent.name}/{path.name}", quote=True)
        tags.append(f'<img src="{src}" width="{width}" height="{height}" alt="">')
    markup = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<title>{escape(title)}</title>"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<style>html,body{margin:0;padding:0;background:#000}"
        "main{width:min(100%,720px);margin:auto;line-height:0;font-size:0}"
        "img{display:block;width:100%;height:auto;margin:0;padding:0;border:0;vertical-align:top}"
        "</style></head><body><main>"
        + "".join(tags)
        + "</main></body></html>"
    )
    temp_path = html_path.with_suffix(".part.html")
    try:
        temp_path.write_text(markup, encoding="utf-8")
        os.replace(temp_path, html_path)
    finally:
        temp_path.unlink(missing_ok=True)


def make_book_index(output_root: Path, book_url: str) -> Path | None:
    """Link completed local chapter readers without depending on PDFs."""
    readers: dict[int, tuple[Path, int | None]] = {}
    for html_path in output_root.glob("chapter_*.html"):
        match = re.fullmatch(r"chapter_(\d{3})(?:_sample(\d+))?\.html", html_path.name)
        if match is None:
            continue
        number = int(match.group(1))
        sample = int(match.group(2)) if match.group(2) else None
        previous = readers.get(number)
        if previous is None or (
            previous[1] is not None and (sample is None or sample > previous[1])
        ):
            readers[number] = (html_path, sample)
    if not readers:
        return None

    rows = []
    total_images = 0
    root = output_root.resolve()
    for number, (html_path, sample) in sorted(readers.items()):
        markup = html_path.read_text(encoding="utf-8")
        image_refs = re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', markup)
        if not image_refs:
            raise ValueError(f"Chapter reader has no images: {html_path}")
        for raw_ref in image_refs:
            target = (output_root / unescape(raw_ref)).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                raise ValueError(f"Chapter reader image is missing: {raw_ref}")
        count = len(image_refs)
        label = f"第 {number} 话" + (f"（试读 {sample} 张）" if sample else "")
        rows.append(
            f'<tr><th scope="row">{escape(label)}</th><td>{count}</td>'
            f'<td><a href="{escape(html_path.name, quote=True)}">打开阅读页</a></td></tr>'
        )
        total_images += count

    title = output_root.name
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · 离线阅读</title>
<style>:root{{color-scheme:dark;font-family:system-ui,sans-serif}}
body{{max-width:900px;margin:0 auto;padding:24px;background:#101114;color:#e9eaec}}
p{{color:#b8bbc2;line-height:1.5}}a{{color:#88c5ff}}
table{{width:100%;border-collapse:collapse;margin-top:22px}}
th,td{{padding:10px 8px;text-align:left;border-bottom:1px solid #31343a}}
@media(max-width:600px){{body{{padding:12px}}th,td{{padding:8px 4px;font-size:14px}}}}
</style></head><body>
<h1>{escape(title)}</h1>
<p>已保存 {len(readers)} 话 · {total_images:,} 张图片。阅读页直接使用本地图片，连续滚动阅读。</p>
<p>来源：<a href="{escape(book_url, quote=True)}">{escape(book_url)}</a></p>
<table><thead><tr><th>章节</th><th>图片</th><th>打开</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></body></html>
"""
    temp_path = output_root / "index.part.html"
    final_path = output_root / "index.html"
    try:
        temp_path.write_text(page, encoding="utf-8")
        os.replace(temp_path, final_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return final_path


def download_chapter(
    book_url: str,
    chapter_index: int,
    output_root: Path,
    workers: int,
    limit: int | None,
    pdf: bool,
    continuous_pdf: bool,
    html_reader: bool,
    overwrite_pdf: bool,
) -> None:
    chapter_url = f"{book_url}/{chapter_index}"
    image_urls = get_image_urls(chapter_url)
    total = len(image_urls)
    if limit is not None:
        image_urls = image_urls[:limit]
    directory = output_root / f"chapter_{chapter_index + 1:03d}"
    directory.mkdir(parents=True, exist_ok=True)
    print(f"Chapter {chapter_index + 1}: {len(image_urls)}/{total} images")

    paths: list[Path | None] = [None] * len(image_urls)
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(download_image, url, chapter_url, directory, index): index
            for index, url in enumerate(image_urls, start=1)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                paths[index - 1] = future.result()
                print(f"  {index:04d}/{len(image_urls):04d} saved")
            except Exception as exc:  # Continue other images; report all failures.
                errors.append(f"image {index}: {exc}")

    if errors:
        raise RuntimeError("Incomplete chapter:\n" + "\n".join(errors))
    ordered_paths = [path for path in paths if path is not None]
    if len(ordered_paths) != len(image_urls):
        raise RuntimeError("The chapter is incomplete")
    if pdf:
        suffix = f"_sample{limit}" if limit is not None else ""
        pdf_path = output_root / f"chapter_{chapter_index + 1:03d}{suffix}.pdf"
        make_pdf(ordered_paths, pdf_path, overwrite_pdf)
        print(f"PDF: {pdf_path}")
    if continuous_pdf:
        suffix = f"_sample{limit}" if limit is not None else ""
        pdf_path = output_root / f"chapter_{chapter_index + 1:03d}{suffix}_continuous.pdf"
        make_continuous_pdf(ordered_paths, pdf_path, overwrite_pdf)
        print(f"Continuous PDF: {pdf_path}")
    if html_reader:
        suffix = f"_sample{limit}" if limit is not None else ""
        html_path = output_root / f"chapter_{chapter_index + 1:03d}{suffix}.html"
        make_html_reader(ordered_paths, html_path)
        print(f"Seamless HTML: {html_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Rouman book or chapter URL")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--chapter", type=int, help="Chapter index from the URL, starting at 0")
    group.add_argument("--all", action="store_true", help="Download every chapter")
    group.add_argument("--list", action="store_true", help="List chapter indices only")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_LIBRARY_ROOT,
        help="Parent folder for book downloads (default: %(default)s)",
    )
    parser.add_argument("--workers", type=int, default=4, help="Concurrent image downloads (1-8)")
    parser.add_argument("--limit", type=int, help="First N images per chapter, for a trial")
    parser.add_argument("--pdf", action="store_true", help="Also export a PDF, one image per page")
    parser.add_argument("--continuous-pdf", action="store_true", help="Join adjacent images into taller PDF pages without gaps")
    parser.add_argument(
        "--html-reader", action=argparse.BooleanOptionalAction, default=True,
        help="Write zero-gap chapter readers and a local book index (default: on)",
    )
    parser.add_argument("--overwrite-pdf", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be between 1 and 8")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.chapter is not None and args.chapter < 0:
        parser.error("--chapter must be 0 or greater")

    try:
        book_id, initial_chapter, book_url = parse_book_url(args.url)
        if args.all or args.list:
            indices = get_chapters(book_id, book_url)
            print(f"Available chapters ({len(indices)}): {', '.join(map(str, indices))}")
            if args.list:
                return 0
        else:
            indices = [args.chapter if args.chapter is not None else (initial_chapter or 0)]
        output_root = book_output_root(args.out, book_id, book_url)
        for index in indices:
            download_chapter(
                book_url, index, output_root, args.workers, args.limit,
                args.pdf, args.continuous_pdf, args.html_reader, args.overwrite_pdf
            )
            if args.html_reader:
                index_path = make_book_index(output_root, book_url)
                print(f"Offline index: {index_path}")
        return 0
    except (HTTPError, URLError, OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
