@echo off
setlocal

rem eBay Business command examples
rem Run this file from: C:\Users\benoi\Downloads\ebay_business
rem Remove "rem" from a command line below to run it.

cd /d "%~dp0"

rem Show help for the main scripts
python ebay_sold.py --help
python ebay_business.py --help
python sell.py --help

rem ------------------------------------------------------------
rem 1) Scrape sold items for a seller
rem ------------------------------------------------------------
rem python ebay_sold.py --seller lecazeprinting --sold-pages 3 --feedback-pages 0
rem python ebay_sold.py --seller laceycommunications --sold-pages 3 --feedback-pages 0
rem python ebay_sold.py --seller kndmeredith --sold-pages 1 --feedback-pages 0

rem Scrape sold items and open item pages to read total quantity sold
rem python ebay_sold.py --seller lacey_communications --sold-pages 5 --stock --stock-max-items 100

rem Run Chrome hidden while scraping
rem python ebay_sold.py --seller lacey_communications --sold-pages 2 --stock --headless

rem ------------------------------------------------------------
rem 2) Process a sold-items CSV into downloads/listing drafts
rem ------------------------------------------------------------
rem Safe dry run: sort CSV, download/check PDFs, and print sell.py commands without running them
rem python ebay_business.py --csv "data_save\lacey_communications_stock_data100.csv" --limit 3 --dry-run

rem Download PDFs only, do not create or edit eBay drafts
rem python ebay_business.py --csv "data_save\lacey_communications_stock_data100.csv" --limit 10 --download-only --keep-going

rem Skip online downloads and only use PDFs already in C:\Users\benoi\Downloads\ebay_manuals
rem python ebay_business.py --csv "data_save\lacey_communications_stock_data100.csv" --limit 5 --skip-download --dry-run

rem Start at sorted row 11 and process 5 rows
rem python ebay_business.py --csv "data_save\lacey_communications_stock_data100.csv" --start-at 11 --limit 5 --dry-run

rem Preview/review mode is the default when neither --pause nor --list is used
rem python ebay_business.py --csv "data_save\lacey_communications_stock_data100.csv" --limit 1 --profile-dir "chrome_selenium_profile" --keep-going

rem Pause mode: edits draft and leaves browser open for manual review
rem python ebay_business.py --csv "data_save\lacey_communications_stock_data100.csv" --limit 1 --pause

rem LIVE LISTING MODE: can create active eBay listings
rem python ebay_business.py --csv "data_save\lacey_communications_stock_data100.csv" --limit 1 --list

rem ------------------------------------------------------------
rem 3) Create one listing draft from one PDF
rem ------------------------------------------------------------
rem Safe dry run for one PDF
rem python sell.py --pdf "C:\Users\benoi\Downloads\ebay_manuals\Icom IC-7300 Full Instruction Manual.pdf" --title "Icom IC-7300 Full Instruction Manual" --dry-run

rem Preview one listing draft using an existing PDF
rem python sell.py --pdf "C:\Users\benoi\Downloads\ebay_manuals\Icom IC-7300 Full Instruction Manual.pdf" --title "Icom IC-7300 Full Instruction Manual" --profile-dir "chrome_selenium_profile" --preview

rem Use angled cover generation
rem python sell.py --pdf "C:\Users\benoi\Downloads\ebay_manuals\Icom IC-7300 Full Instruction Manual.pdf" --title "Icom IC-7300 Full Instruction Manual" --angle --ratio 0.5 --preview

rem Force a specific seed item ID for Sell Similar
rem python sell.py --pdf "C:\Users\benoi\Downloads\ebay_manuals\Icom IC-7300 Full Instruction Manual.pdf" --title "Icom IC-7300 Full Instruction Manual" --seed-item-id 356000157685 --preview

rem LIVE LISTING MODE for one PDF: can create an active eBay listing
rem python sell.py --pdf "C:\Users\benoi\Downloads\ebay_manuals\Icom IC-7300 Full Instruction Manual.pdf" --title "Icom IC-7300 Full Instruction Manual" --list

pause
