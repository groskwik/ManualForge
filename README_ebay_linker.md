# ebay_linker
link ebay item number with existing pdf on the database

## Print360 Manual Two-Sided Mode

Use this mode when you want the `print360` workflow, but with the manual two-sided printing method.

Example:

```bash
python ebay_linker.py --orders-csv clipboard.csv --links-json ebay_links.json --out-links-json ebay_links.json --print360manual2sided --printer 2
```

This mode:

- Plans print jobs like `--print360`.
- Prints first-pass even/simplex pages in 360-page batches.
- Asks whether to continue after each first-pass batch.
- After the first-pass batches are done, asks you to reload the paper for the odd side.
- Uses the matching ` Quiet` printer for the second pass.
- Shows the second-pass SumatraPDF commands before the countdown.
- Does not limit the second pass to 360-page batches.

The selected printer must have a matching quiet printer name.

Example:

```text
Brother HL-L8360CDW Series 2
Brother HL-L8360CDW Series 2 Quiet
```

If the quiet printer does not exist, printing will not start.

## Odd Page Manuals

Manuals with an odd number of pages are automatically padded with one blank page.

The blank page is added to a temporary PDF copy, not to the original PDF. The temporary blank page matches the size of the manual's last page.

This prevents the odd side of one manual from printing on the back of another manual.

Temporary padded PDFs are removed automatically when the run ends.

## Simplex Pages And Duplexshort

If a manual has real one-sided pages inside its print settings, the batch manual two-sided modes insert blank backs in a temporary PDF. This lets those pages stay in the same even/odd batch workflow instead of asking you to remove them from the stack.

For `duplexshort` / landscape settings, the temporary PDF rotates odd pages 180 degrees. The SumatraPDF command is then converted to regular `simplex` without `landscape`, which avoids SumatraPDF trying to use duplex behavior during the manual pass.

## Print720 Manual Two-Sided Mode

Use this mode when you want the two-printer `print720` workflow with manual two-sided printing:

```bash
python ebay_linker.py --orders-csv clipboard.csv --links-json ebay_links.json --out-links-json ebay_links.json --print720manual2sided --printer 1 --printer2 2
```

Main rule: a manual is never split between the two printers. Each manual is assigned entirely to one printer.

This mode:

- Selects one batch of whole manuals.
- Distributes those manuals as evenly as possible between the two printer names.
- Prints first-pass even/simplex pages on both printers when both have work.
- Requires matching ` Quiet` printers for both selected printers.
- Uses the quiet printers for the odd/simplex second pass.
- Shows a summary before printing with each manual assigned to each printer.
- Shows total page counts for each printer batch.
- Does not limit the second pass to 360-page batches.
- Supports `--secondpass` to rerun only the odd-page pass after reopening the GUI or restarting the script.

Whenever the program asks you to continue or load paper, it names the affected printer or printers.
