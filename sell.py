
#!/usr/bin/env python3
import os
import re
import sys
import shlex
import argparse
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError

try:
    from pdf2image import pdfinfo_from_path
except Exception:
    pdfinfo_from_path = None

import matplotlib.pyplot as plt


# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

PDF_FOLDERS = [
    r"C:\Users\benoi\Downloads\ebay_manuals",
    r"C:\Users\benoi\Downloads\manuals"
]

ANGLE_COVER_FILE = "cover_angle.jpg"


# ----------------------------------------------------------------------
# BUSINESS RULES
# ----------------------------------------------------------------------

def compute_weight_from_pages(pages: int) -> str:
    """Compute manual weight from number of pages. Returns '10 oz' or '1 lb 3 oz'."""
    if pages <= 0:
        return "--"
    A = 0.082
    O = pages * A
    E = 1.0
    if pages > 200:
        E = 1.6
    O += E
    pounds = int(O // 16)
    ounces = int(O % 16)
    if pounds == 0:
        return f"{ounces} oz"
    return f"{pounds} lb {ounces} oz"


def manual_price_from_pages(pages: float) -> float:
    """Monotone cubic Hermite (PCHIP-style) pricing curve."""
    if pages <= 0:
        raise ValueError("Pages must be positive")

    xp = np.array([50, 200, 300, 400, 500, 1000], dtype=float)
    fp = np.array([17, 22, 30, 40, 50, 92], dtype=float)

    h = np.diff(xp)
    delta = np.diff(fp) / h

    m = np.zeros_like(fp)
    m[0] = delta[0]
    m[-1] = delta[-1]

    for k in range(1, len(fp) - 1):
        if delta[k-1] == 0 or delta[k] == 0 or np.sign(delta[k-1]) != np.sign(delta[k]):
            m[k] = 0.0
        else:
            w1 = 2*h[k] + h[k-1]
            w2 = h[k] + 2*h[k-1]
            m[k] = (w1 + w2) / (w1/delta[k-1] + w2/delta[k])

    if pages <= xp[0]:
        return float(fp[0])
    if pages >= xp[-1]:
        return float(fp[-1])

    k = np.searchsorted(xp, pages) - 1
    k = max(0, min(k, len(h) - 1))

    xk = xp[k]
    hk = h[k]
    t = (pages - xk) / hk

    f0 = fp[k]
    f1 = fp[k+1]
    m0 = m[k]
    m1 = m[k+1]

    h00 = (2*t**3 - 3*t**2 + 1)
    h10 = (t**3 - 2*t**2 + t)
    h01 = (-2*t**3 + 3*t**2)
    h11 = (t**3 - t**2)

    price = (
        h00*f0 +
        h10*hk*m0 +
        h01*f1 +
        h11*hk*m1
    )

    return float(price)


def weight_string_to_lb_oz(weight_str: str) -> tuple[int, int]:
    """Parse '10 oz' or '1 lb 3 oz' -> (lb, oz)."""
    try:
        s = weight_str.strip().lower()
        if "lb" in s:
            parts = s.replace("lb", "lb ").replace("oz", "oz ").split()
            lb = int(parts[0])
            oz_idx = parts.index("oz")
            oz = int(parts[oz_idx - 1])
            return lb, oz
        else:
            oz = int(s.replace("oz", "").strip())
            return 0, oz
    except Exception:
        return 0, 0


# ----------------------------------------------------------------------
# TITLE -> TOKENS -> PDF SCORING
# ----------------------------------------------------------------------

_STOPWORDS = {
    "the","a","an","and","or","for","to","of","in","on","with","without",
    "owners","owner","operator","operators","operation","manual","printed","book",
    "instructions","instruction","guide","service","repair","parts","catalog",
    "oem","genuine","new","used","set","edition","series"
}

def _normalize_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def title_to_tokens(title: str) -> list[str]:
    norm = _normalize_text(title)
    raw = norm.split()

    tokens = []
    for w in raw:
        if w in _STOPWORDS:
            continue
        if len(w) <= 2:
            continue
        tokens.append(w)

    def weight(tok: str) -> tuple[int, int]:
        modelish = 1 if re.search(r"[a-z]\d|\d[a-z]", tok) else 0
        return (modelish, len(tok))

    return sorted(set(tokens), key=weight, reverse=True)

def score_filename_against_tokens(filename: str, tokens: list[str]) -> int:
    base = _normalize_text(Path(filename).stem)
    score = 0
    matched = 0
    for t in tokens:
        if t in base:
            matched += 1
            score += 8 if re.search(r"[a-z]\d|\d[a-z]", t) else 3
    score += min(matched, 6)
    return score

def gather_all_pdfs() -> list[str]:
    out = []
    for folder in PDF_FOLDERS:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if f.lower().endswith(".pdf"):
                out.append(os.path.join(folder, f))
    return out

def choose_pdf_interactively(title: str | None) -> str | None:
    """
    Always let the user choose.
    If title is provided, show a ranked list (best matches first).
    Otherwise, show a plain list (alphabetical).
    """
    pdfs = gather_all_pdfs()
    if not pdfs:
        print("No PDFs found in configured PDF_FOLDERS.")
        return None

    if title and title.strip():
        tokens = title_to_tokens(title)
        scored = [(score_filename_against_tokens(Path(p).name, tokens), p) for p in pdfs]
        scored.sort(key=lambda x: (x[0], Path(x[1]).name.lower()), reverse=True)

        # If everything scored 0, fallback to alphabetical
        if scored and scored[0][0] == 0:
            ranked = sorted(pdfs, key=lambda p: Path(p).name.lower())
            items = [(None, p) for p in ranked]
            print("\nNo strong filename matches from title; showing alphabetical list.")
        else:
            items = scored
            print("\nPDFs ranked by title match (you choose):")
    else:
        ranked = sorted(pdfs, key=lambda p: Path(p).name.lower())
        items = [(None, p) for p in ranked]
        print("\nNo title provided for ranking; showing alphabetical list (you choose):")

    # Show first N, then allow paging
    page_size = 20
    idx0 = 0
    while True:
        chunk = items[idx0:idx0 + page_size]
        if not chunk:
            print("No more PDFs.")
            return None

        print(f"\nShowing {idx0+1}-{idx0+len(chunk)} of {len(items)}:")
        for i, (s, p) in enumerate(chunk, start=1):
            name = Path(p).name
            if s is None:
                print(f"{i}. {name}")
            else:
                print(f"{i}. (score={s}) {name}")

        prompt = "\nEnter number, 'n' for next page, 'p' for previous page, or 'q' to quit: "
        choice = input(prompt).strip().lower()

        if choice == "q":
            return None
        if choice == "n":
            idx0 = min(idx0 + page_size, max(0, len(items) - page_size))
            continue
        if choice == "p":
            idx0 = max(0, idx0 - page_size)
            continue

        if choice.isdigit():
            k = int(choice)
            if 1 <= k <= len(chunk):
                return chunk[k - 1][1]
            print("Invalid number.")
        else:
            print("Invalid input.")


# ----------------------------------------------------------------------
# PDF METADATA
# ----------------------------------------------------------------------

def get_pdf_page_count(pdf_path: str) -> int:
    if pdfinfo_from_path is not None:
        try:
            info = pdfinfo_from_path(pdf_path)
            pages = int(info.get("Pages", 0))
            if pages > 0:
                return pages
        except PDFInfoNotInstalledError:
            pass
        except Exception:
            pass

    for modname in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(modname)
            reader = mod.PdfReader(pdf_path)
            return len(reader.pages)
        except Exception:
            continue

    return 0

def pdf_first_page_to_image(pdf_path: str) -> Image.Image:
    pages = convert_from_path(pdf_path, first_page=1, last_page=1)
    return pages[0]


# ----------------------------------------------------------------------
# COVER MODES
# ----------------------------------------------------------------------

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

def find_perspective_coeffs(dst_quad, src_quad):
    matrix = []
    B = []
    for (x, y), (u, v) in zip(dst_quad, src_quad):
        matrix.append([-x, -y, -1, 0, 0, 0, u*x, u*y])
        B.append(-u)
        matrix.append([0, 0, 0, -x, -y, -1, v*x, v*y])
        B.append(-v)
    A = np.array(matrix, dtype=float)
    B = np.array(B, dtype=float)
    coeffs, *_ = np.linalg.lstsq(A, B, rcond=None)
    return coeffs

def shrink_quad(quad, ratio):
    if ratio == 1.0:
        return quad
    cx = sum(p[0] for p in quad) / 4.0
    cy = sum(p[1] for p in quad) / 4.0
    out = []
    for x, y in quad:
        out.append((cx + (x - cx) * ratio, cy + (y - cy) * ratio))
    return out

def place_on_angled_cover(base_img: Image.Image, overlay_img: Image.Image, ratio: float) -> Image.Image:
    bw, bh = base_img.size
    if (bw, bh) != (1600, 1600):
        print(f"Warning: expected {ANGLE_COVER_FILE} to be 1600x1600, got {bw}x{bh}")

    dst_quad = [
        (321, 152),
        (1224, 107),
        (1501, 1360),
        (233, 1462),
    ]
    dst_quad = shrink_quad(dst_quad, ratio if ratio > 0 else 1.0)

    ow, oh = overlay_img.size
    src_quad = [(0, 0), (ow, 0), (ow, oh), (0, oh)]
    coeffs = find_perspective_coeffs(dst_quad, src_quad)

    warped = overlay_img.transform(
        base_img.size,
        Image.PERSPECTIVE,
        coeffs,
        Image.BICUBIC
    )

    mask = Image.new("L", base_img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(dst_quad, fill=255)

    return Image.composite(warped, base_img, mask)


# ----------------------------------------------------------------------
# RUN EBAY_SELL
# ----------------------------------------------------------------------

def run_ebay_sell(ebay_sell_path: Path, ebay_args: list[str]) -> None:
    cmd = [sys.executable, str(ebay_sell_path)] + ebay_args
    print("\nRunning:")
    print("  " + " ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True)


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate cover, compute pages/weight/price, then run ebay_sell.py. Title helps rank PDFs, but user chooses."
    )
    parser.add_argument("--title", default=None,
                        help="Listing title used to rank PDF candidates; if omitted you will be prompted.")
    parser.add_argument("--ratio", type=float, default=0.5,
                        help="Flat: fraction of cover width. Angled: size inside quad (1.0=full).")
    parser.add_argument("--cover", type=str, default="cover.png",
                        help="Cover image for flat mode (default=cover.png)")
    parser.add_argument("--angle", action="store_true",
                        help=f"Use angled cover photo ({ANGLE_COVER_FILE}) and perspective warp")
    parser.add_argument("--show", action="store_true", help="Show resulting image")
    parser.add_argument("--profile-dir", type=str, default=None, help="Passed to ebay_sell.py")
    parser.add_argument("--ebay-sell", type=str, default="ebay_sell.py",
                        help="Path to ebay_sell.py (default: ebay_sell.py in current dir)")
    parser.add_argument("--price-round", type=int, default=2, help="Decimals for price rounding (default=2)")
    parser.add_argument("--dry-run", action="store_true", help="Do everything but do not run ebay_sell.py")

    args = parser.parse_args()

    title = args.title
    if not title or not title.strip():
        title = input("\nEnter title (--title): ").strip()

    pdf_path = choose_pdf_interactively(title)
    if not pdf_path:
        raise SystemExit(1)

    pages = get_pdf_page_count(pdf_path)
    if pages <= 0:
        print(f"Error: could not determine page count for: {pdf_path}")
        raise SystemExit(1)

    weight_str = compute_weight_from_pages(pages)
    lb, oz = weight_string_to_lb_oz(weight_str)
    price = round(manual_price_from_pages(float(pages)), args.price_round)

    cover_template = ANGLE_COVER_FILE if args.angle else args.cover
    if not os.path.exists(cover_template):
        print(f"Cover file '{cover_template}' not found.")
        raise SystemExit(1)

    base = Image.open(cover_template).convert("RGB")
    page_img = pdf_first_page_to_image(pdf_path).convert("RGB")

    if args.angle:
        adj_ratio = min(max(args.ratio * 2.0, 0.01), 1.0)
        out_img = place_on_angled_cover(base, page_img, adj_ratio)
        out_name = f"{Path(pdf_path).stem}.png"
    else:
        out_img = place_in_center(base, page_img, args.ratio)
        out_name = Path(pdf_path).with_suffix(".png").name

    out_path = Path(out_name).resolve()
    out_img.save(out_path, "PNG")

    print("\n--- Computed listing data ---")
    print(f"Title:  {title}")
    print(f"PDF:    {pdf_path}")
    print(f"Pages:  {pages}")
    print(f"Weight: {weight_str}  (lb={lb}, oz={oz})")
    print(f"Price:  ${price:.2f}")
    print(f"Cover:  {out_path}")

    if args.show:
        plt.imshow(out_img)
        plt.axis("off")
        plt.title(out_path.name)
        plt.show()

    ebay_sell_path = Path(args.ebay_sell)
    if not ebay_sell_path.is_file():
        script_dir = Path(__file__).resolve().parent
        candidate = script_dir / args.ebay_sell
        if candidate.is_file():
            ebay_sell_path = candidate
        else:
            print(f"Error: ebay_sell.py not found at '{args.ebay_sell}' or '{candidate}'.")
            raise SystemExit(1)

    ebay_args = [
        "--cover", str(out_path),
        "--title", title,
        "--pages", str(pages),
        "--price", f"{price:.2f}",
        "--lb", str(lb),
        "--oz", str(oz),
    ]
    if args.profile_dir:
        ebay_args += ["--profile-dir", args.profile_dir]

    if args.dry_run:
        cmd = [sys.executable, str(ebay_sell_path)] + ebay_args
        print("\nDry-run: would run:")
        print("  " + " ".join(shlex.quote(c) for c in cmd))
        return

    run_ebay_sell(ebay_sell_path, ebay_args)


if __name__ == "__main__":
    main()
