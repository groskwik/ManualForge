#!/usr/bin/env python
import PySimpleGUI as sg
import subprocess
import threading
import queue
import sys
import os

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

# Default is now Tahoma (as requested). Toggle will switch to Consolas.
DEFAULT_OUTPUT_FONT = ("Tahoma", 10)
ALT_OUTPUT_FONT = ("Consolas", 10)
MAX_TABS = 6

# ---------- helpers ----------
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

def get_pdf_page_count(pdf_path):
    if fitz is None or not pdf_path or not os.path.exists(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        return doc.page_count
    except Exception:
        return None

def render_pdf_page_to_bytes(pdf_path, page_index=0, max_height=800):
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

def load_image_as_png_bytes(path, max_height=800):
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

# ---------- tools ----------
TOOLS = [
    ("Print manual", "myprint.py"),
    ("2 Half-letter pdf", "2up.py"),
    ("Create eBay cover", "cover.py"),
    ("Batch eBay covers", "batch_cover.py"),
    ("Print shipping labels", "label.py"),
    ("Lightscribe preview", "lightscribe.py"),
    ("PDF → PNG (all pages)", "pdf2png.py"),
    ("Inventory", "inventory.py"),
    ("Lightscribe print", "lightscribe_print"),  # <-- new button
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

# preview state
current_pdf_path = None
current_pdf_pagecount = None

# per-tab process state
procs = {i: None for i in range(1, MAX_TABS + 1)}
output_queues = {i: queue.Queue() for i in range(1, MAX_TABS + 1)}
last_run_script = {i: None for i in range(1, MAX_TABS + 1)}
last_generated_cover_path = {i: None for i in range(1, MAX_TABS + 1)}
using_alt_font = False
active_tabs_count = 1
active_tab_index = 1  # 1-based

def get_active_tab():
    return active_tab_index

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
]

# ---------- tab builder ----------
def make_console_tab(i: int, visible: bool):
    return sg.Tab(
        f"Console {i}",
        [
            [sg.Multiline(
                "",
                size=(90, 25),
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

# pre-create up to MAX_TABS tabs, only the first visible initially
tabs = [make_console_tab(1, True)] + [make_console_tab(i, False) for i in range(2, MAX_TABS + 1)]

# ---------- layout ----------
left_column = [
    [
        sg.Frame(
            "Tools",
            [[
                sg.Column([[sg.Button(lbl, key=("RUN_TOOL", script), size=(25, 1))] for (lbl, script) in col1], pad=(0, 0)),
                sg.Column([[sg.Button(lbl, key=("RUN_TOOL", script), size=(25, 1))] for (lbl, script) in col2], pad=(8, 0)),
                sg.Column([[sg.Button(lbl, key=("RUN_TOOL", script), size=(25, 1))] for (lbl, script) in col3], pad=(8, 0)),
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
    [sg.Image(key="-PREVIEW-", size=(400, 800))],
    [sg.Push(), sg.Button("← Prev", key="-PREV_PAGE-"), sg.Button("Next →", key="-NEXT_PAGE-"), sg.Push()],
    [sg.Push(), sg.Button("Save image", key="-SAVE_IMAGE-"), sg.Push()],
]

layout = [
    [
        sg.Column(left_column, expand_y=True),
        sg.Column(right_column, pad=(10, 0), expand_y=True),
    ],
    [
        sg.Text("Status:", size=(8, 1)),
        sg.Text("Idle", key="-STATUS-", expand_x=True),
        sg.Text("Pages: --", key="-PAGEINFO-", size=(15, 1), justification="right"),
        sg.Button("Switch Font", key="-SWITCH_FONT-"),
        sg.Button("Exit"),
    ],
]

window = sg.Window(
    "ManualForge",
    layout,
    resizable=True,
    icon="ebay.ico" if os.path.exists("ebay.ico") else None,
    finalize=True,
)
# Bind Enter for each tab's send input
for i in range(1, MAX_TABS + 1):
    window[f"-SEND-{i}-"].bind("<Return>", "_ENTER")

# ---------- subprocess I/O ----------
def stream_reader_char(stream, q):
    while True:
        ch = stream.read(1)
        if not ch:
            break
        q.put(ch)
    stream.close()

def reader_thread(tab_idx, proc, q):
    threading.Thread(target=stream_reader_char, args=(proc.stdout, q), daemon=True).start()
    threading.Thread(target=stream_reader_char, args=(proc.stderr, q), daemon=True).start()

def run_script(tab_idx, script_path, extra_args, auto_inputs=None):
    cmd = [sys.executable, "-u", script_path]
    if extra_args:
        cmd.extend(extra_args)
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
        last_run_script[tab_idx] = os.path.basename(script_path)
    except FileNotFoundError:
        output_queues[tab_idx].put(f"ERROR: could not start {script_path}\n")
        window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        return
    reader_thread(tab_idx, procs[tab_idx], output_queues[tab_idx])
    output_queues[tab_idx].put(f"Started (Tab {tab_idx}): {' '.join(cmd)}\n")
    window["-STATUS-"].update(f"Tab {tab_idx}: Running {os.path.basename(script_path)}")
    window[f"-SEND-{tab_idx}-"].set_focus()
    if auto_inputs:
        for item in auto_inputs:
            try:
                procs[tab_idx].stdin.write(item + "\n")
                procs[tab_idx].stdin.flush()
            except Exception as e:
                output_queues[tab_idx].put(f"ERROR sending auto input: {e}\n")

# ---------- preview helpers ----------
def set_pdf_preview(pdf_path, page=1):
    """Set current_pdf_path, update page count, populate combobox, render page."""
    global current_pdf_path, current_pdf_pagecount
    current_pdf_path = pdf_path
    if not pdf_path or not os.path.exists(pdf_path):
        current_pdf_pagecount = None
        window["-PAGEINFO-"].update("Pages: --")
        window["-PREVIEW-"].update(data=None)
        window["-PREVIEWPAGE-"].update(values=["1"], value="1")
        return

    pagecount = get_pdf_page_count(pdf_path)
    current_pdf_pagecount = pagecount
    if pagecount:
        window["-PAGEINFO-"].update(f"Pages: {pagecount}")
        pages = [str(i) for i in range(1, pagecount + 1)]
        window["-PREVIEWPAGE-"].update(values=pages, value=str(min(page, pagecount)))
        img_bytes = render_pdf_page_to_bytes(pdf_path, page_index=min(page, pagecount) - 1)
        if img_bytes:
            window["-PREVIEW-"].update(data=img_bytes)
        else:
            window["-PREVIEW-"].update(data=None)
    else:
        window["-PAGEINFO-"].update("Pages: --")
        window["-PREVIEWPAGE-"].update(values=["1"], value="1")
        window["-PREVIEW-"].update(data=None)

def update_preview_from_image(path):
    img_bytes = load_image_as_png_bytes(path, max_height=800)
    if img_bytes:
        window["-PREVIEW-"].update(data=img_bytes)

def render_current_preview_page(values):
    """Render the page number currently selected in the combobox."""
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

# ---------- tab utils ----------
def select_tab(idx):
    """Select tab idx (1-based) in the TabGroup."""
    try:
        window["-TABS-"].Widget.select(idx - 1)
    except Exception:
        pass

# ---------- main loop ----------
while True:
    event, values = window.read(timeout=100)

    if event in (sg.WIN_CLOSED, "Exit"):
        for i in range(1, MAX_TABS + 1):
            if procs[i] and procs[i].poll() is None:
                procs[i].terminate()
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
                # focus the new tab's input for immediate typing
                window[f"-SEND-{active_tabs_count}-"].set_focus()
            else:
                output_queues[get_active_tab()].put("Max tabs reached (6).\n")

    # live PDF search
    if event == "-SEARCHTXT-":
        text = values["-SEARCHTXT-"].strip()
        if text:
            matches = fuzzy_find_pdfs(text)
            current_fuzzy_matches = matches
            if matches:
                window["-SEARCHRESULT-"].update(
                    values=[os.path.basename(m) for m in matches],
                    value=os.path.basename(matches[0]),
                )
                set_pdf_preview(matches[0], page=1)
            else:
                current_fuzzy_matches = []
                window["-SEARCHRESULT-"].update(values=["(no matches)"], value="(no matches)")
                set_pdf_preview(None)
        else:
            current_fuzzy_matches = []
            window["-SEARCHRESULT-"].update(values=["(no matches)"], value="(no matches)")
            set_pdf_preview(None)

    # user picks one of the matches
    if event == "-SEARCHRESULT-":
        chosen = values["-SEARCHRESULT-"]
        if chosen != "(no matches)" and current_fuzzy_matches:
            for fullpath in current_fuzzy_matches:
                if os.path.basename(fullpath) == chosen:
                    set_pdf_preview(fullpath, page=1)
                    break

    # user changes preview page via combobox
    if event == "-PREVIEWPAGE-":
        render_current_preview_page(values)

    # arrow buttons under preview
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

    # open PDF with default app
    if event == "-OPENPDF-":
        if current_pdf_path and os.path.exists(current_pdf_path):
            open_with_default_app(current_pdf_path)
        else:
            output_queues[get_active_tab()].put("No PDF selected to open.\n")

    # save current PDF preview page as JPG
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
            # determine current page number from the combobox
            try:
                page_num = int(values["-PREVIEWPAGE-"])
            except Exception:
                page_num = 1

            # get PNG bytes for that page
            png_bytes = render_pdf_page_to_bytes(current_pdf_path, page_index=page_num - 1)
            if not png_bytes:
                output_queues[tab_idx].put("Failed to render current PDF page.\n")
                window["-STATUS-"].update("Failed to render current PDF page")
            else:
                # build output JPG filename: <pdf_name>_p<page>.jpg
                base = os.path.splitext(os.path.basename(current_pdf_path))[0]
                out_name = f"{base}_p{page_num}.jpg"
                out_path = os.path.join(os.getcwd(), out_name)

                try:
                    # convert PNG bytes -> JPG file using Pillow
                    bio = BytesIO(png_bytes)
                    img = Image.open(bio).convert("RGB")
                    img.save(out_path, "JPEG")

                    msg = f"Saved preview as {out_name}\n"
                    output_queues[tab_idx].put(msg)
                    window["-STATUS-"].update(f"Saved preview as {out_name}")
                except Exception as e:
                    output_queues[tab_idx].put(f"ERROR saving preview: {e}\n")
                    window["-STATUS-"].update("ERROR saving preview")

    # run a tool (uses active tab)
    if isinstance(event, tuple) and event[0] == "RUN_TOOL":
        tab_idx = get_active_tab()
        script = event[1]
        # --- Force monospace font for inventory.py ---
        if script == "inventory.py":
            window[f"-OUTPUT-{tab_idx}-"].update(font=ALT_OUTPUT_FONT)


        # --- special case: Lightscribe print (external EXE) ---
        if script == "lightscribe_print":
            exe_path = r"C:\Program Files (x86)\LightScribe Template Labeler\TemplateLabeler.exe"
            if os.path.exists(exe_path):
                try:
                    subprocess.Popen([exe_path])
                    output_queues[tab_idx].put(f"Started Lightscribe Template Labeler:\n  {exe_path}\n")
                    window["-STATUS-"].update(f"Tab {tab_idx}: Lightscribe Template Labeler started")
                except Exception as e:
                    output_queues[tab_idx].put(f"ERROR launching TemplateLabeler.exe: {e}\n")
                    window["-STATUS-"].update(f"Tab {tab_idx}: ERROR launching TemplateLabeler.exe")
            else:
                output_queues[tab_idx].put("ERROR: TemplateLabeler.exe not found at:\n"
                                           "  C:\\Program Files (x86)\\LightScribe Template Labeler\\TemplateLabeler.exe\n")
                window["-STATUS-"].update(f"Tab {tab_idx}: TemplateLabeler.exe not found")
            continue  # skip normal python-script handling for this button

        # --- normal Python tools below ---
        script_path = os.path.join(os.getcwd(), script)
        if not os.path.exists(script_path):
            output_queues[tab_idx].put(f"ERROR: {script_path} not found\n")
            window["-STATUS-"].update(f"Tab {tab_idx}: ERROR: script not found")
        else:
            extra_args = []
            auto_inputs = []
            selected_pdf_basename = None

            scripts_that_need_pdf = {
                "myprint.py",
                "cover.py",
                "batch_cover.py",
                "pdf2png.py",
                "2up.py",
            }

            if script in ("cover.py", "batch_cover.py"):
                ratio = f"{values['-RATIO-']:.2f}"
                coverfile = values["-COVERFILE-"].strip()
                extra_args.append(f"--ratio={ratio}")
                if coverfile:
                    extra_args.append(f"--cover={coverfile}")

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
            if procs[i] and procs[i].poll() is None:
                procs[i].terminate()
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

    # flush output from all tabs
    for i in range(1, MAX_TABS + 1):
        try:
            while True:
                chunk = output_queues[i].get_nowait()
                window[f"-OUTPUT-{i}-"].update(chunk, append=True)
        except queue.Empty:
            pass

    # processes finished? handle previews
    for i in range(1, MAX_TABS + 1):
        if procs[i] and procs[i].poll() is not None:
            window["-STATUS-"].update(f"Tab {i}: Idle")
            if last_run_script[i] == "lightscribe.py":
                ls_path = os.path.join(os.getcwd(), "lightscribe_ebay.jpg")
                if os.path.exists(ls_path):
                    update_preview_from_image(ls_path)
            if last_run_script[i] == "cover.py":
                if last_generated_cover_path[i] and os.path.exists(last_generated_cover_path[i]):
                    update_preview_from_image(last_generated_cover_path[i])
            procs[i] = None

window.close()

