#!/usr/bin/env python
"""
nup_pdf.py

Create 2-up or 4-up PDF layouts from 1..4 source PDFs without rasterization.

DEFAULT BEHAVIOR
----------------
- The program asks for part of a PDF filename.
- It searches the folders in PDF_FOLDERS.
- It uses the selected PDF as a single source and duplicates it
  (2-up: left/right, 4-up: all four slots).

ADVANCED BEHAVIOR
-----------------
- Use --manual-inputs to specify PDFs on the command line or select them
  interactively from the current folder.
- Then you can use 1, 2, or 4 different PDFs in the layout.

Examples
--------
2-up duplicate (default search mode):
    python nup_pdf.py

2-up duplicate with zoom:
    python nup_pdf.py --zoom 0.9

2-up with two different sources (manual mode):
    python nup_pdf.py left.pdf right.pdf --mode 2up --manual-inputs

4-up with four sources (manual mode):
    python nup_pdf.py a.pdf b.pdf c.pdf d.pdf --mode 4up --manual-inputs
"""

import os
import sys
import argparse
from typing import List, Tuple

from pypdf import PdfReader, PdfWriter, PageObject, Transformation

PT_PER_IN = 72.0

SHEET_SIZES = {
    "letter": (8.5 * PT_PER_IN, 11.0 * PT_PER_IN),
    "a4": (595.0, 842.0),  # standard A4 size in PDF points
}

# Folders to search by default when looking for a PDF by partial name.
PDF_FOLDERS = [
    r"C:\Users\benoi\Downloads\ebay_manuals",
    r"C:\Users\benoi\Downloads\manuals",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_pdf(partial_name: str) -> str:
    """
    Find a PDF file in PDF_FOLDERS that contains the given string
    (case insensitive). If multiple matches exist, let the user choose.

    Returns:
        Full path to the selected file, or None if not found or cancelled.
    """
    partial_name_lower = partial_name.lower()

    matching_files = []
    for folder in PDF_FOLDERS:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if f.lower().endswith(".pdf") and partial_name_lower in f.lower():
                matching_files.append(os.path.join(folder, f))

    if not matching_files:
        print("No PDF found containing:", partial_name)
        return None

    if len(matching_files) > 1:
        print("\nMultiple matches found:")
        for idx, file in enumerate(matching_files, start=1):
            print("{} . {}".format(idx, os.path.basename(file)))
        choice = input("\nEnter the number of the file you want to use: ").strip()
        if not choice.isdigit():
            print("Invalid choice.")
            return None
        n = int(choice)
        if n < 1 or n > len(matching_files):
            print("Invalid choice.")
            return None
        return matching_files[n - 1]

    # Single match
    return matching_files[0]


def get_single_input_from_search() -> List[str]:
    """
    Default behavior when --manual-inputs is not used:
    ask the user for a partial name, search in PDF_FOLDERS,
    and return a single input path.
    """
    print("Default mode: one PDF is searched by name in PDF_FOLDERS and duplicated.")
    partial = input("Enter part of the PDF filename: ").strip()
    if not partial:
        print("No search text given. Exiting.")
        return []

    pdf_path = find_pdf(partial)
    if pdf_path is None:
        return []

    return [pdf_path]


def list_pdfs_in_cwd() -> List[str]:
    files = [f for f in os.listdir(".") if f.lower().endswith(".pdf")]
    files.sort(key=lambda x: x.lower())
    return files


def interactive_pick(max_count: int) -> List[str]:
    """
    Let the user pick up to max_count PDFs from the current folder.

    The user enters 1..max_count numbers separated by spaces.
    If fewer than max_count are selected, the last one is repeated
    so that we always have exactly max_count items.
    """
    files = list_pdfs_in_cwd()
    if not files:
        print("No PDF found in current folder.")
        return []

    print("Select up to {} PDF(s) by number (space separated).".format(max_count))
    for i, f in enumerate(files, start=1):
        print("{}: {}".format(i, f))

    while True:
        raw = input("Enter selection: ").strip()
        if not raw:
            print("Please enter at least one number.")
            continue

        parts = raw.split()
        idx = []
        ok = True
        for p in parts:
            if not p.isdigit():
                ok = False
                break
            n = int(p)
            if n < 1 or n > len(files):
                ok = False
                break
            idx.append(n - 1)

        if not ok:
            print("Invalid selection. Try again.")
            continue

        picks = [files[i] for i in idx]
        # Fill remaining slots by repeating the last selection
        while len(picks) < max_count:
            picks.append(picks[-1])

        return picks[:max_count]


def compute_upright_size(page) -> Tuple[float, float, int]:
    """
    Return (visible_width, visible_height, rotation_deg).

    If the page has a 90 or 270 degree rotation flag, width/height are swapped.
    """
    rot = getattr(page, "rotation", 0) or 0
    w = float(page.mediabox.width)
    h = float(page.mediabox.height)
    if rot in (90, 270):
        return h, w, rot
    return w, h, rot


def place_page(
    new_page: PageObject,
    src_page,
    slot_x: float,
    slot_y: float,
    slot_w: float,
    slot_h: float,
    zoom: float,
    align: str = "center",
):
    """
    Merge src_page into new_page, scaled uniformly to fit inside the slot.

    zoom is a factor applied on top of the best-fit scale. Values <= 1.0
    shrink the content. Values > 1.0 are clamped so that the page never
    exceeds the slot.
    """
    if zoom <= 0:
        zoom = 1.0

    src_w, src_h, rot = compute_upright_size(src_page)

    # Base uniform scale so the page fits inside the slot
    base_scale = min(slot_w / src_w, slot_h / src_h)

    # Apply user zoom, but never grow beyond base_scale
    scale = base_scale * zoom
    if scale > base_scale:
        scale = base_scale

    # Vertical alignment
    if align == "top":
        y_offset = slot_y + (slot_h - src_h * scale)
    elif align == "bottom":
        y_offset = slot_y
    else:
        # center
        y_offset = slot_y + (slot_h - src_h * scale) / 2.0

    # Horizontal alignment: always centered in the slot
    x_offset = slot_x + (slot_w - src_w * scale) / 2.0

    t = Transformation()
    if rot:
        t = t.rotate(-rot)
    t = t.scale(scale)
    t = t.translate(x_offset, y_offset)

    new_page.merge_transformed_page(src_page, t)


# ---------------------------------------------------------------------------
# Layout builders
# ---------------------------------------------------------------------------

def build_writer_2up(
    sources: List[PdfReader],
    out_path: str,
    sheet_size: str,
    align: str,
    stop_mode: str,
    margin_in: float,
    gutter_in: float,
    zoom: float,
):
    """
    2-up layout: two columns on a landscape sheet (letter or A4).
    sources should contain 1 or 2 PdfReaders.
    """
    if sheet_size not in SHEET_SIZES:
        raise ValueError("Unknown sheet size: {}".format(sheet_size))

    base_w, base_h = SHEET_SIZES[sheet_size]
    # Force landscape for 2-up
    W, H = base_h, base_w

    margin = margin_in * PT_PER_IN
    gutter = gutter_in * PT_PER_IN

    content_w = W - 2 * margin - gutter
    content_h = H - 2 * margin
    slot_w = content_w / 2.0
    slot_h = content_h

    # Left and right slots
    slots = [
        (margin, margin, slot_w, slot_h),                    # left
        (margin + slot_w + gutter, margin, slot_w, slot_h),  # right
    ]

    writer = PdfWriter()
    counts = [len(r.pages) for r in sources]
    if stop_mode == "shortest":
        total = min(counts)
    else:
        total = max(counts)

    for i in range(total):
        new_page = PageObject.create_blank_page(width=W, height=H)
        for slot_idx, (x, y, sw, sh) in enumerate(slots):
            reader = sources[min(slot_idx, len(sources) - 1)]
            if i < len(reader.pages):
                src_page = reader.pages[i]
                place_page(new_page, src_page, x, y, sw, sh, zoom=zoom, align=align)
            else:
                # This source has no page i: leave this slot blank.
                pass
        writer.add_page(new_page)

    with open(out_path, "wb") as f:
        writer.write(f)


def build_writer_4up(
    sources: List[PdfReader],
    out_path: str,
    sheet_size: str,
    orientation: str,
    align: str,
    stop_mode: str,
    margin_in: float,
    gutter_x_in: float,
    gutter_y_in: float,
    zoom: float,
):
    """
    4-up layout: 2x2 grid. By default, sheet is portrait:
    letter (8.5 x 11) or A4.
    """
    if sheet_size not in SHEET_SIZES:
        raise ValueError("Unknown sheet size: {}".format(sheet_size))

    W, H = SHEET_SIZES[sheet_size]
    if orientation == "landscape":
        W, H = H, W

    margin = margin_in * PT_PER_IN
    gutter_x = gutter_x_in * PT_PER_IN
    gutter_y = gutter_y_in * PT_PER_IN

    content_w = W - 2 * margin - gutter_x
    content_h = H - 2 * margin - gutter_y

    slot_w = content_w / 2.0
    slot_h = content_h / 2.0

    # Slots in reading order:
    # top-left, top-right, bottom-left, bottom-right
    slots = [
        (margin,                     margin + slot_h + gutter_y, slot_w, slot_h),  # TL
        (margin + slot_w + gutter_x, margin + slot_h + gutter_y, slot_w, slot_h),  # TR
        (margin,                     margin,                     slot_w, slot_h),  # BL
        (margin + slot_w + gutter_x, margin,                     slot_w, slot_h),  # BR
    ]

    writer = PdfWriter()
    counts = [len(r.pages) for r in sources]
    if stop_mode == "shortest":
        total = min(counts)
    else:
        total = max(counts)

    for i in range(total):
        new_page = PageObject.create_blank_page(width=W, height=H)
        for slot_idx, (x, y, sw, sh) in enumerate(slots):
            reader = sources[min(slot_idx, len(sources) - 1)]
            if i < len(reader.pages):
                src_page = reader.pages[i]
                place_page(new_page, src_page, x, y, sw, sh, zoom=zoom, align=align)
            else:
                # No page i for this source -> blank slot.
                pass
        writer.add_page(new_page)

    with open(out_path, "wb") as f:
        writer.write(f)


# ---------------------------------------------------------------------------
# Input / argument handling
# ---------------------------------------------------------------------------

def auto_output_name(mode: str, inputs: List[str]) -> str:
    if not inputs:
        return "output_{}.pdf".format(mode)
    base = os.path.splitext(os.path.basename(inputs[0]))[0]
    if len(inputs) == 1:
        return "{}_{}.pdf".format(base, mode)
    return "{}_mix_{}.pdf".format(base, mode)


def resolve_inputs(args) -> List[str]:
    """
    Return an input list for the chosen mode when manual-inputs is enabled.

    2up: expects 1 or 2 inputs. If 1, it is duplicated.
    4up: expects 1, 2, or 4 inputs. Missing slots reuse the last file.

    If no inputs are provided, files are selected interactively
    from the current directory.
    """
    if args.mode == "2up":
        needed = 2
    else:
        needed = 4

    if args.inputs:
        picks = args.inputs[:]
        while len(picks) < needed:
            picks.append(picks[-1])
        return picks[:needed]

    return interactive_pick(needed)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Create 2-up or 4-up PDF layouts from 1..4 source PDFs without rasterization."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help=(
            "Input PDF files. For 2up: 1 or 2. For 4up: 1, 2, or 4. "
            "When --manual-inputs is not used, inputs are ignored and a single "
            "PDF is found by name in PDF_FOLDERS."
        ),
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["2up", "4up"],
        default="2up",
        help="Layout mode: 2up (side-by-side) or 4up (2x2 grid). Default 2up.",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output PDF filename. If omitted, a name is generated automatically.",
    )
    parser.add_argument(
        "--sheet",
        choices=["letter", "a4"],
        default="letter",
        help="Sheet size. Default letter.",
    )
    parser.add_argument(
        "--orientation",
        choices=["portrait", "landscape"],
        default="portrait",
        help="For 4up only: sheet orientation. Default portrait. Ignored for 2up.",
    )
    parser.add_argument(
        "--align",
        choices=["center", "top", "bottom"],
        default="center",
        help="Vertical alignment inside each slot when aspect ratios differ. Default center.",
    )
    parser.add_argument(
        "--stop",
        choices=["longest", "shortest"],
        default="longest",
        help=(
            "When sources have different page counts: process until longest "
            "(default, extra pages are blank for shorter docs) or stop at shortest."
        ),
    )
    parser.add_argument(
        "--margin-in",
        type=float,
        default=0.0,
        help="Outer margin in inches. Default 0.0.",
    )
    parser.add_argument(
        "--gutter-in",
        type=float,
        default=0.0,
        help="Horizontal gutter in inches. Used by 2up and as X-gutter for 4up. Default 0.0.",
    )
    parser.add_argument(
        "--gutter-y-in",
        type=float,
        default=0.0,
        help="Vertical gutter in inches for 4up. Default 0.0.",
    )
    parser.add_argument(
        "--zoom",
        type=float,
        default=1.0,
        help=(
            "Scale factor for pages inside each slot. "
            "Values <= 1.0 shrink the content (e.g. 0.9 makes pages 10 percent smaller). "
            "Values > 1.0 are clamped so content never exceeds the slot. Default 1.0."
        ),
    )
    parser.add_argument(
        "--manual-inputs",
        action="store_true",
        help=(
            "Use positional input files / interactive selection instead of searching "
            "in PDF_FOLDERS. Enables using several different PDFs in one layout."
        ),
    )

    args = parser.parse_args()

    print(
        "Hint: by default, this program searches PDF_FOLDERS for a single PDF by name "
        "and duplicates it (2-up or 4-up).\n"
        "Use --manual-inputs (and optional input files) to work with several different PDFs.\n"
        "For full options, use -h.\n"
    )

    # Decide how we get the list of input files
    if args.manual_inputs:
        inputs = resolve_inputs(args)
    else:
        inputs = get_single_input_from_search()

    if not inputs:
        print("No inputs selected. Exiting.")
        return

    # Truncate to maximum allowed per mode
    if args.mode == "2up":
        inputs = inputs[:2]
    else:
        inputs = inputs[:4]

    # Validate files
    for p in inputs:
        if not os.path.isfile(p):
            print("File not found:", p)
            return

    out_path = args.output or auto_output_name(args.mode, inputs)

    # Load readers
    readers = [PdfReader(p) for p in inputs]

    if args.mode == "2up":
        build_writer_2up(
            readers,
            out_path,
            sheet_size=args.sheet,
            align=args.align,
            stop_mode=args.stop,
            margin_in=args.margin_in,
            gutter_in=args.gutter_in,
            zoom=args.zoom,
        )
    else:
        build_writer_4up(
            readers,
            out_path,
            sheet_size=args.sheet,
            orientation=args.orientation,
            align=args.align,
            stop_mode=args.stop,
            margin_in=args.margin_in,
            gutter_x_in=args.gutter_in,
            gutter_y_in=args.gutter_y_in,
            zoom=args.zoom,
        )

    print("Wrote:", out_path)


if __name__ == "__main__":
    main()

