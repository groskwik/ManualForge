
# **ManualForge**
*A GUI tool to preview, process, print, and manage PDF manuals for eBay sellers and collectors*

![ManualForge Logo](./logo.png)

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)  
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)]()  
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)]()

---

## 📌 Overview

**ManualForge** is a lightweight and fast GUI designed for people who frequently work with *printed manuals*, *PDF covers*, and *2-up/4-up layouts*—especially eBay sellers who print and bind technical manuals.

It provides a single interface to:

- Preview PDF covers  
- Extract first pages  
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
- Instant first‑page rendering  
- Adjustable zoom ratio  
- “Save Image” button exports JPG/PNG  
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
- Uses presets from `listpdf.py`
- Multipage ranges  
- Duplex/simplex  
- Color/mono  
- Works with SumatraPDF, GhostScript, or Windows printing  

### 🔍 Fast PDF Search
- Partial match search  
- Case‑insensitive  
- Auto‑selects closest match  

---

## 📂 Project Structure

```
ManualForge/
│
├── manualforge.py        # Main GUI
├── cover.py              # Cover extraction
├── nup_pdf.py            # 2-up / 4-up generator
├── pdf2png.py            # PDF → PNG high‑res converter
├── listpdf.py            # Printer presets
├── assets/
│   ├── logo.png
│   ├── icons/
│
└── README.md


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
