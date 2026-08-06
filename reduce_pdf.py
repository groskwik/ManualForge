#!/usr/bin/env python
import argparse
import os
import tempfile

import fitz  # PyMuPDF
from PIL import Image


PRESETS = {
    "screen": {"dpi": 96, "quality": 60, "compression": "jpeg"},
    "ebook": {"dpi": 120, "quality": 70, "compression": "jpeg"},
    "print": {"dpi": 300, "quality": 80, "compression": "jpeg"},
    "text": {"dpi": 300, "quality": 70, "compression": "lossless"},
}


def pdf_name(path):
    path = path.strip().strip('"')
    if path and not path.lower().endswith(".pdf"):
        path += ".pdf"
    return path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Reduce a PDF by rendering pages as compressed images and rebuilding the PDF."
    )
    parser.add_argument("input", nargs="?", help="Input PDF file")
    parser.add_argument("output", nargs="?", help="Reduced output PDF file")
    parser.add_argument(
        "--preset",
        choices=PRESETS.keys(),
        default="ebook",
        help="Resolution/compression preset: screen is smallest, text is lossless for text-heavy PDFs. Default: ebook",
    )
    parser.add_argument("--dpi", type=int, help="Custom DPI. Replaces old zoom values with a clearer resolution number.")
    parser.add_argument("--quality", type=int, help="JPEG quality from 1-95. Lower is smaller. Default comes from preset.")
    parser.add_argument(
        "--compression",
        choices=("jpeg", "lossless"),
        help="jpeg gives smaller photo/scan PDFs; lossless keeps sharper text edges but may be larger.",
    )
    return parser.parse_args()


def ask_for_missing_args(args):
    if not args.input:
        args.input = input("Input PDF filename: ")
    if not args.output:
        args.output = input("Output PDF filename: ")

    args.input = pdf_name(args.input)
    args.output = pdf_name(args.output)

    if not args.dpi and args.preset == "ebook":
        print("\nSize/quality presets:")
        print("  1. screen  - smallest file, lower quality")
        print("  2. ebook   - good default")
        print("  3. print   - clearer, larger file")
        print("  4. text    - lossless compression for sharper text")
        choice = input("Choose preset [2]: ").strip()
        if choice == "1":
            args.preset = "screen"
        elif choice == "3":
            args.preset = "print"
        elif choice == "4":
            args.preset = "text"


def save_jpeg_pdf(image_paths, output_pdf, dpi, quality):
    images = [Image.open(path).convert("RGB") for path in image_paths]
    images[0].save(
        output_pdf,
        "PDF",
        save_all=True,
        append_images=images[1:],
        resolution=dpi,
        quality=quality,
    )

    for image in images:
        image.close()


def save_lossless_pdf(source_pdf, image_paths, output_pdf):
    output_doc = fitz.open()

    with fitz.open(source_pdf) as source_doc:
        for page_index, image_path in enumerate(image_paths):
            source_page = source_doc.load_page(page_index)
            page = output_doc.new_page(width=source_page.rect.width, height=source_page.rect.height)
            page.insert_image(page.rect, filename=image_path)

    output_doc.save(output_pdf, garbage=4, deflate=True)
    output_doc.close()


def reduce_pdf(input_pdf, output_pdf, dpi, quality, compression):
    if not os.path.isfile(input_pdf):
        raise SystemExit(f"Input PDF not found: {input_pdf}")

    matrix = fitz.Matrix(dpi / 72, dpi / 72)

    with tempfile.TemporaryDirectory(prefix="pdf_reduce_") as temp_dir:
        image_paths = []

        with fitz.open(input_pdf) as doc:
            total_pages = len(doc)
            print(f"\nConverting {total_pages} pages at {dpi} DPI...")

            for page_index in range(total_pages):
                page = doc.load_page(page_index)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                image_path = os.path.join(temp_dir, f"page_{page_index + 1:05d}.png")
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                image.save(image_path, "PNG")
                image_paths.append(image_path)
                print(f"  Page {page_index + 1} of {total_pages}")

        if compression == "lossless":
            save_lossless_pdf(input_pdf, image_paths, output_pdf)
        else:
            save_jpeg_pdf(image_paths, output_pdf, dpi, quality)

    print(f"\nReduced PDF saved as: {output_pdf}")
    print("Temporary PNG files were removed.")


def main():
    args = parse_args()
    ask_for_missing_args(args)

    preset = PRESETS[args.preset]
    dpi = args.dpi or preset["dpi"]
    quality = args.quality or preset["quality"]
    compression = args.compression or preset["compression"]

    if dpi < 36:
        raise SystemExit("DPI is too low. Use 36 or higher.")
    if quality < 1 or quality > 95:
        raise SystemExit("Quality must be between 1 and 95.")

    print(f"Compression mode: {compression}")
    if compression == "jpeg":
        print(f"JPEG quality: {quality}")

    reduce_pdf(args.input, args.output, dpi, quality, compression)


if __name__ == "__main__":
    main()
