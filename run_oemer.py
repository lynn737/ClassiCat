"""Batch-run oemer OMR over raw_imgs/<Composer>/*.png, writing MusicXML to music_xmls/<Composer>/.

Each image runs as its own `oemer` subprocess -- isolates crashes/hangs to a single
image instead of taking down the whole batch. Deskewing is disabled (-d): the source
pages are clean LilyPond-rendered PDFs, not scans, so there's no warp to correct, and
deskewing was observed to crash on at least one sparse page (assertion error in
oemer's dewarp.py). Already-produced outputs are skipped, so an interrupted run can
be resumed by just re-invoking the script. Images that fail are marked with a
sidecar `.failed` file so a resume doesn't keep re-attempting known-deterministic
failures (oemer has no randomness, so a failure on one run will fail identically
on the next).
"""

import argparse
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw_imgs"
OUT_DIR = BASE_DIR / "music_xmls"
OEMER_BIN = BASE_DIR / ".venv" / "bin" / "oemer"

TIMEOUT_SECONDS = 900  # generous ceiling per image; observed runs are ~2-3 min


def find_images(limit_per_composer: int | None) -> list[tuple[str, Path]]:
    tasks = []
    for composer_dir in sorted(RAW_DIR.iterdir()):
        if not composer_dir.is_dir():
            continue
        images = sorted(composer_dir.glob("*.png"))
        if limit_per_composer is not None:
            images = images[:limit_per_composer]
        tasks.extend((composer_dir.name, img) for img in images)
    return tasks


def run_one(composer: str, img_path: Path) -> dict:
    out_dir = OUT_DIR / composer
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{img_path.stem}.musicxml"
    failed_marker = out_dir / f"{img_path.stem}.failed"
    if out_path.exists():
        return {"composer": composer, "image": img_path.name, "status": "skipped", "elapsed": 0.0}
    if failed_marker.exists():
        return {"composer": composer, "image": img_path.name, "status": "skipped_failed", "elapsed": 0.0}

    start = time.time()
    try:
        result = subprocess.run(
            [str(OEMER_BIN), "-d", str(img_path), "-o", str(out_dir)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"composer": composer, "image": img_path.name, "status": "timeout", "elapsed": TIMEOUT_SECONDS}
    elapsed = time.time() - start

    if not out_path.exists():
        stderr_lines = [ln for ln in result.stderr.strip().splitlines() if ln.strip()]
        error_line = next((ln for ln in reversed(stderr_lines) if "Error" in ln or "Exception" in ln), None)
        error = error_line or (stderr_lines[-1] if stderr_lines else "unknown error")
        failed_marker.write_text(error + "\n")
        return {"composer": composer, "image": img_path.name, "status": "failed", "elapsed": elapsed, "error": error}

    return {"composer": composer, "image": img_path.name, "status": "success", "elapsed": elapsed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-run oemer over raw_imgs, writing MusicXML to music_xmls.")
    parser.add_argument(
        "--limit-per-composer", type=int, default=None,
        help="Only process the first N images per composer (for pilot runs).",
    )
    parser.add_argument("--workers", type=int, default=2, help="Number of oemer subprocesses to run in parallel.")
    args = parser.parse_args()

    tasks = find_images(args.limit_per_composer)
    composers = sorted({c for c, _ in tasks})
    print(f"Queued {len(tasks)} images across {len(composers)} composers ({', '.join(composers)}), {args.workers} parallel workers.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failures_log = OUT_DIR / "_failures.log"

    batch_start = time.time()
    done = succeeded = skipped = skipped_failed = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool, open(failures_log, "a") as flog:
        futures = {pool.submit(run_one, composer, img): (composer, img) for composer, img in tasks}
        for future in as_completed(futures):
            res = future.result()
            done += 1
            if res["status"] == "success":
                succeeded += 1
                print(f"[{done}/{len(tasks)}] OK   {res['composer']}/{res['image']} ({res['elapsed']:.0f}s)")
            elif res["status"] == "skipped":
                skipped += 1
                print(f"[{done}/{len(tasks)}] SKIP {res['composer']}/{res['image']} (already exists)")
            elif res["status"] == "skipped_failed":
                skipped_failed += 1
                print(f"[{done}/{len(tasks)}] SKIP {res['composer']}/{res['image']} (known failure, not retrying)")
            else:
                err = res.get("error", "")
                print(f"[{done}/{len(tasks)}] FAIL {res['composer']}/{res['image']} ({res['status']}): {err}")
                flog.write(f"{res['composer']}/{res['image']}: {res['status']}: {err}\n")
                flog.flush()

    total_elapsed = time.time() - batch_start
    failed = done - succeeded - skipped - skipped_failed
    print(
        f"Done in {total_elapsed / 60:.1f} min. {succeeded} succeeded, {skipped} skipped, "
        f"{skipped_failed} skipped (known failures), {failed} newly failed (see {failures_log})."
    )


if __name__ == "__main__":
    main()
