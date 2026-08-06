"""One-off fix for the page-1 over-crop bug (see scrape_mutopia.py history).

Re-fetches only the PDFs whose page 1 we already have in raw_imgs, re-renders
page 1 uncropped, and overwrites the existing file atomically (write to a temp
path, then os.replace -- safe to run alongside a concurrently-running
run_oemer.py batch, since a reader never sees a partially-written file).

Also deletes any music_xmls output (and .failed marker) that's older than the
raw image it was derived from, so a stale MusicXML produced from the old,
badly-cropped image doesn't get left in place. A subsequent run_oemer.py
invocation will naturally reprocess exactly those.
"""

import os
import tempfile
import time
from pathlib import Path

import fitz  # PyMuPDF
from playwright.sync_api import sync_playwright

from scrape_mutopia import (
    COMPOSERS,
    RAW_DIR,
    RENDER_DPI,
    USER_AGENT,
    collect_pdf_urls,
    is_mostly_blank,
    piece_slug,
)
from PIL import Image

OUT_DIR = Path(__file__).resolve().parent / "music_xmls"
REQUEST_DELAY_SECONDS = 0.5


def render_page1_uncropped(pdf_bytes: bytes) -> Image.Image | None:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    zoom = RENDER_DPI / 72
    mat = fitz.Matrix(zoom, zoom)
    pix = doc[0].get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return None if is_mostly_blank(img) else img


def invalidate_stale_output(composer: str, slug: str, raw_path: Path) -> None:
    out_dir = OUT_DIR / composer
    raw_mtime = raw_path.stat().st_mtime
    for suffix in (".musicxml", ".failed"):
        stale = out_dir / f"{slug}_p01{suffix}"
        if stale.exists() and stale.stat().st_mtime < raw_mtime:
            stale.unlink()
            print(f"    invalidated stale {stale.name}")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        for name, code in COMPOSERS.items():
            raw_dir = RAW_DIR / name
            existing_page1 = {
                f.name[: -len("_p01.png")] for f in raw_dir.glob("*_p01.png")
            }
            if not existing_page1:
                continue

            print(f"[{name}] {len(existing_page1)} page-1 images to fix; collecting piece list...")
            pdf_urls = collect_pdf_urls(page, code)

            fixed = 0
            for url in pdf_urls:
                slug = piece_slug(url)
                if slug not in existing_page1:
                    continue

                raw_path = raw_dir / f"{slug}_p01.png"
                resp = context.request.get(url)
                if resp.status != 200:
                    print(f"  ! failed to fetch {url}: {resp.status}")
                    continue

                img = render_page1_uncropped(resp.body())
                if img is None:
                    print(f"  ! {slug}: page 1 rendered blank, leaving existing file untouched")
                    continue

                fd, tmp_path = tempfile.mkstemp(suffix=".png", dir=raw_dir)
                os.close(fd)
                img.save(tmp_path)
                os.replace(tmp_path, raw_path)
                invalidate_stale_output(name, slug, raw_path)

                fixed += 1
                print(f"  [{fixed}/{len(existing_page1)}] fixed {slug}_p01.png")
                time.sleep(REQUEST_DELAY_SECONDS)

            print(f"[{name}] done: {fixed} page-1 images re-rendered uncropped")

        browser.close()


if __name__ == "__main__":
    main()
