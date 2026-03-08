#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from PyPDF2 import PdfReader

# Where your PDFs are stored (same idea as myprint.py)
PDF_FOLDERS = [
    r"C:\Users\benoi\Downloads\ebay_manuals",
    r"C:\Users\benoi\Downloads\manuals",
]

DB_PATH = Path(__file__).with_name("print_settings.json")


# ----------------------------
# Helpers: DB load/save
# ----------------------------
def load_db() -> Dict[str, List[str]]:
    if not DB_PATH.exists():
        return {}
    with DB_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Defensive: ensure dict[str, list[str]]
    if not isinstance(data, dict):
        return {}
    return data


def save_db(data: Dict[str, List[str]]) -> None:
    with DB_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {DB_PATH}")


def find_existing_key_case_insensitive(data: Dict[str, List[str]], key_lower: str) -> Optional[str]:
    for k in data.keys():
        if k.lower() == key_lower:
            return k
    return None


# ----------------------------
# Helpers: PDF search/selection (same approach as myprint.py)
# ----------------------------
def find_pdf(partial_name: str) -> Optional[str]:
    partial_name_lower = partial_name.lower()
    matches: List[str] = []

    for folder in PDF_FOLDERS:
        if not os.path.isdir(folder):
            continue
        for fn in os.listdir(folder):
            if fn.lower().endswith(".pdf") and partial_name_lower in fn.lower():
                matches.append(os.path.join(folder, fn))

    if not matches:
        print(f"No PDF found containing: {partial_name}")
        return None

    matches.sort(key=lambda p: os.path.basename(p).lower())

    if len(matches) == 1:
        return matches[0]

    print("\nMultiple matches found:")
    for i, p in enumerate(matches, start=1):
        print(f"  {i}. {os.path.basename(p)}")

    choice = input("\nEnter the number of the file you want: ").strip()
    if not choice.isdigit():
        print("Invalid choice.")
        return None

    idx = int(choice)
    if idx < 1 or idx > len(matches):
        print("Invalid choice.")
        return None

    return matches[idx - 1]


def get_pdf_page_count(pdf_path: str) -> Optional[int]:
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            return len(reader.pages)
    except Exception as e:
        print(f"Error reading PDF page count: {e}")
        return None


# ----------------------------
# Wizard prompts
# ----------------------------
def ask_choice(prompt: str, options: Dict[str, str]) -> str:
    """
    options: mapping of canonical_value -> display_text
    Returns canonical_value.
    """
    while True:
        print(f"\n{prompt}")
        keys = list(options.keys())
        for i, k in enumerate(keys, start=1):
            print(f"  {i}. {options[k]}")
        ans = input("Select: ").strip()

        # Allow numeric selection
        if ans.isdigit():
            i = int(ans)
            if 1 <= i <= len(keys):
                return keys[i - 1]

        # Allow direct typing (first letter or full)
        ans_l = ans.lower()
        for k in keys:
            if ans_l == k.lower() or ans_l == k.lower()[0]:
                return k

        print("Invalid choice, try again.")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        ans = input(f"{prompt}{suffix}: ").strip().lower()
        if ans == "":
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("Please answer y or n.")


# ----------------------------
# Rule builder
# ----------------------------
def build_rules(page_count: int, color_mode: str, orientation: str, first_page_color_only: bool) -> List[str]:
    """
    color_mode: "color" or "monochrome"
    orientation: "portrait" or "landscape"
    first_page_color_only: only meaningful when color_mode=="color" and orientation=="portrait"
    """
    n = max(1, int(page_count))

    # Landscape: duplexshort + landscape suffix, keep color/mono as selected
    if orientation == "landscape":
        return [f"{color_mode},1-{n},duplexshort,fit,paper=letter,landscape"]

    # Portrait:
    # If color + portrait and user wants first-page-only-color -> use your 3-rule SIMPLEX pattern
    if color_mode == "color" and first_page_color_only:
        if n == 1:
            return ["color,1,simplex,fit,paper=letter"]
        if n == 2:
            return [
                "color,1,simplex,fit,paper=letter",
                "monochrome,2,simplex,fit,paper=letter",
            ]
        return [
            "color,1,simplex,fit,paper=letter",
            "monochrome,2,simplex,fit,paper=letter",
            f"monochrome,3-{n},duplex,fit,paper=letter",
        ]

    # Otherwise: single rule duplex portrait
    return [f"{color_mode},1-{n},duplex,fit,paper=letter"]


# ----------------------------
# Main wizard flow
# ----------------------------
def main() -> None:
    print("Manage print_settings.json (wizard mode)")

    partial = input("\nEnter part of the PDF filename to search: ").strip()
    if not partial:
        print("No input.")
        return

    pdf_path = find_pdf(partial)
    if not pdf_path:
        return

    page_count = get_pdf_page_count(pdf_path)
    if not page_count:
        print("Unable to determine page count.")
        return

    base = Path(pdf_path).stem
    key_lower = base.lower()

    print(f"\nSelected PDF: {Path(pdf_path).name}")
    print(f"Pages: {page_count}")
    print(f"DB key: {key_lower}")

    db = load_db()
    existing_key = find_existing_key_case_insensitive(db, key_lower)

    if existing_key is not None:
        print("\nExisting settings found:")
        for i, rule in enumerate(db[existing_key], start=1):
            print(f"  {i}. {rule}")

        if not ask_yes_no("Overwrite these settings?", default=False):
            print("No changes made.")
            return

    mode = ask_choice(
        "Choose color mode:",
        {
            "color": "Color",
            "monochrome": "Black and white (monochrome)",
        },
    )

    orientation = ask_choice(
        "Choose orientation:",
        {
            "portrait": "Portrait",
            "landscape": "Landscape",
        },
    )

    first_page_color_only = False
    if mode == "color" and orientation == "portrait":
        first_page_color_only = ask_yes_no(
            "Apply color to first page only, rest monochrome?",
            default=False,
        )

    rules = build_rules(page_count, mode, orientation, first_page_color_only)

    print("\nNew settings to be written:")
    for i, r in enumerate(rules, start=1):
        print(f"  {i}. {r}")

    if not ask_yes_no("Confirm save?", default=True):
        print("Cancelled. No changes made.")
        return

    # Store using normalized lowercase key (consistent with your myprint.py lookup)
    # If you prefer keeping original case, store `base` instead of `key_lower`.
    db[key_lower] = rules
    save_db(db)
    print("Done.")


if __name__ == "__main__":
    main()
