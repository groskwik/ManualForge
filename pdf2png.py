#!/usr/bin/env python
import argparse
import os
import fitz  # PyMuPDF
from PIL import Image
import sys

# Folders to search for PDFs
PDF_FOLDERS = [
    r"C:\Users\benoi\Downloads\ebay_manuals",
    r"C:\Users\benoi\Downloads\manuals"
]

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
        choice = input("\nEnter the number of the file you want to convert: ").strip()
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(matching_files):
            print("Invalid choice.")
            return None
        return matching_files[int(choice) - 1]

    return matching_files[0]  # only match


def parse_args():
    parser = argparse.ArgumentParser(description="Convert PDF pages to PNG images.")
    parser.add_argument("pdf", nargs="?", help="PDF path, or partial name to search for in configured folders")
    parser.add_argument("--zoom", type=float, default=None, help="Render zoom factor. Lower values reduce output size.")
    parser.add_argument("--pages", type=int, help="Number of pages to convert from the start of the PDF")
    parser.add_argument("--output-dir", help="Folder to write PNG files into")
    return parser.parse_args()


def resolve_pdf_path(pdf_arg):
    if pdf_arg:
        if os.path.isfile(pdf_arg):
            return pdf_arg
        return find_pdf(pdf_arg)

    partial_name = input("Enter part of the PDF filename: ").strip()
    return find_pdf(partial_name)


def main():
    args = parse_args()

    pdf_path = resolve_pdf_path(args.pdf)
    if not pdf_path:
        sys.exit(1)

    if args.zoom is not None:
        zoom = args.zoom
    else:
        try:
            zoom = float(input("Enter zoom factor (default 3 for good quality): ") or 3)
        except ValueError:
            zoom = 3

    matrix = fitz.Matrix(zoom, zoom)

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    out_dir = args.output_dir or base_name + "_png"
    os.makedirs(out_dir, exist_ok=True)

    print(f"\nConverting '{pdf_path}' -> '{out_dir}/' ...")

    with fitz.open(pdf_path) as doc:
        page_count = min(args.pages or len(doc), len(doc))
        for page_num in range(page_count):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_path = os.path.join(out_dir, f"page_{page_num + 1:03d}.png")
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img.save(img_path, "PNG")
            print(f"  Saved {img_path}")

    print("\nConversion complete.")

if __name__ == "__main__":
    main()

