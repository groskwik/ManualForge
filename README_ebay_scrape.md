# eBay order scraper

Awaiting shipment (the default):

```bat
C:\Users\benoi\anaconda3\envs\py312\python.exe -u ebay_scrape.py --headless --stdout-short
```

Orders already shipped on or after October 10, 2026:

```bat
C:\Users\benoi\anaconda3\envs\py312\python.exe -u ebay_scrape.py --headless --stdout-short --shipped --since 2026-10-10
```

`--since` is inclusive and refers to the **shipment date**, not the purchase or
payment date. Supply the year explicitly. It requires `--shipped`; `--shipped`
and `--all-orders` are mutually exclusive. Omit `--since` to retrieve shipped
orders without a local date filter.

Shipped mode follows the available result pages, up to `--max-items` (default
500 per account, before quantity expansion and the manual-title filter). Raise
this limit for larger exports. If eBay does not expose a readable shipment date,
a date-filtered run stops with an error rather than silently omitting orders.
The results cover the orders available in eBay's Shipped view.

This uses eBay's **Paid and shipped** view (`PAID_SHIPPED`). For delivered or
returned orders whose outbound shipment date is hidden in the list, the scraper
opens the order-details timeline to read it. This can take longer than scraping
awaiting-shipment orders. Orders delivered before the cutoff are skipped without
opening their details.

The existing features also apply to shipped orders:

- Both accounts by default; use `--account primary` or `--account secondary` to
  select one.
- Manual/guide/handbook title filtering by default; add `--no-manual-filter` to
  include all titles.
- Quantity expansion, full CSV output, and archiving of previous CSV files.
- `--stdout-short` shows account, item ID, and title; the CSV also includes
  `shipped_date` and the usual order fields.

For both accounts, the example writes
`shipped_since_2026-10-10_items.csv` in the current directory. Use `--out-dir`
to choose another location. No CSV is written when no rows match.

Use `--help` to list all options.
