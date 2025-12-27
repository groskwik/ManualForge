@echo off
    
python ebay_scrape.py --headless --stdout-short

python restock.py --headless

python ebay_linker.py ^
  --orders-csv awaiting_shipment_items.csv ^
  --links-json ebay_links.json ^
  --out-links-json ebay_links.json ^
  --recursive ^
  --min-score 60 ^
  --min-margin 8 ^
  --print ^
  --myprint C:\Users\benoi\Downloads\ManualForge\myprint.py

rem  --always-ask-printer ^
rem --printer 2 ^
