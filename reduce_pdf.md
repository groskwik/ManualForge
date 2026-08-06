# reduce_pdf.py

`reduce_pdf.py` reduces PDF file size by rendering each page as an image, rebuilding a new PDF, and deleting the temporary image files when finished.

This is useful for scanned manuals or image-heavy PDFs.

## Requirements

Run from Anaconda Prompt or any Python environment with these packages installed:

```bat
pip install PyMuPDF Pillow
```

## Interactive Use

Run:

```bat
python .\reduce_pdf.py
```

The script will ask for:

```text
Input PDF filename
Output PDF filename
Size/quality preset
```

If you type a filename without `.pdf`, the script adds `.pdf` automatically.

## Command-Line Examples

Good default:

```bat
python .\reduce_pdf.py .\pascal.pdf .\pascal_ebook.pdf --preset ebook
```

Smallest file, lower quality:

```bat
python .\reduce_pdf.py .\pascal.pdf .\pascal_small.pdf --preset screen
```

Text/manual friendly, sharp letters, no JPEG artifacts:

```bat
python .\reduce_pdf.py .\pascal.pdf .\pascal_text.pdf --preset text
```

Print quality, larger file:

```bat
python .\reduce_pdf.py .\pascal.pdf .\pascal_print.pdf --preset print
```

Custom settings:

```bat
python .\reduce_pdf.py .\pascal.pdf .\pascal_custom.pdf --dpi 150 --compression jpeg --quality 70
```

Custom lossless text setting:

```bat
python .\reduce_pdf.py .\pascal.pdf .\pascal_lossless.pdf --dpi 300 --compression lossless
```

## Presets

| Preset | DPI | Compression | Best For |
|---|---:|---|---|
| `screen` | 96 | JPEG quality 60 | Smallest files |
| `ebook` | 120 | JPEG quality 70 | Balanced size and quality |
| `print` | 300 | JPEG quality 80 | Higher quality, larger files |
| `text` | 300 | Lossless | Manuals, text, sharp lettering |

## DPI Versus Old Zoom

The old scripts used `zoom`. This script uses `DPI`, which is easier to understand.

| Old Zoom | Equivalent DPI |
|---:|---:|
| 1.0 | 72 DPI |
| 1.5 | 108 DPI |
| 2.0 | 144 DPI |
| 3.0 | 216 DPI |

Higher DPI gives clearer pages but creates larger files.

Lower DPI creates smaller files but pages may look blurry.

## Compression Modes

JPEG mode:

```bat
--compression jpeg --quality 70
```

JPEG usually makes smaller files, especially for photos or grayscale scans. Lower `--quality` means more compression and smaller files, but more visible artifacts.

Lossless mode:

```bat
--compression lossless
```

Lossless mode keeps text edges sharper and avoids JPEG artifacts. It is usually better for manuals and mostly text pages, but the output file may be larger.

When using `--compression lossless`, `--quality` is ignored.

## Temporary Files

The script creates temporary PNG files in a system temp folder while converting. They are deleted automatically after the output PDF is created.
