#!/usr/bin/env python
import os
from PIL import Image, ImageOps, ImageEnhance, ImageDraw
import numpy as np
import matplotlib.pyplot as plt
import argparse

def list_image_and_choose():
    # list jpg and png (any case)
    img_files = [f for f in os.listdir(".") if f.lower().endswith((".jpg", ".png"))]
    if not img_files:
        print("No JPG or PNG files found in the current folder.")
        return None
    print("\nAvailable image files:")
    for i, f in enumerate(img_files, 1):
        print("{}. {}".format(i, f))
    choice = input("\nEnter the number of the image you want to use as input: ")
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(img_files):
            raise ValueError
    except ValueError:
        print("Invalid choice.")
        return None
    return img_files[idx]

def main():
    parser = argparse.ArgumentParser(description="Overlay a cover image to a lightscrobe disc")
    parser.add_argument("--cover", type=str, help="Cover image file")
    args = parser.parse_args()

    if not os.path.exists(args.cover):
        print(f"Cover file '{args.cover}' not found.")
        raise SystemExit(1)

    print(f"Using cover file: {args.cover}")

    # load and convert to grayscale
    src = Image.open(args.cover).convert("L")
    src = ImageOps.autocontrast(src, cutoff=0.5)

    # colorize to gold
    dark_gold = (35, 31, 18)
    light_gold = (210, 190, 120)
    gold_img = ImageOps.colorize(src, black=dark_gold, white=light_gold)

    # contrast
    gold_img = ImageEnhance.Contrast(gold_img).enhance(1.6)

    # shift toward base gold
    base_gold = np.array([69, 62, 35], dtype=float)
    arr = np.array(gold_img, dtype=float)
    mean_color = arr.mean(axis=(0, 1))
    target = mean_color + 0.5 * (base_gold - mean_color)
    scale = target / mean_color
    arr = arr * scale
    arr = np.clip(arr, 0, 255)

    # lift blacks
    min_floor = 35.0
    dark_mask = arr < min_floor
    arr[dark_mask] = arr[dark_mask] * 0.4 + min_floor * 0.6

    # gentle gamma
    arr = (arr / 255.0) ** 0.93 * 255.0
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    gold_img = Image.fromarray(arr)

    w, h = gold_img.size
    cx, cy = w // 2, h // 2

    # disc mask (always circle)
    disc_mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(disc_mask)
    margin = 1
    draw.ellipse((margin, margin, w - 1 - margin, h - 1 - margin), fill=255)

    # center hole
    hole_radius = int(min(w, h) * 0.17)
    draw.ellipse((cx - hole_radius, cy - hole_radius,
                  cx + hole_radius, cy + hole_radius), fill=0)

    # base disc
    disc = Image.new("RGB", (w, h), (255, 255, 255))
    disc.paste(gold_img, mask=disc_mask)

    # convert to RGBA to add shadow and border
    disc_rgba = disc.convert("RGBA")

    # right-side shadow
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    offset_x = 4
    alpha_main = 45
    alpha_soft = 25

    # soft layer
    sdraw.ellipse(
        (margin + offset_x, margin,
         w - 1 - margin + offset_x, h - 1 - margin),
        fill=(0, 0, 0, alpha_soft)
    )
    # slightly darker
    sdraw.ellipse(
        (margin + offset_x + 1, margin,
         w - 2 - margin + offset_x, h - 2 - margin),
        fill=(0, 0, 0, alpha_main)
    )

    final_rgba = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    final_rgba.alpha_composite(shadow)
    final_rgba.alpha_composite(disc_rgba)

    # border
    bdraw = ImageDraw.Draw(final_rgba)
    border_color = (230, 220, 160, 255)
    bdraw.ellipse((margin, margin, w - 1 - margin, h - 1 - margin),
                  outline=border_color, width=2)

    disc = final_rgba.convert("RGB")

    # add middle if present
    if os.path.exists("middle.png"):
        middle = Image.open("middle.png").convert("RGBA")
        middle_scale = 0.35
        middle_size = int(min(w, h) * middle_scale)
        middle = middle.resize((middle_size, middle_size), Image.LANCZOS)
        mx = cx - middle_size // 2
        my = cy - middle_size // 2
        disc.paste(middle, (mx, my), middle)
    else:
        print("Warning: middle.png not found; skipping hub overlay.")

    output_name = "lightscribe_ebay.jpg"
    disc.save(output_name)
    print("Saved final image as '{}' ({} x {})".format(output_name, disc.size[0], disc.size[1]))

    # display
    # print("Displaying the final image...")
    # plt.imshow(np.array(disc))
    # plt.axis("off")
    # plt.title("Lightscribe Preview")
    # plt.show()

if __name__ == "__main__":
    main()

