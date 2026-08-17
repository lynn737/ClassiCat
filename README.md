# ClassiCat 🎹

Given an unlabelled classical piano score, predict its composer.

## v1 scope

- **Input**: score PDFs (not audio recordings)
- **Encoding**: MusicXML
- **Instrument**: piano only
- **Granularity**: sections of a piece, not entire scores

Open question for the modeling stage: will the classifier learn local
stylistic patterns (voicing, ornamentation, harmonic idiom) or lean on
piece-wide structural cues that happen to correlate with composer in this
dataset? Worth checking once a model exists.

## Pipeline

```
scrape_mutopia.py  -->  raw_imgs/<Composer>/*.png  -->  run_oemer.py  -->  music_xmls/<Composer>/*.musicxml
```

### 1. `scrape_mutopia.py` — collect piano scores

Downloads piano sheet music for Bach, Mozart, and Chopin from the
[Mutopia Project](https://www.mutopiaproject.org). Mutopia was chosen over
IMSLP: IMSLP's `robots.txt` disallows the paths needed to fetch score files
(`/imglnks/`, `/images/`, `/wiki/File:`), while Mutopia's allows crawling
and everything in its catalog is public domain or CC-licensed.

For each composer it walks the paginated `Instrument=Piano` search results
(via Playwright), downloads each piece's A4 PDF, rasterizes every page, and
crops the top 15% off only the **first** page of each piece (that's where
the title/composer header lives — later pages have no such header). Pages
that come out near-blank after cropping (cover pages, license/footer-only
pages) are skipped. Images are saved as
`raw_imgs/<Composer>/<piece-slug>_p<page>.png` until a per-composer target
is hit (200, capped by whatever Mutopia's catalog actually has for that
composer under the Piano tag).

Current corpus:

| Composer | Images |
|---|---|
| Bach | 200 |
| Chopin | 185 |
| Mozart | 114 |

Mozart and Chopin are capped below 200 because Mutopia's volunteer-built,
piano-tagged catalog for them is smaller (31 and 46 pieces respectively,
vs. 125 for Bach) — not a scraper bug.

### 2. `run_oemer.py` — optical music recognition

Batch-runs [oemer](https://github.com/BreezeWhite/oemer) (OMR) over every
image in `raw_imgs/`, writing one `.musicxml` per image to
`music_xmls/<Composer>/`. Each image runs as its own subprocess so one
crashing/hanging page can't take down the batch; deskewing is disabled
(`-d`) since the source pages are clean LilyPond-rendered PDFs with no scan
warp to correct (and deskewing was observed to crash oemer on at least one
sparse page). Already-produced outputs are skipped, so an interrupted run
can be resumed by re-invoking the script.

```
python3 run_oemer.py                          # full batch, 2 parallel workers
python3 run_oemer.py --limit-per-composer 20   # pilot run
python3 run_oemer.py --workers 4               # more parallelism
```

Failures are logged to `music_xmls/_failures.log` rather than aborting the
run. On this machine (10 cores), a single oemer invocation uses ~4 cores
and takes ~2.5-3 minutes per page, so 2 parallel workers is a safe ceiling
without heavy contention.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
```

**macOS + python.org Python note**: the framework build doesn't ship a
working CA bundle by default, which breaks HTTPS downloads (checkpoint
downloads, Mutopia requests) with `CERTIFICATE_VERIFY_FAILED`. Fix:

```bash
pip install certifi
export SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())")
```

**oemer compatibility patches**: oemer 0.1.5 is unmaintained and predates
current numpy/opencv. Installing it into `.venv` requires two one-line
patches to its own source (`np.int` → `int` in
`oemer/staffline_extraction.py` and `oemer/symbol_extraction.py` for numpy
≥1.24; and handling `cv2.HoughLinesP`'s new `(N, 4)` output shape — it used
to be `(N, 1, 4)` — in `oemer/bbox.py`). These live in `.venv/`, which is
gitignored, so they need to be reapplied if the venv is ever recreated.

## Project layout

```
scrape_mutopia.py   # Mutopia scraper
run_oemer.py         # batch OMR runner
raw_imgs/             # scraped page images, labelled by composer (gitignored)
music_xmls/           # OMR output, labelled by composer (gitignored)
output/               # scratch OMR output from manual/one-off oemer runs (gitignored)
.venv/                # project virtualenv (gitignored)
```

## License

MIT — see [LICENSE](LICENSE). Note this covers the code in this repo only;
the scraped sheet music itself is public domain or CC-licensed per
Mutopia's per-piece licensing.
