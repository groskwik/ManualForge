import argparse
import csv
import html
import re
from collections import defaultdict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(description="Create an HTML sales report from eBay OrdersReport CSV exports.")
    parser.add_argument("csv_files", nargs="*", type=Path, help="eBay OrdersReport CSV files")
    parser.add_argument("--out-html", default="ebay_orders_summary.html", help="Output HTML report filename")
    parser.add_argument("--out-csv", default="ebay_orders_summary.csv", help="Output CSV summary filename")
    parser.add_argument("--manual-only", action="store_true", help="Keep only titles containing manual/guide/handbook")
    return parser.parse_args()


def clean_title(title):
    return re.sub(r"\s+", " ", (title or "")).strip()


def parse_money(text):
    match = re.search(r"-?[\d,.]+", (text or "").replace(",", ""))
    return float(match.group(0)) if match else 0.0


def parse_int(text, default=1):
    try:
        value = int(str(text or "").strip())
        return value if value > 0 else default
    except Exception:
        return default


def read_ebay_orders_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        lines = f.readlines()

    header_index = None
    for i, line in enumerate(lines):
        if "Sales Record Number" in line and "Item Title" in line:
            header_index = i
            break

    if header_index is None:
        raise ValueError(f"Could not find eBay OrdersReport header in {path}")

    reader = csv.DictReader(lines[header_index:])
    rows = []
    for row in reader:
        item_number = (row.get("Item Number") or "").strip()
        title = clean_title(row.get("Item Title"))
        if not item_number and not title:
            continue
        rows.append(row)
    return rows


def summarize_rows(rows, manual_only=False):
    groups = defaultdict(lambda: {
        "title": "",
        "item_ids": set(),
        "order_count": 0,
        "quantity": 0,
        "sold_for_total": 0.0,
        "total_price_total": 0.0,
        "dates": set(),
        "example_item_id": "",
    })

    for row in rows:
        title = clean_title(row.get("Item Title"))
        if not title:
            continue

        if manual_only and not re.search(r"\b(manuals?|guides?|handbooks?)\b", title, re.IGNORECASE):
            continue

        item_id = (row.get("Item Number") or "").strip()
        qty = parse_int(row.get("Quantity"), default=1)
        sold_for = parse_money(row.get("Sold For"))
        total_price = parse_money(row.get("Total Price"))
        sale_date = (row.get("Sale Date") or "").strip()

        g = groups[title.lower()]
        g["title"] = title
        g["order_count"] += 1
        g["quantity"] += qty
        g["sold_for_total"] += sold_for * qty
        g["total_price_total"] += total_price
        if item_id:
            g["item_ids"].add(item_id)
            g["example_item_id"] = g["example_item_id"] or item_id
        if sale_date:
            g["dates"].add(sale_date)

    summary = []
    for g in groups.values():
        qty = g["quantity"] or 1
        summary.append({
            "title": g["title"],
            "order_count": g["order_count"],
            "quantity": g["quantity"],
            "avg_sold_for": g["sold_for_total"] / qty,
            "sold_for_total": g["sold_for_total"],
            "total_price_total": g["total_price_total"],
            "item_ids": ", ".join(sorted(g["item_ids"])),
            "example_url": f"https://www.ebay.com/itm/{g['example_item_id']}" if g["example_item_id"] else "",
            "sale_dates": ", ".join(sorted(g["dates"])),
        })

    summary.sort(key=lambda r: (r["sold_for_total"], r["quantity"]), reverse=True)
    return summary


def write_summary_csv(summary, filename):
    headers = [
        "title",
        "order_count",
        "quantity",
        "avg_sold_for",
        "sold_for_total",
        "total_price_total",
        "item_ids",
        "example_url",
        "sale_dates",
    ]
    with open(filename, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(summary)


def money(value):
    return f"${value:,.2f}"


def create_html_report(summary, source_files, filename):
    rows_html = ""
    for row in summary:
        title = html.escape(row["title"])
        url = html.escape(row["example_url"])
        dates = html.escape(row["sale_dates"])
        item_ids = html.escape(row["item_ids"])

        title_html = f'<a href="{url}" target="_blank">{title}</a>' if url else title
        rows_html += f"""
            <tr>
                <td class="title" data-sort="{title}">{title_html}</td>
                <td data-sort="{row['quantity']}">{row['quantity']}</td>
                <td data-sort="{row['order_count']}">{row['order_count']}</td>
                <td data-sort="{row['avg_sold_for']:.2f}">{money(row['avg_sold_for'])}</td>
                <td data-sort="{row['sold_for_total']:.2f}">{money(row['sold_for_total'])}</td>
                <td data-sort="{row['total_price_total']:.2f}">{money(row['total_price_total'])}</td>
                <td data-sort="{item_ids}">{item_ids}</td>
                <td data-sort="{dates}">{dates}</td>
            </tr>
        """

    source_html = "<br>".join(html.escape(str(p)) for p in source_files)
    total_qty = sum(row["quantity"] for row in summary)
    total_sales = sum(row["sold_for_total"] for row in summary)
    total_with_tax = sum(row["total_price_total"] for row in summary)

    html_text = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>eBay Orders Export Report</title>

<style>
body {{
    font-family: Arial, Helvetica, sans-serif;
    background: #f7f7f7;
    margin: 0;
    padding: 30px;
    color: #191919;
}}
.container {{
    max-width: 1500px;
    margin: auto;
    background: white;
    padding: 30px;
    border-radius: 16px;
    box-shadow: 0 8px 28px rgba(0,0,0,0.10);
    border-top: 8px solid #e53238;
}}
.ebay-logo {{
    font-size: 34px;
    font-weight: bold;
    letter-spacing: -2px;
    margin-bottom: 8px;
}}
.e {{ color: #e53238; }}
.b {{ color: #0064d2; }}
.a {{ color: #f5af02; }}
.y {{ color: #86b817; }}
h1 {{ margin: 0; font-size: 26px; }}
.subtitle {{ color: #555; margin-top: 8px; margin-bottom: 25px; line-height: 1.5; }}
.stats {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 22px; }}
.stat {{ background: #f5f5f5; border-radius: 12px; padding: 12px 16px; min-width: 150px; }}
.stat strong {{ display: block; font-size: 20px; color: #0064d2; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th {{
    background: #0064d2;
    color: white;
    text-align: left;
    padding: 12px;
    cursor: pointer;
    user-select: none;
    position: sticky;
    top: 0;
}}
th:hover {{ background: #004ea8; }}
th::after {{ content: " ⇅"; font-size: 12px; opacity: 0.75; }}
td {{ padding: 11px 12px; border-bottom: 1px solid #e5e5e5; vertical-align: top; }}
tr:hover {{ background: #fff8e1; }}
td.title {{ width: 36%; font-weight: 500; }}
a {{ color: #0064d2; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.note {{ margin-top: 22px; padding: 14px 16px; background: #f5f5f5; border-left: 5px solid #86b817; border-radius: 10px; font-size: 13px; color: #555; }}
</style>

<script>
function sortTable(columnIndex) {{
    const table = document.getElementById("salesTable");
    const tbody = table.tBodies[0];
    const rows = Array.from(tbody.rows);
    const currentDirection = table.getAttribute("data-sort-dir") || "asc";
    const currentColumn = table.getAttribute("data-sort-col");
    let direction = "asc";
    if (currentColumn == columnIndex && currentDirection === "asc") {{
        direction = "desc";
    }}

    rows.sort(function(a, b) {{
        let aValue = a.cells[columnIndex].getAttribute("data-sort") || a.cells[columnIndex].innerText;
        let bValue = b.cells[columnIndex].getAttribute("data-sort") || b.cells[columnIndex].innerText;
        let aNum = parseFloat(aValue);
        let bNum = parseFloat(bValue);
        if (!isNaN(aNum) && !isNaN(bNum)) {{
            return direction === "asc" ? aNum - bNum : bNum - aNum;
        }}
        return direction === "asc" ? aValue.localeCompare(bValue) : bValue.localeCompare(aValue);
    }});

    rows.forEach(row => tbody.appendChild(row));
    table.setAttribute("data-sort-dir", direction);
    table.setAttribute("data-sort-col", columnIndex);
}}
</script>
</head>
<body>
<div class="container">
    <div class="ebay-logo"><span class="e">e</span><span class="b">b</span><span class="a">a</span><span class="y">y</span></div>
    <h1>Orders Export Sales Report</h1>
    <div class="subtitle">Source files:<br>{source_html}<br>Click any column header to sort the table.</div>
    <div class="stats">
        <div class="stat">Unique titles<strong>{len(summary):,}</strong></div>
        <div class="stat">Total quantity<strong>{total_qty:,}</strong></div>
        <div class="stat">Sold-for total<strong>{money(total_sales)}</strong></div>
        <div class="stat">Total price<strong>{money(total_with_tax)}</strong></div>
    </div>
    <table id="salesTable">
        <thead>
            <tr>
                <th onclick="sortTable(0)">Item Title</th>
                <th onclick="sortTable(1)">Quantity</th>
                <th onclick="sortTable(2)">Orders</th>
                <th onclick="sortTable(3)">Average Sold For</th>
                <th onclick="sortTable(4)">Sold For Total</th>
                <th onclick="sortTable(5)">Total Price</th>
                <th onclick="sortTable(6)">Item IDs</th>
                <th onclick="sortTable(7)">Sale Dates</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
    <div class="note">Sold For Total uses eBay's item price column. Total Price includes eBay's exported total price column, which may include taxes/fees collected by eBay.</div>
</div>
</body>
</html>
"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_text)


def main():
    args = parse_args()
    csv_files = args.csv_files or sorted(SCRIPT_DIR.glob("eBay-OrdersReport-*.csv"))
    if not csv_files:
        raise SystemExit("No eBay OrdersReport CSV files found.")

    all_rows = []
    for csv_file in csv_files:
        rows = read_ebay_orders_csv(csv_file)
        print(f"Loaded {len(rows)} rows from: {csv_file}")
        all_rows.extend(rows)

    summary = summarize_rows(all_rows, manual_only=args.manual_only)
    write_summary_csv(summary, args.out_csv)
    create_html_report(summary, csv_files, args.out_html)

    print(f"Summary rows: {len(summary)}")
    print(f"Saved: {args.out_csv}")
    print(f"Saved: {args.out_html}")


if __name__ == "__main__":
    main()
