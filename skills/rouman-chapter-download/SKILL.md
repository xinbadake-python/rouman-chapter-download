---
name: rouman-chapter-download
description: Download explicitly selected Rouman chapters as ordered images with a zero-gap offline reader and chapter index. Use for rouman5.com book or reader URLs, not unrelated comic sites.
---

# Rouman chapter download

Use `scripts/rouman_downloader.py` for chapters the user asks to save. The script reads chapter image URLs from the site's `imagePaths` page data, downloads the images in page order, and reconstructs images marked `sr:1` using the strip order implemented by the site's reader. Images marked `sr:0` are saved in their detected source format.

The script creates a zero-gap HTML reader for each downloaded chapter and an `index.html` linking completed chapters. These pages read the numbered images directly. Books are saved under `downloads/` relative to the current working directory by default, with one child folder per book ID. A renamed existing folder is reused when its index records the same book URL. Use `--out` to change the parent folder. Do not generate PDFs unless the user explicitly requests that format. If requested, `--continuous-pdf` joins adjacent tiles into taller pages (up to 12,000 pixels high), while `--pdf` creates one page per image.

## Scope and run

1. Confirm the requested book URL and chapter numbers. URL chapter indices start at **0**; `chapter_001` is URL `/0`. Run `--list` when the chapter list is uncertain.
2. Run only the requested indices with `--chapter`. Use `--all` only when the user explicitly requests the entire book. Run `--limit N` only for a trial; sample HTML/PDF outputs include `_sampleN` in the name.
3. Use Python with Pillow installed for image reconstruction, plus ReportLab only if the user requested PDF. Example using the default relative download folder:

   ```text
   python scripts/rouman_downloader.py https://rouman5.com/books/BOOK_ID --chapter 0
   ```

4. If a run is interrupted, repeat the same command. Completed image files are reused; each HTML reader is written after its chapter finishes, then the book index is refreshed.

## Check the result

- Compare each chapter's printed image count with its numbered files, then check that the HTML reader references them in order and `index.html` links to the completed chapters. When a PDF was requested, also check its page count.
- Check a representative joined boundary when diagnosing a reported visual seam. A display gap between two source tiles does not imply the saved image pixels contain a black line.
- If the site's page data, CDN hosts, or image scrambling changes, inspect the current reader and update the script before downloading more chapters. The script accepts only Rouman book URLs and the observed CDN hosts (`kelv47.xyz` subdomains and `v1`–`v5.towm85.xyz`).
