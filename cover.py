#!/usr/bin/env python3
import os
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pdf2image import convert_from_path
import matplotlib.pyplot as plt

# Folders where PDFs are stored
PDF_FOLDERS = [
    r"C:\Users\benoi\Downloads\ebay_manuals",
    r"C:\Users\benoi\Downloads\manuals"
]

# Default angled cover file (the photo)
ANGLE_COVER_FILE = "cover_angle.jpg"

# ----------------------------------------------------------------------
# PDF SEARCH
# ----------------------------------------------------------------------

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
        choice = input("\nEnter the number of the file you want to use: ").strip()
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(matching_files):
            print("Invalid choice.")
            return None
        return matching_files[int(choice) - 1]

    return matching_files[0]  # Return the only match


def pdf_first_page_to_image(pdf_path: str) -> Image.Image:
    pages = convert_from_path(pdf_path, first_page=1, last_page=1)
    return pages[0]

# ----------------------------------------------------------------------
# FLAT COVER MODE
# ----------------------------------------------------------------------

def place_in_center(base_img: Image.Image, overlay_img: Image.Image, scale_ratio: float) -> Image.Image:
    """Flat mode: simple centered rectangle on a flat cover."""
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
# ANGLED COVER MODE (PERSPECTIVE)
# ----------------------------------------------------------------------
def find_perspective_coeffs(dst_quad, src_quad):
    """
    Compute perspective transform coefficients for PIL.Image.transform.

    dst_quad: list of 4 (x,y) destination points on the base image
    src_quad: list of 4 (x,y) source points on the overlay image

    The resulting coefficients map from *output* coordinates (x,y) on the
    base canvas to *input* coordinates (u,v) on the overlay image.
    """
    matrix = []
    B = []
    # For each point pair: (x,y) on base -> (u,v) on overlay
    for (x, y), (u, v) in zip(dst_quad, src_quad):
        # From the equations:
        # u = (a*x + b*y + c) / (g*x + h*y + 1)
        # v = (d*x + e*y + f) / (g*x + h*y + 1)
        #
        # we derive two linear equations per point:
        matrix.append([-x, -y, -1, 0, 0, 0, u*x, u*y])
        B.append(-u)
        matrix.append([0, 0, 0, -x, -y, -1, v*x, v*y])
        B.append(-v)

    A = np.array(matrix, dtype=float)
    B = np.array(B, dtype=float)

    # Least-squares solve for a..h
    coeffs, *_ = np.linalg.lstsq(A, B, rcond=None)
    return coeffs
def shrink_quad(quad, ratio):
    """
    Shrink or expand a quadrilateral towards/away from its center.

    quad: list of 4 (x,y) points
    ratio: 1.0 = original size, 0.9 = 10% smaller, etc.
    """
    if ratio == 1.0:
        return quad

    cx = sum(p[0] for p in quad) / 4.0
    cy = sum(p[1] for p in quad) / 4.0
    out = []
    for x, y in quad:
        dx = x - cx
        dy = y - cy
        out.append((cx + dx * ratio, cy + dy * ratio))
    return out

def place_on_angled_cover(base_img: Image.Image,
                          overlay_img: Image.Image,
                          ratio: float) -> Image.Image:
    """
    Warp overlay_img so it matches the perspective of the angled cover
    in 'cover_angle.jpg', then composite it onto base_img.

    ratio:
      - 1.0 -> the page fills the whole visible cover quadrilateral
      - <1.0 -> the page is inset inside that quadrilateral, same perspective
    """
    bw, bh = base_img.size

    # Expected size (only a warning if different)
    if (bw, bh) != (1600, 1600):
        print(f"Warning: expected {ANGLE_COVER_FILE} to be 1600x1600, got {bw}x{bh}")

    # Destination quadrilateral on the angled photo:
    # (top-left, top-right, bottom-right, bottom-left)
    dst_quad = [
        (321, 152),   # top-left corner of visible front cover
        (1224, 107),  # top-right
        (1501, 1360), # bottom-right
        (233, 1462),  # bottom-left
    ]

    # Apply ratio (shrink/expand around center of the quad)
    dst_quad = shrink_quad(dst_quad, ratio if ratio > 0 else 1.0)

    # Source quadrilateral is the full PDF page
    ow, oh = overlay_img.size
    src_quad = [
        (0, 0),
        (ow, 0),
        (ow, oh),
        (0, oh),
    ]

    # Get coefficients that map from base canvas -> overlay image
    coeffs = find_perspective_coeffs(dst_quad, src_quad)

    # Warp overlay into the base image size
    warped = overlay_img.transform(
        base_img.size,
        Image.PERSPECTIVE,
        coeffs,
        Image.BICUBIC
    )

    # Mask so we only paste inside the quadrilateral
    mask = Image.new("L", base_img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(dst_quad, fill=255)

    return Image.composite(warped, base_img, mask)

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Overlay first page of a PDF onto a cover image."
    )
    parser.add_argument(
        "--ratio",
        type=float,
        default=0.5,
        help="Flat mode: fraction of cover width.\n"
             "Angled mode: size of page inside cover quad (1.0 = full)."
    )
    parser.add_argument(
        "--cover",
        type=str,
        default="cover.png",
        help="Cover image file for flat mode (default = cover.png)"
    )
    parser.add_argument(
        "--angle",
        action="store_true",
        help=f"Use angled cover photo ({ANGLE_COVER_FILE}) and warp the PDF to match its perspective"
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display the resulting image using matplotlib"
    )
    args = parser.parse_args()

    partial_name = input("\nEnter part of the PDF filename: ").strip()
    pdf_name = find_pdf(partial_name)
    if not pdf_name:
        raise SystemExit(1)

    # Choose cover depending on mode
    cover_path = ANGLE_COVER_FILE if args.angle else args.cover

    if not os.path.exists(cover_path):
        print(f"Cover file '{cover_path}' not found.")
        raise SystemExit(1)

    print(f"Using PDF: {pdf_name}")
    print(f"Using cover file: {cover_path}")
    if args.angle:
        print(f"Mode: angled cover (perspective warp), ratio={args.ratio}")
    else:
        print(f"Mode: flat cover, ratio={args.ratio}")

    base = Image.open(cover_path).convert("RGB")
    page_img = pdf_first_page_to_image(pdf_name).convert("RGB")

    if args.angle:
        # Scale ratio so that 0.5 behaves like 1.0 (×2 scale)
        adj_ratio = args.ratio * 2.0

        # Clamp to [0, 1]
        if adj_ratio > 1.0:
            adj_ratio = 1.0
        if adj_ratio <= 0:
            adj_ratio = 0.01  # avoid degenerate quad

        print(f"Adjusted angled ratio: {adj_ratio}")

        out_img = place_on_angled_cover(base, page_img, adj_ratio)
        out_name = f"{Path(pdf_name).stem}.png"
    else:
        out_img = place_in_center(base, page_img, args.ratio)
        out_name = Path(pdf_name).with_suffix(".png").name

    out_img.save(out_name, "PNG")
    print(f"Saved: {out_name}")

    if args.show:
        plt.imshow(out_img)
        plt.axis("off")
        plt.title(out_name)
        plt.show()


if __name__ == "__main__":
    main()
