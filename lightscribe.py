#!/usr/bin/env python
import os
from PIL import Image, ImageOps, ImageEnhance, ImageDraw
import numpy as np
import argparse
# import matplotlib.pyplot as plt  # uncomment if you want the preview window

def main():
    parser = argparse.ArgumentParser(description="Overlay a cover image to a Lightscribe disc")
    parser.add_argument("--cover", type=str, required=True, help="Cover image file (jpg or png)")
    parser.add_argument("--rim", type=str, default="", help="Optional rim overlay PNG (transparent). If not given, tries outsid.png then outside.png")
    args = parser.parse_args()

    if not os.path.exists(args.cover):
        print("Cover file '{}' not found.".format(args.cover))
        raise SystemExit(1)

    # optional rim path resolving
    rim_path = args.rim.strip()
    if rim_path == "":
        if os.path.exists("outsid.png"):
            rim_path = "outsid.png"
        elif os.path.exists("outside.png"):
            rim_path = "outside.png"
        else:
            rim_path = ""  # none found

    print("Using cover file: {}".format(args.cover))
    if rim_path:
        print("Using rim overlay: {}".format(rim_path))

    # ---------------------------
    # build gold-tinted cover
    # ---------------------------
    src = Image.open(args.cover).convert("L")
    src = ImageOps.autocontrast(src, cutoff=0.5)

    dark_gold = (35, 31, 18)
    light_gold = (210, 190, 120)
    gold_img = ImageOps.colorize(src, black=dark_gold, white=light_gold)

    gold_img = ImageEnhance.Contrast(gold_img).enhance(1.6)

    base_gold = np.array([69, 62, 35], dtype=float)
    arr = np.array(gold_img, dtype=float)
    mean_color = arr.mean(axis=(0, 1))
    target = mean_color + 0.5 * (base_gold - mean_color)
    scale = target / mean_color
    arr = np.clip(arr * scale, 0, 255)

    min_floor = 35.0
    dark_mask = arr < min_floor
    arr[dark_mask] = arr[dark_mask] * 0.4 + min_floor * 0.6

    arr = (arr / 255.0) ** 0.93 * 255.0
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    gold_img = Image.fromarray(arr)

    w, h = gold_img.size
    cx, cy = w // 2, h // 2

    # disc mask (outer circle + hole)
    disc_mask = Image.new("L", (w, h), 0)
    mdraw = ImageDraw.Draw(disc_mask)
    margin = 1
    mdraw.ellipse((margin, margin, w - 1 - margin, h - 1 - margin), fill=255)

    hole_radius = int(min(w, h) * 0.17)
    mdraw.ellipse((cx - hole_radius, cy - hole_radius,
                   cx + hole_radius, cy + hole_radius), fill=0)

    disc = Image.new("RGB", (w, h), (255, 255, 255))
    disc.paste(gold_img, mask=disc_mask)

    # to RGBA for shadow / overlays
    disc_rgba = disc.convert("RGBA")

    # right-side shadow on same canvas
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    offset_x = 4
    alpha_main = 45
    alpha_soft = 25
    sdraw.ellipse(
        (margin + offset_x, margin,
         w - 1 - margin + offset_x, h - 1 - margin),
        fill=(0, 0, 0, alpha_soft)
    )
    sdraw.ellipse(
        (margin + offset_x + 1, margin,
         w - 2 - margin + offset_x, h - 2 - margin),
        fill=(0, 0, 0, alpha_main)
    )

    final_rgba = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    final_rgba.alpha_composite(shadow)
    final_rgba.alpha_composite(disc_rgba)

    # if rim overlay exists, composite it; else draw simple border
    if rim_path and os.path.exists(rim_path):
        rim = Image.open(rim_path).convert("RGBA")
        # resize overlay to match disc size exactly
        if rim.size != (w, h):
            rim = rim.resize((w, h), Image.LANCZOS)
        final_rgba.alpha_composite(rim)
    else:
        # fallback: draw a thin border
        bdraw = ImageDraw.Draw(final_rgba)
        border_color = (230, 220, 160, 255)
        bdraw.ellipse((margin, margin, w - 1 - margin, h - 1 - margin),
                      outline=border_color, width=2)

    # paste middle hub if present
    out_img = final_rgba.convert("RGB")
    if os.path.exists("middle.png"):
        middle = Image.open("middle.png").convert("RGBA")
        middle_scale = 0.35
        middle_size = int(min(w, h) * middle_scale)
        middle = middle.resize((middle_size, middle_size), Image.LANCZOS)
        mx = cx - middle_size // 2
        my = cy - middle_size // 2
        out_img.paste(middle, (mx, my), middle)
    else:
        print("Warning: middle.png not found; skipping hub overlay.")

    output_name = "lightscribe_ebay.jpg"
    out_img.save(output_name, quality=95)
    print("Saved final image as '{}' ({} x {})".format(output_name, out_img.size[0], out_img.size[1]))

    # Optional preview
    # import matplotlib.pyplot as plt
    # import numpy as np
    # plt.imshow(np.array(out_img))
    # plt.axis("off")
    # plt.title("Lightscribe Preview")
    # plt.show()

if __name__ == "__main__":
    main()
