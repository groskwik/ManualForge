#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import difflib
import re
from typing import Dict, List, Tuple, Optional

# ============================================================
# Data model: title -> {"box": "BOX 1|BOX 2|BOX 3|None", "cover": bool}
# ============================================================

def rec(box: Optional[str] = None, cover: bool = False) -> Dict[str, Optional[str] | bool]:
    return {"box": box, "cover": cover}

# ---- Base catalog (everything you’ve listed so far with boxes) ----
manuals: Dict[str, Dict[str, Optional[str] | bool]] = {
    # BOX 1
    "HP 48G Advanced user's reference manual": rec("BOX 1"),
    "Nikon Z7 Z6 Reference Manual": rec("BOX 1"),
    "HP 2404A HP IL interface HP 71B": rec("BOX 1"),
    "HP 19C HP 29C Owner Manual": rec("BOX 1"),
    "HP 35S Quick Start Guide": rec("BOX 1"),
    "GOPRO Hero 5 Black": rec("BOX 1"),
    "Baby Lock Coronet": rec("BOX 1"),
    "Baby Lock BLSA3 Embroidery Design Guide": rec("BOX 1"),
    "Nikon D7200": rec("BOX 1"),
    "Getting Started with TI Nspire CX II": rec("BOX 1"),
    "Nikon Coolpix P950 reference manual": rec("BOX 1"),
    "Lowrance Hook 2 series": rec("BOX 1"),
    "PFAFF ICON 1": rec("BOX 1"),
    "HP 75 Forth / Assembler": rec("BOX 1"),
    "TI NSPIRE CX II Guidebook": rec("BOX 1"),
    "HP 82104A Card Reader": rec("BOX 1"),
    "HP 75 Reference Manual": rec("BOX 1"),
    "Tandy Model 100 Reference": rec("BOX 1"),
    "HP 75 Owner Manual": rec("BOX 1"),
    "TDS 48GX Suveyin Card User's Manual": rec("BOX 1"),
    "HP 12C Solutions Handbook": rec("BOX 1"),
    "Brother xp3 embroidery design guide (beginning only)": rec("BOX 1"),

    # BOX 2
    "Gopro 10 Black": rec("BOX 2"),
    "Tektronix MS022 MSO24": rec("BOX 2"),
    "Bernina 790 Plus": rec("BOX 2"),
    "HP 15C Limited Edition Owner Handbook": rec("BOX 2"),
    "HP 41C P 41CV Owener handbook and Programming Guide": rec("BOX 2"),
    "Canon EOS R6 Mark II": rec("BOX 2"),
    "Canon EOS 70D": rec("BOX 2"),
    "Sony DSC-H300": rec("BOX 2"),
    "Nikon 3500 Reference Manual": rec("BOX 2"),
    "Nikon D5": rec("BOX 2"),
    "HP 67 Civil Engineering": rec("BOX 2"),
    "HP 50g advanced user's reference manual": rec("BOX 2"),
    "Brother XP2 Embroidery Design Guide": rec("BOX 2"),
    "Yamaha dgx-670 owner manual": rec("BOX 2"),
    "Canon Powershot SX500 IS": rec("BOX 2"),
    "HP 15C advanced function handbook (half letter)": rec("BOX 2"),
    "Brother XP2 Embroidery": rec("BOX 2"),

    # BOX 3 (as requested)
    "Humminbird Helix 5": rec("BOX 3"),
    "HP 71B Forth Assembler": rec("BOX 3"),
    "Baby Lock BLSA3 embroidery (few pages)": rec("BOX 3"),
    "HP 71 Made Easy": rec("BOX 3"),
    "HP 71 Owner Manual": rec("BOX 3"),
    "HP 71 Reference Manual": rec("BOX 3"),
    "Nikon Coolpix P950": rec("BOX 3"),
    "Panasonic Lumix DC-ZS70": rec("BOX 3"),
    "HP 67 EE pac": rec("BOX 3"),
    "Free42": rec("BOX 3"),
    "Lowrance Hook Reveal Series": rec("BOX 3"),
    "Lowrance Elite FS": rec("BOX 3"),
    "BabyLock BLSA3 Sewing": rec("BOX 3"),
    "HP 50G um": rec("BOX 3"),
    "HP 75 reference manual": rec("BOX 3"),
    "Denon AVR-760H": rec("BOX 3"),
}

# ---- COVER (cover-only or also have a box). Case-insensitive linking to avoid dup keys. ----
cover_items = [
    "HP 35S Quick Start Guide (black)",
    "Brother XP3 Embroidery Design Guide",
    "HP 75 Service Manual",
    "Bernette B77 [1]",
    "Bernette B77 [2]",
    "Bernette B77 [3]",
    "Lowrance Hook Series",
    "HP 71 Disassembler",
    "An easy Course using the HP 48GX",
    "An easy course in using the HP-42S",
    "HP 10BII user's Guide",
    "The Basic HP-71",
    "HP-10C Owner's Handbook",
    "TSDS Surveying Card User's Manual",
    "HP 75 I/O Rom",
    "Baby Lock BLSA3 Sewing",
    "HP 71 Data Communications",
    "HP 67",
    "HP 75 Owner Manual",
    "HP 41 Synthetic ",
    "Brother XP2 Embroidery Design Guide",
    "Canon EOS R6 Mark II",
    "HP 49G+ users's manual",
    "Husqvarna emerald",
    "HP 75 Statistics",
    "HP 41 Easy Course",
    "HP 12C Platinum Owner's Handbook",
    "HP 32S Engineering Applications",
    "Blackmagic Cinema 6K",
    "HP19C HP 29C",
    "Baby Lock BLSA3 Sewing",
    "Tandy Model 100 [1]",
    "HP 97 Service Manual",
    "Tandy Model 100 [2]",
    "Canon EOS 3000D",
    "Kodak AZ528",
    "HP28S Owner's Manual",
    "TDS-48GX Survey Pro User's Manual",
    "HP-41C Applied Statistics II",
    "HP-41C Math Pac",
    "Brother XP3 Embroidery",
    "An easy Course in programming the HP48GX",
    "HP 65 Owner Handbook",
    "HP 42S Programming",
    "Brother XP2 Embroidery design guide [1]",
    "Brother XP2 Embroidery design guide [2]",
    "HP22S Owner's Manual",
    "HP 82153A Wand",
    "Blackmagic Studio Cameras",
    "Brother XP3 Embroidery Design Guide",
    "TI Nspire CX CAS Handheld guidebook",
    "HP12C Platinum Handbook",
    "HP 50G Advanced User's Reference Manual",
    "HP 41CL The Easy Way",
    "HP 15C Owners's Handbook",
    "HP12C Platinum Owner's Handbook",
    "Pentax 645D",
    "Nikon D50",
    "Boss DR-880",
    "Husqvarna Sapphire",
    "Canon EOS 5D Mark II",
    "An easy Course in Programming the HP 15C",
    "HP 19C HP 29C",
    "Brother XP2 Sewing",
    "An easy Course in using the HP 17BII",
    "HP 15C Collector Edition Owner Handbook",
    "HP Prime QSG",
    "HP 45",
    "HP 15C Collector's Edition Owner Handbook",
    "Canon EOS 1D Mark IV",
    "GOPRO HERO 12",
    "DGX670 Reference",
    "Blackmagic Pocket Cinema Camera",   # will link to existing "BlackMagic ..." entry
    "HP 49G+ User's Manual",
    "Canon EOS R100",
    "Brother XP3 sewing",
    "HP 42S Programming Technique",
    "HP 15C Collector's Edition Advanced Function Handbook",
    "HP 15C Collector's Edition Owner's Handbook",
    "Baby Lock BLSA3 Embroidery",
    "Baby Lock BLSA3 Sewing",
    "HP 42S Owner's Manual",
    "TI 84Plus CE Getting Started",
    "Husqvarna Huskylock 936",
    "Canon EOS 6D",
    "HP 15C Advanced Functions Handbook",
    "TC Helicon Voicelive",
    "HP 41CV Service Manual",
]

# Build a lowercase index for case-insensitive linking
def _lc_key_map(d: Dict[str, Dict[str, Optional[str] | bool]]) -> Dict[str, str]:
    return {k.lower(): k for k in d.keys()}

_lc_index = _lc_key_map(manuals)

# Set cover=True for each title; if not present, create as cover-only
for title in cover_items:
    key_lc = title.lower()
    if key_lc in _lc_index:
        manuals[_lc_index[key_lc]]["cover"] = True
    else:
        # try to link minor case-variant like "Blackmagic" vs "BlackMagic"
        found = None
        for existing_lc, original in _lc_index.items():
            if existing_lc == key_lc:
                found = original
                break
        if found:
            manuals[found]["cover"] = True
        else:
            manuals[title] = rec(None, True)  # cover-only item (no box)
            _lc_index = _lc_key_map(manuals)  # refresh for any further matches

# ============================================================
# Search engine (case-insensitive, smarter fuzzy + aligned tables)
# ============================================================

def rebuild_lc_index():
    global _lc_index
    _lc_index = {title.lower(): title for title in manuals.keys()}

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
    print("Manual Query Tool (case-insensitive, smarter fuzzy, BOX + COVER aware)")
    print("Commands:")
    print("  search <text>       — fuzzy/partial search (aligned table)")
    print("  exact <title>       — exact (case-insensitive, aligned row)")
    print("  list                — list all grouped by display box (BOX 1/2/3, COVER, UNKNOWN)")
    print("  list box 1|2|3      — list a specific box (aligned table)")
    print("  list cover          — list all items that have a cover")
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
                for box_label in sorted(grouped.keys()):
                    print(f"\n{box_label}")
                    rows = [(t, manuals[t]["box"], bool(manuals[t]["cover"]), None) for t in grouped[box_label]]
                    print_table(rows, show_score=False)
            continue

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

        # Fallback: treat line as a search
        matches = smart_search(raw)
        if matches:
            rows = [(t, meta["box"], bool(meta["cover"]), s) for (t, meta, s) in matches]
            print("Matches:")
            print_table(rows, show_score=True)
        else:
            print("No close matches found.")

if __name__ == "__main__":
    interactive()
