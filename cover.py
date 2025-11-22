#!/usr/bin/env python3
import os
import argparse
from pathlib import Path
from PIL import Image
from pdf2image import convert_from_path
import matplotlib.pyplot as plt

# Folders where PDFs are stored
PDF_FOLDERS = [
    r"C:\Users\benoi\Downloads\ebay_manuals",
    r"C:\Users\benoi\Downloads\manuals"
]

# ----------------------------------------------------------------------
# FUNCTIONS
# ----------------------------------------------------------------------

def find_pdf(partial_name):
    """Finds a PDF file in the specified folders that contains the given string (case insensitive)."""
    partial_name_lower = partial_name.lower()

    matching_files = []
    for folder in PDF_FOLDERS:
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

def pdf_first_page_to_image(pdf_path: str) -> Image.Image:
    pages = convert_from_path(pdf_path, first_page=1, last_page=1)
    return pages[0]

def place_in_center(base_img: Image.Image, overlay_img: Image.Image, scale_ratio: float) -> Image.Image:
    bw, bh = base_img.size
    ow, oh = overlay_img.size

    target_w = int(bw * scale_ratio)
    scale = target_w / ow
    target_h = int(oh * scale)

    overlay_resized = overlay_img.resize((target_w, target_h), Image.LANCZOS)
    x = (bw - target_w) // 2
    y = (bh - target_h) // 2

    base_img.paste(overlay_resized, (x, y))
    return base_img

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Overlay first page of a PDF onto a cover image.")
    parser.add_argument("--ratio", type=float, default=0.5, help="Scale ratio (default = 0.5)")
    parser.add_argument("--cover", type=str, default="cover.png", help="Cover image file (default = cover.png)")
    parser.add_argument("--show", action="store_true", help="Display the resulting image using matplotlib")
    args = parser.parse_args()

    partial_name = input("\nEnter part of the PDF filename: ").strip()
    pdf_name = find_pdf(partial_name)

    if not os.path.exists(args.cover):
        print(f"Cover file '{args.cover}' not found.")
        raise SystemExit(1)

    print(f"Using PDF: {pdf_name}")
    print(f"Using cover file: {args.cover}")
    print(f"Scale ratio: {args.ratio}")

    base = Image.open(args.cover).convert("RGB")
    page_img = pdf_first_page_to_image(pdf_name).convert("RGB")
    out_img = place_in_center(base, page_img, args.ratio)

    out_name = Path(pdf_name).with_suffix(".png").name
    out_img.save(out_name, "PNG")
    print(f"Saved: {out_name}")

    if args.show:
        plt.imshow(out_img)
        plt.axis("off")
        plt.title(f"{out_name} (ratio={args.ratio})")
        plt.show()

if __name__ == "__main__":
    main()
