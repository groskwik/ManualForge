#!/usr/bin/env python3
import os
import argparse
from pathlib import Path
from PIL import Image
from pdf2image import convert_from_path

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

def main():
    parser = argparse.ArgumentParser(description="Batch process all PDFs into PNG covers.")
    parser.add_argument("--folder", type=str, default=".", help="Folder containing PDFs (default = current)")
    parser.add_argument("--ratio", type=float, default=0.5, help="Scale ratio (default = 0.5)")
    parser.add_argument("--cover", type=str, default="cover.png", help="Cover image file (default = cover.png)")
    args = parser.parse_args()

    folder_path = Path(args.folder)
    cover_path = Path(args.cover)

    if not cover_path.exists():
        print(f"Cover file '{cover_path}' not found.")
        raise SystemExit(1)

    pdfs = sorted([p for p in folder_path.iterdir() if p.suffix.lower() == ".pdf"])
    if not pdfs:
        print("No PDF found in", folder_path)
        return

    print(f"Using cover: {cover_path}")
    print(f"Scale ratio: {args.ratio}")

    for pdf in pdfs:
        print(f"Processing {pdf.name} ...")
        base = Image.open(cover_path).convert("RGB")
        page_img = pdf_first_page_to_image(str(pdf)).convert("RGB")
        out_img = place_in_center(base, page_img, args.ratio)
        out_name = pdf.with_suffix(".png")
        out_img.save(out_name, "PNG")
        print(f" -> saved {out_name.name}")

if __name__ == "__main__":
    main()
