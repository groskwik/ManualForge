#!/usr/bin/env python
import os
import re
import subprocess
import time
from PyPDF2 import PdfReader
import psutil
import json
from pathlib import Path
import csv
import sys
import threading
import queue

# Path to SumatraPDF executable
SUMATRA_PATH = r"C:\portableapps\sumatrapdf\sumatrapdf.exe"

# Folders where PDFs are stored
PDF_FOLDERS = [
    r"C:\Users\benoi\Downloads\ebay_manuals",
    r"C:\Users\benoi\Downloads\manuals",
    r"/home/benoit/Downloads/manuals",
    r"/home/benoit/Downloads/ebay_manuals"
]

# Hard-coded CSV path (as requested)
MANUALS_CSV_PATH = r"C:\Users\benoi\Downloads\ManualForge\manuals.csv"

# Available printers
PRINTERS = {
    "1": "Brother HL-L8360CDW Series",
    "2": "Brother HL-L8360CDW Series 2"
}


def other_python_scripts_running():
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] == 'python.exe' and proc.info['pid'] != current_pid:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def select_printer():
    """Prompts the user to select a printer."""
    print("\nSelect a printer:")
    for key, name in PRINTERS.items():
        print(f"{key}. {name}")

    choice = input("Enter the number of the printer: ").strip()
    return PRINTERS.get(choice, PRINTERS["1"])


def find_pdf(partial_name):
    """Finds a PDF file in the specified folders that contains the given string (case insensitive)."""
    partial_name_lower = partial_name.lower()

    matching_files = []
    for folder in PDF_FOLDERS:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if f.lower().endswith(".pdf") and partial_name_lower in f.lower():
                matching_files.append(os.path.join(folder, f))

    if not matching_files:
        print(f"No PDF found containing: {partial_name}")
        return None

    if len(matching_files) > 1:
        print("\nMultiple matches found:")
        for idx, file in enumerate(matching_files, start=1):
            print(f"{idx}. {os.path.basename(file)}")
        choice = input("\nEnter the number of the file you want to print: ").strip()
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(matching_files):
            print("Invalid choice.")
            return None
        return matching_files[int(choice) - 1]

    return matching_files[0]  # Return the only match


def get_pdf_page_count(pdf_path):
    """Returns the number of pages in the given PDF file."""
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            return len(reader.pages)
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None


def parse_page_token(token):
    """
    Parse a token that might represent a page selection.
    Returns:
      ("single", page) or ("range", start, end) or (None, ...)
    """
    t = token.strip()
    if t.isdigit():
        return ("single", int(t))
    if "-" in t:
        a, b = t.split("-", 1)
        a, b = a.strip(), b.strip()
        if a.isdigit() and b.isdigit():
            return ("range", int(a), int(b))
    return (None,)


def extract_page_selector_index(parts):
    """
    Find the index in the comma-split setting parts that corresponds to page selection.
    Your conventions are:
      - either a single number token (e.g. "102")
      - or a range token (e.g. "3-34")
    Returns index or None.
    """
    for i, part in enumerate(parts):
        kind = parse_page_token(part)[0]
        if kind in ("single", "range"):
            return i
    return None


def clip_setting_to_custom_range(setting, custom_start, custom_end):
    """
    Given one setting string and a custom range [custom_start, custom_end],
    return:
      - None if no intersection
      - otherwise, a NEW setting string with the page selector clipped
        (keeping all other parameters intact).
    """
    parts = [p.strip() for p in setting.split(",")]
    idx = extract_page_selector_index(parts)
    if idx is None:
        # No page selector found => leave it untouched (unusual for your DB)
        return setting

    tok = parts[idx]
    parsed = parse_page_token(tok)

    if parsed[0] == "single":
        p = parsed[1]
        if custom_start <= p <= custom_end:
            return setting
        return None

    if parsed[0] == "range":
        a, b = parsed[1], parsed[2]
        ia = max(a, custom_start)
        ib = min(b, custom_end)
        if ia > ib:
            return None
        parts[idx] = f"{ia}-{ib}"
        return ",".join(parts)

    return None


def compute_delay_between_batches(printer_name):
    """
    Keep your existing logic (including the special-case printer).
    """
    delay_between_batches = 240
    if printer_name == "Brother HL-L3290CDW [Wireless]":
        delay_between_batches = 480
    return delay_between_batches


def print_one_setting(pdf_path, setting, printer_name, batch_size=70, small_range_no_wait_threshold=10):
    """
    Print according to one setting entry, using your SumatraPDF command format.
    Handles both single pages and ranges with batching.

    - If the total page span in THIS setting is < small_range_no_wait_threshold (default 10),
      do NOT wait between batches (or after it).
    - Larger ranges keep the normal delay between batches.
    """
    delay_between_batches = compute_delay_between_batches(printer_name)

    setting_parts = [p.strip() for p in setting.split(",")]
    page_idx = extract_page_selector_index(setting_parts)

    # Defensive: if no page selector token, just print once
    if page_idx is None:
        print(f"Printing (no explicit page selector found): {setting}")
        subprocess.run([SUMATRA_PATH, "-print-to", printer_name, "-print-settings", setting, pdf_path], check=True)
        time.sleep(10)
        return

    page_token = setting_parts[page_idx]
    parsed = parse_page_token(page_token)

    if parsed[0] == "single":
        p = parsed[1]
        print(f"Printing page {p} with settings: {setting}")
        subprocess.run([SUMATRA_PATH, "-print-to", printer_name, "-print-settings", setting, pdf_path], check=True)
        time.sleep(10)
        return

    if parsed[0] == "range":
        start_page, end_page = parsed[1], parsed[2]
        current_page = start_page

        total_span = end_page - start_page + 1
        no_wait_for_this_setting = total_span < small_range_no_wait_threshold

        while current_page <= end_page:
            batch_end = min(current_page + batch_size - 1, end_page)
            batch_range = f"{current_page}-{batch_end}"

            # replace only the page token occurrence at that index
            batch_parts = list(setting_parts)
            batch_parts[page_idx] = batch_range
            batch_setting = ",".join(batch_parts)

            print(f"Printing pages {batch_range} on {printer_name}")
            subprocess.run([SUMATRA_PATH, "-print-to", printer_name, "-print-settings", batch_setting, pdf_path], check=True)

            current_page = batch_end + 1

            # Delay only if:
            #  - there is another batch to print for this setting
            #  - AND this setting is not considered a "small range"
            if current_page <= end_page and (not no_wait_for_this_setting):
                print(f"Waiting for {delay_between_batches // 60} minutes before next batch...")
                time.sleep(delay_between_batches)

        return

    # Fallback
    print(f"Printing (unrecognized page selector): {setting}")
    subprocess.run([SUMATRA_PATH, "-print-to", printer_name, "-print-settings", setting, pdf_path], check=True)
    time.sleep(10)


# -------------------- NEW: manuals.csv lookup + timed prompt --------------------

def load_manuals_index(csv_path: str):
    """
    Build a lookup by normalized title and by normalized PDF stem.
    Returns:
      - rows: list of dict rows
      - by_title: dict[norm_title] -> list[row]
    """
    if not os.path.isfile(csv_path):
        print(f"[WARN] manuals.csv not found at: {csv_path} (skipping existence check)")
        return [], {}

    rows = []
    by_title = {}
    try:
        with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
                t = (r.get("title") or "").strip()
                nt = normalize_for_db(t)
                if nt:
                    by_title.setdefault(nt, []).append(r)
    except Exception as e:
        print(f"[WARN] Failed to read manuals.csv ({csv_path}): {e}")
        return [], {}

    return rows, by_title


def normalize_for_db(s: str) -> str:
    """
    Aggressive normalization for matching:
    - lowercase
    - keep alnum tokens
    - join with single space
    """
    s = (s or "").lower()
    tokens = re.findall(r"[a-z0-9]+", s)
    return " ".join(tokens)


def interpret_manuals_row(r: dict) -> str:
    """
    Interpret one manuals.csv row with your rules:
    - box column reports BOX 1/2/3/BOXL etc.
    - cover column == '1' => cover printed only
    """
    box = (r.get("box") or "").strip()
    cover = (r.get("cover") or "").strip()

    parts = []
    if box:
        parts.append(f"in {box}")
    if cover == "1":
        parts.append("cover-only (cover=1)")
    elif cover == "0":
        parts.append("not cover-only (cover=0)")
    elif cover:
        parts.append(f"cover={cover}")

    if not parts:
        return "present (no box/cover info)"
    return ", ".join(parts)


def timed_input(prompt: str, timeout_s: int = 30) -> str | None:
    """
    Wait up to timeout_s seconds for user input.
    Returns:
      - string (possibly empty) if user typed something and pressed Enter
      - None if timeout expires with no input (batch mode)
    Works on Windows and Linux (uses a background thread).
    """
    q: "queue.Queue[str]" = queue.Queue()

    def worker():
        try:
            s = input(prompt)
        except EOFError:
            s = ""
        q.put(s)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    try:
        return q.get(timeout=timeout_s)
    except queue.Empty:
        return None


def check_already_in_manuals_csv(pdf_path: str, manuals_by_title: dict):
    """
    Check if selected PDF is already referenced in manuals.csv.
    We match on:
      - PDF stem
      - PDF stem without aggressive punctuation differences (normalize_for_db)
    """
    stem = Path(pdf_path).stem
    nstem = normalize_for_db(stem)

    hits = manuals_by_title.get(nstem, [])
    return stem, hits


# -------------------- printing flow --------------------

def print_pdf(printer_name, partial_name):
    """Prints a PDF with predefined settings or user-defined page ranges."""
    pdf_path = find_pdf(partial_name)
    if not pdf_path:
        return

    # NEW: check manuals.csv BEFORE printing (after user chose a specific PDF)
    _, manuals_by_title = load_manuals_index(MANUALS_CSV_PATH)
    stem, hits = check_already_in_manuals_csv(pdf_path, manuals_by_title)

    if hits:
        print("\n[INFO] This PDF seems to already exist in manuals.csv:")
        for idx, r in enumerate(hits, start=1):
            t = (r.get("title") or "").strip()
            print(f"  {idx}) title='{t}' -> {interpret_manuals_row(r)}")

        resp = timed_input("\nPress Enter to continue printing, or type 's' to skip this print (30s timeout): ", 30)
        if resp is None:
            print("\n[INFO] No response after 30 seconds -> continuing (batch mode).")
        else:
            resp = resp.strip().lower()
            if resp == "s":
                print("[INFO] Skipping print as requested.")
                return
            # any other response (including empty) continues

    page_count = get_pdf_page_count(pdf_path)
    if page_count:
        print(f"The document '{os.path.basename(pdf_path)}' has {page_count} pages.")
    else:
        print("Unable to determine the number of pages.")
        return

    file_name_without_ext = os.path.splitext(os.path.basename(pdf_path))[0].lower()

    DB_PATH = Path(__file__).with_name("print_settings.json")
    with DB_PATH.open("r", encoding="utf-8") as f:
        _RAW_PRINT_SETTINGS = json.load(f)

    PRINT_SETTINGS = {k.lower(): v for k, v in _RAW_PRINT_SETTINGS.items()}

    # Default if no entry found
    default_setting = f"color,1-{page_count},duplex,fit,paper=letter"
    print_settings = PRINT_SETTINGS.get(file_name_without_ext, [default_setting])

    print("")
    print(f"Found settings for {pdf_path}:")
    for setting in print_settings:
        print(setting)

    custom_range = input("\nEnter the page range to print (e.g., 40-215), or press Enter for default: ").strip()

    effective_settings = list(print_settings)

    if custom_range:
        if "-" not in custom_range:
            print("Invalid custom range format. Use like 40-215.")
            return
        a1, b1 = custom_range.split("-", 1)
        a1, b1 = a1.strip(), b1.strip()
        if not (a1.isdigit() and b1.isdigit()):
            print("Invalid custom range format. Use like 40-215.")
            return

        custom_start, custom_end = int(a1), int(b1)
        if custom_start < 1:
            custom_start = 1
        if custom_end > page_count:
            custom_end = page_count
        if custom_start > custom_end:
            print("Invalid custom range: start > end.")
            return

        clipped = []
        for setting in print_settings:
            new_setting = clip_setting_to_custom_range(setting, custom_start, custom_end)
            if new_setting is not None:
                clipped.append(new_setting)

        if not clipped:
            print(f"No pages to print after applying custom range {custom_start}-{custom_end}.")
            return

        effective_settings = clipped

        print("\nEffective settings after applying custom range:")
        for s in effective_settings:
            print(s)

    print(f"\nPrinting: {os.path.basename(pdf_path)} on {printer_name}...")

    batch_size = 70
    for setting in effective_settings:
        # removes wait only when THIS setting range < 10 pages
        print_one_setting(
            pdf_path,
            setting,
            printer_name,
            batch_size=batch_size,
            small_range_no_wait_threshold=10,
        )


if __name__ == "__main__":
    selected_printer = select_printer()
    file_name = input("\nEnter part of the PDF filename: ").strip()
    print_pdf(selected_printer, file_name)
