#!/usr/bin/env python3
"""
Batch workflow for turning high-value eBay manual research rows into listings.

Flow:
1. Read an ebay_sold.py CSV export.
2. Sort rows by estimated total value, matching the HTML report order.
3. For each row, download the matching PDF into the main manuals folder.
4. Call sell.py with the downloaded PDF and original row title.
"""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable
import re

import downloadpdf
from selenium.common.exceptions import WebDriverException


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MANUALS_DIR = Path(r"C:\Users\benoi\Downloads\ebay_manuals")
DEFAULT_PROFILE_DIR = SCRIPT_DIR / "chrome_profile_selenium"
DEFAULT_LINKS_JSON = SCRIPT_DIR / "ebay_links.json"
DEFAULT_PROGRESS_FILE = SCRIPT_DIR / "ebay_business_progress.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download profitable manuals from an ebay_sold CSV and create eBay listings."
    )
    parser.add_argument("--csv", dest="csv_path", default=None,
                        help="Input CSV from ebay_sold.py. Default: newest *_stock_data.csv or *_sales_data.csv in this folder.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N sorted rows.")
    parser.add_argument("--start-at", type=int, default=None,
                        help="1-based sorted row number to start at. Overrides saved resume progress.")
    parser.add_argument("--no-resume", action="store_true",
                        help="Ignore saved resume progress and start from --start-at or row 1.")
    parser.add_argument("--progress-file", default=str(DEFAULT_PROGRESS_FILE),
                        help=f"Resume progress file (default: {DEFAULT_PROGRESS_FILE}).")
    parser.add_argument("--manuals-dir", default=str(DEFAULT_MANUALS_DIR),
                        help=f"Final PDF folder (default: {DEFAULT_MANUALS_DIR}).")
    parser.add_argument("--sorted-output", default=None,
                        help="Optional path to write the sorted CSV. Default: <input>_sorted.csv.")
    parser.add_argument("--max-results", type=int, default=10,
                        help="Google result count to scan for each missing PDF.")
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR),
                        help="Chrome profile dir passed to sell.py/ebay_sell.py.")
    parser.add_argument("--links-json", default=str(DEFAULT_LINKS_JSON),
                        help="ebay_links.json path to update after a created listing ID is detected.")
    parser.add_argument("--sell-script", default=str(SCRIPT_DIR / "sell.py"),
                        help="Path to sell.py.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Download/sort, then print sell.py commands without running them.")
    parser.add_argument("--download-only", action="store_true",
                        help="Only sort and download PDFs; do not call sell.py.")
    parser.add_argument("--skip-download", action="store_true",
                        help="Do not search online; only process rows whose PDF already exists.")
    parser.add_argument("--list", dest="do_list", action="store_true",
                        help="Pass --list to sell.py. This can create live listings.")
    parser.add_argument("--pause", action="store_true",
                        help="Pass --pause to sell.py instead of preview/list.")
    parser.add_argument("--angle", action="store_true",
                        help="Pass --angle to sell.py for angled cover generation.")
    parser.add_argument("--ratio", type=float, default=None,
                        help="Optional ratio passed to sell.py.")
    parser.add_argument("--keep-going", action="store_true",
                        help="Continue with the next row if download or listing fails.")
    return parser.parse_args()


def find_default_csv() -> Path:
    candidates = []
    for pattern in ("*_stock_data.csv", "*_sales_data.csv", "*.csv"):
        candidates.extend(SCRIPT_DIR.glob(pattern))

    candidates = [p for p in candidates if p.is_file() and not p.name.endswith("_sorted.csv")]
    if not candidates:
        raise FileNotFoundError("No CSV found. Provide --csv.")

    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_rows(csv_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    if not rows:
        raise ValueError(f"CSV has no rows: {csv_path}")

    rows, fieldnames = normalize_input_rows(rows, fieldnames)

    if "title" not in fieldnames:
        raise ValueError("CSV must contain a 'title' column, or a supported alias such as 'competitor_title'.")

    return rows, fieldnames


def extract_item_id_from_url(url: str) -> str:
    match = re.search(r"/itm/(\d+)", url or "")
    return match.group(1) if match else ""


def normalize_input_rows(rows: list[dict[str, str]], fieldnames: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    aliases = {
        "title": "competitor_title",
        "avg_price": "competitor_avg_price",
        "estimated_total": "competitor_estimated_total",
        "url": "competitor_url",
    }

    for canonical, alias in aliases.items():
        if canonical not in fieldnames and alias in fieldnames:
            fieldnames.append(canonical)
            for row in rows:
                row[canonical] = row.get(alias, "")

    if "item_id" not in fieldnames and "url" in fieldnames:
        fieldnames.append("item_id")
        for row in rows:
            row["item_id"] = extract_item_id_from_url(row.get("url", ""))

    return rows, fieldnames


def value_for_sort(row: dict[str, str]) -> float:
    for key in ("stock_estimated_total", "total_estimated_sales", "estimated_total", "price"):
        raw = (row.get(key) or "").replace("$", "").replace(",", "").strip()
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return 0.0


def competitor_price_from_row(row: dict[str, str]) -> float | None:
    for key in ("avg_price", "price", "price_text"):
        raw = (row.get(key) or "").replace("$", "").replace(",", "").strip()
        if not raw:
            continue
        try:
            price = float(raw)
        except ValueError:
            continue
        if price > 0:
            return price
    return None


def sorted_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(rows, key=value_for_sort, reverse=True)


def write_sorted_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_resume_start(progress_file: Path, csv_path: Path) -> int | None:
    if not progress_file.exists():
        return None

    try:
        data = json.loads(progress_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if data.get("csv_path") != str(csv_path):
        return None

    next_start_at = data.get("next_start_at")
    return next_start_at if isinstance(next_start_at, int) and next_start_at > 1 else None


def save_resume_start(progress_file: Path, csv_path: Path, next_start_at: int) -> None:
    data = {
        "csv_path": str(csv_path),
        "next_start_at": next_start_at,
    }
    progress_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def clear_resume_start(progress_file: Path, csv_path: Path) -> None:
    if not progress_file.exists():
        return

    try:
        data = json.loads(progress_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    if data.get("csv_path") == str(csv_path):
        progress_file.unlink()


def close_driver(driver) -> None:
    if driver is None:
        return
    try:
        driver.quit()
    except WebDriverException:
        pass


def pdf_path_for_title(manuals_dir: Path, title: str) -> Path:
    meaningful_title = downloadpdf.clean_ebay_title(title)
    return manuals_dir / downloadpdf.safe_filename(meaningful_title)


def listing_title_from_source(title: str) -> str:
    """Remove competitor suffixes from source listing titles."""

    return downloadpdf.clean_ebay_title(title or "")


def download_pdf_for_row(driver, row: dict[str, str], output_path: Path, max_results: int) -> bool:
    title = row.get("title", "").strip()
    meaningful_title = downloadpdf.clean_ebay_title(title)
    search_query = meaningful_title + " pdf"

    print(f"\nSearching PDF for: {title}")
    print(f"Query: {search_query}")

    results = downloadpdf.google_search(driver, search_query, max_results=max_results)
    if not results:
        print("No Google results found.")
        return False

    for link in results:
        print(f"Checking: {link}")

        if downloadpdf.is_pdf_url(link):
            if downloadpdf.download_pdf(driver, link, str(output_path)):
                return True

        pdf_links = downloadpdf.find_pdf_links_on_page(link)
        for pdf_link in pdf_links:
            print(f"PDF candidate: {pdf_link}")
            if downloadpdf.download_pdf(driver, pdf_link, str(output_path)):
                return True

    return False


def build_sell_command(args: argparse.Namespace, row: dict[str, str], pdf_path: Path) -> list[str]:
    source_title = (row.get("title") or "").strip()
    title = listing_title_from_source(source_title)
    seed_item_id = (row.get("item_id") or "").strip()

    cmd = [
        sys.executable,
        str(Path(args.sell_script).expanduser().resolve()),
        "--pdf", str(pdf_path.resolve()),
        "--title", title,
        "--profile-dir", str(Path(args.profile_dir).expanduser().resolve()),
        "--no-wait-exit",
        "--update-links-json", str(Path(args.links_json).expanduser().resolve()),
        "--links-title", title,
    ]

    if seed_item_id.isdigit():
        cmd += ["--seed-item-id", seed_item_id]

    competitor_price = competitor_price_from_row(row)
    if competitor_price is not None:
        cmd += ["--competitor-price", f"{competitor_price:.2f}"]

    if args.do_list:
        cmd += ["--list"]
    elif args.pause:
        cmd += ["--pause"]
    else:
        cmd += ["--preview"]
    if args.angle:
        cmd += ["--angle"]
    if args.ratio is not None:
        cmd += ["--ratio", str(args.ratio)]

    return cmd


def run_sell_command(cmd: list[str], dry_run: bool) -> bool:
    printable = " ".join(shlex.quote(part) for part in cmd)
    print("\nSell command:")
    print(printable)

    if dry_run:
        return True

    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    return result.returncode == 0


def download_pdf_with_driver_restart(driver, manuals_dir: Path, row: dict[str, str], pdf_path: Path, max_results: int):
    if driver is None:
        driver = downloadpdf.setup_driver(str(manuals_dir))

    try:
        return download_pdf_for_row(driver, row, pdf_path, max_results), driver
    except WebDriverException as e:
        print(f"Download browser session failed: {e.__class__.__name__}. Restarting Chrome and retrying once.")
        close_driver(driver)
        driver = downloadpdf.setup_driver(str(manuals_dir))
        try:
            return download_pdf_for_row(driver, row, pdf_path, max_results), driver
        except WebDriverException:
            close_driver(driver)
            raise


def main() -> None:
    args = parse_args()

    csv_path = Path(args.csv_path).expanduser().resolve() if args.csv_path else find_default_csv()
    manuals_dir = Path(args.manuals_dir).expanduser().resolve()
    progress_file = Path(args.progress_file).expanduser().resolve()
    manuals_dir.mkdir(parents=True, exist_ok=True)

    rows, fieldnames = read_csv_rows(csv_path)
    rows = sorted_rows(rows)

    sorted_output = (
        Path(args.sorted_output).expanduser().resolve()
        if args.sorted_output
        else csv_path.with_name(csv_path.stem + "_sorted.csv")
    )
    write_sorted_csv(sorted_output, rows, fieldnames)
    print(f"Sorted CSV saved: {sorted_output}")

    start_at = args.start_at or 1
    if args.start_at is None and not args.no_resume:
        resume_start_at = load_resume_start(progress_file, csv_path)
        if resume_start_at is not None:
            start_at = resume_start_at
            print(f"Resuming at row {start_at} from: {progress_file}")

    if start_at < 1:
        raise ValueError("--start-at must be >= 1")
    selected = rows[start_at - 1:]
    if args.limit is not None:
        selected = selected[:args.limit]

    print(f"Rows selected: {len(selected)}")
    if args.do_list:
        print("Mode: LIST live listings")
    elif args.pause:
        print("Mode: pause after draft edits")
    else:
        print("Mode: preview/review only")

    driver = None
    failures = 0

    try:
        for idx, row in enumerate(selected, start=start_at):
            title = (row.get("title") or "").strip()
            if not title:
                print(f"\n[{idx}] Skipping row with empty title.")
                continue

            pdf_path = pdf_path_for_title(manuals_dir, title)
            print(f"\n[{idx}] {title}")
            print(f"Estimated value: {value_for_sort(row):,.2f}")
            print(f"PDF path: {pdf_path}")

            if pdf_path.exists() and not downloadpdf.validate_downloaded_pdf(str(pdf_path)):
                print("Existing PDF is invalid; re-downloading.")

            if not pdf_path.exists():
                if args.skip_download:
                    print("PDF missing and --skip-download is active. Skipping row.")
                    failures += 1
                    if not args.keep_going:
                        break
                    continue

                try:
                    ok, driver = download_pdf_with_driver_restart(driver, manuals_dir, row, pdf_path, args.max_results)
                except WebDriverException as e:
                    driver = None
                    print(f"PDF download browser failed after retry: {e.__class__.__name__}.")
                    ok = False
                if not ok or not pdf_path.exists():
                    print("PDF download failed.")
                    failures += 1
                    if not args.keep_going:
                        break
                    continue
            else:
                print("PDF already exists; skipping download.")

            if args.download_only:
                save_resume_start(progress_file, csv_path, idx + 1)
                continue

            cmd = build_sell_command(args, row, pdf_path)
            ok = run_sell_command(cmd, dry_run=args.dry_run)
            if not ok:
                print("sell.py failed for this row.")
                failures += 1
                if not args.keep_going:
                    break
                continue

            save_resume_start(progress_file, csv_path, idx + 1)

    finally:
        if driver is not None:
            print("\nClosing download Chrome...")
            close_driver(driver)

    if failures:
        raise SystemExit(f"Completed with {failures} failure(s).")

    clear_resume_start(progress_file, csv_path)

    print("\nCompleted successfully.")


if __name__ == "__main__":
    main()
