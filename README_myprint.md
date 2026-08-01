# MyPrint — Intelligent PDF Printing Utility

MyPrint is a Python-based command-line tool designed to streamline the printing of manuals, sewing machine guides, camera documentation, and other large PDF files.  
It features filename substring searching, automated print presets, JSON-based settings management, and SumatraPDF integration.

A companion tool, **`manage_print_settings.py`**, allows easy editing of the print settings database with the same filename substring search.

---

## ✨ Features

### 🔍 PDF Filename Search
Enter part of a filename — MyPrint finds PDFs whose filenames contain that text across the configured folders:

- Case-insensitive  
- Supports partial names
- Shows matching files with numeric selection when needed

### 🖨 Printer Selection
Choose a printer at runtime from a predefined list or automatically fall back to a default printer.

### 🎛 JSON-Based Print Settings
Each manual can have custom print profiles stored in a shared JSON file:

```
print_settings.json
```

Profiles include color mode, page ranges, duplex modes, orientation, paper size, and scaling.

### 🔄 Interactive Print Settings Editor
Use:

```
python manage_print_settings.py
```

to:

- Search entries fuzzily  
- Add new manuals  
- Modify existing print settings  
- Delete entries  
- Validate the JSON automatically  

### 📚 Batch Printing for Large PDFs
MyPrint can automatically split big PDFs into print-safe chunks (default: 70 pages per batch), adding a delay between batches.

### 🎚 Custom Page Range Override
If no print profile exists—or you want a special range—you can enter a custom page range manually.

### 🔁 Manual Two-Sided Printing Mode
For printers that have a problem with automatic duplex printing, MyPrint supports a manual two-pass mode:

```
python myprint.py -manual2sided
```

In this mode, duplex settings are converted to simplex/even for the first pass, then simplex/odd for the second pass.

Example:

```
monochrome,1-260,duplex,fit,paper=letter
```

becomes this on the first pass:

```
monochrome,1-260,even,simplex,fit,paper=letter
```

and this on the second pass:

```
monochrome,1-260,odd,simplex,fit,paper=letter
```

Real one-sided pages are given blank backs in a temporary PDF, so they follow the same even/odd workflow as duplex pages.

For `duplexshort` / landscape manuals, MyPrint rotates odd pages 180 degrees in the temporary PDF and prints with regular `simplex` settings. This avoids SumatraPDF short-edge duplex behavior during manual two-sided printing.

### 📄 PDF Metadata Extraction
MyPrint uses PyPDF2 to read:

- Page count  
- Document title  
- Basic metadata  

---

## 📦 Requirements

- **Python 3.10 or newer**
- **SumatraPDF** (for command-line printing)  
  https://www.sumatrapdfreader.org/docs/Command-line-arguments  
- **Python packages:**

```
pip install PyPDF2 psutil
```

---

## 🧩 Setup

### 1. Set the path to SumatraPDF
Edit in `myprint.py`:

```python
SUMATRA_PATH = r"C:\path\to\sumatrapdf.exe"
```

### 2. Configure your PDF folders
MyPrint scans the top level of these directories (not subfolders):

```python
PDF_FOLDERS = [
    r"C:\Users\YourName\Manuals",
    r"D:\PDFs"
]
```

### 3. Configure your available printers
Example:

```python
PRINTERS = {
    "1": "Brother_HL2350DW",
    "2": "HP_OfficeJet_Pro_9015",
    "3": "Kyocera_Color"
}
```

For `-manual2sided`, the selected printer must also have a matching Windows printer whose name ends with ` Quiet`.

Example:

```text
Brother HL-L8360CDW Series 2
Brother HL-L8360CDW Series 2 Quiet
```

The first pass uses the normal printer. The second pass uses the ` Quiet` printer.

If the matching quiet printer does not exist, MyPrint does not start the first pass. This is intentional: it assumes that printers without a quiet version have working automatic duplex printing and should not use manual two-sided mode.

### 4. Create or edit your print settings database
Print settings live in:

```
print_settings.json
```

Example entry:

```json
"nikon d850": [
  "monochrome,1-400,duplex,fit,paper=letter"
]
```

Keys must be lowercase manual names without `.pdf`.

---

## 🚀 Usage

Run:

```
python myprint.py
```

For manual two-sided printing:

```
python myprint.py -manual2sided
```

To rerun only the manual two-sided second pass:

```
python myprint.py -secondpass
```

### Step-by-step workflow

1. **Choose a printer**  
   MyPrint lists your configured printers with their IDs.

2. **Search for a PDF**  
   Enter part of the name (e.g., `"nikon 85"`).  
   MyPrint shows files whose names contain the search text:

   ```
   1) nikon d850.pdf
   2) nikon d810.pdf
   3) nikon d800.pdf
   ```

   Then select the correct number.

3. **Check for predefined print settings**  
   If a match exists in `print_settings.json`, MyPrint applies it automatically.

4. **Optional: Custom page range**  
   If no preset exists, or if you want a one-off override, enter:

   ```
   1-50
   ```

   or press Enter for full-document printing.

5. **Batch printing**  
   For documents larger than the batch size (default = 70 pages), MyPrint prints them in waves:

   ```
   Printing pages 1–70...
   Waiting 180 seconds...
   Printing pages 71–140...
   ```

### Manual two-sided workflow

When using `-manual2sided`:

1. MyPrint verifies that a matching ` Quiet` printer exists before printing anything.

2. Duplex settings are transformed for the first pass.

   Example first pass:

   ```
   monochrome,1-260,even,simplex,fit,paper=letter
   ```

   In manual two-sided mode, first-pass batch waits are 1 minute.

3. MyPrint displays the exact SumatraPDF command before each print command is executed.

4. After the first pass finishes, MyPrint asks you to put the paper back in the tray:

   ```text
   even pages face up, top of the paper down
   ```

5. MyPrint displays the exact second-pass SumatraPDF commands before the countdown.

6. A 15-second countdown starts. Press any key during the countdown to cancel the second pass.

7. If not cancelled, the second pass prints through the matching ` Quiet` printer using odd/simplex settings.

   Example second pass:

   ```
   monochrome,1-260,odd,simplex,fit,paper=letter
   ```

   In manual two-sided mode, second-pass batch waits are 90 seconds.

### Second pass recovery mode

Use `-secondpass` if the first pass already completed, but the second pass failed or was cancelled and the paper is still available for the odd-page side.

```
python myprint.py -secondpass
```

This mode:

1. Uses the same saved print settings and custom range prompt.

2. Builds only the odd/simplex second-pass settings.

3. Requires the matching ` Quiet` printer.

4. Displays the exact second-pass SumatraPDF commands before printing.

5. Starts the same 15-second countdown, allowing cancellation by pressing any key.

6. Uses 90-second waits between second-pass batches.

Example with real one-sided pages:

Original settings:

```json
[
  "color,1,simplex,fit,paper=letter",
  "monochrome,2,duplex,fit,paper=letter",
  "monochrome,3-64,duplex,fit,paper=letter"
]
```

Temporary PDF settings used for the manual workflow:

```json
[
  "color,1-2,duplex,fit,paper=letter",
  "monochrome,3-4,duplex,fit,paper=letter",
  "monochrome,5-66,duplex,fit,paper=letter"
]
```

These are then split into even/simplex and odd/simplex passes automatically.

Second pass command settings include:

```json
[
  "color,1-2,odd,simplex,fit,paper=letter",
  "monochrome,3-4,odd,simplex,fit,paper=letter",
  "monochrome,5-66,odd,simplex,fit,paper=letter"
]
```

---

## 🛠 Managing Print Settings

Launch:

```
python manage_print_settings.py
```

This interactive tool allows you to:

- Find a manual by part of its filename
- Add a new entry  
- Edit existing settings  
- Remove outdated entries  
- Save the updated JSON database  

---

## ⚠ Notes

- Ensure printer names match exactly what Windows reports.  
- SumatraPDF may fail silently if a printer name is invalid.  
- `-manual2sided` requires a matching printer named exactly like the selected printer plus ` Quiet`.
- The second pass command is shown before the 15-second cancellation countdown.
- PDF metadata is extracted using PyPDF2.  
- All print setting keys must be lowercase for consistent matching.

---

## 📄 License

MIT License.
