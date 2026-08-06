@echo off
setlocal

rem PDF size reduction examples for Anaconda Prompt.
rem Run this file from anywhere; it switches to this script's folder.
rem Remove "rem" from one example below to run it.

cd /d "%~dp0"

rem ------------------------------------------------------------
rem Interactive mode: asks for input PDF, output PDF, and preset
rem ------------------------------------------------------------
rem python .\reduce_pdf.py

rem ------------------------------------------------------------
rem Smallest file, lower quality
rem ------------------------------------------------------------
rem python .\reduce_pdf.py .\pascal.pdf .\pascal_small.pdf --preset screen

rem ------------------------------------------------------------
rem Good default size/quality balance
rem ------------------------------------------------------------
rem python .\reduce_pdf.py .\pascal.pdf .\pascal_ebook.pdf --preset ebook

rem ------------------------------------------------------------
rem Print quality, much larger file
rem ------------------------------------------------------------
rem python .\reduce_pdf.py .\pascal.pdf .\pascal_print.pdf --preset print

rem ------------------------------------------------------------
rem Text/manual friendly: sharper letters, no JPEG artifacts
rem ------------------------------------------------------------
rem python .\reduce_pdf.py .\pascal.pdf .\pascal_text.pdf --preset text

rem ------------------------------------------------------------
rem Custom DPI and compression quality
rem Old zoom 1.0 equals 72 DPI, zoom 1.5 equals 108 DPI, zoom 2.0 equals 144 DPI.
rem ------------------------------------------------------------
rem python .\reduce_pdf.py .\pascal.pdf .\pascal_custom.pdf --dpi 110 --quality 65

pause
