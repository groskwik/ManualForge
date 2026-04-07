#!/usr/bin/env python
import PySimpleGUI as sg
import subprocess
import threading
import queue
import sys
import os
import json
import re
import webbrowser
from pathlib import Path
from typing import List

# try to import PyMuPDF for PDF preview
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# try to import Pillow for image preview
try:
    from PIL import Image
    from io import BytesIO
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ---------- configuration ----------
PDF_FOLDERS = [
    r"C:\Users\benoi\Downloads\ebay_manuals",
    r"C:\Users\benoi\Downloads\manuals",
]

# ISO burning folder (same as isoburn.py default)
ISO_FOLDER = r"C:\Users\benoi\Downloads\Lightscribe"

# Listing DB (JSON) in current working directory
LISTINGS_JSON = "ebay_links.json"

# eBay helper scripts
REVENUE_SCRIPT = "ebay_revenue.py"
SHIPPING_SCRIPT = "ebay_shipping.py"
RESTOCK_SCRIPT = "restock.py"
SCRAPE_SCRIPT = "ebay_scrape.py"
LINKER_SCRIPT = "ebay_linker.py"

# Used by ebay_linker.py
MYPRINT_PATH = r"C:\Users\benoi\Downloads\ManualForge\myprint.py"
AWAITING_CSV = "awaiting_shipment_items.csv"

PRINT_SETTINGS_JSON = "print_settings.json"
LINKED_EVENT = "-LINKED_PDF-"

# Default is now Tahoma (as requested). Toggle will switch to Consolas.
DEFAULT_OUTPUT_FONT = ("Tahoma", 10)
ALT_OUTPUT_FONT = ("Consolas", 10)
MAX_TABS = 6

# per-tab incremental line buffer for stdout/stderr scanning
line_buffers = {i: "" for i in range(1, MAX_TABS + 1)}

SEQ_STATUS_EVENT = "-SEQ_STATUS-"
sequence_threads = {i: None for i in range(1, MAX_TABS + 1)}

RE_LINKED = re.compile(
    r"\bLinked:\s*(.+?)(?:\s*->\s*.*)?$",
    re.IGNORECASE
)

GUI_PREVIEW_EVENT = "-AUTO_PREVIEW_PDF-"

# per-tab line buffer for parsing streamed console output
line_buffers = {i: "" for i in range(1, MAX_TABS + 1)}


# ---------- helpers ----------
def resolve_pdf_from_linked_name(name: str) -> str | None:
    """
    Given a 'Linked: <name>' stdout token, try to find the best matching PDF.
    Strategy:
      1) Try exact basename match (case-insensitive) across PDF_FOLDERS
      2) Fallback: fuzzy contains search using your existing fuzzy_find_pdfs
    """
    if not name:
        return None

    # common: ebay_linker prints the PDF basename (without .pdf)
    wanted = name.strip()
    wanted_lower = wanted.lower()

    # 1) exact basename match
    for folder in PDF_FOLDERS:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if not f.lower().endswith(".pdf"):
                continue
            base = os.path.splitext(f)[0].lower()
            if base == wanted_lower:
                return os.path.join(folder, f)

    # 2) fallback: contains match (your existing engine)
    matches = fuzzy_find_pdfs(wanted)
    if matches:
        return matches[0]

    return None

def get_print_settings_summary(pdf_path: str | None, db: dict) -> str:
    """
    Return a one-line summary of print settings for this PDF.
    - Case-insensitive match on PDF basename
    - Joins settings with ' | '
    - Trimmed to 100 characters + '...' if needed
    """
    if not pdf_path:
        return "Print settings: --"

    base = os.path.splitext(os.path.basename(pdf_path))[0].strip().lower()
    if not base:
        return "Print settings: --"

    # case-insensitive lookup
    for k, v in db.items():
        if str(k).strip().lower() == base and isinstance(v, list) and v:
            summary = " | ".join(v)
            if len(summary) > 100:
                summary = summary[:100] + "..."
            return f"Print settings: {summary}"

    return "Print settings: none"

def set_status_with_print_settings(msg: str, pdf_path: str | None):
    """
    Update status bar message + print settings summary (trimmed).
    Reloads DB so edits via manager are immediately visible.
    """
    db = load_print_settings_db(os.path.join(os.getcwd(), PRINT_SETTINGS_JSON))
    ps_summary = get_print_settings_summary(pdf_path, db)
    window["-STATUS-"].update(f"{msg} | {ps_summary}")

def load_print_settings_db(path: str) -> dict:
    """
    Load print_settings.json. Expected format: { "manualname": [ "...", ... ], ... }
    Returns {} if missing/invalid.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def print_settings_has_pdf(pdf_path: str | None, db: dict) -> bool:
    """
    Case-insensitive match on PDF basename (without extension).
    """
    if not pdf_path:
        return False
    base = os.path.splitext(os.path.basename(pdf_path))[0].strip().lower()
    if not base:
        return False

    # Case-insensitive lookup: normalize DB keys once
    # (fast enough for your size; simplest + robust)
    db_keys_lower = {str(k).strip().lower() for k in db.keys()}
    return base in db_keys_lower

def force_console_monospace(tab_idx: int):
    window[f"-OUTPUT-{tab_idx}-"].update(font=ALT_OUTPUT_FONT)

def list_cover_images():
    """List all PNG/JPG in cwd, excluding middle.png and lightscribe_ebay.jpg, cover.png first."""
    exts = {".png", ".jpg"}
    exclude = {"middle.png", "lightscribe_ebay.jpg"}
    files = []
    for f in os.listdir(os.getcwd()):
        ext = os.path.splitext(f)[1].lower()
        if ext in exts and f.lower() not in exclude:
            files.append(f)
    files.sort()
    if "cover.png" in files:
        files.remove("cover.png")
        files.insert(0, "cover.png")
    return files or ["cover.png"]

def fuzzy_find_pdfs(partial: str):
    """Case-insensitive contains search across PDF_FOLDERS."""
    partial_lower = partial.lower()
    matches = []
    for folder in PDF_FOLDERS:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if f.lower().endswith(".pdf") and partial_lower in f.lower():
                matches.append(os.path.join(folder, f))
    return matches

# ----- ISO fuzzy find (same idea as isoburn.py: list + contains match) -----
def list_iso_files(folder: str) -> List[Path]:
    p = Path(folder)
    if not p.is_dir():
        return []
    return sorted(
        [f for f in p.iterdir() if f.is_file() and f.suffix.lower() == ".iso"],
        key=lambda x: x.name.lower(),
    )

def find_iso_matches(iso_files: List[Path], partial_name: str) -> List[Path]:
    q = partial_name.lower().strip()
    if not q:
        return []
    return [f for f in iso_files if q in f.name.lower()]

def fuzzy_find_isos(partial: str) -> List[Path]:
    files = list_iso_files(ISO_FOLDER)
    return find_iso_matches(files, partial)

def get_pdf_page_count(pdf_path):
    if fitz is None or not pdf_path or not os.path.exists(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        return doc.page_count
    except Exception:
        return None

def render_pdf_page_to_bytes(pdf_path, page_index=0, max_height=700):
    if fitz is None:
        return None
    try:
        doc = fitz.open(pdf_path)
        if page_index < 0 or page_index >= doc.page_count:
            return None
        page = doc.load_page(page_index)
        pix = page.get_pixmap()
        if pix.height > max_height:
            scale = max_height / pix.height
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)
        return pix.tobytes("png")
    except Exception:
        return None

def is_supported_image(path):
    if not PIL_AVAILABLE:
        return False
    try:
        with Image.open(path) as im:
            return im.format.lower() in ("jpeg", "png")
    except Exception:
        return False

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

def load_image_as_png_bytes(path, max_height=700):
    """Open jpg/png → resize → return PNG bytes safe for sg.Image."""
    if not os.path.exists(path):
        return None
    if not is_supported_image(path):
        return None
    try:
        with Image.open(path) as img:
            w, h = img.size
            if h > max_height:
                ratio = max_height / float(h)
                img = img.resize((int(w * ratio), max_height), Image.LANCZOS)
            bio = BytesIO()
            img.save(bio, format="PNG")
            return bio.getvalue()
    except Exception:
        return None

def open_with_default_app(path):
    """Open a file with the OS default application."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        output_queues[get_active_tab()].put(f"ERROR opening file: {e}\n")

def open_url(url: str):
    """Open URL in default browser."""
    try:
        webbrowser.open(url, new=2)  # new tab when possible
    except Exception as e:
        output_queues[get_active_tab()].put(f"ERROR opening URL: {e}\n")

# ---------- Listing DB helpers ----------
def load_listings_db(path: str) -> dict:
    """Load JSON mapping of manual_basename -> {url:..., itemId:...} (flexible)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

ITEMID_RE = re.compile(r"(?:/itm/|item=|itemId=)(\d{9,15})", re.IGNORECASE)

def extract_item_id_from_url(url: str) -> str | None:
    if not url:
        return None
    m = ITEMID_RE.search(url)
    return m.group(1) if m else None

def get_listing_info_for_pdf(pdf_path: str, listings_db: dict) -> tuple[str | None, str | None]:
    """Returns (listing_url, item_id) for the given PDF, based on PDF basename."""
    if not pdf_path:
        return (None, None)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    entry = listings_db.get(base)
    if entry is None:
        return (None, None)

    url = None
    item_id = None

    if isinstance(entry, str):
        url = entry
        item_id = extract_item_id_from_url(url)
        return (url, item_id)

    if isinstance(entry, dict):
        if "url" in entry and isinstance(entry["url"], str):
            url = entry["url"].strip() or None
        if "itemId" in entry and isinstance(entry["itemId"], str):
            item_id = entry["itemId"].strip() or None
        if item_id is None and url is not None:
            item_id = extract_item_id_from_url(url)
        if url is None and item_id is not None:
            url = f"https://www.ebay.com/itm/{item_id}"
        return (url, item_id)

    return (None, None)

def build_revise_url(item_id: str) -> str:
    return f"https://www.ebay.com/sl/list?itemId={item_id}&mode=ReviseItem"

def build_purchase_history_url(item_id: str) -> str:
    return f"https://www.ebay.com/bin/purchaseHistory?item={item_id}"

def build_sell_similar_url(item_id: str) -> str:
    return f"https://www.ebay.com/sl/list?itemId={item_id}&mode=SellSimilarItem"

ORDERS_URL = "https://www.ebay.com/sh/ord/?filter=status:ALL_ORDERS"
ORDERS_AWAITING_URL = "https://www.ebay.com/sh/ord/?filter=status:AWAITING_SHIPMENT"

# ---------- tools ----------
TOOLS = [
    ("Print manual", "myprint.py"),
    ("2 Half-letter pdf", "2up.py"),
    ("Create eBay cover", "cover.py"),
    ("Burn ISO file", "isoburn.py"),
    ("Print shipping labels", "label.py"),
    ("Lightscribe preview", "lightscribe.py"),
    ("Sell manual", "sell.py"),
    ("Inventory", "inventory.py"),
    ("Lightscribe print", "lightscribe_print"),
]

# ---------- theme / options ----------
sg.theme("SystemDefault")
sg.set_options(button_color=(sg.theme_text_color(), sg.theme_background_color()))

n = len(TOOLS)
col_size = (n + 2) // 3
col1 = TOOLS[:col_size]
col2 = TOOLS[col_size:2 * col_size]
col3 = TOOLS[2 * col_size:]

cover_choices = list_cover_images()
current_fuzzy_matches = []

# ISO selection state
current_iso_matches: List[Path] = []

# preview state
current_pdf_path = None
current_pdf_pagecount = None

# listing state
listings_db = load_listings_db(os.path.join(os.getcwd(), LISTINGS_JSON))
print_settings_db = load_print_settings_db(os.path.join(os.getcwd(), PRINT_SETTINGS_JSON))
current_listing_url = None
current_item_id = None

# per-tab process state
procs = {i: None for i in range(1, MAX_TABS + 1)}
stop_flags = {i: threading.Event() for i in range(1, MAX_TABS + 1)}
output_queues = {i: queue.Queue() for i in range(1, MAX_TABS + 1)}
last_run_script = {i: None for i in range(1, MAX_TABS + 1)}
last_generated_cover_path = {i: None for i in range(1, MAX_TABS + 1)}
using_alt_font = False
active_tabs_count = 1
active_tab_index = 1  # 1-based

def get_active_tab():
    return active_tab_index

def update_listing_buttons_state():
    """Enable/disable listing buttons based on current_item_id/current_listing_url."""
    has_listing = (current_listing_url is not None) and (current_item_id is not None)
    try:
        window["-OPEN_LISTING-"].update(disabled=not has_listing)
        window["-REVISE_LISTING-"].update(disabled=not has_listing)
        window["-PURCHASE_HISTORY-"].update(disabled=not has_listing)
        window["-SELL_SIMILAR-"].update(disabled=not has_listing)
    except Exception:
        pass

# ---------- options (left/mid/right) ----------
col_left_options = [
    [sg.Text("Cover:")],
    [sg.Combo(
        cover_choices,
        default_value=cover_choices[0],
        key="-COVERFILE-",
        size=(28, 1),
        background_color="white",
        text_color="black",
        tooltip="Image file used for cover/lightscribe (PNG or JPG)",
    )],
    [sg.Text("Search PDF:", tooltip="Type part of the PDF name – same logic as your scripts")],
    [sg.Input(
        key="-SEARCHTXT-",
        size=(30, 1),
        enable_events=True,
        tooltip="Type part of the PDF name here – will be auto-sent to scripts",
    )],
    [sg.Text("Matches:")],
    [sg.Combo(
        ["(no matches)"],
        default_value="(no matches)",
        key="-SEARCHRESULT-",
        size=(28, 1),
        background_color="white",
        text_color="black",
        enable_events=True,
        tooltip="If multiple PDFs match, pick the one to auto-answer to the script",
    )],
    [sg.Button(
        "Manage print settings",
        key="-MANAGE_PRINT_SETTINGS-",
        size=(22, 1),
        pad=((0, 0), (8, 0))
    )],
    [sg.Button(
        "Reload Database",
        key="-RELOAD_DATABASES-",
        size=(22, 1),
        pad=((0, 0), (10, 0))
    )]

]

col_mid_options = [
    [sg.Text("Printer:")],
    [sg.Radio("Brother HL-L8360CDW [Wireless]", "PRN", key="-PRN1-", default=False)],
    [sg.Radio("Brother HL-L8360CDW series", "PRN", key="-PRN2-", default=True)],
    [sg.Text("Preview page:")],
    [
        sg.Combo(
            ["1"],
            default_value="1",
            key="-PREVIEWPAGE-",
            size=(10, 1),
            readonly=True,
            enable_events=True,
            background_color="white",
            text_color="black",
            tooltip="Select which page to preview from the selected PDF",
        ),
        sg.Button("Open PDF", key="-OPENPDF-")
    ],
]

col_right_options = [
    [sg.Text("Ratio:", tooltip="Scale the cover inside the base image (0.3 → 0.7)")],
    [sg.Slider(
        range=(0.3, 0.7),
        default_value=0.5,
        resolution=0.01,
        orientation="h",
        size=(15, 15),
        key="-RATIO-",
        enable_events=True,
    )],
    [sg.Checkbox(
        "Angle",
        key="-ANGLE-",
        default=False,
        tooltip="Use angled cover layout when running cover.py",
    )],
    [sg.HorizontalSeparator()],
    [sg.Text("Search ISO:", tooltip=f"Type part of the ISO name in {ISO_FOLDER}")],
    [sg.Input(
        key="-ISO_SEARCHTXT-",
        size=(30, 1),
        enable_events=True,
        tooltip="Type part of the ISO name here – used to auto-answer isoburn.py",
    )],
    [sg.Text("ISO matches:")],
    [sg.Combo(
        ["(no matches)"],
        default_value="(no matches)",
        key="-ISO_RESULT-",
        size=(28, 1),
        background_color="white",
        text_color="black",
        enable_events=True,
        tooltip="Pick the ISO to auto-answer selection to isoburn.py",
    )],
    [sg.Text("Burner:")],
    [
        sg.Radio("isoburn", "BURNER", key="-BURN_ISOBURN-", default=True),
        sg.Radio("CDBurnerXP", "BURNER", key="-BURN_CDBXP-", default=False),
        sg.Radio("cdrecord", "BURNER", key="-BURN_CDRECORD-", default=False),
    ],
]

# ---------- tab builder ----------
def make_console_tab(i: int, visible: bool):
    return sg.Tab(
        f"Console {i}",
        [
            [sg.Multiline(
                "",
                size=(90, 15),  # reduced to make room for additional UI
                key=f"-OUTPUT-{i}-",
                autoscroll=True,
                font=DEFAULT_OUTPUT_FONT,
                disabled=True,
                expand_x=True,
                expand_y=True,
            )],
            [
                sg.Input(key=f"-SEND-{i}-", size=(50, 1)),
                sg.Button("Send Command", key=f"-SEND_BTN-{i}-"),
                sg.Button("Stop", key=f"-STOP-{i}-"),
                sg.Button("Clear", key=f"-CLEAR-{i}-"),
                sg.Button("+", key=f"-ADD_TAB-{i}-", tooltip="Add a new console tab (max 6)"),
            ],
        ],
        key=f"-TAB-{i}-",
        visible=visible,
        expand_x=True,
        expand_y=True,
    )

tabs = [make_console_tab(1, True)] + [make_console_tab(i, False) for i in range(2, MAX_TABS + 1)]

# ---------- layout ----------
left_column = [
    [
        sg.Frame(
            "Tools",
            [[
                sg.Column([[sg.Button(lbl, key=("RUN_TOOL", script), size=(25, 1))] for (lbl, script) in col1], pad=(0, 0)),
                sg.Column([[sg.Button(lbl, key=("RUN_TOOL", script), size=(25, 1))] for (lbl, script) in col2], pad=(28, 0)),
                sg.Column([[sg.Button(lbl, key=("RUN_TOOL", script), size=(25, 1))] for (lbl, script) in col3], pad=(28, 0)),
            ]],
            expand_x=True,
        )
    ],
    [
        sg.Frame(
            "Options",
            [[
                sg.Column(col_left_options, vertical_alignment="top"),
                sg.Column(col_mid_options, pad=(15, 0), vertical_alignment="top"),
                sg.Column(col_right_options, pad=(15, 0), vertical_alignment="top"),
            ]],
            expand_x=True,
        )
    ],
    [
        sg.TabGroup(
            [[*tabs]],
            key="-TABS-",
            tab_location="topleft",
            enable_events=True,
            expand_x=True,
            expand_y=True,
        ),
    ],
]

right_column = [
    [sg.Text("Preview:")],
    [sg.Image(key="-PREVIEW-", size=(400, 650))],
    [sg.Push(), sg.Button("← Prev", key="-PREV_PAGE-"), sg.Button("Next →", key="-NEXT_PAGE-"), sg.Push()],
    [
        sg.Push(),
        sg.Button("Save image", key="-SAVE_IMAGE-"),
        sg.Button("Open listing", key="-OPEN_LISTING-", disabled=True),
        sg.Button("Revise listing", key="-REVISE_LISTING-", disabled=True),
        sg.Push(),
    ],
    [
        sg.Push(),
        sg.Button("View purchase history", key="-PURCHASE_HISTORY-", disabled=True),
        sg.Button("Sell similar item", key="-SELL_SIMILAR-", disabled=True),
        sg.Button("Reload funds", key="-RELOAD_FUNDS-"),
        sg.Push(),
    ],
    [
        sg.Push(),
        sg.Button("Orders", key="-ORDERS-"),
        sg.Button("Orders awaiting shipment", key="-ORDERS_AWAITING-"),
        sg.Button("Print label", key="-PRINT_LABEL-"),
        sg.Button("Restock", key="-RESTOCK-"),
        sg.Button("List orders awaiting shipment", key="-LIST_AWAITING-"),
        sg.Push(),
    ],
    [
        sg.Push(),
        sg.Button("Update links", key="-UPDATE_LINKS-"),
        sg.Button("Print360", key="-PRINT360-"),
        sg.Button("Print720", key="-PRINT720-"),
        sg.Button("Check orders and print", key="-CHECK_AND_PRINT-"),
        sg.Checkbox("Always ask printer", key="-ALWAYS_ASK_PRINTER-", default=False),
        sg.Push(),
    ],
]

layout = [
    [
        sg.Column(left_column, expand_y=True),
        sg.Column(right_column, pad=(10, 0), expand_y=True),
    ],
    [
        sg.Text("Status:", size=(8, 1)),
        sg.Text("Idle", key="-STATUS-", expand_x=True),
        sg.Text("Total funds: --", key="-FUNDS-", size=(18, 1), justification="right"),
        sg.Text("Pages: -- | Weight: --", key="-PAGEINFO-", size=(30, 1), justification="right"),
        sg.Button("Switch Font", key="-SWITCH_FONT-"),
        sg.Button("Exit"),
    ],
]

window = sg.Window(
    "ManualForge",
    layout,
    resizable=True,
    location=(0, 0),  # top of screen
    icon="logo.ico" if os.path.exists("logo.ico") else None,
    finalize=True,
)
# Prevent resizing so small that the status bar row disappears
#try:
#    window.TKroot.minsize(950, 650)  # adjust to taste
#except Exception:
#    pass


for i in range(1, MAX_TABS + 1):
    window[f"-SEND-{i}-"].bind("<Return>", "_ENTER")

# ---------- subprocess I/O ----------
def stream_reader_char(tab_idx: int, stream, q):
    while True:
        ch = stream.read(1)
        if not ch:
            break

        # always push raw output to the console queue
        q.put(ch)

        # accumulate line buffer for pattern detection
        buf = line_buffers.get(tab_idx, "") + ch
        line_buffers[tab_idx] = buf

        if ch == "\n":
            line = buf.strip("\r\n")
            line_buffers[tab_idx] = ""  # reset for next line

            m = RE_LINKED.search(line)
            if m:
                linked_name = m.group(1).strip()
                window.write_event_value(GUI_PREVIEW_EVENT, (tab_idx, linked_name))


    try:
        stream.close()
    except Exception:
        pass


def reader_thread(tab_idx, proc, q):
    threading.Thread(target=stream_reader_char, args=(tab_idx, proc.stdout, q), daemon=True).start()
    threading.Thread(target=stream_reader_char, args=(tab_idx, proc.stderr, q), daemon=True).start()

def _start_process(tab_idx: int, cmd: List[str], status_label: str):
    """Start a process and stream output to the tab console."""
    # clear any previous stop flag
    stop_flags[tab_idx].clear()

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        procs[tab_idx] = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=0,
            env=env,
        )
    except FileNotFoundError:
        output_queues[tab_idx].put(f"ERROR: Command not found: {cmd[0]}\n")
        window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: command not found")
        procs[tab_idx] = None
        return

    last_run_script[tab_idx] = status_label
    reader_thread(tab_idx, procs[tab_idx], output_queues[tab_idx])
    output_queues[tab_idx].put(f"Started (Tab {tab_idx}): {' '.join(cmd)}\n")
    window["-STATUS-"].update(f"Tab {tab_idx}: {status_label}")
    window[f"-SEND-{tab_idx}-"].set_focus()

def run_script(tab_idx, script_path, extra_args, auto_inputs=None):
    """Run a python script (interactive OK) and optionally feed auto_inputs."""
    cmd = [sys.executable, "-u", script_path]
    if extra_args:
        cmd.extend(extra_args)

    _start_process(tab_idx, cmd, f"Running {os.path.basename(script_path)}")

    # feed auto inputs
    if auto_inputs and procs[tab_idx] and procs[tab_idx].poll() is None:
        for item in auto_inputs:
            try:
                procs[tab_idx].stdin.write(item + "\n")
                procs[tab_idx].stdin.flush()
            except Exception as e:
                output_queues[tab_idx].put(f"ERROR sending auto input: {e}\n")

def run_python_cmd(tab_idx: int, args: List[str], label: str):
    """Run `python <args...>` and stream output to console."""
    cmd = [sys.executable, "-u", *args]
    _start_process(tab_idx, cmd, label)

def run_sequence_in_thread(tab_idx: int, commands: List[List[str]], labels: List[str]):
    """
    Run a sequence of commands (each is a full cmd list) in a background thread, streaming output.

    Fixes:
      - Clears stop flag at start so a previous cancellation doesn't cancel the next run.
      - Clears stop flag when done (cancelled or completed).
      - Avoids starting a second sequence on the same tab if one is already running.
      - Uses window.write_event_value to update GUI safely from thread.
    """
    # Don't allow two sequences to overlap in the same tab
    t = sequence_threads.get(tab_idx)
    if t is not None and t.is_alive():
        output_queues[tab_idx].put("[Sequence already running in this tab]\n")
        return

    # CRITICAL FIX: reset cancellation state for the new run
    stop_flags[tab_idx].clear()

    def worker():
        cancelled = False
        try:
            window.write_event_value(SEQ_STATUS_EVENT, (tab_idx, f"Tab {tab_idx}: Running sequence"))

            for cmd, label in zip(commands, labels):
                # If user cancelled before we even start this command
                if stop_flags[tab_idx].is_set():
                    cancelled = True
                    output_queues[tab_idx].put("\n[Sequence cancelled]\n")
                    break

                output_queues[tab_idx].put("\n" + "=" * 70 + "\n")
                output_queues[tab_idx].put(f"{label}\n")
                output_queues[tab_idx].put("=" * 70 + "\n")

                _start_process(tab_idx, cmd, label)
                p = procs.get(tab_idx)
                if not p:
                    # _start_process failed or was refused
                    break

                # Wait until finished or cancelled
                while p.poll() is None:
                    if stop_flags[tab_idx].is_set():
                        cancelled = True
                        try:
                            p.terminate()
                        except Exception:
                            pass
                        break
                    threading.Event().wait(0.1)

                # Ensure process slot cleared so next cmd doesn't race the main loop
                procs[tab_idx] = None

                if cancelled:
                    output_queues[tab_idx].put("\n[Sequence cancelled]\n")
                    break

        finally:
            # CRITICAL FIX: make sure next sequence is not instantly cancelled
            stop_flags[tab_idx].clear()

            # Clear "running thread" slot
            sequence_threads[tab_idx] = None

            # Status update (thread-safe)
            window.write_event_value(SEQ_STATUS_EVENT, (tab_idx, f"Tab {tab_idx}: Idle"))

    sequence_threads[tab_idx] = threading.Thread(target=worker, daemon=True)
    sequence_threads[tab_idx].start()

# ---------- preview + listing helpers ----------
def refresh_listing_for_pdf(pdf_path: str | None):
    """Update current listing variables and enable/disable buttons."""
    global current_listing_url, current_item_id

    if not pdf_path or not os.path.exists(pdf_path):
        current_listing_url = None
        current_item_id = None
        update_listing_buttons_state()
        return

    url, item_id = get_listing_info_for_pdf(pdf_path, listings_db)
    current_listing_url = url
    current_item_id = item_id
    update_listing_buttons_state()

def set_pdf_preview(pdf_path, page=1):
    """Set current_pdf_path, update page count, populate combobox, render page."""
    global current_pdf_path, current_pdf_pagecount
    current_pdf_path = pdf_path
    
    set_status_with_print_settings("PDF selected", pdf_path)

    refresh_listing_for_pdf(pdf_path)

    if not pdf_path or not os.path.exists(pdf_path):
        current_pdf_pagecount = None
        window["-PAGEINFO-"].update("Pages: -- | Weight: --")
        window["-PREVIEW-"].update(data=None)
        window["-PREVIEWPAGE-"].update(values=["1"], value="1")
        set_status_with_print_settings("No PDF selected", None)   # NEW (optional)
        return

    pagecount = get_pdf_page_count(pdf_path)
    current_pdf_pagecount = pagecount
    if pagecount:
        weight_str = compute_weight_from_pages(pagecount)
        window["-PAGEINFO-"].update(f"Pages: {pagecount} | Weight: {weight_str}")
        pages = [str(i) for i in range(1, pagecount + 1)]
        window["-PREVIEWPAGE-"].update(values=pages, value=str(min(page, pagecount)))
        img_bytes = render_pdf_page_to_bytes(pdf_path, page_index=min(page, pagecount) - 1)
        window["-PREVIEW-"].update(data=img_bytes if img_bytes else None)
    else:
        window["-PAGEINFO-"].update("Pages: -- | Weight: --")
        window["-PREVIEWPAGE-"].update(values=["1"], value="1")
        window["-PREVIEW-"].update(data=None)

def update_preview_from_image(path):
    img_bytes = load_image_as_png_bytes(path, max_height=700)
    if img_bytes:
        window["-PREVIEW-"].update(data=img_bytes)

def render_current_preview_page(values):
    if not current_pdf_path or not current_pdf_pagecount:
        return
    try:
        page_num = int(values["-PREVIEWPAGE-"])
    except Exception:
        page_num = 1
    page_num = max(1, min(page_num, current_pdf_pagecount))
    img_bytes = render_pdf_page_to_bytes(current_pdf_path, page_index=page_num - 1)
    if img_bytes:
        window["-PREVIEW-"].update(data=img_bytes)

def select_tab(idx):
    try:
        window["-TABS-"].Widget.select(idx - 1)
    except Exception:
        pass

def get_selected_burner(values) -> str:
    if values.get("-BURN_CDBXP-", False):
        return "cdburnerxp"
    if values.get("-BURN_CDRECORD-", False):
        return "cdrecord"
    return "isoburn"

def get_selected_iso_path(values) -> str | None:
    chosen = values.get("-ISO_RESULT-", "(no matches)")
    if not chosen or chosen == "(no matches)":
        return None
    for p in current_iso_matches:
        if p.name == chosen:
            return str(p.resolve())
    candidate = os.path.join(ISO_FOLDER, chosen)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)
    return None

def get_selected_printer_number(values) -> int:
    # matches your existing logic: 1 if PRN1 checked else 2
    return 1 if values.get("-PRN1-", False) else 2

def reload_combo_databases(values):
    """Reload data sources used by the cover, PDF matches, and ISO matches comboboxes."""
    global cover_choices, current_fuzzy_matches, current_iso_matches, listings_db, print_settings_db

    cover_choices = list_cover_images()
    current_cover = values.get("-COVERFILE-", "")
    if current_cover in cover_choices:
        cover_value = current_cover
    else:
        cover_value = cover_choices[0] if cover_choices else ""
    window["-COVERFILE-"].update(values=cover_choices, value=cover_value)

    pdf_query = values.get("-SEARCHTXT-", "").strip()
    if pdf_query:
        current_fuzzy_matches = fuzzy_find_pdfs(pdf_query)
        if current_fuzzy_matches:
            pdf_values = [os.path.basename(m) for m in current_fuzzy_matches]
            current_pdf_choice = values.get("-SEARCHRESULT-", "")
            pdf_value = current_pdf_choice if current_pdf_choice in pdf_values else pdf_values[0]
            window["-SEARCHRESULT-"].update(values=pdf_values, value=pdf_value)
            for fullpath in current_fuzzy_matches:
                if os.path.basename(fullpath) == pdf_value:
                    set_pdf_preview(fullpath, page=1)
                    break
        else:
            current_fuzzy_matches = []
            window["-SEARCHRESULT-"].update(values=["(no matches)"], value="(no matches)")
            set_pdf_preview(None)
    else:
        current_fuzzy_matches = []
        window["-SEARCHRESULT-"].update(values=["(no matches)"], value="(no matches)")
        set_pdf_preview(None)

    iso_query = values.get("-ISO_SEARCHTXT-", "").strip()
    if iso_query:
        current_iso_matches = fuzzy_find_isos(iso_query)
        if current_iso_matches:
            iso_values = [p.name for p in current_iso_matches]
            current_iso_choice = values.get("-ISO_RESULT-", "")
            iso_value = current_iso_choice if current_iso_choice in iso_values else iso_values[0]
            window["-ISO_RESULT-"].update(values=iso_values, value=iso_value)
        else:
            current_iso_matches = []
            window["-ISO_RESULT-"].update(values=["(no matches)"], value="(no matches)")
    else:
        current_iso_matches = []
        window["-ISO_RESULT-"].update(values=["(no matches)"], value="(no matches)")

    listings_db = load_listings_db(os.path.join(os.getcwd(), LISTINGS_JSON))
    print_settings_db = load_print_settings_db(os.path.join(os.getcwd(), PRINT_SETTINGS_JSON))

# ---------- revenue at startup ----------
TOTAL_FUNDS_RE = re.compile(r"Total\s+funds:\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)

def update_total_funds_at_startup():
    """
    Runs ebay_revenue.py once.
    Updates the GUI field -FUNDS-.
    Does NOT write to console.
    """
    script_path = os.path.join(os.getcwd(), REVENUE_SCRIPT)
    if not os.path.exists(script_path):
        window["-FUNDS-"].update("Total funds: --")
        return
    try:
        r = subprocess.run(
            [sys.executable, "-u", script_path],
            capture_output=True,
            text=True,
            check=False,
        )
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        m = TOTAL_FUNDS_RE.search(out)
        if m:
            window["-FUNDS-"].update(f"Total funds: {m.group(1)}")
        else:
            window["-FUNDS-"].update("Total funds: --")
    except Exception:
        window["-FUNDS-"].update("Total funds: --")

update_listing_buttons_state()
update_total_funds_at_startup()

# ---------- main loop ----------
while True:
    event, values = window.read(timeout=100)

    if event in (sg.WIN_CLOSED, "Exit"):
        for i in range(1, MAX_TABS + 1):
            if procs[i] and procs[i].poll() is None:
                try:
                    procs[i].terminate()
                except Exception:
                    pass
        break

    # handle tab change
    if event == "-TABS-":
        tab_key = values["-TABS-"]
        try:
            active_tab_index = int(str(tab_key).split("-TAB-")[1].split("-")[0])
        except Exception:
            active_tab_index = 1

    # per-tab add new console tab
    for i in range(1, MAX_TABS + 1):
        if event == f"-ADD_TAB-{i}-":
            if active_tabs_count < MAX_TABS:
                active_tabs_count += 1
                window[f"-TAB-{active_tabs_count}-"].update(visible=True)
                select_tab(active_tabs_count)
                active_tab_index = active_tabs_count
                window[f"-SEND-{active_tabs_count}-"].set_focus()
            else:
                output_queues[get_active_tab()].put("Max tabs reached (6).\n")

    if event == SEQ_STATUS_EVENT:
        tab_idx, text = values[SEQ_STATUS_EVENT]
        window["-STATUS-"].update(text)

    if event == LINKED_EVENT:
        tab_idx, manual_name = values[LINKED_EVENT]

        pdf_path = resolve_pdf_from_linked_name(manual_name)
        if pdf_path and os.path.exists(pdf_path):
            # Update preview to the PDF currently being printed
            set_pdf_preview(pdf_path, page=1)

            # Optional: sync the PDF search UI (nice UX)
            window["-SEARCHTXT-"].update(manual_name)
            # You can also update the matches combo if you want, but not required.
        else:
            # Don’t spam console; maybe just status
            window["-STATUS-"].update(f"Linked: {manual_name} (PDF not found in folders)")

    if event == GUI_PREVIEW_EVENT:
        tab_idx, linked_name = values[GUI_PREVIEW_EVENT]

        pdf_path = resolve_pdf_from_linked_name(linked_name)
        if pdf_path and os.path.exists(pdf_path):
            # update the preview pane
            set_pdf_preview(pdf_path, page=1)

            # also keep your PDF combobox in sync (optional but recommended)
            window["-SEARCHTXT-"].update(linked_name)
            # trigger the same behavior as typing (optional):
            # window.write_event_value("-SEARCHTXT-", linked_name)

            # status update (optional)
            window["-STATUS-"].update(f"Printing: {os.path.basename(pdf_path)}")
        else:
            # don’t spam status too hard; but useful the first time
            output_queues[get_active_tab()].put(
                f"\n[WARN] Could not resolve PDF for Linked: {linked_name}\n"
            )

    # live PDF search
    if event == "-SEARCHTXT-":
        text = values["-SEARCHTXT-"].strip()
        if text:
            matches = fuzzy_find_pdfs(text)
            current_fuzzy_matches = matches
            if matches:
                window["-SEARCHRESULT-"].update(values=[os.path.basename(m) for m in matches], value=os.path.basename(matches[0]))
                set_pdf_preview(matches[0], page=1)
            else:
                current_fuzzy_matches = []
                window["-SEARCHRESULT-"].update(values=["(no matches)"], value="(no matches)")
                set_pdf_preview(None)
        else:
            current_fuzzy_matches = []
            window["-SEARCHRESULT-"].update(values=["(no matches)"], value="(no matches)")
            set_pdf_preview(None)
            
    if event == "-RELOAD_DATABASES-":
        reload_combo_databases(values)
        window["-STATUS-"].update("Reloaded cover, PDF matches, and ISO matches")

    if event == "-MANAGE_PRINT_SETTINGS-":
        tab_idx = get_active_tab()

        script_name = "manage_print_settings.py"
        script_path = os.path.join(os.getcwd(), script_name)

        # Optional: monospace in the console for this tool
        window[f"-OUTPUT-{tab_idx}-"].update(font=ALT_OUTPUT_FONT)

        if not os.path.exists(script_path):
            output_queues[tab_idx].put(f"ERROR: {script_path} not found\n")
            window["-STATUS-"].update("Manage print settings: script not found")
        else:
            extra_args = []
            auto_inputs = []

            # Same behavior as myprint.py BUT without printer selection
            search_txt = values["-SEARCHTXT-"].strip()
            if search_txt:
                auto_inputs.append(search_txt)

                # If we have multiple matches, send the chosen index like you do for myprint.py
                if current_fuzzy_matches:
                    chosen_basename = values["-SEARCHRESULT-"]
                    if chosen_basename and chosen_basename != "(no matches)":
                        # Only needed if there are multiple matches, but sending it is harmless
                        # if the script prompts anyway.
                        if len(current_fuzzy_matches) > 1:
                            for idx, fullpath in enumerate(current_fuzzy_matches, start=1):
                                if os.path.basename(fullpath) == chosen_basename:
                                    auto_inputs.append(str(idx))
                                    break
                        #else:
                        #    # one match → select 1 (safe)
                        #    auto_inputs.append("1")

            run_script(tab_idx, script_path, extra_args=extra_args, auto_inputs=auto_inputs)
            
    # user picks one of the PDF matches
    if event == "-SEARCHRESULT-":
        chosen = values["-SEARCHRESULT-"]
        if chosen != "(no matches)" and current_fuzzy_matches:
            for fullpath in current_fuzzy_matches:
                if os.path.basename(fullpath) == chosen:
                    set_pdf_preview(fullpath, page=1)
                    break

    # live ISO search
    if event == "-ISO_SEARCHTXT-":
        t = values["-ISO_SEARCHTXT-"].strip()
        if t:
            iso_matches = fuzzy_find_isos(t)
            current_iso_matches = iso_matches
            if iso_matches:
                window["-ISO_RESULT-"].update(values=[p.name for p in iso_matches], value=iso_matches[0].name)
            else:
                current_iso_matches = []
                window["-ISO_RESULT-"].update(values=["(no matches)"], value="(no matches)")
        else:
            current_iso_matches = []
            window["-ISO_RESULT-"].update(values=["(no matches)"], value="(no matches)")

    # user changes preview page
    if event == "-PREVIEWPAGE-":
        render_current_preview_page(values)

    # arrow buttons
    if event in ("-PREV_PAGE-", "-NEXT_PAGE-"):
        if current_pdf_pagecount:
            try:
                page_num = int(values["-PREVIEWPAGE-"])
            except Exception:
                page_num = 1
            if event == "-PREV_PAGE-":
                page_num = max(1, page_num - 1)
            else:
                page_num = min(current_pdf_pagecount, page_num + 1)
            window["-PREVIEWPAGE-"].update(value=str(page_num))
            render_current_preview_page(values)

    # open PDF
    if event == "-OPENPDF-":
        if current_pdf_path and os.path.exists(current_pdf_path):
            open_with_default_app(current_pdf_path)
        else:
            output_queues[get_active_tab()].put("No PDF selected to open.\n")

    # ----- Listing buttons -----
    if event == "-OPEN_LISTING-":
        if current_listing_url:
            open_url(current_listing_url)
        else:
            output_queues[get_active_tab()].put("No listing URL for current PDF (check ebay_links.json).\n")

    if event == "-REVISE_LISTING-":
        if current_item_id:
            open_url(build_revise_url(current_item_id))
        else:
            output_queues[get_active_tab()].put("No itemId for current PDF (check ebay_links.json).\n")

    if event == "-PURCHASE_HISTORY-":
        if current_item_id:
            open_url(build_purchase_history_url(current_item_id))
        else:
            output_queues[get_active_tab()].put("No itemId for current PDF (check ebay_links.json).\n")

    if event == "-SELL_SIMILAR-":
        if current_item_id:
            open_url(build_sell_similar_url(current_item_id))
        else:
            output_queues[get_active_tab()].put("No itemId for current PDF (check ebay_links.json).\n")

    if event == "-RELOAD_FUNDS-":
        update_total_funds_at_startup()
        window["-STATUS-"].update("Total funds reloaded")

    # ----- Orders buttons -----
    if event == "-ORDERS-":
        open_url(ORDERS_URL)

    if event == "-ORDERS_AWAITING-":
        open_url(ORDERS_AWAITING_URL)

    # NEW: Print label -> ebay_shipping.py
    if event == "-PRINT_LABEL-":
        tab_idx = get_active_tab()
        force_console_monospace(tab_idx)
        script_path = os.path.join(os.getcwd(), SHIPPING_SCRIPT)
        if not os.path.exists(script_path):
            output_queues[tab_idx].put(f"ERROR: {script_path} not found\n")
            window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        else:
            run_script(tab_idx, script_path, extra_args=[], auto_inputs=None)

    # NEW: Restock -> restock.py
    if event == "-RESTOCK-":
        tab_idx = get_active_tab()
        script_path = os.path.join(os.getcwd(), RESTOCK_SCRIPT)
        if not os.path.exists(script_path):
            output_queues[tab_idx].put(f"ERROR: {script_path} not found\n")
            window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        else:
            run_script(tab_idx, script_path, extra_args=[], auto_inputs=None)

    # NEW: List orders awaiting shipment -> python ebay_scrape.py --headless --stdout-short
    if event == "-LIST_AWAITING-":
        tab_idx = get_active_tab()
        force_console_monospace(tab_idx)
        script_path = os.path.join(os.getcwd(), SCRAPE_SCRIPT)
        if not os.path.exists(script_path):
            output_queues[tab_idx].put(f"ERROR: {script_path} not found\n")
            window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        else:
            run_python_cmd(tab_idx, [SCRAPE_SCRIPT, "--headless", "--stdout-short"], "Listing awaiting shipment")

    if event == "-PRINT720-":
        tab_idx = get_active_tab()
        force_console_monospace(tab_idx)

        linker_path = os.path.join(os.getcwd(), LINKER_SCRIPT)
        if not os.path.exists(linker_path):
            output_queues[tab_idx].put(f"ERROR: {linker_path} not found\n")
            window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        else:
            # Printer selection from GUI
            prn1 = str(get_selected_printer_number(values))

            # Second printer = the other one
            # (keeps logic explicit and robust)
            prn2 = "2" if prn1 == "1" else "1"

            cmd = [
                sys.executable, "-u", LINKER_SCRIPT,
                "--orders-csv", AWAITING_CSV,
                "--links-json", LISTINGS_JSON,
                "--out-links-json", LISTINGS_JSON,
                "--print720",
                "--printer", prn1,
                "--printer2", prn2,
            ]

            _start_process(tab_idx, cmd, "ebay_linker.py (print720)")

    if event == "-PRINT360-":
        tab_idx = get_active_tab()
        force_console_monospace(tab_idx)

        linker_path = os.path.join(os.getcwd(), LINKER_SCRIPT)
        if not os.path.exists(linker_path):
            output_queues[tab_idx].put(f"ERROR: {linker_path} not found\n")
            window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        else:
            prn = str(get_selected_printer_number(values))
            cmd = [
                sys.executable, "-u", LINKER_SCRIPT,
                "--orders-csv", AWAITING_CSV,
                "--links-json", LISTINGS_JSON,
                "--out-links-json", LISTINGS_JSON,
                "--print360",
                "--printer", prn,
            ]
            _start_process(tab_idx, cmd, "ebay_linker.py (print360)")

    if event == "-UPDATE_LINKS-":
        tab_idx = get_active_tab()
        force_console_monospace(tab_idx)

        linker_path = os.path.join(os.getcwd(), LINKER_SCRIPT)
        if not os.path.exists(linker_path):
            output_queues[tab_idx].put(f"ERROR: {linker_path} not found\n")
            window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        else:
            cmd = [
                sys.executable, "-u", LINKER_SCRIPT,
                "--orders-csv", AWAITING_CSV,
                "--links-json", LISTINGS_JSON,
                "--out-links-json", LISTINGS_JSON,
                "--recursive",
                "--min-score", "60",
                "--min-margin", "8",
            ]
            _start_process(tab_idx, cmd, "ebay_linker.py (update links)")

    if event == "-CHECK_AND_PRINT-":
        tab_idx = get_active_tab()
        force_console_monospace(tab_idx)

        # Optional but recommended: clear any previous cancellation *right here*
        stop_flags[tab_idx].clear()

        scrape_path = os.path.join(os.getcwd(), SCRAPE_SCRIPT)
        linker_path = os.path.join(os.getcwd(), LINKER_SCRIPT)

        if not os.path.exists(scrape_path):
            output_queues[tab_idx].put(f"ERROR: {scrape_path} not found\n")
            window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        elif not os.path.exists(linker_path):
            output_queues[tab_idx].put(f"ERROR: {linker_path} not found\n")
            window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        else:
            cmd1 = [sys.executable, "-u", SCRAPE_SCRIPT, "--headless", "--stdout-short"]

            cmd2 = [
                sys.executable, "-u", LINKER_SCRIPT,
                "--orders-csv", AWAITING_CSV,
                "--links-json", LISTINGS_JSON,
                "--out-links-json", LISTINGS_JSON,
                "--recursive",
                "--min-score", "60",
                "--min-margin", "8",
                "--print",
                "--myprint", MYPRINT_PATH,
            ]

            if values.get("-ALWAYS_ASK_PRINTER-", False):
                cmd2.extend(["--always-ask-printer"])
            else:
                prn = str(get_selected_printer_number(values))
                cmd2.extend(["--printer", prn])

            run_sequence_in_thread(
                tab_idx,
                commands=[cmd1, cmd2],
                labels=[
                    "ebay_scrape.py --headless --stdout-short",
                    "ebay_linker.py (link + print)",
                ],
            )

    # save current preview as JPG
    if event == "-SAVE_IMAGE-":
        tab_idx = get_active_tab()

        if fitz is None:
            output_queues[tab_idx].put("Cannot save preview: PyMuPDF (fitz) is not available.\n")
            window["-STATUS-"].update("Cannot save preview (no PyMuPDF)")
        elif current_pdf_path is None or not os.path.exists(current_pdf_path):
            output_queues[tab_idx].put("No PDF page preview to save.\n")
            window["-STATUS-"].update("No PDF page preview to save")
        elif not PIL_AVAILABLE:
            output_queues[tab_idx].put("Cannot save as JPG: Pillow (PIL) is not available.\n")
            window["-STATUS-"].update("Cannot save as JPG (no Pillow)")
        else:
            try:
                page_num = int(values["-PREVIEWPAGE-"])
            except Exception:
                page_num = 1

            png_bytes = render_pdf_page_to_bytes(current_pdf_path, page_index=page_num - 1)
            if not png_bytes:
                output_queues[tab_idx].put("Failed to render current PDF page.\n")
                window["-STATUS-"].update("Failed to render current PDF page")
            else:
                base = os.path.splitext(os.path.basename(current_pdf_path))[0]
                out_name = f"{base}_p{page_num}.jpg"
                out_path = os.path.join(os.getcwd(), out_name)
                try:
                    bio = BytesIO(png_bytes)
                    img = Image.open(bio).convert("RGB")
                    img.save(out_path, "JPEG")
                    output_queues[tab_idx].put(f"Saved preview as {out_name}\n")
                    window["-STATUS-"].update(f"Saved preview as {out_name}")
                except Exception as e:
                    output_queues[tab_idx].put(f"ERROR saving preview: {e}\n")
                    window["-STATUS-"].update("ERROR saving preview")

    # run a tool (uses active tab)
    if isinstance(event, tuple) and event[0] == "RUN_TOOL":
        tab_idx = get_active_tab()
        script = event[1]

        # If a process is already running in this tab, warn
        if procs[tab_idx] and procs[tab_idx].poll() is None:
            output_queues[tab_idx].put("A process is already running in this tab. Stop it first.\n")
            continue

        # inventory -> monospace
        if script == "inventory.py":
            window[f"-OUTPUT-{tab_idx}-"].update(font=ALT_OUTPUT_FONT)

        # lightscribe print (external EXE or open .lsl if ISO selected)
        if script == "lightscribe_print":
            exe_path = r"C:\Program Files (x86)\LightScribe Template Labeler\TemplateLabeler.exe"

            iso_path = get_selected_iso_path(values)
            if iso_path:
                base = os.path.splitext(iso_path)[0]
                lsl_path = base + ".lsl"
                if os.path.exists(lsl_path):
                    try:
                        open_with_default_app(lsl_path)
                        output_queues[tab_idx].put(f"Opened LightScribe project:\n  {lsl_path}\n")
                        window["-STATUS-"].update("Opened .lsl for selected ISO")
                    except Exception as e:
                        output_queues[tab_idx].put(f"ERROR opening .lsl: {e}\n")
                        window["-STATUS-"].update("ERROR opening .lsl")
                    continue
                else:
                    output_queues[tab_idx].put(
                        f"WARNING: .lsl not found for selected ISO:\n  {lsl_path}\n"
                        "Opening TemplateLabeler.exe instead.\n"
                    )

            if os.path.exists(exe_path):
                try:
                    subprocess.Popen([exe_path])
                    output_queues[tab_idx].put(f"Started Lightscribe Template Labeler:\n  {exe_path}\n")
                    window["-STATUS-"].update("Lightscribe Template Labeler started")
                except Exception as e:
                    output_queues[tab_idx].put(f"ERROR launching TemplateLabeler.exe: {e}\n")
                    window["-STATUS-"].update("ERROR launching TemplateLabeler.exe")
            else:
                output_queues[tab_idx].put(
                    "ERROR: TemplateLabeler.exe not found at:\n"
                    "  C:\\Program Files (x86)\\LightScribe Template Labeler\\TemplateLabeler.exe\n"
                )
                window["-STATUS-"].update("TemplateLabeler.exe not found")
            continue

        # isoburn.py special case (auto answer)
        if script == "isoburn.py":
            script_path = os.path.join(os.getcwd(), script)
            if not os.path.exists(script_path):
                output_queues[tab_idx].put(f"ERROR: {script_path} not found\n")
                window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
                continue

            extra_args = []
            auto_inputs = []

            burner = get_selected_burner(values)
            extra_args.append(f"--burner={burner}")
            extra_args.append(f"--folder={ISO_FOLDER}")

            iso_query = values.get("-ISO_SEARCHTXT-", "").strip()
            if iso_query:
                auto_inputs.append(iso_query)
                if current_iso_matches:
                    chosen_iso = values.get("-ISO_RESULT-", "(no matches)")
                    if chosen_iso != "(no matches)":
                        idx_to_send = None
                        for idx, p in enumerate(current_iso_matches, start=1):
                            if p.name == chosen_iso:
                                idx_to_send = idx
                                break
                        if idx_to_send is not None:
                            auto_inputs.append(str(idx_to_send))

            run_script(tab_idx, script_path, extra_args, auto_inputs=auto_inputs)
            continue

        # normal python script tools
        script_path = os.path.join(os.getcwd(), script)
        if not os.path.exists(script_path):
            output_queues[tab_idx].put(f"ERROR: {script_path} not found\n")
            window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        else:
            extra_args = []
            auto_inputs = []
            selected_pdf_basename = None

            scripts_that_need_pdf = {"myprint.py", "cover.py", "2up.py"}

            if script == "cover.py":
                ratio = f"{values['-RATIO-']:.2f}"
                coverfile = values["-COVERFILE-"].strip()
                extra_args.append(f"--ratio={ratio}")
                if coverfile:
                    extra_args.append(f"--cover={coverfile}")
                if values.get("-ANGLE-", False):
                    extra_args.append("--angle")

            if script == "lightscribe.py":
                coverfile = values["-COVERFILE-"].strip()
                if coverfile:
                    extra_args.append(f"--cover={coverfile}")

            if script in scripts_that_need_pdf:
                if script == "myprint.py":
                    auto_inputs.append("1" if values["-PRN1-"] else "2")

                search_txt = values["-SEARCHTXT-"].strip()
                if search_txt:
                    auto_inputs.append(search_txt)
                    if current_fuzzy_matches:
                        chosen_basename = values["-SEARCHRESULT-"]
                        if chosen_basename != "(no matches)":
                            selected_pdf_basename = chosen_basename
                            for idx, fullpath in enumerate(current_fuzzy_matches, start=1):
                                if os.path.basename(fullpath) == chosen_basename and len(current_fuzzy_matches) > 1:
                                    auto_inputs.append(str(idx))
                                    break

            if script == "cover.py":
                if selected_pdf_basename:
                    expected_png = os.path.splitext(selected_pdf_basename)[0] + ".png"
                    last_generated_cover_path[tab_idx] = os.path.join(os.getcwd(), expected_png)
                else:
                    last_generated_cover_path[tab_idx] = None

            run_script(tab_idx, script_path, extra_args, auto_inputs=auto_inputs)

    # per-tab controls: Stop / Clear / Send
    for i in range(1, MAX_TABS + 1):
        if event == f"-STOP-{i}-":
            stop_flags[i].set()
            if procs[i] and procs[i].poll() is None:
                try:
                    procs[i].terminate()
                except Exception:
                    pass
                output_queues[i].put("\n[Process stopped by user]\n")
                window["-STATUS-"].update(f"Tab {i}: Stopped")
            else:
                output_queues[i].put("No running process to stop.\n")

        if event == f"-CLEAR-{i}-":
            window[f"-OUTPUT-{i}-"].update("")

        if event in (f"-SEND_BTN-{i}-", f"-SEND-{i}-" + "_ENTER"):
            text_to_send = values.get(f"-SEND-{i}-", "")
            if procs[i] and procs[i].poll() is None:
                try:
                    procs[i].stdin.write(text_to_send + "\n")
                    procs[i].stdin.flush()
                except Exception as e:
                    output_queues[i].put(f"ERROR sending input: {e}\n")
            else:
                output_queues[i].put("No running process.\n")
            window[f"-SEND-{i}-"].update("")

    # toggle fonts for ALL consoles
    if event == "-SWITCH_FONT-":
        using_alt_font = not using_alt_font
        new_font = (ALT_OUTPUT_FONT if using_alt_font else DEFAULT_OUTPUT_FONT)
        for i in range(1, MAX_TABS + 1):
            window[f"-OUTPUT-{i}-"].update(font=new_font)

    # flush output from all tabs + parse "Linked:" lines
    for i in range(1, MAX_TABS + 1):
        try:
            while True:
                chunk = output_queues[i].get_nowait()

                # still append to console
                window[f"-OUTPUT-{i}-"].update(chunk, append=True)

                # accumulate into a line buffer for parsing
                line_buffers[i] += chunk
                while "\n" in line_buffers[i]:
                    line, remainder = line_buffers[i].split("\n", 1)
                    line_buffers[i] = remainder

                    m = RE_LINKED.match(line)
                    if m:
                        linked_name = m.group(1).strip()
                        # send an event to the GUI thread with tab + name
                        window.write_event_value(GUI_PREVIEW_EVENT, (i, linked_name))
        except queue.Empty:
            pass

    # processes finished? handle previews
    for i in range(1, MAX_TABS + 1):
        if procs[i] and procs[i].poll() is not None:
            window["-STATUS-"].update(f"Tab {i}: Idle")
            if last_run_script[i] == "Running lightscribe.py":
                ls_path = os.path.join(os.getcwd(), "lightscribe_ebay.jpg")
                if os.path.exists(ls_path):
                    update_preview_from_image(ls_path)
            if last_run_script[i] == "Running cover.py":
                if last_generated_cover_path[i] and os.path.exists(last_generated_cover_path[i]):
                    update_preview_from_image(last_generated_cover_path[i])
            procs[i] = None

window.close()

