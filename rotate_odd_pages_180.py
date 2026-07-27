#!/usr/bin/env python
import argparse
import time
from pathlib import Path


def load_pdf_classes():
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
        return PdfReader, PdfWriter
    except Exception:
        from PyPDF2 import PdfReader, PdfWriter  # type: ignore
        return PdfReader, PdfWriter


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_odd180{input_path.suffix}")


def rotate_page_180(page):
    if hasattr(page, "rotate"):
        return page.rotate(180)
    if hasattr(page, "rotate_clockwise"):
        return page.rotate_clockwise(180)
    raise RuntimeError("PDF library does not support page rotation")


def rotate_odd_pages(input_path: Path, output_path: Path) -> int:
    PdfReader, PdfWriter = load_pdf_classes()

    reader = PdfReader(str(input_path))
    writer = PdfWriter()

    for index, page in enumerate(reader.pages, start=1):
        if index % 2 == 1:
            page = rotate_page_180(page)
        writer.add_page(page)

    if getattr(reader, "metadata", None):
        try:
            writer.add_metadata(dict(reader.metadata))
        except Exception:
            pass

    with output_path.open("wb") as f:
        writer.write(f)

    return len(reader.pages)


def main():
    parser = argparse.ArgumentParser(
        description="Create a PDF copy with every odd page rotated 180 degrees."
    )
    parser.add_argument("input", type=Path, help="Input PDF path")
    parser.add_argument("output", nargs="?", type=Path, help="Output PDF path; default: <input>_odd180.pdf")
    args = parser.parse_args()

    input_path = args.input.expanduser().resolve()
    output_path = (args.output.expanduser().resolve() if args.output else default_output_path(input_path))

    if not input_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_path}")
    if input_path.suffix.lower() != ".pdf":
        raise ValueError(f"Input file is not a PDF: {input_path}")
    if output_path.exists():
        raise FileExistsError(f"Output already exists: {output_path}")

    start = time.perf_counter()
    page_count = rotate_odd_pages(input_path, output_path)
    elapsed = time.perf_counter() - start

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Pages processed: {page_count}")
    print(f"Output size: {size_mb:.2f} MB")
    print(f"Elapsed time: {elapsed:.2f} seconds")


if __name__ == "__main__":
    main()
