##!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import psutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException


AWAITING_URL = "https://www.ebay.com/sh/ord/?filter=status:AWAITING_SHIPMENT"
ALL_ORDERS_URL = "https://www.ebay.com/sh/ord/?filter=status:ALL_ORDERS"

RE_ORDER_FULL = re.compile(r"^\d{2}-\d{5}-\d{5}$")   # e.g. 27-13984-70927
RE_AVAILABLE = re.compile(r"\((\d+)\s+available\)", re.IGNORECASE)
RE_PRICE = re.compile(r"\$?\s*([0-9]+(?:\.[0-9]{2})?)")
RE_MANUAL = re.compile(r"\b(manuals?|guides?|handbooks?)\b", re.IGNORECASE)

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass


@dataclass(frozen=True)
class AccountSpec:
    name: str
    profile_dir: Path


def ensure_logged_in_or_pause(driver, headless: bool):
    cur = (driver.current_url or "").lower()
    if "signin" in cur or "login" in cur:
        if headless:
            raise RuntimeError(
                "Redirected to eBay sign-in while running headless. "
                "Run without --headless to log in to this Selenium profile, then retry."
            )
        print("Redirected to sign-in. Please log in in the Chrome window, then press Enter here.")
        input()


def scroll_to_bottom(driver, steps=6, pause_s=0.5):
    for _ in range(steps):
        driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
        time.sleep(pause_s)


def extract_item_id_from_url(href: str) -> str | None:
    try:
        path = urlparse(href).path
    except Exception:
        path = href
    m = re.search(r"/itm/(\d+)", path)
    return m.group(1) if m else None


def extract_short_order(full_text: str) -> str | None:
    t = (full_text or "").strip()
    if not RE_ORDER_FULL.match(t):
        return None
    parts = t.split("-")
    return f"{parts[1]}-{parts[2]}" if len(parts) == 3 else None


def parse_qty_available(text: str) -> int | None:
    m = RE_AVAILABLE.search(text or "")
    return int(m.group(1)) if m else None


def parse_price(text: str) -> float | None:
    if not text:
        return None
    m = RE_PRICE.search(text.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def safe_int(value, default=None):
    try:
        if value is None:
            return default
        s = str(value).strip()
        if not s:
            return default
        return int(s)
    except Exception:
        return default


def find_row_container(el, max_hops=12):
    """
    Walk up the DOM until we reach something row-ish.
    eBay changes markup; this heuristic keeps it robust.
    """
    cur = el
    for _ in range(max_hops):
        try:
            tag = cur.tag_name.lower()
            cls = (cur.get_attribute("class") or "").lower()
            role = (cur.get_attribute("role") or "").lower()

            if tag == "tr":
                return cur
            if role in ("row", "rowgroup"):
                return cur
            if "row" in cls or "card" in cls:
                return cur

            cur = cur.find_element(By.XPATH, "..")
        except Exception:
            break
    return el


def safe_find_text(root, by, sel) -> str:
    try:
        return (root.find_element(by, sel).text or "").strip()
    except Exception:
        return ""


def scrape_orders(driver, timeout=30, max_items=500, debug=False):
    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    scroll_to_bottom(driver, steps=6, pause_s=0.5)

    # Start from item links, but deduplicate by ROW CONTAINER first,
    # not by item_id/title.
    item_links = driver.find_elements(By.XPATH, "//a[contains(@href,'/itm/')]")
    if debug:
        print(f"Found /itm/ anchors: {len(item_links)}")

    rows = []
    seen_row_signatures = set()

    for a in item_links:
        try:
            row = find_row_container(a)

            # Build a stable signature from the visible row text.
            # This prevents duplicate processing of the same DOM row,
            # while still keeping separate buyer orders for the same item.
            row_text = " ".join((row.text or "").split())
            if not row_text:
                continue

            row_sig = row_text
            if row_sig in seen_row_signatures:
                continue
            seen_row_signatures.add(row_sig)

            # Item link for this row
            try:
                item_el = row.find_element(By.XPATH, ".//a[contains(@href,'/itm/')]")
            except Exception:
                item_el = a

            href = (item_el.get_attribute("href") or "").strip()
            title = (item_el.text or "").strip()
            item_id = extract_item_id_from_url(href)
            if not item_id:
                continue

            # order number anchor
            order_full = ""
            try:
                order_el = row.find_element(
                    By.XPATH,
                    ".//a[contains(@href,'/mesh/ord/details') and contains(normalize-space(.),'-')]"
                )
                cand = (order_el.text or "").strip()
                if RE_ORDER_FULL.match(cand):
                    order_full = cand
            except Exception:
                try:
                    # fallback: search any text in the row matching full order pattern
                    m = RE_ORDER_FULL.search(row_text)
                    if m:
                        order_full = m.group(0)
                except Exception:
                    order_full = ""

            order_short = extract_short_order(order_full) if order_full else None

            # quantity sold & available
            qty_sold = None
            qty_avail = None

            try:
                avail_span = row.find_element(By.XPATH, ".//span[contains(@class,'available-quantity')]")
                avail_text = (avail_span.text or "").strip()
                qty_avail = parse_qty_available(avail_text)

                try:
                    strong_el = avail_span.find_element(By.XPATH, "./preceding-sibling::strong[1]")
                except Exception:
                    strong_el = row.find_element(
                        By.XPATH,
                        ".//span[contains(@class,'available-quantity')]/preceding::strong[1]"
                    )

                s = (strong_el.text or "").strip()
                qty_sold = int(s) if s.isdigit() else None
            except Exception:
                pass

            # More robust fallback for quantity sold:
            # look for patterns like "2 sold" or "Qty 2" anywhere in row text
            if qty_sold is None:
                m = re.search(r"\b(\d+)\s+sold\b", row_text, re.IGNORECASE)
                if m:
                    qty_sold = int(m.group(1))
                else:
                    m = re.search(r"\bqty\b[:\s]+(\d+)\b", row_text, re.IGNORECASE)
                    if m:
                        qty_sold = int(m.group(1))

            # price
            price_text = safe_find_text(row, By.CSS_SELECTOR, "div.price-column-item")
            if not price_text:
                m = re.search(r"\$[0-9]+(?:\.[0-9]{2})?", row_text)
                if m:
                    price_text = m.group(0)

            price = parse_price(price_text)

            rows.append({
                "order_number": order_short or "",
                "order_full": order_full or "",
                "item_id": item_id or "",
                "title": title or "",
                "item_url": href or "",
                "qty_sold": "" if qty_sold is None else str(qty_sold),
                "qty_available": "" if qty_avail is None else str(qty_avail),
                "price": "" if price is None else f"{price:.2f}",
                "price_text": price_text or "",
            })

            if len(rows) >= max_items:
                break

        except StaleElementReferenceException:
            continue

    return rows


def filter_out_phantom_rows(rows):
    out = []
    for r in rows:
        title = (r.get("title") or "").strip()
        order_full = (r.get("order_full") or "").strip()
        order_number = (r.get("order_number") or "").strip()
        price_text = (r.get("price_text") or "").strip()
        qty_sold = (r.get("qty_sold") or "").strip()
        qty_avail = (r.get("qty_available") or "").strip()

        if (not title) and (not order_full) and (not order_number) and (not price_text) and (not qty_sold) and (not qty_avail):
            continue
        if (not title) and (not order_full) and (not order_number):
            continue

        out.append(r)
    return out


def filter_rows_by_manual(rows, enabled=True):
    if not enabled:
        return rows
    out = []
    for r in rows:
        title = (r.get("title") or "").strip()
        if RE_MANUAL.search(title):
            out.append(r)
    return out

def expand_rows_by_quantity(rows, debug=False, max_expand_qty=20):
    """
    Duplicate rows when qty_sold > 1, but protect against bogus huge values.

    Rules:
    - blank / invalid qty -> treat as 1
    - qty < 1 -> treat as 1
    - qty > max_expand_qty -> treat as 1 and warn in debug mode
    """

    expanded = []

    for r in rows:
        raw_qty = r.get("qty_sold")

        try:
            qty = int(str(raw_qty).strip()) if str(raw_qty).strip() else 1
        except Exception:
            qty = 1

        if qty < 1:
            qty = 1

        if qty > max_expand_qty:
            if debug:
                print(
                    f"[WARN] Suspicious qty_sold={qty} for "
                    f"order={r.get('order_full','')} item={r.get('item_id','')} "
                    f"title={r.get('title','')[:80]!r}. "
                    f"Using 1 instead."
                )
            qty = 1

        if qty == 1:
            rr = dict(r)
            rr["qty_sold_original"] = str(raw_qty).strip() if raw_qty is not None else ""
            rr["line_instance"] = "1"
            rr["qty_sold"] = "1"
            expanded.append(rr)
            continue

        if debug:
            print(
                f"[INFO] Expanding order={r.get('order_full','')} "
                f"item={r.get('item_id','')} into {qty} lines"
            )

        for i in range(1, qty + 1):
            rr = dict(r)
            rr["qty_sold_original"] = str(raw_qty).strip() if raw_qty is not None else str(qty)
            rr["line_instance"] = str(i)
            rr["qty_sold"] = "1"
            expanded.append(rr)

    return expanded
def print_table(rows, headers=None, max_widths=None):
    if not rows:
        print("(no rows)")
        return

    if headers is None:
        headers = list(rows[0].keys())

    widths = {h: len(h) for h in headers}
    for r in rows:
        for h in headers:
            widths[h] = max(widths[h], len(str(r.get(h, ""))))

    if max_widths:
        for h, cap in max_widths.items():
            if h in widths:
                widths[h] = min(widths[h], cap)

    def fmt_cell(h, v):
        s = str(v)
        cap = widths[h]
        if len(s) > cap:
            s = s[: max(0, cap - 1)] + "…"
        return s.ljust(widths[h])

    sep = " | "
    line = "-+-".join("-" * widths[h] for h in headers)

    print(sep.join(h.ljust(widths[h]) for h in headers))
    print(line)
    for r in rows:
        print(sep.join(fmt_cell(h, r.get(h, "")) for h in headers))


def archive_existing_file(path: Path) -> Path | None:
    """
    If path already exists, rename it to an archive file with timestamp.
    """
    if not path.exists():
        return None

    ts = time.strftime("%Y%m%d_%H%M%S")
    archived = path.with_name(f"{path.stem}_archive_{ts}{path.suffix}")
    path.rename(archived)
    return archived


def write_csv(rows, path: Path, headers: list[str] | None = None):
    if not rows:
        return None

    if headers is None:
        headers = list(rows[0].keys())

    archived = archive_existing_file(path)

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)

    return archived


def kill_chrome_using_profile(profile_dir: Path, debug: bool = True, kill_driver: bool = False) -> None:
    """
    Kill Chrome processes that were launched with --user-data-dir pointing to profile_dir.
    """
    profile_dir_abs = str(profile_dir.resolve())
    hit = 0

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline_list = proc.info.get("cmdline") or []
            if not cmdline_list:
                continue

            cmdline = " ".join(cmdline_list)

            is_chrome = ("chrome" in name) or ("chrome.exe" in name)
            is_driver = ("chromedriver" in name) or ("chromedriver.exe" in name)

            if is_chrome:
                if profile_dir_abs in cmdline:
                    hit += 1
                    if debug:
                        print(f"[INFO] Killing stale Chrome PID={proc.pid} using profile: {profile_dir_abs}")
                    proc.kill()

            if kill_driver and is_driver:
                hit += 1
                if debug:
                    print(f"[INFO] Killing chromedriver PID={proc.pid}")
                proc.kill()

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if debug and hit == 0:
        print(f"[INFO] No stale Chrome found for profile: {profile_dir_abs}")

    time.sleep(0.5)


def build_driver(profile_dir: Path, headless: bool, chrome_binary: str | None = None):
    options = webdriver.ChromeOptions()
    profile_dir.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={str(profile_dir)}")

    if chrome_binary:
        options.binary_location = chrome_binary

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,900")

    return webdriver.Chrome(options=options)


def scrape_account(account: AccountSpec, url: str, args) -> list[dict]:
    if not args.no_kill_profile:
        kill_chrome_using_profile(account.profile_dir, debug=args.debug, kill_driver=args.kill_chromedriver)

    driver = build_driver(account.profile_dir, headless=args.headless, chrome_binary=args.chrome_binary)
    try:
        if args.debug:
            print(f"\n=== Account: {account.name} | Profile: {account.profile_dir} ===")

        driver.get(url)
        ensure_logged_in_or_pause(driver, headless=args.headless)
        driver.get(url)

        rows = scrape_orders(driver, timeout=args.timeout, max_items=args.max_items, debug=args.debug)
        rows = filter_out_phantom_rows(rows)

        for r in rows:
            r["account"] = account.name

        rows = filter_rows_by_manual(rows, enabled=not args.no_manual_filter)
        rows = expand_rows_by_quantity(rows, debug=args.debug)

        return rows
    finally:
        driver.quit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-orders", action="store_true",
                    help="Scrape ALL_ORDERS instead of AWAITING_SHIPMENT (default).")
    ap.add_argument("--headless", action="store_true",
                    help="Run without showing Chrome. Use only after you have a valid logged-in profile.")
    ap.add_argument("--stdout-short", action="store_true",
                    help="Print only account,item_id,title to stdout (CSV remains full).")
    ap.add_argument("--max-items", type=int, default=500)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--out-dir", default=".", help="Output folder for CSV.")

    ap.add_argument("--account", choices=["primary", "secondary", "both"], default="both",
                    help="Which eBay account(s) to scrape (profiles are separate). Default: both.")
    ap.add_argument("--primary-profile", default=None,
                    help="Folder for the primary Chrome user-data-dir (default: ./chrome_profile_selenium).")
    ap.add_argument("--secondary-profile", default=None,
                    help="Folder for the secondary Chrome user-data-dir (default: ./chrome_profile_selenium_2).")

    ap.add_argument("--chrome-binary", default=None,
                    help="Optional path to Chrome/Chromium binary.")

    ap.add_argument("--no-manual-filter", action="store_true",
                    help="Disable the default filter that keeps only items with 'manual(s)|guide(s)|handbook(s)' in the title.")

    ap.add_argument("--no-kill-profile", action="store_true",
                    help="Do NOT kill stale Chrome processes using the same Selenium profile(s) before starting.")
    ap.add_argument("--kill-chromedriver", action="store_true",
                    help="Also kill chromedriver processes (use only if things are very stuck).")

    args = ap.parse_args()

    url = ALL_ORDERS_URL if args.all_orders else AWAITING_URL
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    script_dir = Path(__file__).resolve().parent
    primary_profile = Path(args.primary_profile).resolve() if args.primary_profile else (script_dir / "chrome_profile_selenium")
    secondary_profile = Path(args.secondary_profile).resolve() if args.secondary_profile else (script_dir / "chrome_profile_selenium_2")

    accounts = [
        AccountSpec("primary", primary_profile),
        AccountSpec("secondary", secondary_profile),
    ]

    if args.account == "primary":
        accounts = [accounts[0]]
    elif args.account == "secondary":
        accounts = [accounts[1]]

    combined_rows: list[dict] = []
    for acc in accounts:
        rows = scrape_account(acc, url, args)
        combined_rows.extend(rows)

    preferred = [
        "account",
        "order_number",
        "order_full",
        "item_id",
        "title",
        "item_url",
        "qty_sold",
        "qty_sold_original",
        "line_instance",
        "qty_available",
        "price",
        "price_text",
    ]
    headers = preferred

    page_tag = "all_orders" if args.all_orders else "awaiting_shipment"
    csv_name = (
        f"{page_tag}_items.csv"
        if args.account == "both"
        else f"{page_tag}_{args.account}.csv"
    )
    out_csv = out_dir / csv_name

    print()
    if args.stdout_short:
        short_headers = ["account", "item_id", "title"]
        print_table(combined_rows, headers=short_headers, max_widths={"title": 90})
    else:
        print_table(
            combined_rows,
            headers=headers,
            max_widths={"title": 60, "item_url": 60, "price_text": 40}
        )

    archived = None
    if combined_rows:
        archived = write_csv(combined_rows, out_csv, headers=headers)

    print(f"\nSaved CSV: {out_csv}")
    if archived:
        print(f"Previous CSV archived as: {archived}")
    print(f"Rows kept: {len(combined_rows)}")

    if not args.no_manual_filter:
        print("Filter applied: title contains 'manual(s)' or 'guide(s)' or 'handbook(s)' (case-insensitive).")
    else:
        print("Filter disabled: keeping all titles.")


if __name__ == "__main__":
    main()
