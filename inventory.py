#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import difflib
import re
import csv
import os
from typing import Dict, List, Tuple, Optional

# ============================================================
# Config & data model
# ============================================================

# CSV file used as single source of truth
MANUALS_CSV = "manuals.csv"

# manuals: title -> {"box": "BOX 1|BOX 2|BOX 3|None", "cover": bool}
manuals: Dict[str, Dict[str, Optional[str] | bool]] = {}

# lowercase index: title.lower() -> title
_lc_index: Dict[str, str] = {}

# ============================================================
# CSV load/save
# ============================================================

def load_manuals_from_csv(path: str = MANUALS_CSV) -> Dict[str, Dict[str, Optional[str] | bool]]:
    """Load manuals from a CSV file: columns title,box,cover."""
    manuals_from_file: Dict[str, Dict[str, Optional[str] | bool]] = {}
    if not os.path.exists(path):
        return manuals_from_file

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("title") or "").strip()
            if not title:
                continue
            box_raw = (row.get("box") or "").strip()
            box = box_raw or None
            cover_raw = (row.get("cover") or "").strip().lower()
            cover = cover_raw in ("1", "true", "yes", "y", "on")
            manuals_from_file[title] = {"box": box, "cover": cover}
    return manuals_from_file

def save_manuals_to_csv(path: str = MANUALS_CSV) -> None:
    """Save the current manuals dict to CSV."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["title", "box", "cover"])
        for title in sorted(manuals.keys(), key=str.lower):
            meta = manuals[title]
            box = meta.get("box") or ""
            cover = "1" if meta.get("cover") else "0"
            writer.writerow([title, box, cover])

def rebuild_lc_index() -> None:
    global _lc_index
    _lc_index = {title.lower(): title for title in manuals.keys()}

def init_manuals() -> None:
    """
    Load manuals from CSV if it exists, otherwise:
      - create an empty manuals.csv
      - start with an empty catalog
    """
    global manuals
    from_csv = load_manuals_from_csv(MANUALS_CSV)
    if from_csv:
        manuals = from_csv
    else:
        manuals = {}
        # create an empty CSV with header so you can edit it in Excel/LibreOffice
        save_manuals_to_csv(MANUALS_CSV)
        print(f"Created empty {MANUALS_CSV}. Add rows (title, box, cover) and rerun.")
    rebuild_lc_index()

def remove_manual_by_title(title: str) -> bool:
    """Remove a manual by its exact stored title and persist to CSV."""
    global manuals
    if title in manuals:
        del manuals[title]
        rebuild_lc_index()
        save_manuals_to_csv(MANUALS_CSV)
        return True
    return False

# ============================================================
# Search engine (case-insensitive, fuzzy)
# ============================================================

_word_re = re.compile(r"[a-z0-9]+")

def normalize(s: str) -> str:
    return " ".join(_word_re.findall(s.lower()))

def tokens(s: str) -> List[str]:
    return _word_re.findall(s.lower())

def token_overlap_score(q_tokens: List[str], c_tokens: List[str]) -> float:
    if not q_tokens:
        return 0.0
    qset, cset = set(q_tokens), set(c_tokens)
    overlap = len(qset & cset)
    return overlap / max(1, len(qset))

def partial_window_ratio(query: str, candidate: str, max_window_words: int = 8) -> float:
    q = normalize(query)
    c = normalize(candidate)
    q_tokens = q.split()
    c_tokens = c.split()
    if not q_tokens or not c_tokens:
        return 0.0
    if q in c:
        return 1.0
    w = min(max(len(q_tokens), 1), max_window_words)
    best = 0.0
    for i in range(0, len(c_tokens)):
        window = " ".join(c_tokens[i:i + w])
        if not window:
            continue
        r = difflib.SequenceMatcher(None, q, window).ratio()
        if r > best:
            best = r
    return best

def composite_score(query: str, candidate: str) -> float:
    q_norm = normalize(query)
    c_norm = normalize(candidate)
    sub = 1.0 if q_norm and q_norm in c_norm else 0.0
    tok = token_overlap_score(tokens(query), tokens(candidate))
    glob = difflib.SequenceMatcher(None, q_norm, c_norm).ratio()
    part = partial_window_ratio(query, candidate)
    return max(sub, part, 0.85 * tok, 0.75 * glob)

def exact_lookup(query: str) -> Tuple[str, Dict[str, Optional[str] | bool]] | None:
    key = query.strip().lower()
    if key in _lc_index:
        orig = _lc_index[key]
        return (orig, manuals[orig])
    return None

def smart_search(query: str, top_n: int = 10, min_score: float = 0.52) -> List[Tuple[str, Dict[str, Optional[str] | bool], float]]:
    scored: List[Tuple[str, Dict[str, Optional[str] | bool], float]] = []
    for title, meta in manuals.items():
        s = composite_score(query, title)
        if s >= min_score:
            scored.append((title, meta, s))
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:top_n]

def list_grouped_by_display_box(box_filter: Optional[str] = None) -> Dict[str, List[str]]:
    """
    Groups by display label used in the Box column:
      - If box is set: that BOX label
      - Else if cover=True: 'COVER'
      - Else: 'UNKNOWN'
    """
    by_box: Dict[str, List[str]] = {}
    for title, meta in manuals.items():
        label = meta["box"] if meta["box"] else ("COVER" if meta["cover"] else "UNKNOWN")
        if box_filter and (label.lower() != box_filter.lower()):
            continue
        by_box.setdefault(str(label), []).append(title)
    for v in by_box.values():
        v.sort(key=str.lower)
    return by_box

# ============================================================
# Pretty printing (aligned table)
# ============================================================

COL_TITLE = 64
COL_BOX = 8
COL_COVER = 5
COL_SCORE = 6

def _truncate(s: str, width: int) -> str:
    if len(s) <= width:
        return s
    if width <= 3:
        return s[:width]
    return s[: width - 3] + "..."

def _format_row(title: str, box: Optional[str], cover: bool, score: Optional[float]) -> str:
    # Show 'COVER' when no box but cover=True; else 'UNKNOWN'
    label = box if box else ("COVER" if cover else "UNKNOWN")
    t = _truncate(title, COL_TITLE)
    b = _truncate(str(label), COL_BOX)
    c = "Yes" if cover else "No"
    if score is None:
        sc = " " * COL_SCORE
    else:
        sc = f"{score:>{COL_SCORE}.2f}"
    return f"{t:<{COL_TITLE}}  {b:<{COL_BOX}}  {c:<{COL_COVER}}  {sc}"

def _print_header(show_score: bool) -> None:
    line = f"{'Title':<{COL_TITLE}}  {'Box':<{COL_BOX}}  {'Cover':<{COL_COVER}}"
    if show_score:
        line += f"  {'Score':>{COL_SCORE}}"
    print(line)
    print("-" * (COL_TITLE + 2 + COL_BOX + 2 + COL_COVER + (2 + COL_SCORE if show_score else 0)))

def print_table(rows: List[Tuple[str, Optional[str], bool, Optional[float]]], show_score: bool) -> None:
    _print_header(show_score)
    for title, box, cover, score in rows:
        print(_format_row(title, box, cover, score))

# ============================================================
# Interactive CLI
# ============================================================

def interactive():
    print("Manual Query Tool (CSV-based, case-insensitive fuzzy search, BOX + COVER aware)")
    print("Using CSV file:", MANUALS_CSV)
    print("Commands:")
    print("  search <text>       — fuzzy/partial search (aligned table)")
    print("  exact <title>       — exact (case-insensitive, aligned row)")
    print("  list                — list all grouped by display box (BOX 1/2/3, COVER, UNKNOWN)")
    print("  list box 1|2|3      — list a specific box (aligned table)")
    print("  list cover          — list all items that have a cover")
    print("  remove <text>       — remove an entry and update manuals.csv")
    print("  quit                — exit")

    while True:
        try:
            raw = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if not raw:
            continue
        if raw.lower() in ("quit", "exit"):
            print("Goodbye!")
            break

        parts = raw.split(" ", 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        # ---------- REMOVE ----------
        if cmd in ("remove", "delete", "rm"):
            if not arg:
                print("Usage: remove <text>")
                continue

            # 1) Try exact lookup
            res = exact_lookup(arg)
            if res:
                t, meta = res
                confirm = input(
                    f"Delete exact match '{t}' (box={meta['box']}, cover={meta['cover']})? [y/N]: "
                ).strip().lower()
                if confirm == "y":
                    if remove_manual_by_title(t):
                        print(f"Removed '{t}' and updated {MANUALS_CSV}.")
                    else:
                        print("Entry not found (unexpected).")
                else:
                    print("Cancelled.")
                continue

            # 2) Fuzzy matches
            matches = smart_search(arg, top_n=5)
            if not matches:
                print("No close matches to remove.")
                continue

            print("Possible matches to delete:")
            for idx, (t, meta, s) in enumerate(matches, start=1):
                print(f"  {idx}. {t}  [box={meta['box']}, cover={meta['cover']}, score={s:.2f}]")

            sel = input("Number to delete (blank to cancel): ").strip()
            if not sel:
                print("Cancelled.")
                continue

            try:
                n = int(sel)
            except ValueError:
                print("Invalid selection.")
                continue

            if not (1 <= n <= len(matches)):
                print("Selection out of range.")
                continue

            t, meta, _ = matches[n - 1]
            confirm = input(f"Delete '{t}'? [y/N]: ").strip().lower()
            if confirm == "y":
                if remove_manual_by_title(t):
                    print(f"Removed '{t}' and updated {MANUALS_CSV}.")
                else:
                    print("Entry not found (unexpected).")
            else:
                print("Cancelled.")
            continue

        # ---------- LIST ----------
        if cmd == "list":
            if arg.lower().startswith("box"):
                box = arg.upper().strip()  # "BOX 1", "BOX 2", "BOX 3"
                grouped = list_grouped_by_display_box(box)
                titles = grouped.get(box, [])
                rows = [(t, manuals[t]["box"], bool(manuals[t]["cover"]), None) for t in titles]
                if not rows:
                    print(f"No items in {box}.")
                else:
                    print_table(rows, show_score=False)
            elif arg.lower() == "cover":
                titles = sorted([t for t, m in manuals.items() if m["cover"]], key=str.lower)
                if not titles:
                    print("No items with cover flag.")
                else:
                    rows = [(t, manuals[t]["box"], True, None) for t in titles]
                    print_table(rows, show_score=False)
            else:
                grouped = list_grouped_by_display_box()
                if not grouped:
                    print("No items in catalog.")
                for box_label in sorted(grouped.keys()):
                    print(f"\n{box_label}")
                    rows = [(t, manuals[t]["box"], bool(manuals[t]["cover"]), None) for t in grouped[box_label]]
                    print_table(rows, show_score=False)
            continue

        # ---------- EXACT ----------
        if cmd == "exact":
            if not arg:
                print("Usage: exact <title>")
                continue
            res = exact_lookup(arg)
            if res:
                t, meta = res
                print_table([(t, meta["box"], bool(meta["cover"]), 1.00)], show_score=True)
            else:
                print("No exact (case-insensitive) match.")
            continue

        # ---------- SEARCH ----------
        if cmd == "search":
            if not arg:
                print("Usage: search <text>")
                continue
            # Show exact if any
            res = exact_lookup(arg)
            if res:
                print("Exact match:")
                t, meta = res
                print_table([(t, meta["box"], bool(meta["cover"]), 1.00)], show_score=True)

            matches = smart_search(arg)
            if matches:
                rows = [(t, meta["box"], bool(meta["cover"]), s) for (t, meta, s) in matches]
                print("Matches:")
                print_table(rows, show_score=True)
            else:
                print("No close matches found.")
            continue

        # ---------- Fallback: treat line as a search ----------
        matches = smart_search(raw)
        if matches:
            rows = [(t, meta["box"], bool(meta["cover"]), s) for (t, meta, s) in matches]
            print("Matches:")
            print_table(rows, show_score=True)
        else:
            print("No close matches found.")

if __name__ == "__main__":
    init_manuals()
    interactive()

