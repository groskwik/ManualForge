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
import argparse
import tempfile

try:
    import msvcrt
except ImportError:
    msvcrt = None

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


def is_duplex_setting(setting):
    parts = [p.strip().lower() for p in setting.split(",")]
    return "duplex" in parts or "duplexshort" in parts


def extract_page_selector_indices(parts):
    return [i for i, part in enumerate(parts) if parse_page_token(part)[0] in ("single", "range")]


def setting_needs_manual_2sided(setting):
    parts = [p.strip() for p in setting.split(",")]
    page_indices = extract_page_selector_indices(parts)
    if len(page_indices) > 1:
        return True
    if not page_indices:
        return True

    parsed = parse_page_token(parts[page_indices[0]])
    return parsed[0] == "range" and parsed[1] != parsed[2]


def make_simplex_setting(setting):
    parts = [p.strip() for p in setting.split(",")]
    has_duplexshort = any(p.lower() == "duplexshort" for p in parts)
    new_parts = []
    for part in parts:
        low = part.lower()
        if low == "duplex":
            new_parts.append("simplex")
        elif low == "duplexshort":
            new_parts.append("simplex")
        elif has_duplexshort and low == "landscape":
            continue
        elif low not in ("even", "odd"):
            new_parts.append(part)
    return ",".join(new_parts)


def make_manual_2sided_setting(setting, side):
    parts = [p.strip() for p in setting.split(",")]
    page_indices = extract_page_selector_indices(parts)
    last_page_idx = page_indices[-1] if page_indices else None

    new_parts = make_simplex_setting(setting).split(",")

    if side not in [p.lower() for p in new_parts]:
        insert_at = last_page_idx + 1 if last_page_idx is not None else len(new_parts)
        new_parts.insert(insert_at, side)

    return ",".join(new_parts)


def describe_setting_pages(setting):
    parts = [p.strip() for p in setting.split(",")]
    page_indices = extract_page_selector_indices(parts)
    if not page_indices:
        return setting
    return ",".join(parts[i] for i in page_indices)


def compute_delay_between_batches(printer_name):
    """
    Keep your existing logic (including the special-case printer).
    """
    delay_between_batches = 240
    if printer_name == "Brother HL-L3290CDW [Wireless]":
        delay_between_batches = 480
    return delay_between_batches


def sumatra_command(printer_name, setting, pdf_path):
    return [SUMATRA_PATH, "-print-to", printer_name, "-print-settings", setting, pdf_path]


def display_sumatra_command(command):
    print("SumatraPDF command:")
    print(subprocess.list2cmdline(command))


def run_sumatra_command(printer_name, setting, pdf_path):
    command = sumatra_command(printer_name, setting, pdf_path)
    display_sumatra_command(command)
    subprocess.run(command, check=True)


def sumatra_commands_for_setting(pdf_path, setting, printer_name, batch_size=70):
    setting_parts = [p.strip() for p in setting.split(",")]
    page_idx = extract_page_selector_index(setting_parts)

    if page_idx is None:
        return [sumatra_command(printer_name, setting, pdf_path)]

    parsed = parse_page_token(setting_parts[page_idx])
    if parsed[0] != "range":
        return [sumatra_command(printer_name, setting, pdf_path)]

    start_page, end_page = parsed[1], parsed[2]
    commands = []
    current_page = start_page
    while current_page <= end_page:
        batch_end = min(current_page + batch_size - 1, end_page)
        batch_parts = list(setting_parts)
        batch_parts[page_idx] = f"{current_page}-{batch_end}"
        commands.append(sumatra_command(printer_name, ",".join(batch_parts), pdf_path))
        current_page = batch_end + 1
    return commands


def display_sumatra_commands_for_settings(pdf_path, settings, printer_name, batch_size=70):
    for setting in settings:
        for command in sumatra_commands_for_setting(pdf_path, setting, printer_name, batch_size=batch_size):
            display_sumatra_command(command)


def has_short_edge_setting(settings):
    for setting in settings:
        parts = [p.strip().lower() for p in setting.split(",")]
        if "duplexshort" in parts or "simplexshort" in parts:
            return True
    return False


def confirm_short_edge_second_pass(settings):
    if not has_short_edge_setting(settings):
        return True

    print("\nWARNING: This job uses duplexshort / simplexshort.")
    print("Put the even pages face up, with the top of the paper down.")
    resp = input("Type y to continue with the second pass: ").strip().lower()
    if resp == "y":
        return True
    print("Second pass cancelled.")
    return False


def pages_from_setting(setting, max_page):
    parts = [p.strip() for p in setting.split(",")]
    pages = []
    for idx in extract_page_selector_indices(parts):
        parsed = parse_page_token(parts[idx])
        if parsed[0] == "single":
            p = parsed[1]
            if 1 <= p <= max_page:
                pages.append(p)
        elif parsed[0] == "range":
            a, b = parsed[1], parsed[2]
            pages.extend(range(max(1, a), min(max_page, b) + 1))
    return pages


def selected_page_bounds(settings, page_count):
    pages = []
    for setting in settings:
        pages.extend(pages_from_setting(setting, page_count))
    if not pages:
        return 1, page_count
    return min(pages), max(pages)


def make_batch_pair_setting(setting):
    parts = []
    for part in [p.strip() for p in setting.split(",")]:
        low = part.lower()
        if low == "simplex":
            parts.append("duplex")
        elif low == "simplexshort":
            parts.append("duplexshort")
        else:
            parts.append(part)
    if not is_duplex_setting(",".join(parts)):
        parts.append("duplex")
    return ",".join(parts)


def replace_setting_page_tokens(setting, replacements):
    parts = [p.strip() for p in setting.split(",")]
    for idx in extract_page_selector_indices(parts):
        if idx in replacements:
            parts[idx] = replacements[idx]
    return ",".join(parts)


def extend_setting_to_page(setting, end_page):
    parts = [p.strip() for p in setting.split(",")]
    page_indices = extract_page_selector_indices(parts)
    if not page_indices:
        parts.insert(1 if parts else 0, str(end_page))
        return ",".join(parts)

    idx = page_indices[-1]
    parsed = parse_page_token(parts[idx])
    if parsed[0] in ("single", "range"):
        parts[idx] = f"{parsed[1]}-{end_page}"
    return ",".join(parts)


def rotate_page_180(page):
    if hasattr(page, "rotate"):
        return page.rotate(180)
    if hasattr(page, "rotate_clockwise"):
        return page.rotate_clockwise(180)
    raise RuntimeError("PDF library does not support page rotation")


def prepare_pdf_for_manual_2sided(pdf_path, effective_settings, page_count, temp_dir):
    start_page, end_page = selected_page_bounds(effective_settings, page_count)
    simplex_pages = set()
    for setting in effective_settings:
        if not (is_duplex_setting(setting) and setting_needs_manual_2sided(setting)):
            simplex_pages.update(pages_from_setting(setting, page_count))
    simplex_pages = {p for p in simplex_pages if start_page <= p <= end_page}

    short_edge = has_short_edge_setting(effective_settings)
    mapping = {}
    new_page_no = 1
    for old_page in range(start_page, end_page + 1):
        mapping[old_page] = new_page_no
        new_page_no += 1
        if old_page in simplex_pages:
            new_page_no += 1

    new_total = new_page_no - 1
    needs_final_blank = new_total % 2 == 1
    if needs_final_blank:
        new_total += 1

    needs_temp_pdf = start_page != 1 or end_page != page_count or simplex_pages or needs_final_blank or short_edge
    output_pdf = pdf_path

    if needs_temp_pdf:
        try:
            from pypdf import PdfReader, PdfWriter  # type: ignore
        except Exception:
            from PyPDF2 import PdfReader, PdfWriter  # type: ignore

        reader = PdfReader(str(pdf_path))
        writer = PdfWriter()
        output_page_no = 1
        last_selected_page = None
        for page_index in range(start_page, end_page + 1):
            page = reader.pages[page_index - 1]
            last_selected_page = page
            if short_edge and output_page_no % 2 == 1:
                page = rotate_page_180(page)
            writer.add_page(page)
            output_page_no += 1
            if page_index in simplex_pages:
                box = page.mediabox
                writer.add_blank_page(width=float(box.width), height=float(box.height))
                output_page_no += 1
        if needs_final_blank:
            blank_source = last_selected_page or reader.pages[end_page - 1]
            box = blank_source.mediabox
            writer.add_blank_page(width=float(box.width), height=float(box.height))

        output_pdf = os.path.join(temp_dir, f"{Path(pdf_path).stem}__manual2sided.pdf")
        with open(output_pdf, "wb") as f:
            writer.write(f)

    remapped_settings = []
    for setting in effective_settings:
        replacements = {}
        parts = [p.strip() for p in setting.split(",")]
        for idx in extract_page_selector_indices(parts):
            parsed = parse_page_token(parts[idx])
            if parsed[0] == "single":
                p = parsed[1]
                if p in mapping:
                    start = mapping[p]
                    replacements[idx] = f"{start}-{start + 1}" if p in simplex_pages else str(start)
            elif parsed[0] == "range":
                a, b = parsed[1], parsed[2]
                a, b = max(a, start_page), min(b, end_page)
                if a in mapping and b in mapping:
                    range_pages = list(range(a, b + 1))
                    mapped_start = mapping[a]
                    mapped_end = mapping[b] + (1 if any(p in simplex_pages for p in range_pages) else 0)
                    replacements[idx] = f"{mapped_start}-{mapped_end}"

        remapped = replace_setting_page_tokens(setting, replacements)
        if any(p in simplex_pages for p in pages_from_setting(setting, page_count)):
            remapped = make_batch_pair_setting(remapped)
        remapped_settings.append(remapped)

    if needs_final_blank and remapped_settings:
        remapped_settings[-1] = make_batch_pair_setting(extend_setting_to_page(remapped_settings[-1], new_total))

    return output_pdf, remapped_settings


def printer_exists(printer_name):
    if os.name != "nt":
        return False

    ps_script = "$p = Get-CimInstance Win32_Printer | Where-Object { $_.Name -eq $env:PRINTER_NAME }; if ($p) { exit 0 } else { exit 1 }"
    env = os.environ.copy()
    env["PRINTER_NAME"] = printer_name
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    except OSError:
        return False


def countdown_allow_cancel(seconds):
    print(f"\nSecond pass starts in {seconds} seconds. Press any key to cancel.")
    if msvcrt is None:
        input("Press Enter to start the second pass, or Ctrl+C to cancel...")
        return True

    while msvcrt.kbhit():
        msvcrt.getch()

    for remaining in range(seconds, 0, -1):
        print(f"Starting second pass in {remaining}...", end="\r", flush=True)
        for _ in range(10):
            time.sleep(0.1)
            if msvcrt.kbhit():
                msvcrt.getch()
                print("\nSecond pass cancelled.")
                return False
    print("Starting second pass now.          ")
    return True


def print_one_setting(pdf_path, setting, printer_name, batch_size=70, small_range_no_wait_threshold=10, delay_between_batches=None):
    """
    Print according to one setting entry, using your SumatraPDF command format.
    Handles both single pages and ranges with batching.

    - If the total page span in THIS setting is < small_range_no_wait_threshold (default 10),
      do NOT wait between batches (or after it).
    - Larger ranges keep the normal delay between batches.
    """
    if delay_between_batches is None:
        delay_between_batches = compute_delay_between_batches(printer_name)

    setting_parts = [p.strip() for p in setting.split(",")]
    page_idx = extract_page_selector_index(setting_parts)

    # Defensive: if no page selector token, just print once
    if page_idx is None:
        print(f"Printing (no explicit page selector found): {setting}")
        run_sumatra_command(printer_name, setting, pdf_path)
        time.sleep(10)
        return

    page_token = setting_parts[page_idx]
    parsed = parse_page_token(page_token)

    if parsed[0] == "single":
        p = parsed[1]
        print(f"Printing page {p} with settings: {setting}")
        run_sumatra_command(printer_name, setting, pdf_path)
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
            run_sumatra_command(printer_name, batch_setting, pdf_path)

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
    run_sumatra_command(printer_name, setting, pdf_path)
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

def print_pdf(printer_name, partial_name, manual_2sided=False, second_pass_only=False):
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

    batch_size = 70

    if manual_2sided or second_pass_only:
        quiet_printer_name = f"{printer_name} Quiet"
        if not printer_exists(quiet_printer_name):
            print(f"\nManual 2-sided mode requires a quiet printer named:")
            print(quiet_printer_name)
            print("No matching quiet printer was found, so printing will not start.")
            print("This printer is assumed to have working automatic double-sided printing.")
            return

        with tempfile.TemporaryDirectory(prefix="myprint_manual2sided_") as temp_dir:
            manual_pdf_path, manual_settings = prepare_pdf_for_manual_2sided(
                pdf_path,
                effective_settings,
                page_count,
                temp_dir,
            )

            first_pass_settings = []
            second_pass_settings = []

            for setting in manual_settings:
                if is_duplex_setting(setting) and setting_needs_manual_2sided(setting):
                    first_pass_settings.append(make_manual_2sided_setting(setting, "even"))
                    second_pass_settings.append(make_manual_2sided_setting(setting, "odd"))
                else:
                    pair_setting = make_batch_pair_setting(setting)
                    first_pass_settings.append(make_manual_2sided_setting(pair_setting, "even"))
                    second_pass_settings.append(make_manual_2sided_setting(pair_setting, "odd"))

            if second_pass_only:
                if not second_pass_settings:
                    print("\nNo duplex settings found, so no manual 2-sided second pass is needed.")
                    return

                print(f"\nSecond pass only: {os.path.basename(pdf_path)} on {quiet_printer_name}...")
                print(f"\nSecond pass commands that will be used on {quiet_printer_name}:")
                display_sumatra_commands_for_settings(
                    manual_pdf_path,
                    second_pass_settings,
                    quiet_printer_name,
                    batch_size=batch_size,
                )
                input("Press Enter when the paper is loaded and ready for the odd-page second pass...")
                if not countdown_allow_cancel(15):
                    return

                for setting in second_pass_settings:
                    print_one_setting(
                        manual_pdf_path,
                        setting,
                        quiet_printer_name,
                        batch_size=batch_size,
                        small_range_no_wait_threshold=10,
                        delay_between_batches=90,
                    )
                return

            print(f"\nManual 2-sided first pass: {os.path.basename(pdf_path)} on {printer_name}...")
            for setting in first_pass_settings:
                print_one_setting(
                    manual_pdf_path,
                    setting,
                    printer_name,
                    batch_size=batch_size,
                    small_range_no_wait_threshold=10,
                    delay_between_batches=60,
                )

            if not second_pass_settings:
                print("\nNo duplex settings found, so no manual 2-sided second pass is needed.")
                return

            print("\nFirst pass complete.")
            print("Put the paper back in the tray: even pages face up, top of the paper down.")

            print(f"\nSecond pass commands that will be used on {quiet_printer_name}:")
            display_sumatra_commands_for_settings(
                manual_pdf_path,
                second_pass_settings,
                quiet_printer_name,
                batch_size=batch_size,
            )
            input("Press Enter when ready to start the odd-page second pass...")
            if not countdown_allow_cancel(15):
                return

            print(f"\nManual 2-sided second pass: {os.path.basename(pdf_path)} on {quiet_printer_name}...")
            for setting in second_pass_settings:
                print_one_setting(
                    manual_pdf_path,
                    setting,
                    quiet_printer_name,
                    batch_size=batch_size,
                    small_range_no_wait_threshold=10,
                    delay_between_batches=90,
                )
            return

    print(f"\nPrinting: {os.path.basename(pdf_path)} on {printer_name}...")

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
    parser = argparse.ArgumentParser(description="Print a manual PDF with saved SumatraPDF settings.")
    parser.add_argument(
        "-manual2sided",
        action="store_true",
        help="Print duplex settings manually in two simplex passes: even pages first, then odd pages.",
    )
    parser.add_argument(
        "-secondpass",
        action="store_true",
        help="Run only the manual two-sided odd-page second pass, using the matching Quiet printer.",
    )
    args = parser.parse_args()

    if args.manual2sided and args.secondpass:
        parser.error("-manual2sided and -secondpass cannot be used together")

    selected_printer = select_printer()
    file_name = input("\nEnter part of the PDF filename: ").strip()
    print_pdf(
        selected_printer,
        file_name,
        manual_2sided=args.manual2sided,
        second_pass_only=args.secondpass,
    )
