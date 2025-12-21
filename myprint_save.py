#!/usr/bin/env python
import os
import subprocess
import time
from PyPDF2 import PdfReader
import psutil
import json
from pathlib import Path

# Path to SumatraPDF executable
SUMATRA_PATH = r"C:\portableapps\sumatrapdf\sumatrapdf.exe"

# Folders where PDFs are stored
PDF_FOLDERS = [
    r"C:\Users\benoi\Downloads\ebay_manuals",
    r"C:\Users\benoi\Downloads\manuals"
]

# Available printers
PRINTERS = {
    "1": "Brother HL-L8360CDW [Wireless]",
    "2": "Brother HL-L8360CDW series"
}

def other_python_scripts_running():
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] == 'python.exe' and proc.info['pid'] != current_pid:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

def select_printer():
    """Prompts the user to select a printer."""
    print("\nSelect a printer:")
    for key, name in PRINTERS.items():
        print(f"{key}. {name}")
    
    choice = input("Enter the number of the printer: ").strip()
    return PRINTERS.get(choice, PRINTERS["1"])

def find_pdf(partial_name):
    """Finds a PDF file in the specified folders that contains the given string (case insensitive)."""
    partial_name_lower = partial_name.lower()

    matching_files = []
    for folder in PDF_FOLDERS:
        for f in os.listdir(folder):
            if f.lower().endswith(".pdf") and partial_name_lower in f.lower():
                matching_files.append(os.path.join(folder, f))

    if not matching_files:
        print(f"No PDF found containing: {partial_name}")
        return None
    
    if len(matching_files) > 1:
        print("\nMultiple matches found:")
        for idx, file in enumerate(matching_files, start=1):
            print(f"{idx}. {os.path.basename(file)}")
        choice = input("\nEnter the number of the file you want to print: ").strip()
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(matching_files):
            print("Invalid choice.")
            return None
        return matching_files[int(choice) - 1]

    return matching_files[0]  # Return the only match

def get_pdf_page_count(pdf_path):
    """Returns the number of pages in the given PDF file."""
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            return len(reader.pages)
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None

def print_pdf(printer_name, partial_name):
    """Prints a PDF with predefined settings or user-defined page ranges."""
    pdf_path = find_pdf(partial_name)
    if not pdf_path:
        return

    # Display the number of pages in the selected PDF
    page_count = get_pdf_page_count(pdf_path)
    if page_count:
        print(f"The document '{os.path.basename(pdf_path)}' has {page_count} pages.")
    else:
        print("Unable to determine the number of pages.")

    file_name_without_ext = os.path.splitext(os.path.basename(pdf_path))[0].lower()
    
    DB_PATH = Path(__file__).with_name("print_settings.json")

    with DB_PATH.open("r", encoding="utf-8") as f:
        _RAW_PRINT_SETTINGS = json.load(f)

    # Normalize keys once (case-insensitive access)
    PRINT_SETTINGS = {k.lower(): v for k, v in _RAW_PRINT_SETTINGS.items()}
    # Get predefined print settings 
    print_settings = PRINT_SETTINGS.get(file_name_without_ext, [f"color,1-{page_count},fit,paper=letter"])
    print("")
    print(f"Found settings for {pdf_path}:")
    for setting in print_settings:
        print(setting)
        if "landscape" in setting:
            printer_name1 = printer_name.replace("Wireless","Landscape")
        else:
            printer_name1 = printer_name

    # Get custom page range input
    custom_range = input("\nEnter the page range to print (e.g., 40-215), or press Enter for default: ").strip()

    # print("Wait for other jobs to finish...")
    
    # while other_python_scripts_running():
    #     time.sleep(10)

    # print("All other jobs are done. Proceeding...")

    anew = 0
    
    if custom_range:
        print_settings_copy = print_settings
        new_print_settings = []
        for setting in print_settings:
            setting_parts = setting.split(",")
            modified_setting = []
            
            for part in setting_parts:
                if "-" in part and part.replace("-", "").isdigit():
                    if anew ==0: 
                        a = int(part.split('-')[0])
                    else:
                        a = anew
                    b = int(part.split('-')[1])
                    a1 = int(custom_range.split('-')[0])
                    b1 = int(custom_range.split('-')[1])
                    if a1>b or b1<a:
                        pass
                    else:
                        a2 = max(a1,a)
                        b2 = min(b1,b)
                        anew  = b+1
                        modified_setting.append(f"{a2}-{b2}")
                        new_print_settings.append(",".join(modified_setting))
        parts = print_settings[0].split(',')
        parts[1] = f"{a2}-{b2}"
        print_settings = [','.join(parts)]
        new_page_count = min(page_count,b2)
    else:
        new_page_count = page_count

    print(f"Printing: {os.path.basename(pdf_path)} on {printer_name1}...")

    batch_size = 70  # Number of pages per batch
    delay_between_batches = 240  # Delay in seconds between batches
    if printer_name == "Brother HL-L3290CDW [Wireless]":
        delay_between_batches = 480  # Delay in seconds between batches

    for setting in print_settings:
        # Extract page range from the setting
        setting_parts = setting.split(",")
        page_range = None
        for part in setting_parts:
            if ("-" in part and part.replace("-", "").isdigit()):
                page_range = part
                break
            elif (part.isdigit()):
                #print a single page
                print(f"Printing page {part}")
                subprocess.run([SUMATRA_PATH, "-print-to", printer_name1, "-print-settings", setting, pdf_path], check=True)
                time.sleep(10)
        if page_range:
            start_page, end_page = map(int, page_range.split("-"))
            current_page = start_page

            while current_page <= end_page:
                batch_end = min(current_page + batch_size - 1, end_page)
                batch_range = f"{current_page}-{batch_end}"
                batch_setting = setting.replace(page_range, batch_range)

                print(f"Printing pages {batch_range}")
                subprocess.run([SUMATRA_PATH, "-print-to", printer_name1, "-print-settings", batch_setting, pdf_path], check=True)

                current_page += batch_size
                if current_page <= new_page_count:
                    print(f"Waiting for {delay_between_batches // 60} minutes before next batch...")
                    time.sleep(delay_between_batches)

if __name__ == "__main__":
    selected_printer = select_printer()
    file_name = input("\nEnter part of the PDF filename: ").strip()

    print_pdf(selected_printer, file_name)

 

