"""Collect piano sheet-music page images from the Mutopia Project, per composer.

Source: https://www.mutopiaproject.org (all pieces public domain or CC-licensed,
robots.txt permits crawling). IMSLP was considered but its robots.txt disallows
the paths needed to fetch score files (/imglnks/, /images/, /wiki/File:).

For each composer, walks the paginated "Instrument=Piano" search results,
downloads each piece's A4 PDF, rasterizes every page, and crops the top 15%
off only the first page of each piece (removing the title/composer header;
later pages have no such header so are kept uncropped). Skips pages that
come out near-blank (cover pages, license/footer-only pages), and saves the
rest as PNGs under raw_imgs/<Composer>/ until the per-composer target is
reached.
"""

import re
import time
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw_imgs"

COMPOSERS = {
    "Bach": "BachJS",
    "Mozart": "MozartWA",
    "Chopin": "ChopinFF",
}

SEARCH_URL = "https://www.mutopiaproject.org/cgibin/make-table.cgi"
USER_AGENT = "ClassiCat-research-scraper/1.0 (educational ML dataset; contact: lynn737@gmail.com)"

TARGET_PER_COMPOSER = 200
CROP_TOP_FRACTION = 0.15
RENDER_DPI = 150
MIN_INK_FRACTION = 0.005  # below this, treat page as blank (cover/license page) and skip
REQUEST_DELAY_SECONDS = 0.5


def collect_pdf_urls(page, composer_code: str) -> list[str]:
    """Paginate the composer's piano-instrument search results and return A4 PDF URLs."""
    urls: list[str] = []
    start = 0
    while True:
        page.goto(
            f"{SEARCH_URL}?startat={start}&Composer={composer_code}&Instrument=Piano",
            wait_until="domcontentloaded",
        )
        hrefs = page.eval_on_selector_all("a[href$='-a4.pdf']", "els => els.map(e => e.href)")
        found = sorted(set(hrefs))
        if not found:
            break
        urls.extend(found)
        start += 10
        time.sleep(REQUEST_DELAY_SECONDS)
    return urls


def is_mostly_blank(img: Image.Image) -> bool:
    gray = np.array(img.convert("L"))
    ink_fraction = (gray < 200).mean()
    return ink_fraction < MIN_INK_FRACTION


def piece_slug(pdf_url: str) -> str:
    name = pdf_url.rsplit("/", 1)[-1]
    return re.sub(r"-a4\.pdf$", "", name)


def process_pdf(pdf_bytes: bytes, out_dir: Path, slug: str, remaining: int) -> int:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    zoom = RENDER_DPI / 72
    mat = fitz.Matrix(zoom, zoom)
    saved = 0
    for page_num in range(doc.page_count):
        if saved >= remaining:
            break
        pix = doc[page_num].get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if page_num == 0:
            crop_top_px = int(img.height * CROP_TOP_FRACTION)
            img = img.crop((0, crop_top_px, img.width, img.height))
        if is_mostly_blank(img):
            continue
        out_path = out_dir / f"{slug}_p{page_num + 1:02d}.png"
        img.save(out_path)
        saved += 1
    return saved


def main() -> None:
    for name in COMPOSERS:
        (RAW_DIR / name).mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        for name, code in COMPOSERS.items():
            out_dir = RAW_DIR / name
            print(f"[{name}] collecting piece list...")
            pdf_urls = collect_pdf_urls(page, code)
            print(f"[{name}] found {len(pdf_urls)} pieces")

            saved_total = 0
            for url in pdf_urls:
                if saved_total >= TARGET_PER_COMPOSER:
                    break
                resp = context.request.get(url)
                if resp.status != 200:
                    print(f"  ! failed to fetch {url}: {resp.status}")
                    continue
                slug = piece_slug(url)
                remaining = TARGET_PER_COMPOSER - saved_total
                n = process_pdf(resp.body(), out_dir, slug, remaining)
                saved_total += n
                print(f"  {slug}: +{n} images (total {saved_total}/{TARGET_PER_COMPOSER})")
                time.sleep(REQUEST_DELAY_SECONDS)

            print(f"[{name}] done: {saved_total} images saved to {out_dir}")

        browser.close()


if __name__ == "__main__":
    main()
