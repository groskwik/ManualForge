import argparse
import os
from PIL import Image


def parse_args():
    parser = argparse.ArgumentParser(description="Combine page PNG files into a PDF.")
    parser.add_argument("image_dir", nargs="?", default=".", help="Folder containing page_001.png style files")
    parser.add_argument("--output", default="new_no_watermark.pdf", help="Output PDF path")
    parser.add_argument("--pages", type=int, help="Number of images to combine from the start")
    return parser.parse_args()


def page_number(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return int(name.rsplit("_", 1)[1])


def main():
    args = parse_args()

    image_paths = [
        os.path.join(args.image_dir, name)
        for name in os.listdir(args.image_dir)
        if name.lower().startswith("page_") and name.lower().endswith(".png")
    ]
    image_paths.sort(key=page_number)

    if args.pages:
        image_paths = image_paths[:args.pages]

    if not image_paths:
        raise SystemExit(f"No page_*.png files found in {args.image_dir}")

    images = [Image.open(image_path).convert("RGB") for image_path in image_paths]
    images[0].save(args.output, save_all=True, append_images=images[1:])

    for image in images:
        image.close()

    print(f"New PDF saved as {args.output}")


if __name__ == "__main__":
    main()
