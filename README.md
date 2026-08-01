
# **ManualForge**
*A GUI tool to preview, process, print, and manage PDF manuals for eBay sellers and collectors*

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)  
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)]()  
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)]()

---

## 📌 Overview

**ManualForge** is a lightweight and fast GUI designed for people who frequently work with *printed manuals*, *PDF covers*, and *2-up/4-up layouts*—especially eBay sellers who print and bind technical manuals.

It provides a single interface to:

- Preview PDF covers  [cover.py](https://github.com/groskwik/cover)
- Extract and preview selected pages
- Generate high‑resolution PNG previews  
- Create 2‑up / 4‑up printable PDFs  
- Manage custom printing presets  
- Save cover images in one click  
- Search PDFs by partial name  
- Automatically scale, crop, and place images  

Built with **Python**, **PySimpleGUI**, **PyMuPDF**, **Pillow**, and **pypdf**.

---

## ✨ Features

### 📄 PDF Preview & Cover Extraction
- Instant selected-page rendering
- Adjustable zoom ratio  
- “Save Image” button exports JPG
- Automatic file naming

### 🧰 Layout Tools (2‑up / 4‑up)
- No rasterization  
- Clean printable layouts  
- Ideal for letter & half‑letter printing  

### 🎨 Image Tools
- Optional LightScribe‑style circular crop  
- Square conversion for CD images  
- Right‑side drop shadows  
- JPG & PNG support  

### 🖨 Printing Integrations
- Uses presets from `myprint.py` / `print_settings.json`
- Multipage ranges  
- Duplex/simplex  
- Color/mono  
- Works with SumatraPDF, GhostScript, or Windows printing  
- Manual 2-sided checkbox for printers with unreliable automatic duplex printing
- `Print manual` can run `myprint.py -manual2sided` from the GUI
- `Print360` can run the manual two-sided print360 workflow from the GUI

### 🔁 Manual 2-Sided GUI Option
The GUI includes a `Manual 2-sided` checkbox below the printer selection.

When checked:

- `Print manual` uses `myprint.py -manual2sided`.
- `Print360` uses `ebay_linker.py --print360manual2sided`.
- `Print720` uses `ebay_linker.py --print720manual2sided`.
- The first pass prints even/simplex pages.
- The second pass uses the matching ` Quiet` printer.
- Print720 manual mode assigns whole manuals to one printer only; it does not split one manual across both printers.

The `Second pass` checkbox reruns only the odd-page pass for `Print manual`, `Print360`, or `Print720`.

Example printer pair:

```text
Brother HL-L8360CDW Series 2
Brother HL-L8360CDW Series 2 Quiet
```

### 🛒 eBay Automation

`ebay_scrape.py` reads awaiting-shipment orders from both configured eBay accounts by default. It keeps each account's login in a separate Selenium profile next to the script:

Install its Python dependencies with `pip install selenium psutil`.

- Primary: `chrome_profile_selenium`
- Secondary: `chrome_profile_selenium_2`

Before using headless mode, initialize each profile with a visible browser and complete the eBay login:

```powershell
python ebay_scrape.py --account primary --stdout-short
python ebay_scrape.py --account secondary --stdout-short
```

After both accounts are authenticated, run both headlessly:

```powershell
python ebay_scrape.py --account both --headless --stdout-short
```

The scraper writes `awaiting_shipment_items.csv`, keeps only titles containing `manual`, `guide`, or `handbook` (including plurals) unless `--no-manual-filter` is supplied, and expands multi-quantity orders into one row per copy.

`restock.py` changes listings whose Restock dialog reports an available quantity of `0` or blank to `1`. Start with a dry run:

```powershell
python restock.py --dry-run --show-window
```

Then run `python restock.py` to update listings. It shares the primary eBay profile and normally closes Chrome processes using that profile before it starts. Do not run it alongside another task using the primary profile. It is non-headless and hidden/minimized by default; use `--show-window` to watch it. Useful options include `--max-items`, `--profile-dir`, and `--no-kill-profile`.

### 🔍 Fast PDF Search
- Partial match search  
- Case‑insensitive  
- Shows matching files for selection

---

## 📂 Project Structure

```
ManualForge/
│
├── ManualForge.py        # Main GUI
├── cover.py              # Cover extraction
├── 2up.py                # 2-up / 4-up generator
├── pdf2png.py            # PDF → PNG high‑res converter
├── myprint.py            # Interactive PDF printing
├── manage_print_settings.py
├── ebay_scrape.py        # Awaiting-shipment order scraper
├── ebay_linker.py        # Order-to-PDF linking and batch printing
├── restock.py            # Restock zero-quantity listings
│
└── README.md
```


## 📜 License

Licensed under the **MIT License**.

---

## 🙏 Acknowledgements

Thanks to:  
- PySimpleGUI  
- PyMuPDF  
- Pillow  
- pypdf  
- The vintage calculator & sewing machine manual community
