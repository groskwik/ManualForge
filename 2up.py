#!/usr/bin/env python
#!/usr/bin/env python
"""
2up.py

Create 2-up or 4-up PDF layouts from 1..4 source PDFs without rasterization.

DEFAULT BEHAVIOR
----------------
- Ask for part of a PDF filename.
- Search the folders in PDF_FOLDERS.
- Use the selected PDF as a single source and duplicate it.

ADVANCED BEHAVIOR
-----------------
- Use --manual-inputs to specify PDFs on the command line or select them
  interactively from the current folder.
- Then you can use 1, 2, 3, or 4 different PDFs in the layout.

CONFLICT HANDLING
-----------------
If a reference matches multiple PDFs across PDF_FOLDERS, the program will
ASK YOU TO CHOOSE (or you can cancel). It will not guess.

DUPLEX CUT FEATURE (2-up)
-------------------------
When printing duplex and then cutting down the center, the back side often
needs the left/right halves swapped to preserve the correct page sequence.

Enable with:
  --swap-even
Meaning:
  sheet 1 (odd): source0 left, source1 right
  sheet 2 (even): source0 right, source1 left
  sheet 3 (odd): normal again, etc.

PERFORMANCE
-----------
Use --workers N (N > 1) to enable multiprocessing. The script will:
- split the output into chunks
- each worker writes a temporary PDF chunk
- parent concatenates chunks into the final output

This keeps vector content (no rasterization).
"""

import os
import sys
import argparse
import tempfile
import shutil
from dataclasses import dataclass
from typing import List, Tuple, Optional

from pypdf import PdfReader, PdfWriter, PageObject, Transformation


PT_PER_IN = 72.0

SHEET_SIZES = {
    "letter": (8.5 * PT_PER_IN, 11.0 * PT_PER_IN),
    "a4": (595.0, 842.0),
}

PDF_FOLDERS = [
    r"C:\Users\benoi\Downloads\ebay_manuals",
    r"C:\Users\benoi\Downloads\manuals",
]


# ---------------------------------------------------------------------------
# ASCII progress indicator
# ---------------------------------------------------------------------------

def spinner_update(i: int, total: int, prefix: str = "Merging") -> None:
    spin = "|/-\\"
    ch = spin[i % len(spin)]
    msg = "\r{} {} {}/{}".format(prefix, ch, i + 1, total)
    sys.stdout.write(msg)
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# PDF discovery / conflict-aware resolution
# ---------------------------------------------------------------------------

def _list_pdfs_in_folder(folder: str) -> List[str]:
    if not os.path.isdir(folder):
        return []
    out: List[str] = []
    for fn in os.listdir(folder):
        if fn.lower().endswith(".pdf"):
            out.append(os.path.join(folder, fn))
    return out


def search_pdfs(token: str) -> List[str]:
    """
    Search PDF_FOLDERS for PDFs whose filename contains token (case-insensitive).
    """
    token_l = token.lower()
    matches: List[str] = []
    for folder in PDF_FOLDERS:
        for p in _list_pdfs_in_folder(folder):
            if token_l in os.path.basename(p).lower():
                matches.append(p)
    matches.sort(key=lambda p: (os.path.basename(p).lower(), p.lower()))
    return matches


def search_pdfs_exact(filename: str) -> List[str]:
    """
    Search PDF_FOLDERS for PDFs whose filename equals filename (case-insensitive).
    Returns all matches (to detect conflicts).
    """
    name_l = filename.lower()
    matches: List[str] = []
    for folder in PDF_FOLDERS:
        for p in _list_pdfs_in_folder(folder):
            if os.path.basename(p).lower() == name_l:
                matches.append(p)
    matches.sort(key=lambda p: p.lower())
    return matches


def pick_from_list(paths: List[str], title: str) -> Optional[str]:
    """
    Force a choice when there are multiple matches.
    """
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]

    print("\n" + title)
    for i, p in enumerate(paths, start=1):
        print("{} . {}   [{}]".format(i, os.path.basename(p), os.path.dirname(p)))

    while True:
        choice = input("Enter number (or blank to cancel): ").strip()
        if choice == "":
            return None
        if not choice.isdigit():
            print("Invalid choice.")
            continue
        n = int(choice)
        if 1 <= n <= len(paths):
            return paths[n - 1]
        print("Invalid choice.")


def resolve_pdf_reference(user_value: str) -> Optional[str]:
    """
    Resolve a PDF reference robustly, with conflict detection:

    1) If user_value is an existing path -> use it.
    2) Else if it ends with .pdf -> do an exact filename search in PDF_FOLDERS.
       If multiple matches -> prompt user.
    3) Else treat it as a partial token -> search in PDF_FOLDERS.
       If multiple matches -> prompt user.
    """
    if not user_value:
        return None

    # Existing path?
    if os.path.isfile(user_value):
        return os.path.abspath(user_value)

    base = os.path.basename(user_value)

    # Exact filename resolution (conflict-aware)
    if base.lower().endswith(".pdf"):
        exact = search_pdfs_exact(base)
        if not exact:
            # Fall back to "contains" using the stem
            token = base[:-4]
            cand = search_pdfs(token)
            if not cand:
                return None
            return pick_from_list(cand, "Multiple matches for '{}':".format(token))
        return pick_from_list(exact, "Conflict: multiple files named '{}' found:".format(base))

    # Partial token resolution (conflict-aware)
    cand = search_pdfs(base)
    if not cand:
        return None
    return pick_from_list(cand, "Multiple matches for '{}':".format(base))


def get_single_input_from_search() -> List[str]:
    print("Default mode: one PDF is searched by name in PDF_FOLDERS and duplicated.")
    token = input("Enter part of the PDF filename: ").strip()
    if not token:
        print("No search text given. Exiting.")
        return []

    cand = search_pdfs(token)
    if not cand:
        print("No PDF found containing:", token)
        return []

    chosen = pick_from_list(cand, "Select a PDF:")
    if not chosen:
        print("Cancelled.")
        return []

    return [chosen]


def list_pdfs_in_cwd() -> List[str]:
    files = [f for f in os.listdir(".") if f.lower().endswith(".pdf")]
    files.sort(key=lambda x: x.lower())
    return files


def interactive_pick_cwd(max_count: int) -> List[str]:
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
        idx: List[int] = []
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

        picks = [os.path.abspath(files[i]) for i in idx]
        while len(picks) < max_count:
            picks.append(picks[-1])
        return picks[:max_count]


def resolve_inputs(args) -> List[str]:
    needed = 2 if args.mode == "2up" else 4

    if args.inputs:
        resolved: List[str] = []
        for val in args.inputs:
            p = resolve_pdf_reference(val)
            if not p or not os.path.isfile(p):
                print("Could not resolve:", val)
                return []
            resolved.append(p)

        while len(resolved) < needed:
            resolved.append(resolved[-1])
        return resolved[:needed]

    return interactive_pick_cwd(needed)


# ---------------------------------------------------------------------------
# Document model + one-time normalization
# ---------------------------------------------------------------------------

@dataclass
class Document:
    path: str
    reader: PdfReader
    pages: List


def normalize_pages_once(reader: PdfReader) -> List:
    """
    Normalize /Rotate into the content stream ONCE (vector-safe) if supported.
    This must NOT be done inside the per-page placement loop.
    """
    pages = list(reader.pages)
    for p in pages:
        if hasattr(p, "transfer_rotation_to_content"):
            try:
                p.transfer_rotation_to_content()
            except Exception:
                pass
    return pages


def load_documents(paths: List[str]) -> List[Document]:
    docs: List[Document] = []
    for p in paths:
        r = PdfReader(p)
        pages = normalize_pages_once(r)
        docs.append(Document(path=p, reader=r, pages=pages))
    return docs


# ---------------------------------------------------------------------------
# Placement helpers
# ---------------------------------------------------------------------------

def get_page_size(page) -> Tuple[float, float]:
    return float(page.mediabox.width), float(page.mediabox.height)


def place_page(
    new_page: PageObject,
    src_page,
    slot_x: float,
    slot_y: float,
    slot_w: float,
    slot_h: float,
    zoom: float,
    align: str = "center",
) -> None:
    if zoom <= 0:
        zoom = 1.0

    src_w, src_h = get_page_size(src_page)
    base_scale = min(slot_w / src_w, slot_h / src_h)

    scale = base_scale * zoom
    if scale > base_scale:
        scale = base_scale

    if align == "top":
        y_offset = slot_y + (slot_h - src_h * scale)
    elif align == "bottom":
        y_offset = slot_y
    else:
        y_offset = slot_y + (slot_h - src_h * scale) / 2.0

    x_offset = slot_x + (slot_w - src_w * scale) / 2.0

    t = Transformation().scale(scale).translate(x_offset, y_offset)
    new_page.merge_transformed_page(src_page, t)


def get_total_pages(docs: List[Document], stop_mode: str) -> int:
    counts = [len(d.pages) for d in docs]
    if not counts:
        return 0
    return min(counts) if stop_mode == "shortest" else max(counts)


# ---------------------------------------------------------------------------
# Slot mapping (with duplex swap option for 2up)
# ---------------------------------------------------------------------------

def slot_to_source_index_2up(num_sources: int, slot_idx: int, page_index: int, swap_even: bool) -> int:
    """
    2up mapping:
    - 1 source: both slots use source 0
    - 2 sources: normally slot0->0 slot1->1
      If swap_even is enabled: swap on even SHEETS (page_index 1,3,5... since 0-based)
        page_index 0: slot0->0 slot1->1
        page_index 1: slot0->1 slot1->0
        etc.
    """
    if num_sources <= 1:
        return 0

    if not swap_even:
        return 0 if slot_idx == 0 else 1

    # swap on even sheets (human even = 2nd,4th,... => 0-based odd indices)
    if (page_index % 2) == 1:
        return 1 if slot_idx == 0 else 0
    return 0 if slot_idx == 0 else 1


def slot_to_source_index_4up(num_sources: int, slot_idx: int) -> int:
    """
    4up strict mapping:
    - 1 source: all slots 0
    - 2 sources: top row=0, bottom row=1
    - 3 sources: slot0=0 slot1=1 slot2=2 slot3=2
    - 4 sources: slot i = i
    """
    if num_sources <= 1:
        return 0
    if num_sources == 2:
        return 0 if slot_idx in (0, 1) else 1
    if num_sources >= 4:
        return slot_idx
    return slot_idx if slot_idx < 3 else 2


# ---------------------------------------------------------------------------
# Layout builders (single-process)
# ---------------------------------------------------------------------------

def build_writer_2up_pages(
    docs: List[Document],
    sheet_size: str,
    align: str,
    stop_mode: str,
    margin_in: float,
    gutter_in: float,
    zoom: float,
    swap_even: bool,
    page_start: int,
    page_end_excl: int,
    show_progress: bool = False,
) -> PdfWriter:
    """
    Build a PdfWriter for a range of output sheets [page_start, page_end_excl).
    Used both for single-process and multiprocess chunk generation.
    """
    if sheet_size not in SHEET_SIZES:
        raise ValueError("Unknown sheet size: {}".format(sheet_size))

    base_w, base_h = SHEET_SIZES[sheet_size]
    W, H = base_h, base_w  # landscape

    margin = margin_in * PT_PER_IN
    gutter = gutter_in * PT_PER_IN

    content_w = W - 2 * margin - gutter
    content_h = H - 2 * margin
    slot_w = content_w / 2.0
    slot_h = content_h

    slots = [
        (margin, margin, slot_w, slot_h),                      # left
        (margin + slot_w + gutter, margin, slot_w, slot_h),    # right
    ]

    writer = PdfWriter()
    total_global = get_total_pages(docs, stop_mode)
    num_sources = len(docs)

    # Safety clamp in case page_end_excl > total_global
    end = min(page_end_excl, total_global)

    for i in range(page_start, end):
        if show_progress:
            spinner_update(i, total_global, prefix="Merging")

        new_page = PageObject.create_blank_page(width=W, height=H)

        for slot_idx, (x, y, sw, sh) in enumerate(slots):
            src_idx = slot_to_source_index_2up(num_sources, slot_idx, i, swap_even)
            pages = docs[src_idx].pages

            if i < len(pages):
                place_page(new_page, pages[i], x, y, sw, sh, zoom=zoom, align=align)
            # else blank

        writer.add_page(new_page)

    return writer


def build_writer_4up_pages(
    docs: List[Document],
    sheet_size: str,
    orientation: str,
    align: str,
    stop_mode: str,
    margin_in: float,
    gutter_x_in: float,
    gutter_y_in: float,
    zoom: float,
    page_start: int,
    page_end_excl: int,
    show_progress: bool = False,
) -> PdfWriter:
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

    slots = [
        (margin,                     margin + slot_h + gutter_y, slot_w, slot_h),  # TL
        (margin + slot_w + gutter_x, margin + slot_h + gutter_y, slot_w, slot_h),  # TR
        (margin,                     margin,                     slot_w, slot_h),  # BL
        (margin + slot_w + gutter_x, margin,                     slot_w, slot_h),  # BR
    ]

    writer = PdfWriter()
    total_global = get_total_pages(docs, stop_mode)
    num_sources = len(docs)

    end = min(page_end_excl, total_global)

    for i in range(page_start, end):
        if show_progress:
            spinner_update(i, total_global, prefix="Merging")

        new_page = PageObject.create_blank_page(width=W, height=H)

        for slot_idx, (x, y, sw, sh) in enumerate(slots):
            src_idx = slot_to_source_index_4up(num_sources, slot_idx)
            pages = docs[src_idx].pages
            if i < len(pages):
                place_page(new_page, pages[i], x, y, sw, sh, zoom=zoom, align=align)

        writer.add_page(new_page)

    return writer


# ---------------------------------------------------------------------------
# Multiprocessing support (chunk -> temp pdf -> concatenate)
# ---------------------------------------------------------------------------

def _worker_make_chunk(args_tuple) -> str:
    """
    Worker function: open PDFs, build writer for a page range, write temp PDF.
    Returns the temp PDF path.
    """
    (
        mode,
        input_paths,
        out_dir,
        chunk_index,
        page_start,
        page_end_excl,
        sheet,
        orientation,
        align,
        stop_mode,
        margin_in,
        gutter_in,
        gutter_y_in,
        zoom,
        swap_even,
    ) = args_tuple

    docs = load_documents(input_paths)

    if mode == "2up":
        writer = build_writer_2up_pages(
            docs=docs,
            sheet_size=sheet,
            align=align,
            stop_mode=stop_mode,
            margin_in=margin_in,
            gutter_in=gutter_in,
            zoom=zoom,
            swap_even=swap_even,
            page_start=page_start,
            page_end_excl=page_end_excl,
            show_progress=False,
        )
    else:
        writer = build_writer_4up_pages(
            docs=docs,
            sheet_size=sheet,
            orientation=orientation,
            align=align,
            stop_mode=stop_mode,
            margin_in=margin_in,
            gutter_x_in=gutter_in,
            gutter_y_in=gutter_y_in,
            zoom=zoom,
            page_start=page_start,
            page_end_excl=page_end_excl,
            show_progress=False,
        )

    tmp_path = os.path.join(out_dir, "chunk_{:04d}.pdf".format(chunk_index))
    with open(tmp_path, "wb") as f:
        writer.write(f)

    return tmp_path


def build_with_multiprocessing(
    mode: str,
    input_paths: List[str],
    out_path: str,
    workers: int,
    sheet: str,
    orientation: str,
    align: str,
    stop_mode: str,
    margin_in: float,
    gutter_in: float,
    gutter_y_in: float,
    zoom: float,
    swap_even: bool,
    chunk_size: int,
) -> None:
    """
    Multiprocess strategy:
      - compute total pages
      - split into chunks
      - each worker writes a chunk PDF in temp dir
      - parent concatenates chunk PDFs in order
    """
    from multiprocessing import Pool

    # Determine total pages once (cheap)
    docs0 = load_documents(input_paths)
    total = get_total_pages(docs0, stop_mode)
    if total <= 0:
        raise RuntimeError("No pages to process.")

    temp_dir = tempfile.mkdtemp(prefix="nup_chunks_")
    try:
        tasks = []
        chunk_index = 0
        for start in range(0, total, chunk_size):
            end = min(start + chunk_size, total)
            tasks.append(
                (
                    mode,
                    input_paths,
                    temp_dir,
                    chunk_index,
                    start,
                    end,
                    sheet,
                    orientation,
                    align,
                    stop_mode,
                    margin_in,
                    gutter_in,
                    gutter_y_in,
                    zoom,
                    swap_even,
                )
            )
            chunk_index += 1

        # Run workers
        chunk_paths: List[str] = []
        completed = 0
        sys.stdout.write("Multiprocessing: {} pages in {} chunk(s) using {} worker(s)\n".format(total, len(tasks), workers))
        sys.stdout.flush()

        with Pool(processes=workers) as pool:
            for tmp_path in pool.imap_unordered(_worker_make_chunk, tasks):
                chunk_paths.append(tmp_path)
                completed += 1
                sys.stdout.write("\rCompleted chunks: {}/{}".format(completed, len(tasks)))
                sys.stdout.flush()

        sys.stdout.write("\nConcatenating chunks...\n")
        sys.stdout.flush()

        # Concatenate in correct order
        chunk_paths.sort()  # chunk_0000.pdf, chunk_0001.pdf, ...
        final = PdfWriter()
        for p in chunk_paths:
            r = PdfReader(p)
            for pg in r.pages:
                final.add_page(pg)

        with open(out_path, "wb") as f:
            final.write(f)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Output naming
# ---------------------------------------------------------------------------

def auto_output_name(mode: str, inputs: List[str]) -> str:
    if not inputs:
        return "output_{}.pdf".format(mode)
    base = os.path.splitext(os.path.basename(inputs[0]))[0]
    if len(inputs) == 1:
        return "{}_{}.pdf".format(base, mode)
    return "{}_mix_{}.pdf".format(base, mode)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create 2-up or 4-up PDF layouts from 1..4 source PDFs without rasterization."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help=(
            "Input PDF references (used only with --manual-inputs). "
            "Each can be a path, an exact filename in PDF_FOLDERS, or a partial token. "
            "For 2up: 1 or 2. For 4up: 1, 2, 3, or 4."
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
        help="Process until longest (default) or stop at shortest.",
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
        help="Scale factor inside each slot. Values <= 1.0 shrink. Values > 1.0 are clamped.",
    )
    parser.add_argument(
        "--manual-inputs",
        action="store_true",
        help="Use positional input references / interactive selection instead of default search mode.",
    )

    # New: duplex cut swap feature (2up only)
    parser.add_argument(
        "--swap-even",
        action="store_true",
        help="2up only: swap left/right slots on even output sheets (2nd, 4th, ...). Useful for duplex cut workflows.",
    )

    # New: multiprocessing
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Use N worker processes (N>1 enables multiprocessing). Default 1.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=20,
        help="When using multiprocessing, pages per chunk PDF. Default 20.",
    )

    args = parser.parse_args()

    print(
        "Hint: by default, this program searches PDF_FOLDERS for a single PDF by name and duplicates it.\n"
        "Use --manual-inputs to combine multiple PDFs.\n"
        "For full options, use -h.\n"
    )

    # Resolve inputs
    if args.manual_inputs:
        input_paths = resolve_inputs(args)
        if not input_paths:
            print("No inputs selected. Exiting.")
            return
        print("Resolved inputs:")
        for i, p in enumerate(input_paths):
            print("  {}: {}".format(i, p))
    else:
        # Default: single PDF search, later duplicated by the mapping logic
        input_paths = get_single_input_from_search()
        if not input_paths:
            print("No inputs selected. Exiting.")
            return

    out_path = args.output or auto_output_name(args.mode, input_paths)

    # Multiprocessing path
    if args.workers and args.workers > 1:
        build_with_multiprocessing(
            mode=args.mode,
            input_paths=input_paths,
            out_path=out_path,
            workers=args.workers,
            sheet=args.sheet,
            orientation=args.orientation,
            align=args.align,
            stop_mode=args.stop,
            margin_in=args.margin_in,
            gutter_in=args.gutter_in,
            gutter_y_in=args.gutter_y_in,
            zoom=args.zoom,
            swap_even=bool(args.swap_even),
            chunk_size=max(1, int(args.chunk_size)),
        )
        print("Wrote:", out_path)
        return

    # Single-process path
    docs = load_documents(input_paths)
    total = get_total_pages(docs, args.stop)
    if total <= 0:
        print("No pages to process.")
        return

    if args.mode == "2up":
        writer = build_writer_2up_pages(
            docs=docs,
            sheet_size=args.sheet,
            align=args.align,
            stop_mode=args.stop,
            margin_in=args.margin_in,
            gutter_in=args.gutter_in,
            zoom=args.zoom,
            swap_even=bool(args.swap_even),
            page_start=0,
            page_end_excl=total,
            show_progress=True,
        )
    else:
        writer = build_writer_4up_pages(
            docs=docs,
            sheet_size=args.sheet,
            orientation=args.orientation,
            align=args.align,
            stop_mode=args.stop,
            margin_in=args.margin_in,
            gutter_x_in=args.gutter_in,
            gutter_y_in=args.gutter_y_in,
            zoom=args.zoom,
            page_start=0,
            page_end_excl=total,
            show_progress=True,
        )

    sys.stdout.write("\n")
    with open(out_path, "wb") as f:
        writer.write(f)

    print("Wrote:", out_path)


if __name__ == "__main__":
    main()

