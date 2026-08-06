import argparse
import csv
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from bs4 import BeautifulSoup


SCRIPT_DIR = Path(__file__).resolve().parent

STOPWORDS = {
    "a", "an", "and", "for", "from", "in", "of", "on", "or", "the", "to", "with", "w",
    "manual", "manuals", "guide", "guides", "handbook", "handbooks", "instruction", "instructions",
    "owner", "owners", "operation", "operating", "service", "workshop", "repair", "user", "users",
    "page", "pages", "printed", "print", "reprint", "reprinted", "book", "booklet", "copy",
    "protective", "cover", "covers", "clear", "plastic", "pvc", "card", "stock", "paper",
    "full", "color", "colour", "premium", "quality", "complete", "set", "bundle", "size",
    "new", "original", "oem", "download", "pdf", "free", "shipping",
}

ROMAN_MODEL_TOKENS = {"ii", "iii", "iv", "vi", "vii", "viii", "ix", "xi", "xii"}

PHRASE_REPLACEMENTS = [
    r"\bfull color\b",
    r"\bfull colour\b",
    r"\bprotective covers?\b",
    r"\bclear covers?\b",
    r"\bpremium card stock covers?\b",
    r"\b\d+\s*pages?\b",
    r"\bhalf[- ]letter\b",
    r"\b8\.5\s*x\s*11\b",
]


@dataclass
class CompetitorItem:
    title: str
    total_sold: int
    avg_price: float
    estimated_total: float
    url: str
    norm: str
    tokens: set[str]


@dataclass
class OwnItem:
    title: str
    latest_price: float
    avg_price: float
    quantity: int
    last_sale_date: str
    url: str
    norm: str
    tokens: set[str]


def parse_args():
    parser = argparse.ArgumentParser(description="Compare competitor eBay stock report against your own eBay sales.")
    parser.add_argument("--competitor-html", type=Path, default=Path("kndmeredith_stock_summary.html"))
    parser.add_argument("--own-orders", nargs="*", type=Path, help="Your eBay OrdersReport CSV files. Default: all eBay-OrdersReport-*.csv in this folder")
    parser.add_argument("--out-prefix", default="kndmeredith_compare")
    parser.add_argument("--auto-threshold", type=float, default=0.82, help="Score at/above this is accepted automatically")
    parser.add_argument("--ask-threshold", type=float, default=0.62, help="Score at/above this asks for confirmation")
    parser.add_argument("--no-interactive", action="store_true", help="Do not ask questions; uncertain matches are treated as not selling")
    parser.add_argument("--decisions", type=Path, default=Path("ebay_compare_decisions.json"), help="Remember manual yes/no choices")
    return parser.parse_args()


def parse_money(text):
    match = re.search(r"-?[\d,.]+", (text or "").replace(",", ""))
    return float(match.group(0)) if match else 0.0


def parse_int(text):
    match = re.search(r"\d[\d,]*", text or "")
    return int(match.group(0).replace(",", "")) if match else 0


def parse_date(text):
    text = (text or "").strip()
    for fmt in ("%b-%d-%y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return datetime.min


def normalize_title(title):
    text = html.unescape(title or "").lower()
    text = text.replace("&", " and ")
    for pattern in PHRASE_REPLACEMENTS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    raw_tokens = [t for t in text.split() if t not in STOPWORDS and len(t) > 1]

    tokens = set()
    for token in raw_tokens:
        tokens.add(token)

        parts = re.findall(r"[a-z]+|\d+", token)
        if len(parts) > 1:
            tokens.add("".join(parts))
            for part in parts:
                if part in ROMAN_MODEL_TOKENS:
                    tokens.add(part)

    for i in range(len(raw_tokens) - 1):
        first = raw_tokens[i]
        second = raw_tokens[i + 1]
        if (any(ch.isdigit() for ch in first) and second.isalpha()) or (first.isalpha() and any(ch.isdigit() for ch in second)):
            tokens.add(first + second)
        if first.isalpha() and second in ROMAN_MODEL_TOKENS:
            tokens.add(first + second)

    for i in range(len(raw_tokens) - 2):
        first, second, third = raw_tokens[i:i + 3]
        if first.isalpha() and second.isdigit() and third.isalpha():
            tokens.add(first + second)
            tokens.add(second + third)
            tokens.add(first + second + third)

    ordered_tokens = [t for t in raw_tokens if t in tokens]
    for token in sorted(tokens):
        if token not in ordered_tokens:
            ordered_tokens.append(token)

    return " ".join(ordered_tokens), tokens


def model_tokens(tokens):
    models = set()
    for token in tokens:
        if any(ch.isdigit() for ch in token) and not is_year_token(token):
            models.add(token)
    return models


def is_year_token(token):
    return bool(re.fullmatch(r"(?:19|20)\d{2}", token or ""))


def brand_tokens(tokens):
    return {t for t in tokens if t.isalpha() and t not in ROMAN_MODEL_TOKENS}


def similarity(a_norm, a_tokens, b_norm, b_tokens):
    if not a_norm or not b_norm or not a_tokens or not b_tokens:
        return 0.0

    overlap = len(a_tokens & b_tokens)
    token_precision = overlap / len(a_tokens)
    token_recall = overlap / len(b_tokens)
    token_score = (2 * token_precision * token_recall / (token_precision + token_recall)) if (token_precision + token_recall) else 0.0
    seq_score = SequenceMatcher(None, a_norm, b_norm).ratio()

    score = (token_score * 0.62) + (seq_score * 0.18)

    a_models = model_tokens(a_tokens)
    b_models = model_tokens(b_tokens)
    shared_models = a_models & b_models
    shared_brands = brand_tokens(a_tokens) & brand_tokens(b_tokens)

    if a_models and b_models and shared_models:
        model_coverage = len(shared_models) / min(len(a_models), len(b_models))
        if shared_brands:
            model_score = 0.78 + (0.17 * model_coverage) + 0.05
            score = max(score, min(model_score, 1.0))
        else:
            model_score = 0.68 + (0.12 * model_coverage)
            score = max(score, min(model_score, 0.80))
    elif a_models and b_models:
        score *= 0.55

    return min(score, 1.0)


def read_competitor_html(path):
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    out = []
    for tr in soup.select("tbody tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        title_cell = cells[0]
        title = title_cell.get("data-sort") or title_cell.get_text(" ", strip=True)
        link = title_cell.find("a")
        url = link.get("href", "") if link else ""
        total_sold = parse_int(cells[1].get("data-sort") or cells[1].get_text(" ", strip=True))
        avg_price = parse_money(cells[2].get("data-sort") or cells[2].get_text(" ", strip=True))
        estimated_total = parse_money(cells[3].get("data-sort") or cells[3].get_text(" ", strip=True))
        norm, tokens = normalize_title(title)
        out.append(CompetitorItem(title, total_sold, avg_price, estimated_total, url, norm, tokens))
    return out


def read_orders_csv(path):
    lines = path.read_text(encoding="utf-8-sig").splitlines(True)
    header_index = None
    for i, line in enumerate(lines):
        if "Sales Record Number" in line and "Item Title" in line:
            header_index = i
            break
    if header_index is None:
        raise ValueError(f"Could not find eBay OrdersReport header in {path}")
    return list(csv.DictReader(lines[header_index:]))


def read_own_items(paths):
    groups = {}
    for path in paths:
        for row in read_orders_csv(path):
            title = (row.get("Item Title") or "").strip()
            item_id = (row.get("Item Number") or "").strip()
            if not title:
                continue
            price = parse_money(row.get("Sold For"))
            qty = max(1, parse_int(row.get("Quantity")))
            sale_date = (row.get("Sale Date") or "").strip()
            key_norm, key_tokens = normalize_title(title)
            if not key_norm:
                continue
            g = groups.setdefault(key_norm, {
                "title": title,
                "tokens": key_tokens,
                "quantity": 0,
                "total_price": 0.0,
                "latest_price": price,
                "last_sale_date": sale_date,
                "last_dt": parse_date(sale_date),
                "url": f"https://www.ebay.com/itm/{item_id}" if item_id else "",
            })
            g["quantity"] += qty
            g["total_price"] += price * qty
            dt = parse_date(sale_date)
            if dt >= g["last_dt"]:
                g["latest_price"] = price
                g["last_sale_date"] = sale_date
                g["last_dt"] = dt
                g["title"] = title
                if item_id:
                    g["url"] = f"https://www.ebay.com/itm/{item_id}"

    out = []
    for norm, g in groups.items():
        avg = g["total_price"] / g["quantity"] if g["quantity"] else 0.0
        out.append(OwnItem(g["title"], g["latest_price"], avg, g["quantity"], g["last_sale_date"], g["url"], norm, g["tokens"]))
    return out


def load_decisions(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_decisions(path, decisions):
    path.write_text(json.dumps(decisions, indent=2, sort_keys=True), encoding="utf-8")


def best_candidates(comp, own_items, limit=5):
    scored = []
    for own in own_items:
        score = similarity(comp.norm, comp.tokens, own.norm, own.tokens)
        if score > 0:
            scored.append((score, own))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:limit]


def ask_match(comp, candidates):
    print("\nPossible match needs confirmation")
    print(f"Competitor: {comp.title}")
    print(f"Competitor avg price: ${comp.avg_price:.2f}  sold: {comp.total_sold}")
    for i, (score, own) in enumerate(candidates, start=1):
        print(f"  {i}. {own.title}")
        print(f"     score={score:.3f} latest price=${own.latest_price:.2f} last sale={own.last_sale_date}")
    print("  n. Not the same / I am not selling it")
    print("  s. Skip for now")

    while True:
        choice = input("Choice: ").strip().lower()
        if choice == "n":
            return None, "no"
        if choice == "s":
            return None, "skip"
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            return candidates[int(choice) - 1][1], "yes"
        print("Enter a candidate number, n, or s.")


def compare_items(competitor_items, own_items, auto_threshold, ask_threshold, interactive, decisions):
    matched = []
    missing = []

    for comp in competitor_items:
        candidates = best_candidates(comp, own_items)
        best_score = candidates[0][0] if candidates else 0.0
        best_own = candidates[0][1] if candidates else None
        decision_key = comp.norm

        if decision_key in decisions:
            saved = decisions[decision_key]
            if saved.get("own_norm"):
                best_own = next((o for o in own_items if o.norm == saved["own_norm"]), None)
                best_score = saved.get("score", best_score)
                if best_own:
                    matched.append(match_row(comp, best_own, best_score, "saved"))
                    continue
            if saved.get("decision") == "no":
                missing.append(missing_row(comp, best_score, "saved no"))
                continue

        if best_own and best_score >= auto_threshold:
            matched.append(match_row(comp, best_own, best_score, "auto"))
        elif best_own and best_score >= ask_threshold and interactive:
            chosen, decision = ask_match(comp, candidates)
            if decision == "yes" and chosen:
                score = similarity(comp.norm, comp.tokens, chosen.norm, chosen.tokens)
                decisions[decision_key] = {"decision": "yes", "own_norm": chosen.norm, "score": score}
                matched.append(match_row(comp, chosen, score, "manual"))
            elif decision == "no":
                decisions[decision_key] = {"decision": "no", "score": best_score}
                missing.append(missing_row(comp, best_score, "manual no"))
            else:
                missing.append(missing_row(comp, best_score, "skipped"))
        else:
            missing.append(missing_row(comp, best_score, "no match"))

    return matched, missing


def match_row(comp, own, score, method):
    diff = own.latest_price - comp.avg_price
    return {
        "competitor_title": comp.title,
        "competitor_total_sold": comp.total_sold,
        "competitor_avg_price": comp.avg_price,
        "competitor_estimated_total": comp.estimated_total,
        "competitor_url": comp.url,
        "my_title": own.title,
        "my_latest_price": own.latest_price,
        "my_avg_price": own.avg_price,
        "my_quantity_sold": own.quantity,
        "my_last_sale_date": own.last_sale_date,
        "my_url": own.url,
        "price_difference": diff,
        "score": score,
        "match_method": method,
    }


def missing_row(comp, score, method):
    return {
        "competitor_title": comp.title,
        "competitor_total_sold": comp.total_sold,
        "competitor_avg_price": comp.avg_price,
        "competitor_estimated_total": comp.estimated_total,
        "competitor_url": comp.url,
        "best_score": score,
        "match_method": method,
    }


def write_csv(path, rows, headers):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def money(value):
    return f"${value:,.2f}"


def link(title, url):
    safe_title = html.escape(title or "")
    safe_url = html.escape(url or "")
    return f'<a href="{safe_url}" target="_blank">{safe_title}</a>' if safe_url else safe_title


def html_page(title, subtitle, headers, rows_html, note):
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: Arial, Helvetica, sans-serif; background:#f7f7f7; margin:0; padding:30px; color:#191919; }}
.container {{ max-width:1500px; margin:auto; background:white; padding:30px; border-radius:16px; box-shadow:0 8px 28px rgba(0,0,0,.10); border-top:8px solid #e53238; }}
.ebay-logo {{ font-size:34px; font-weight:bold; letter-spacing:-2px; margin-bottom:8px; }}
.e {{ color:#e53238; }} .b {{ color:#0064d2; }} .a {{ color:#f5af02; }} .y {{ color:#86b817; }}
h1 {{ margin:0; font-size:26px; }}
.subtitle {{ color:#555; margin-top:8px; margin-bottom:25px; line-height:1.5; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th {{ background:#0064d2; color:white; text-align:left; padding:12px; cursor:pointer; user-select:none; position:sticky; top:0; }}
th:hover {{ background:#004ea8; }} th::after {{ content:" ⇅"; font-size:12px; opacity:.75; }}
td {{ padding:11px 12px; border-bottom:1px solid #e5e5e5; vertical-align:top; }}
tr:hover {{ background:#fff8e1; }}
td.title {{ width:34%; font-weight:500; }}
a {{ color:#0064d2; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
.green {{ color:#16833a; font-weight:bold; }} .red {{ color:#c62828; font-weight:bold; }} .neutral {{ color:#555; }}
.note {{ margin-top:22px; padding:14px 16px; background:#f5f5f5; border-left:5px solid #86b817; border-radius:10px; font-size:13px; color:#555; }}
</style>
<script>
function sortTable(columnIndex) {{
  const table = document.getElementById("salesTable");
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  const currentDirection = table.getAttribute("data-sort-dir") || "asc";
  const currentColumn = table.getAttribute("data-sort-col");
  let direction = "asc";
  if (currentColumn == columnIndex && currentDirection === "asc") direction = "desc";
  rows.sort(function(a, b) {{
    let aValue = a.cells[columnIndex].getAttribute("data-sort") || a.cells[columnIndex].innerText;
    let bValue = b.cells[columnIndex].getAttribute("data-sort") || b.cells[columnIndex].innerText;
    let aNum = parseFloat(aValue); let bNum = parseFloat(bValue);
    if (!isNaN(aNum) && !isNaN(bNum)) return direction === "asc" ? aNum - bNum : bNum - aNum;
    return direction === "asc" ? aValue.localeCompare(bValue) : bValue.localeCompare(aValue);
  }});
  rows.forEach(row => tbody.appendChild(row));
  table.setAttribute("data-sort-dir", direction); table.setAttribute("data-sort-col", columnIndex);
}}
</script>
</head>
<body><div class="container">
<div class="ebay-logo"><span class="e">e</span><span class="b">b</span><span class="a">a</span><span class="y">y</span></div>
<h1>{html.escape(title)}</h1>
<div class="subtitle">{subtitle}</div>
<table id="salesTable"><thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>
<div class="note">{html.escape(note)}</div>
</div></body></html>"""


def write_missing_html(path, rows):
    rows_html = ""
    for r in rows:
        rows_html += f"""
        <tr>
            <td class="title" data-sort="{html.escape(r['competitor_title'])}">{link(r['competitor_title'], r['competitor_url'])}</td>
            <td data-sort="{r['competitor_total_sold']}">{r['competitor_total_sold']}</td>
            <td data-sort="{r['competitor_avg_price']:.2f}">{money(r['competitor_avg_price'])}</td>
            <td data-sort="{r['competitor_estimated_total']:.2f}">{money(r['competitor_estimated_total'])}</td>
            <td data-sort="{r['best_score']:.3f}">{r['best_score']:.3f}</td>
            <td data-sort="{html.escape(r['match_method'])}">{html.escape(r['match_method'])}</td>
        </tr>"""
    headers = """
        <th onclick="sortTable(0)">Competitor Title</th>
        <th onclick="sortTable(1)">Total Sold</th>
        <th onclick="sortTable(2)">Competitor Avg Price</th>
        <th onclick="sortTable(3)">Estimated Total</th>
        <th onclick="sortTable(4)">Best Score</th>
        <th onclick="sortTable(5)">Reason</th>
    """
    path.write_text(html_page(
        "Manuals I Am Not Currently Selling",
        f"Rows: <strong>{len(rows):,}</strong>. Sorted by competitor estimated sales unless you click another column.",
        headers,
        rows_html,
        "These competitor listings did not match your own eBay order history above the selected threshold.",
    ), encoding="utf-8")


def write_matched_html(path, rows):
    rows_html = ""
    for r in rows:
        diff = r["price_difference"]
        cls = "green" if diff < 0 else "red" if diff > 0 else "neutral"
        label = f"{money(abs(diff))} lower" if diff < 0 else f"{money(diff)} higher" if diff > 0 else "$0.00"
        rows_html += f"""
        <tr>
            <td class="title" data-sort="{html.escape(r['competitor_title'])}">{link(r['competitor_title'], r['competitor_url'])}</td>
            <td class="title" data-sort="{html.escape(r['my_title'])}">{link(r['my_title'], r['my_url'])}</td>
            <td data-sort="{r['competitor_total_sold']}">{r['competitor_total_sold']}</td>
            <td data-sort="{r['competitor_avg_price']:.2f}">{money(r['competitor_avg_price'])}</td>
            <td data-sort="{r['my_latest_price']:.2f}">{money(r['my_latest_price'])}</td>
            <td class="{cls}" data-sort="{diff:.2f}">{label}</td>
            <td data-sort="{r['my_last_sale_date']}">{html.escape(r['my_last_sale_date'])}</td>
            <td data-sort="{r['score']:.3f}">{r['score']:.3f}</td>
            <td data-sort="{html.escape(r['match_method'])}">{html.escape(r['match_method'])}</td>
        </tr>"""
    headers = """
        <th onclick="sortTable(0)">Competitor Title</th>
        <th onclick="sortTable(1)">My Matched Title</th>
        <th onclick="sortTable(2)">Competitor Sold</th>
        <th onclick="sortTable(3)">Competitor Avg Price</th>
        <th onclick="sortTable(4)">My Latest Price</th>
        <th onclick="sortTable(5)">My Price Difference</th>
        <th onclick="sortTable(6)">My Last Sale</th>
        <th onclick="sortTable(7)">Score</th>
        <th onclick="sortTable(8)">Match</th>
    """
    path.write_text(html_page(
        "Manuals I Also Sell - Price Comparison",
        f"Rows: <strong>{len(rows):,}</strong>. Green means my latest price is lower than competitor average; red means higher.",
        headers,
        rows_html,
        "Your price is the latest Sold For price found in your eBay OrdersReport CSV exports.",
    ), encoding="utf-8")


def main():
    args = parse_args()
    competitor_path = args.competitor_html
    own_paths = args.own_orders or sorted(SCRIPT_DIR.glob("eBay-OrdersReport-*.csv"))
    if not competitor_path.exists():
        raise SystemExit(f"Competitor HTML not found: {competitor_path}")
    if not own_paths:
        raise SystemExit("No own eBay OrdersReport CSV files found.")

    competitor_items = read_competitor_html(competitor_path)
    own_items = read_own_items(own_paths)
    decisions = load_decisions(args.decisions)

    print(f"Loaded competitor rows: {len(competitor_items)} from {competitor_path}")
    print(f"Loaded own title groups: {len(own_items)} from {len(own_paths)} order report(s)")

    matched, missing = compare_items(
        competitor_items,
        own_items,
        auto_threshold=args.auto_threshold,
        ask_threshold=args.ask_threshold,
        interactive=not args.no_interactive,
        decisions=decisions,
    )
    save_decisions(args.decisions, decisions)

    matched.sort(key=lambda r: abs(r["price_difference"]), reverse=True)
    missing.sort(key=lambda r: (r["competitor_estimated_total"], r["competitor_total_sold"]), reverse=True)

    missing_csv = Path(f"{args.out_prefix}_not_selling.csv")
    missing_html = Path(f"{args.out_prefix}_not_selling.html")
    matched_csv = Path(f"{args.out_prefix}_matched.csv")
    matched_html = Path(f"{args.out_prefix}_matched.html")

    write_csv(missing_csv, missing, [
        "competitor_title", "competitor_total_sold", "competitor_avg_price", "competitor_estimated_total",
        "competitor_url", "best_score", "match_method",
    ])
    write_csv(matched_csv, matched, [
        "competitor_title", "competitor_total_sold", "competitor_avg_price", "competitor_estimated_total", "competitor_url",
        "my_title", "my_latest_price", "my_avg_price", "my_quantity_sold", "my_last_sale_date", "my_url",
        "price_difference", "score", "match_method",
    ])
    write_missing_html(missing_html, missing)
    write_matched_html(matched_html, matched)

    print(f"Matched: {len(matched)}")
    print(f"Not selling: {len(missing)}")
    print(f"Saved: {missing_csv}")
    print(f"Saved: {missing_html}")
    print(f"Saved: {matched_csv}")
    print(f"Saved: {matched_html}")


if __name__ == "__main__":
    main()
