#!/bin/bash
python ebay_linker.py \
    
  --orders-csv awaiting_shipment_items.csv \
  --links-json ebay_links.json \
  --out-links-json ebay_links.json \
  --recursive \
  --min-score 60 \
  --min-margin 8 \
  --pdf-folder /home/benoit/Downloads/ebay_manuals \
  --pdf-folder2 /home/benoit/Downloads/manuals

