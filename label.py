#!/usr/bin/env python
import win32print
import os
import glob
import time
import fitz  # PyMuPDF for extracting pages
import tempfile

# List of available printers
PRINTERS = [
    "Brother HL-L8360CDW [Wireless]",
    "Brother HL-L3290CDW [Wireless]"
]

def select_printer():
    """Prompts the user to select a printer from the available options."""
    print("Select a printer:")
    for i, printer in enumerate(PRINTERS, start=1):
        print(f"{i}. {printer}")
    
    while True:
        try:
            choice = int(input("Enter the number of the printer to use: "))
            if 1 <= choice <= len(PRINTERS):
                return PRINTERS[choice - 1]
            else:
                print("Invalid selection. Please enter a valid number.")
        except ValueError:
            print("Invalid input. Please enter a number.")

def print_pdf_with_delay(pdf_path, printer_name, delay=20):
    """Prints each page of a PDF separately with a delay using Win32 API."""
    try:
        print(f"Using printer: {printer_name}")

        # Open the PDF document
        doc = fitz.open(pdf_path)

        for page_num in range(len(doc)):
            # Create a temporary PDF file for the single page
            temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_path = temp_pdf.name
            temp_pdf.close()

            # Extract the single page into a new document
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            new_doc.save(temp_path)
            new_doc.close()

            print(f"Printing page {page_num + 1} on {printer_name}...")

            # Open printer
            hprinter = win32print.OpenPrinter(printer_name)
            win32print.StartDocPrinter(hprinter, 1, (f"Print Job - Page {page_num + 1}", None, "RAW"))
            win32print.StartPagePrinter(hprinter)

            # Read and send the file
            with open(temp_path, "rb") as f:
                win32print.WritePrinter(hprinter, f.read())

            win32print.EndPagePrinter(hprinter)
            win32print.EndDocPrinter(hprinter)
            win32print.ClosePrinter(hprinter)

            # Wait before printing the next page
            time.sleep(delay)

            # Delete the temporary file
            os.remove(temp_path)

        print("Printing complete.")

    except Exception as e:
        print(f"Error: {e}")
        
def find_most_recent_pdf(folder_path):
    # Get all PDF files containing 'label' in the filename
    pdf_files = glob.glob(os.path.join(folder_path, "*label*.pdf"))

    if not pdf_files:
        return None  # No matching files found

    # Get the most recent file based on modification time
    most_recent_file = max(pdf_files, key=os.path.getmtime)
    return most_recent_file

if __name__ == "__main__":
    # Let user select a printer
    selected_printer = select_printer()
    
    pdf_path = find_most_recent_pdf('.')
    print(f"Found {pdf_path}")
    
    # Start printing
    print_pdf_with_delay(pdf_path, selected_printer, delay=20)

