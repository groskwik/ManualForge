import time
import re
import html
import argparse
import pandas as pd
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlencode
from selenium import webdriver
from selenium.webdriver.chrome.options import Options


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILE_DIR = SCRIPT_DIR / "chrome_profile_selenium"


class ManualActionRequired(RuntimeError):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze eBay seller sales.")

    parser.add_argument("--seller", required=True, help="eBay seller username, not store URL slug")
    parser.add_argument("--sold-pages", type=int, default=None, help="Max sold pages; default = auto")
    parser.add_argument("--feedback-pages", type=int, default=None, help="Max feedback pages; default = auto")
    parser.add_argument("--no-sold", action="store_true", help="Disable sold listing scraping")
    parser.add_argument("--no-feedback", action="store_true", help="Disable feedback scraping")
    parser.add_argument("--stock", action="store_true", help="Open each unique sold listing and read total quantity sold")
    parser.add_argument("--stock-max-items", type=int, default=None, help="In stock mode, stop after scanning N unique item pages")
    parser.add_argument("--headless", action="store_true", help="Run Chrome without visible window")
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR), help="Chrome user-data-dir for Selenium profile")

    return parser.parse_args()


def clean_title(title):
    if not title:
        return ""

    for phrase in [
        "Opens in a new window or tab",
        "opens in a new window or tab",
        "New Listing",
    ]:
        title = title.replace(phrase, "")

    return re.sub(r"\s+", " ", title).strip()


def clean_price(text):
    if not text:
        return None

    match = re.search(r"[\d,.]+", text.replace(",", ""))
    return float(match.group(0)) if match else None


def extract_item_id(url):
    match = re.search(r"/itm/(\d+)", url or "")
    return match.group(1) if match else ""


def page_blocked(soup):
    text = soup.get_text(" ", strip=True).lower()
    blocked_phrases = [
        "access denied",
        "not allowed to access",
        "pardon our interruption",
        "verify yourself",
    ]
    return any(phrase in text for phrase in blocked_phrases)


def manual_action_reason(driver, soup):
    cur = (driver.current_url or "").lower()
    if "signin" in cur or "login" in cur:
        return "sign-in"

    text = soup.get_text(" ", strip=True).lower()
    captcha_phrases = [
        "captcha",
        "pardon our interruption",
        "verify yourself",
        "please verify",
        "security check",
    ]
    if any(phrase in text for phrase in captcha_phrases):
        return "captcha/verification"

    return None


def handle_manual_action(driver, soup, context, headless=False):
    reason = manual_action_reason(driver, soup)
    if reason == "sign-in":
        if headless:
            raise ManualActionRequired(f"eBay requires sign-in on {context} while running headless. Rerun without --headless to log in.")
        print(f"Redirected to sign-in on {context}. Please log in in the Chrome window, then press Enter here.")
        input()
        return True

    if reason:
        raise ManualActionRequired(
            f"eBay requires {reason} on {context}. Stopping now instead of retrying pages. "
            "Wait and rerun later, or complete the verification manually outside this run."
        )

    return False


def scrape_sold_page(driver, seller, page, headless=False):
    params = {
        "_ssn": seller,
        "LH_Sold": "1",
        "LH_Complete": "1",
        "_sop": "13",
        "_pgn": page,
        "_ipg": "240",
    }

    url = "https://www.ebay.com/sch/i.html?" + urlencode(params)
    print("Reading sold page:", url)

    driver.get(url)
    time.sleep(5)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    if handle_manual_action(driver, soup, f"sold page {page}", headless=headless):
        driver.get(url)
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, "html.parser")

    if page_blocked(soup):
        print(f"Access issue on sold page {page}. Will retry later.")
        return None

    links = soup.select("a[href*='/itm/']")
    print(f"Found {len(links)} sold item links")

    if len(links) == 0:
        return []

    rows = []

    for link_el in links:
        link = link_el.get("href", "")
        title = clean_title(link_el.get_text(" ", strip=True))

        if not title:
            img = link_el.select_one("img")
            title = clean_title(img.get("alt", "") if img else "")

        if not title:
            continue

        block = link_el
        for _ in range(8):
            if block and "$" in block.get_text(" ", strip=True):
                break
            block = block.find_parent() if block else None

        text = block.get_text(" ", strip=True) if block else ""

        price_match = re.search(r"\$[\d,.]+", text)
        price_text = price_match.group(0) if price_match else ""

        sold_match = re.search(r"Sold\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}", text)
        sold_date = sold_match.group(0) if sold_match else ""

        clean_link = link.split("?")[0]
        item_id = extract_item_id(clean_link)
        if item_id == "123456":
            continue

        rows.append({
            "source": "sold_search",
            "seller": seller,
            "item_id": item_id,
            "title": title,
            "price_text": price_text,
            "price": clean_price(price_text),
            "sold_date": sold_date,
            "url": clean_link,
            "stock_sold_qty": None,
        })

    return rows


def scrape_feedback_page(driver, seller, page, headless=False):
    url = (
        f"https://www.ebay.com/fdbk/feedback_profile/{seller}"
        f"?filter=feedback_page%3ARECEIVED_AS_SELLER"
        f"&page_id=0&limit=200&page={page}"
    )

    print("Reading feedback page:", url)

    driver.get(url)
    time.sleep(5)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    if handle_manual_action(driver, soup, f"feedback page {page}", headless=headless):
        driver.get(url)
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, "html.parser")

    if page_blocked(soup):
        print(f"Access issue on feedback page {page}. Will retry later.")
        return None

    links = soup.select("a[href*='/itm/']")
    print(f"Found {len(links)} feedback item links")

    if len(links) == 0:
        return []

    rows = []

    for link_el in links:
        link = link_el.get("href", "")
        title = clean_title(link_el.get_text(" ", strip=True))

        if not title:
            img = link_el.select_one("img")
            title = clean_title(img.get("alt", "") if img else "")

        if not title:
            continue

        clean_link = link.split("?")[0]
        item_id = extract_item_id(clean_link)

        rows.append({
            "source": "feedback",
            "seller": seller,
            "item_id": item_id,
            "title": title,
            "price_text": "",
            "price": None,
            "sold_date": "",
            "url": clean_link,
            "stock_sold_qty": None,
        })

    return rows


def scrape_pages(driver, scrape_func, seller, max_pages, label, headless=False):
    all_rows = []
    failed_pages = []

    if max_pages is not None and max_pages <= 0:
        print(f"Skipping {label}: page limit is {max_pages}")
        return all_rows

    page = 2

    while True:
        if max_pages is not None and page > max_pages:
            print(f"Reached {label} page limit: {max_pages}")
            break

        rows = scrape_func(driver, seller, page, headless=headless)

        if rows is None:
            failed_pages.append(page)
            page += 1
            time.sleep(2)
            continue

        if not rows:
            print(f"No more {label} results after page {page - 1}")
            break

        all_rows.extend(rows)
        page += 1
        time.sleep(2)

    print(f"Retrying {label} page 1 at the end")
    rows = scrape_func(driver, seller, 1, headless=headless)

    if rows is None:
        failed_pages.append(1)
    else:
        all_rows.extend(rows)

    if failed_pages:
        print(f"Retrying failed {label} pages: {failed_pages}")

    for failed_page in failed_pages:
        rows = scrape_func(driver, seller, failed_page, headless=headless)

        if rows is None:
            print(f"{label} page {failed_page} still failed after retry.")
            continue

        all_rows.extend(rows)
        time.sleep(2)

    return all_rows


def extract_stock_sold_qty_from_text(text):
    if not text:
        return None

    text = re.sub(r"\s+", " ", text)

    strong_patterns = [
        r"Quantity:\s*\d[\d,]*\s+available\s+(\d[\d,]*)\s+sold\s+Buy It Now",
        r"Quantity:\s*\d[\d,]*\s+available\s+(\d[\d,]*)\s+sold",
        r"\b\d[\d,]*\s+available\s+(\d[\d,]*)\s+sold\s+Buy It Now",
        r"\b\d[\d,]*\s+available\s+(\d[\d,]*)\s+sold",
    ]

    for pattern in strong_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))

    candidates = []

    for match in re.finditer(r"\b(\d[\d,]*)\s+sold\b", text, flags=re.IGNORECASE):
        value = int(match.group(1).replace(",", ""))

        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 120)
        snippet = text[start:end].lower()

        bad_context = [
            "seller",
            "recommended",
            "similar sponsored items",
            "shop with confidence",
            "popular item",
            "people are checking",
            "also viewed",
            "sponsored",
            "feedback",
            "items listed",
            "store",
        ]

        if any(bad in snippet for bad in bad_context):
            continue

        candidates.append((value, snippet))

    if not candidates:
        return None

    for value, snippet in candidates:
        if "quantity" in snippet or "buy it now" in snippet or "add to cart" in snippet:
            return value

    return candidates[0][0]


def scan_stock_quantities(driver, df, stock_max_items=None, headless=False):
    stock_map = {}

    unique_items = (
        df[df["item_id"].astype(str) != ""]
        .drop_duplicates(subset=["item_id"])
        [["item_id", "url"]]
        .to_dict("records")
    )

    if stock_max_items is not None:
        unique_items = unique_items[:stock_max_items]

    print(f"Stock mode: scanning {len(unique_items)} unique item pages")

    for i, item in enumerate(unique_items, start=1):
        item_id = item["item_id"]
        url = item["url"]

        if item_id in stock_map:
            continue

        print(f"[{i}/{len(unique_items)}] Opening item {item_id}: {url}")

        try:
            driver.get(url)
            time.sleep(4)

            soup = BeautifulSoup(driver.page_source, "html.parser")

            if handle_manual_action(driver, soup, f"item {item_id}", headless=headless):
                driver.get(url)
                time.sleep(4)
                soup = BeautifulSoup(driver.page_source, "html.parser")

            if page_blocked(soup):
                print(f"Access issue on item {item_id}. Skipping.")
                stock_map[item_id] = None
                continue

            text = soup.get_text(" ", strip=True)
            qty = extract_stock_sold_qty_from_text(text)

            stock_map[item_id] = qty
            print(f"  sold quantity: {qty}")

        except ManualActionRequired:
            raise
        except Exception as e:
            print(f"  error scanning item {item_id}: {e}")
            stock_map[item_id] = None

        time.sleep(1)

    df["stock_sold_qty"] = df["item_id"].map(stock_map)
    return df


def create_html_report(summary, seller, filename, stock_mode=False):
    rows_html = ""

    for _, row in summary.iterrows():
        title = html.escape(str(row["title"]))
        avg_price = row["avg_price"]
        total = row["total_estimated_sales"]
        example_url = html.escape(str(row["example_url"]))

        stock_qty = row.get("stock_sold_qty", None)
        stock_qty_txt = "" if pd.isna(stock_qty) else str(int(stock_qty))

        avg_price_txt = "" if pd.isna(avg_price) else f"${avg_price:,.2f}"
        total_txt = "" if pd.isna(total) else f"${total:,.2f}"

        if stock_mode:

            rows_html += f"""
            <tr>
                <td class="title" data-sort="{title}">
                    <a href="{example_url}" target="_blank">{title}</a>
                </td>

                <td data-sort="{0 if pd.isna(stock_qty) else stock_qty}">
                    {stock_qty_txt}
                </td>

                <td data-sort="{0 if pd.isna(avg_price) else avg_price}">
                    {avg_price_txt}
                </td>

                <td data-sort="{0 if pd.isna(total) else total}">
                    {total_txt}
                </td>
            </tr>
            """

        else:
            count = int(row["count"])
            sources = html.escape(str(row["sources"]))

            rows_html += f"""
            <tr>
                <td class="title" data-sort="{title}">
                    <a href="{example_url}" target="_blank">{title}</a>
                </td>

                <td data-sort="{count}">
                    {count}
                </td>

                <td data-sort="{0 if pd.isna(avg_price) else avg_price}">
                    {avg_price_txt}
                </td>

                <td data-sort="{0 if pd.isna(total) else total}">
                    {total_txt}
                </td>

                <td data-sort="{sources}">
                    {sources}
                </td>
            </tr>
            """

    if stock_mode:
        table_headers = f"""
            <th onclick="sortTable(0)">Item Title</th>
            <th onclick="sortTable(1)">Total Sold</th>
            <th onclick="sortTable(2)">Average Price</th>
            <th onclick="sortTable(3)">Estimated Total</th>
        """
    else:
        table_headers = f"""
            <th onclick="sortTable(0)">Item Title</th>
            <th onclick="sortTable(1)">Sales Count</th>
            <th onclick="sortTable(2)">Average Price</th>
            <th onclick="sortTable(3)">Estimated Total</th>
            <th onclick="sortTable(4)">Sources</th>
        """

    html_text = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>eBay Seller Sales Report - {seller}</title>

<style>
body {{
    font-family: Arial, Helvetica, sans-serif;
    background: #f7f7f7;
    margin: 0;
    padding: 30px;
    color: #191919;
}}

.container {{
    max-width: 1300px;
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

h1 {{
    margin: 0;
    font-size: 26px;
}}

.subtitle {{
    color: #555;
    margin-top: 8px;
    margin-bottom: 25px;
    line-height: 1.5;
}}

table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}}

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

th:hover {{
    background: #004ea8;
}}

th::after {{
    content: " ⇅";
    font-size: 12px;
    opacity: 0.75;
}}

td {{
    padding: 11px 12px;
    border-bottom: 1px solid #e5e5e5;
    vertical-align: top;
}}

tr:hover {{
    background: #fff8e1;
}}

td.title {{
    width: 60%;
    font-weight: 500;
}}

a {{
    color: #0064d2;
    text-decoration: none;
}}

a:hover {{
    text-decoration: underline;
}}

.note {{
    margin-top: 22px;
    padding: 14px 16px;
    background: #f5f5f5;
    border-left: 5px solid #86b817;
    border-radius: 10px;
    font-size: 13px;
    color: #555;
}}
</style>

<script>
function sortTable(columnIndex) {{
    const table = document.getElementById("salesTable");
    const tbody = table.tBodies[0];
    const rows = Array.from(tbody.rows);

    const currentDirection =
        table.getAttribute("data-sort-dir") || "asc";

    const currentColumn =
        table.getAttribute("data-sort-col");

    let direction = "asc";

    if (currentColumn == columnIndex &&
        currentDirection === "asc") {{
        direction = "desc";
    }}

    rows.sort(function(a, b) {{

        let aValue =
            a.cells[columnIndex].getAttribute("data-sort") ||
            a.cells[columnIndex].innerText;

        let bValue =
            b.cells[columnIndex].getAttribute("data-sort") ||
            b.cells[columnIndex].innerText;

        let aNum = parseFloat(aValue);
        let bNum = parseFloat(bValue);

        if (!isNaN(aNum) && !isNaN(bNum)) {{
            return direction === "asc"
                ? aNum - bNum
                : bNum - aNum;
        }}

        return direction === "asc"
            ? aValue.localeCompare(bValue)
            : bValue.localeCompare(aValue);

    }});

    rows.forEach(row => tbody.appendChild(row));

    table.setAttribute("data-sort-dir", direction);
    table.setAttribute("data-sort-col", columnIndex);
}}
</script>

</head>

<body>

<div class="container">

    <div class="ebay-logo">
        <span class="e">e</span>
        <span class="b">b</span>
        <span class="a">a</span>
        <span class="y">y</span>
    </div>

    <h1>Seller Sales Report</h1>

    <div class="subtitle">
        Seller: <strong>{seller}</strong><br>
        Mode:
        <strong>
            {"Stock listing quantity scan" if stock_mode else "Sold search + feedback"}
        </strong><br>
        Click any column header to sort the table.
    </div>

    <table id="salesTable">
        <thead>
            <tr>
                {table_headers}
            </tr>
        </thead>

        <tbody>
            {rows_html}
        </tbody>
    </table>

    <div class="note">

        In stock mode, the script opens each unique sold item page
        once and extracts the total sold quantity shown by eBay.

        Estimated total is calculated as:

        <strong>
            total sold × average price
        </strong>

    </div>

</div>

</body>
</html>
"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_text)


def main():
    args = parse_args()

    seller = args.seller
    stock_mode = args.stock

    scrape_sold = not args.no_sold
    scrape_feedback = not args.no_feedback

    if stock_mode:
        scrape_feedback = False
        scrape_sold = True

    if stock_mode:
        print("Mode: stock scan. Sold listings will be opened one by one to read total sold quantity.")
    else:
        print("Mode: sales summary. Add --stock to open each sold listing and read total sold quantity.")

    options = Options()
    options.add_argument("--start-maximized")
    profile_dir = Path(args.profile_dir).expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")

    if args.headless:
        options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=options)

    all_rows = []

    try:
        try:
            if scrape_sold:
                all_rows.extend(
                    scrape_pages(driver, scrape_sold_page, seller, args.sold_pages, "sold", headless=args.headless)
                )

            if scrape_feedback:
                all_rows.extend(
                    scrape_pages(driver, scrape_feedback_page, seller, args.feedback_pages, "feedback", headless=args.headless)
                )

            df = pd.DataFrame(all_rows)

            if df.empty:
                print("No data found.")
                return

            df["title"] = df["title"].apply(clean_title)
            df["item_id"] = df["item_id"].fillna("")
            df["sale_key"] = df["item_id"]
            df.loc[df["sale_key"] == "", "sale_key"] = df["title"]

            source_priority = {
                "sold_search": 0,
                "feedback": 1,
            }

            df["source_priority"] = df["source"].map(source_priority).fillna(9)

            df.sort_values(
                by=["sale_key", "source_priority"],
                ascending=[True, True],
                inplace=True
            )

            before_dedup = len(df)

            df.drop_duplicates(
                subset=["sale_key"],
                keep="first",
                inplace=True
            )

            after_dedup = len(df)

            if stock_mode:
                df = scan_stock_quantities(driver, df, stock_max_items=args.stock_max_items, headless=args.headless)
        except ManualActionRequired as e:
            print()
            print(str(e))
            return

    finally:
        driver.quit()

    suffix = "stock" if stock_mode else "sales"

    raw_file = f"{seller}_{suffix}_data.xlsx"
    csv_file = f"{seller}_{suffix}_data.csv"
    summary_file = f"{seller}_{suffix}_summary.xlsx"
    html_file = f"{seller}_{suffix}_summary.html"

    if stock_mode:
        df["stock_estimated_total"] = df["price"] * df["stock_sold_qty"]

    df.to_excel(raw_file, index=False)
    df.to_csv(csv_file, index=False)

    if stock_mode:
        summary = (
            df.groupby("title", as_index=False)
            .agg(
                count=("title", "size"),
                stock_sold_qty=("stock_sold_qty", "max"),
                avg_price=("price", "mean"),
                total_estimated_sales=("stock_estimated_total", "max"),
                example_url=("url", "first"),
                sources=("source", lambda x: ", ".join(sorted(set(x))))
            )
            .sort_values(
                by=["total_estimated_sales", "stock_sold_qty"],
                ascending=[False, False]
            )
        )
    else:
        summary = (
            df.groupby("title", as_index=False)
            .agg(
                count=("title", "size"),
                avg_price=("price", "mean"),
                total_estimated_sales=("price", "sum"),
                example_url=("url", "first"),
                sources=("source", lambda x: ", ".join(sorted(set(x))))
            )
            .sort_values(
                by=["total_estimated_sales", "count"],
                ascending=[False, False]
            )
        )

    summary.to_excel(summary_file, index=False)
    create_html_report(summary, seller, html_file, stock_mode=stock_mode)

    print()
    print(f"Raw records before deduplication: {before_dedup}")
    print(f"Records after deduplication: {after_dedup}")
    print(f"Duplicates removed: {before_dedup - after_dedup}")

    if stock_mode and args.stock_max_items is not None:
        print(f"Stock scan limited to first {args.stock_max_items} unique item pages.")

    if not stock_mode:
        print("Note: this was not a stock scan. Use --stock if you want the script to open each sold listing one by one.")

    print()
    print(f"Saved: {raw_file}")
    print(f"Saved: {csv_file}")
    print(f"Saved: {summary_file}")
    print(f"Saved: {html_file}")


if __name__ == "__main__":
    main()
