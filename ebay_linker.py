#!/usr/bin/env python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import importlib.util
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass


# =============================================================================
# Normalization / similarity
# =============================================================================

_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with",
    "manual", "user", "users", "guide", "instruction", "instructions",
    "reference", "owner", "owners", "operating", "operation",
}


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"[^\w\s\-]+", " ", s)
    s = re.sub(r"[_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(s: str) -> List[str]:
    s = _norm(s)
    if not s:
        return []
    toks = s.split()
    toks = [t for t in toks if t not in _STOPWORDS and len(t) >= 2]
    return toks


def _jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def _ratio(a: str, b: str) -> float:
    import difflib
    a2, b2 = _norm(a), _norm(b)
    if not a2 and not b2:
        return 1.0
    if not a2 or not b2:
        return 0.0
    return difflib.SequenceMatcher(None, a2, b2).ratio()


def similarity_score(title: str, other: str) -> float:
    r = _ratio(title, other)
    j = _jaccard(_tokens(title), _tokens(other))
    return 100.0 * (0.55 * r + 0.45 * j)


# =============================================================================
# URL -> item_id helper
# =============================================================================

RE_ITM = re.compile(r"/itm/(\d+)")


def extract_item_id_from_url(url: str) -> str:
    try:
        path = urlparse(url).path
    except Exception:
        path = url or ""
    m = RE_ITM.search(path)
    return m.group(1) if m else ""


# =============================================================================
# PDF inventory
# =============================================================================

@dataclass
class PdfEntry:
    base: str
    path: Path


@dataclass
class InventoryHit:
    title: str
    box: Optional[str]
    cover: str


@dataclass
class SkippedInventoryRecord:
    pdf_base: str
    pdf_path: str
    location: str


class InventorySkipCollector:
    def __init__(self) -> None:
        self._lock = Lock()
        self._records: Dict[str, SkippedInventoryRecord] = {}

    def add(self, record: SkippedInventoryRecord) -> None:
        key = _norm(record.pdf_base)
        with self._lock:
            self._records[key] = record

    def has_records(self) -> bool:
        with self._lock:
            return bool(self._records)

    def records(self) -> List[SkippedInventoryRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda r: _norm(r.pdf_base))


# =============================================================================
# manuals.csv inventory lookup (mirrors myprint.py logic)
# =============================================================================


def normalize_for_db(s: str) -> str:
    s = (s or "").lower()
    tokens = re.findall(r"[a-z0-9]+", s)
    return " ".join(tokens)


DEFAULT_MANUALS_CSV = Path(r"C:\Users\benoi\Downloads\ManualForge\manuals.csv")


class ManualsInventory:
    def __init__(self, by_title: Dict[str, List[InventoryHit]], csv_path: Path) -> None:
        self.by_title = by_title
        self.csv_path = csv_path

    @classmethod
    def load(cls, csv_path: Path) -> "ManualsInventory":
        if not csv_path.exists():
            print(f"[inventory] manuals.csv not found at: {csv_path} (inventory check disabled)")
            return cls({}, csv_path)

        by_title: Dict[str, List[InventoryHit]] = {}
        try:
            with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    title = (row.get("title") or "").strip()
                    ntitle = normalize_for_db(title)
                    if not ntitle:
                        continue
                    hit = InventoryHit(
                        title=title,
                        box=((row.get("box") or "").strip() or None),
                        cover=(row.get("cover") or "").strip(),
                    )
                    by_title.setdefault(ntitle, []).append(hit)
        except Exception as e:
            print(f"[inventory] WARNING: failed to read manuals.csv {csv_path}: {e}")
            return cls({}, csv_path)

        return cls(by_title, csv_path)

    def lookup_pdf(self, pdf: PdfEntry) -> List[InventoryHit]:
        return list(self.by_title.get(normalize_for_db(pdf.base), []))


def interpret_inventory_hit(hit: InventoryHit) -> str:
    parts: List[str] = []
    if hit.box:
        parts.append(f"in {hit.box}")
    if hit.cover == "1":
        parts.append("cover-only (cover=1)")
    elif hit.cover == "0":
        parts.append("not cover-only (cover=0)")
    elif hit.cover:
        parts.append(f"cover={hit.cover}")

    if not parts:
        return "present (no box/cover info)"
    return ", ".join(parts)


def inventory_location_summary(hits: List[InventoryHit]) -> str:
    if not hits:
        return ""
    return " | ".join(interpret_inventory_hit(h) for h in hits)


def list_pdfs(folder: Path, recursive: bool) -> List[PdfEntry]:
    if not folder.exists():
        raise FileNotFoundError(f"PDF folder not found: {folder}")

    paths = list(folder.rglob("*.pdf")) if recursive else list(folder.glob("*.pdf"))

    seen = set()
    out: List[PdfEntry] = []
    for p in paths:
        base = p.stem
        key = _norm(base)
        if key in seen:
            continue
        seen.add(key)
        out.append(PdfEntry(base=base, path=p))
    return out


def get_pdf_pagecount(pdf_path: Path) -> Optional[int]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception:
            print("WARNING: Neither 'pypdf' nor 'PyPDF2' is installed; cannot read page counts.")
            return None

    try:
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)
    except Exception as e:
        print(f"WARNING: failed to read page count for {pdf_path}: {e}")
        return None


# =============================================================================
# Links JSON (pdf_base -> {url, item_id, ...})
# =============================================================================


def load_links_json(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("links json must be an object/dict")

    out: Dict[str, Dict[str, str]] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            out[k] = {str(kk): str(vv) for kk, vv in v.items()}
        else:
            out[k] = {"url": str(v)}
    return out


def save_links_json(path: Path, data: Dict[str, Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nSaved links JSON: {path}")


def _as_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def build_itemid_index_and_flags(links: Dict[str, Dict[str, str]]) -> Tuple[Dict[str, str], Dict[str, bool]]:
    idx: Dict[str, str] = {}
    tw: Dict[str, bool] = {}

    for pdf_base, rec in links.items():
        if not isinstance(rec, dict):
            continue

        item_id = (rec.get("item_id") or "").strip()
        if not item_id:
            item_id = extract_item_id_from_url(rec.get("url", ""))
        if not item_id:
            continue

        idx[item_id] = pdf_base
        tw[item_id] = _as_bool(rec.get("typewriter", False))

    return idx, tw


# =============================================================================
# Orders CSV
# =============================================================================


def read_orders_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"orders csv not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        rows = []
        for row in r:
            row.setdefault("item_id", "")
            row.setdefault("title", "")
            row.setdefault("item_url", "")
            rows.append(row)
    return rows


def order_item_id(row: Dict[str, str]) -> str:
    """Return the eBay item id, preferring the URL when available.

    Some exports have stale or duplicated item_id values while item_url is
    correct. The URL is the safer source because it identifies this line item.
    """
    item_id = (row.get("item_id") or "").strip()
    url_item_id = extract_item_id_from_url((row.get("item_url") or "").strip())
    return url_item_id or item_id


# =============================================================================
# Printed manual inventory CSV (optional) - kept for compatibility
# =============================================================================

@dataclass
class ManualEntry:
    title: str
    box: Optional[str]
    cover: bool


def load_manuals_from_csv_any(path: Path) -> Dict[str, ManualEntry]:
    out: Dict[str, ManualEntry] = {}
    if not path or not path.exists():
        return out

    first_line = ""
    with path.open("r", encoding="utf-8", newline="") as f:
        for line in f:
            if line.strip():
                first_line = line.strip()
                break
    if not first_line:
        return out

    lower = first_line.lower()
    has_header = ("title" in lower and "box" in lower and "cover" in lower)

    if has_header:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = (row.get("title") or "").strip()
                if not title:
                    continue
                box_raw = (row.get("box") or "").strip()
                box = box_raw or None
                cover_raw = (row.get("cover") or "").strip().lower()
                cover = cover_raw in ("1", "true", "yes", "y", "on")
                out[title] = ManualEntry(title=title, box=box, cover=cover)
        return out

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            if len(row) == 1:
                title = row[0].strip()
                box = None
                cover = False
            elif len(row) == 2:
                title = row[0].strip()
                box = row[1].strip() or None
                cover = False
            else:
                title = ",".join(row[:-2]).strip()
                box = row[-2].strip() or None
                cover_raw = (row[-1] or "").strip().lower()
                cover = cover_raw in ("1", "true", "yes", "y", "on")

            if not title:
                continue
            out[title] = ManualEntry(title=title, box=box, cover=cover)
    return out


# =============================================================================
# Matching helpers (normal mode only)
# =============================================================================

@dataclass
class Candidate:
    pdf: PdfEntry
    score: float


def top_candidates(title: str, pdfs: List[PdfEntry], k: int = 0) -> List[Candidate]:
    """Return candidates sorted by similarity.

    k <= 0 means return all candidates. This is useful for the interactive
    paged selector: show the best few first, then let the user continue down
    the ranked list if the correct PDF is not in the first screen.
    """
    scored = [Candidate(p, similarity_score(title, p.base)) for p in pdfs]
    scored.sort(key=lambda c: c.score, reverse=True)
    if k and k > 0:
        return scored[:k]
    return scored


def choose_match_interactive(
    order_title: str,
    cands: List[Candidate],
    min_score: float,
    min_margin: float,
) -> Optional[PdfEntry]:
    if not cands:
        print("\nNo candidates found.")
        return None

    best = cands[0]
    second = cands[1] if len(cands) > 1 else None
    margin = best.score - (second.score if second else 0.0)
    auto_ok = (best.score >= min_score) and ((second is None) or (margin >= min_margin))

    print("\nOrder title:")
    print(f"  {order_title}")

    if auto_ok:
        print("\nTop matches:")
        for i, c in enumerate(cands[:3], start=1):
            print(f"  {i}. {c.pdf.base}   ({c.score:.1f}%)")
        print(f"\nAuto-selected: {best.pdf.base}  (score={best.score:.1f}%, margin={margin:.1f})")
        return best.pdf

    shown = 0
    next_batch_size = 3

    while True:
        end = min(shown + next_batch_size, len(cands))

        if shown == 0:
            print("\nTop matches:")
        else:
            print("\nAdditional matches:")

        for i in range(shown, end):
            c = cands[i]
            print(f"  {i + 1}. {c.pdf.base}   ({c.score:.1f}%)")

        shown = end
        next_batch_size = 10

        if shown < len(cands):
            prompt = f"\nSelect match: 1-{shown}, type 0 to continue the list, or q to give up: "
        else:
            prompt = f"\nSelect match: 1-{shown}, or q to give up: "

        while True:
            s = input(prompt).strip().lower()

            if s == "q":
                return None

            if s == "0":
                if shown < len(cands):
                    break
                print("No more matches to show. Type a number to select, or q to give up.")
                continue

            if s.isdigit():
                idx = int(s) - 1
                if 0 <= idx < shown:
                    return cands[idx].pdf
                if 0 <= idx < len(cands):
                    print("That option has not been shown yet. Type 0 to continue the list.")
                else:
                    print("That option is not available.")
                continue

            if shown < len(cands):
                print(f"Invalid input. Use 1-{shown}, 0 to continue, or q.")
            else:
                print(f"Invalid input. Use 1-{shown}, or q.")


# =============================================================================
# myprint automation (with inventory-aware skip handling)
# =============================================================================


def find_pdf_matches_like_myprint(pdfs: List[PdfEntry], partial_name: str) -> List[PdfEntry]:
    q = (partial_name or "").strip().lower()
    if not q:
        return []
    matches = [p for p in pdfs if q in p.path.name.lower() and p.path.suffix.lower() == ".pdf"]
    return matches


def pick_index_for_exact_basename(matches: List[PdfEntry], chosen_basename: str) -> Optional[int]:
    target_pdf = (chosen_basename or "").strip()
    if not target_pdf:
        return None
    target_filename = target_pdf + ".pdf"
    for i, p in enumerate(matches, start=1):
        if p.path.name == target_filename:
            return i
    return None


@dataclass
class MyPrintResult:
    exit_code: int
    skipped_in_inventory: bool = False
    inventory_location: str = ""


def run_myprint_with_auto_inputs(myprint_path: str, python_exe: Optional[str], auto_inputs: List[str]) -> int:
    py = python_exe or sys.executable
    cmd = [py, myprint_path]
    payload = "\n".join(auto_inputs) + "\n"

    print("\n=== Running myprint.py with auto inputs ===")
    print("Command:", " ".join(f'\"{c}\"' if " " in c else c for c in cmd))
    print("Auto-inputs:", auto_inputs)

    completed = subprocess.run(cmd, input=payload, text=True)
    return completed.returncode


def myprint_auto_print_range(
    *,
    pdfs: List[PdfEntry],
    chosen_pdf: PdfEntry,
    printer: str,
    page_range: str,
    myprint_path: str,
    python_exe: Optional[str],
    inventory: Optional[ManualsInventory] = None,
    skip_collector: Optional[InventorySkipCollector] = None,
) -> MyPrintResult:
    hits: List[InventoryHit] = []
    if inventory is not None:
        hits = inventory.lookup_pdf(chosen_pdf)

    if hits:
        location = inventory_location_summary(hits)
        print(f"\n[inventory] SKIP printing '{chosen_pdf.base}' because it is already in manuals.csv")
        print(f"[inventory] Location/info: {location}")
        if skip_collector is not None:
            skip_collector.add(
                SkippedInventoryRecord(
                    pdf_base=chosen_pdf.base,
                    pdf_path=str(chosen_pdf.path),
                    location=location,
                )
            )
        return MyPrintResult(exit_code=0, skipped_in_inventory=True, inventory_location=location)

    auto_inputs: List[str] = []
    auto_inputs.append(printer)
    auto_inputs.append(chosen_pdf.base)

    matches = find_pdf_matches_like_myprint(pdfs, chosen_pdf.base)
    if len(matches) > 1:
        idx = pick_index_for_exact_basename(matches, chosen_pdf.base)
        if idx is None:
            idx = 1
            print("WARNING: multiple PDF matches; exact filename not found. Selecting #1 by default.")
        auto_inputs.append(str(idx))

    auto_inputs.append(page_range)
    rc = run_myprint_with_auto_inputs(myprint_path, python_exe, auto_inputs)
    return MyPrintResult(exit_code=rc)


# =============================================================================
# print360 mode (inventory-aware)
# =============================================================================

@dataclass
class Print360Resume:
    order_index: int
    pdf: PdfEntry
    total_pages: int
    next_page: int


@dataclass
class Print360ManualTask:
    order_index: int
    pdf: PdfEntry
    print_path: Path
    original_pages: int
    padded_pages: int
    page_range: str
    padded: bool
    effective_settings: Optional[List[str]] = None


def load_myprint_module(myprint_path: str) -> Any:
    path = Path(myprint_path)
    if not path.is_absolute():
        path = Path(__file__).with_name(myprint_path)
    spec = importlib.util.spec_from_file_location("manualforge_myprint", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load myprint module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_padded_pdf(original: Path, out_dir: Path) -> Path:
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
    except Exception:
        from PyPDF2 import PdfReader, PdfWriter  # type: ignore

    reader = PdfReader(str(original))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    last_page = reader.pages[-1]
    box = last_page.mediabox
    width = float(box.width)
    height = float(box.height)
    writer.add_blank_page(width=width, height=height)

    out_path = out_dir / f"{original.stem}__padded_even_pages.pdf"
    with out_path.open("wb") as f:
        writer.write(f)
    return out_path


def resolve_printer_name(myprint_module: Any, printer: str) -> Optional[str]:
    printers = getattr(myprint_module, "PRINTERS", {})
    return printers.get(printer, printer)


def load_print_settings_for_myprint(myprint_module: Any) -> Dict[str, List[str]]:
    db_path = Path(myprint_module.__file__).with_name("print_settings.json")
    with db_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return {k.lower(): v for k, v in raw.items()}


def plan_print360_manual_batch(
    *,
    orders: List[Dict[str, str]],
    start_index: int,
    start_resume: Optional[Print360Resume],
    itemid_index: Dict[str, str],
    pdf_by_normbase: Dict[str, PdfEntry],
    page_limit: int,
    temp_dir: Path,
    padding_executor: ThreadPoolExecutor,
    padding_futures: Dict[Path, Any],
    queue_padding: bool = True,
    inventory: Optional[ManualsInventory] = None,
    skip_collector: Optional[InventorySkipCollector] = None,
) -> Tuple[int, int, Optional[Print360Resume], List[Print360ManualTask]]:
    pages_planned = 0
    idx = start_index
    resume: Optional[Print360Resume] = None
    tasks: List[Print360ManualTask] = []

    while idx < len(orders) and pages_planned < page_limit:
        row = orders[idx]
        title = (row.get("title") or "").strip()
        item_id = order_item_id(row)
        url = (row.get("item_url") or "").strip()

        if not title or not url:
            idx += 1
            start_resume = None
            continue

        if not item_id or item_id not in itemid_index:
            print(f"\n[print360manual2sided] SKIP (not in links DB): item_id={item_id!r}  title={title}")
            idx += 1
            start_resume = None
            continue

        pdf_base = itemid_index[item_id]
        pdf = pdf_by_normbase.get(_norm(pdf_base))
        if not pdf:
            print(f"\n[print360manual2sided] SKIP (PDF not found): item_id={item_id}  pdf_base={pdf_base!r}")
            idx += 1
            start_resume = None
            continue

        hits = inventory.lookup_pdf(pdf) if inventory is not None else []
        if hits:
            location = inventory_location_summary(hits)
            print(f"\n[inventory] SKIP printing '{pdf.base}' because it is already in manuals.csv")
            print(f"[inventory] Location/info: {location}")
            if skip_collector is not None:
                skip_collector.add(SkippedInventoryRecord(pdf_base=pdf.base, pdf_path=str(pdf.path), location=location))
            idx += 1
            start_resume = None
            continue

        total_pages = get_pdf_pagecount(pdf.path)
        if not total_pages or total_pages <= 0:
            print(f"\n[print360manual2sided] SKIP (cannot read page count): {pdf.path}")
            idx += 1
            start_resume = None
            continue

        padded_pages = total_pages + (total_pages % 2)
        if queue_padding and padded_pages != total_pages and pdf.path not in padding_futures:
            print(f"[print360manual2sided] Padding queued in background: {pdf.base} ({total_pages} -> {padded_pages} pages)")
            padding_futures[pdf.path] = padding_executor.submit(create_padded_pdf, pdf.path, temp_dir)

        start_page = 1
        if start_resume is not None and start_resume.order_index == idx:
            start_page = max(1, min(start_resume.next_page, padded_pages + 1))

        if start_page > padded_pages:
            idx += 1
            start_resume = None
            continue

        remaining_capacity = page_limit - pages_planned
        if remaining_capacity <= 0:
            break

        remaining_pages = padded_pages - start_page + 1
        if remaining_pages <= remaining_capacity:
            end_page = padded_pages
            next_idx = idx + 1
            next_resume = None
        else:
            end_page = start_page + remaining_capacity - 1
            if end_page % 2 == 1:
                end_page -= 1
            if end_page < start_page:
                break
            next_idx = idx
            next_resume = Print360Resume(order_index=idx, pdf=pdf, total_pages=padded_pages, next_page=end_page + 1)

        pr = f"{start_page}-{end_page}"
        planned_now = end_page - start_page + 1
        print(f"\n[print360manual2sided] PLAN: {pdf.base}  pages={pr}  (original={total_pages}, padded={padded_pages})")
        tasks.append(
            Print360ManualTask(
                order_index=idx,
                pdf=pdf,
                print_path=pdf.path,
                original_pages=total_pages,
                padded_pages=padded_pages,
                page_range=pr,
                padded=(padded_pages != total_pages),
            )
        )
        pages_planned += planned_now

        if next_resume is not None:
            resume = next_resume
            break

        idx = next_idx
        start_resume = None

    return idx, pages_planned, resume, tasks


def plan_print720_manual_batch(
    *,
    orders: List[Dict[str, str]],
    start_index: int,
    itemid_index: Dict[str, str],
    pdf_by_normbase: Dict[str, PdfEntry],
    page_limit_each: int,
    temp_dir: Path,
    padding_executor: ThreadPoolExecutor,
    padding_futures: Dict[Path, Any],
    queue_padding: bool = True,
    inventory: Optional[ManualsInventory] = None,
    skip_collector: Optional[InventorySkipCollector] = None,
) -> Tuple[int, List[Print360ManualTask]]:
    selected: List[Print360ManualTask] = []
    selected_pages = 0
    total_limit = page_limit_each * 2
    idx = start_index

    while idx < len(orders):
        row = orders[idx]
        title = (row.get("title") or "").strip()
        item_id = order_item_id(row)
        url = (row.get("item_url") or "").strip()

        if not title or not url:
            idx += 1
            continue

        if not item_id or item_id not in itemid_index:
            print(f"\n[print720manual2sided] SKIP (not in links DB): item_id={item_id!r}  title={title}")
            idx += 1
            continue

        pdf_base = itemid_index[item_id]
        pdf = pdf_by_normbase.get(_norm(pdf_base))
        if not pdf:
            print(f"\n[print720manual2sided] SKIP (PDF not found): item_id={item_id}  pdf_base={pdf_base!r}")
            idx += 1
            continue

        hits = inventory.lookup_pdf(pdf) if inventory is not None else []
        if hits:
            location = inventory_location_summary(hits)
            print(f"\n[inventory] SKIP printing '{pdf.base}' because it is already in manuals.csv")
            print(f"[inventory] Location/info: {location}")
            if skip_collector is not None:
                skip_collector.add(SkippedInventoryRecord(pdf_base=pdf.base, pdf_path=str(pdf.path), location=location))
            idx += 1
            continue

        total_pages = get_pdf_pagecount(pdf.path)
        if not total_pages or total_pages <= 0:
            print(f"\n[print720manual2sided] SKIP (cannot read page count): {pdf.path}")
            idx += 1
            continue

        padded_pages = total_pages + (total_pages % 2)
        if selected and selected_pages + padded_pages > total_limit:
            break

        if queue_padding and padded_pages != total_pages and pdf.path not in padding_futures:
            print(f"[print720manual2sided] Padding queued in background: {pdf.base} ({total_pages} -> {padded_pages} pages)")
            padding_futures[pdf.path] = padding_executor.submit(create_padded_pdf, pdf.path, temp_dir)

        selected.append(
            Print360ManualTask(
                order_index=idx,
                pdf=pdf,
                print_path=pdf.path,
                original_pages=total_pages,
                padded_pages=padded_pages,
                page_range=f"1-{padded_pages}",
                padded=(padded_pages != total_pages),
            )
        )
        selected_pages += padded_pages
        idx += 1

        if selected_pages >= total_limit:
            break

    return idx, selected


def wait_for_padded_paths(tasks: List[Print360ManualTask], padding_futures: Dict[Path, Any], label: str) -> None:
    for task in tasks:
        if not task.padded:
            continue
        fut = padding_futures.get(task.pdf.path)
        if fut is None:
            continue
        print(f"[{label}] Waiting for padded PDF: {task.pdf.base}")
        task.print_path = fut.result()


def manual_task_page_count(task: Print360ManualTask) -> int:
    start_s, end_s = task.page_range.split("-", 1)
    return max(0, int(end_s) - int(start_s) + 1)


def summarize_manual_tasks(label: str, tasks: List[Print360ManualTask], printer_name: Optional[str] = None) -> None:
    total_pages = sum(manual_task_page_count(t) for t in tasks)
    first_pass_pages = sum((manual_task_page_count(t) + 1) // 2 for t in tasks)
    heading = f"\n[{label}] Summary"
    if printer_name:
        heading += f" for {printer_name}"
    print(heading + ":")
    print(f"  Manuals: {len(tasks)}")
    print(f"  Total document pages to print: {total_pages}")
    print(f"  First-pass even/simplex pages: {first_pass_pages}")
    for task in tasks:
        start_s, end_s = task.page_range.split("-", 1)
        includes_padding = task.padded and int(start_s) <= task.padded_pages <= int(end_s)
        pad_note = " + blank padding page" if includes_padding else ""
        print(f"  - {task.pdf.base}: {task.page_range} ({manual_task_page_count(task)} pages{pad_note})")


def partition_tasks_evenly(tasks: List[Print360ManualTask]) -> Tuple[List[Print360ManualTask], List[Print360ManualTask]]:
    total = sum(t.padded_pages for t in tasks)
    best_sum = 0
    best_mask = 0
    sums = {0: 0}
    for i, task in enumerate(tasks):
        page_count = task.padded_pages
        additions = {s + page_count: mask | (1 << i) for s, mask in sums.items()}
        sums.update(additions)

    for s, mask in sums.items():
        if abs(total - 2 * s) < abs(total - 2 * best_sum) or (
            abs(total - 2 * s) == abs(total - 2 * best_sum) and s > best_sum
        ):
            best_sum = s
            best_mask = mask

    p1: List[Print360ManualTask] = []
    p2: List[Print360ManualTask] = []
    for i, task in enumerate(tasks):
        if best_mask & (1 << i):
            p1.append(task)
        else:
            p2.append(task)
    return p1, p2


def make_padding_blank_setting(myprint_module: Any, base_setting: str, padded_page: int) -> str:
    parts = myprint_module.make_simplex_setting(base_setting).split(",")
    page_idx = myprint_module.extract_page_selector_index(parts)
    if page_idx is None:
        insert_at = 1 if parts else 0
        parts.insert(insert_at, str(padded_page))
    else:
        parts[page_idx] = str(padded_page)
    return ",".join(parts)


def pages_from_setting(myprint_module: Any, setting: str, max_page: int) -> List[int]:
    parts = [p.strip() for p in setting.split(",")]
    pages: List[int] = []
    for idx in myprint_module.extract_page_selector_indices(parts):
        parsed = myprint_module.parse_page_token(parts[idx])
        if parsed[0] == "single":
            p = parsed[1]
            if 1 <= p <= max_page:
                pages.append(p)
        elif parsed[0] == "range":
            a, b = parsed[1], parsed[2]
            pages.extend(range(max(1, a), min(max_page, b) + 1))
    return pages


def make_batch_pair_setting(myprint_module: Any, setting: str) -> str:
    parts = []
    for part in [p.strip() for p in setting.split(",")]:
        low = part.lower()
        if low == "simplex":
            parts.append("duplex")
        elif low == "simplexshort":
            parts.append("duplexshort")
        else:
            parts.append(part)
    if not myprint_module.is_duplex_setting(",".join(parts)):
        parts.append("duplex")
    return ",".join(parts)


def replace_setting_page_tokens(myprint_module: Any, setting: str, replacements: Dict[int, str]) -> str:
    parts = [p.strip() for p in setting.split(",")]
    page_indices = myprint_module.extract_page_selector_indices(parts)
    for idx in page_indices:
        if idx in replacements:
            parts[idx] = replacements[idx]
    return ",".join(parts)


def extend_setting_to_page(myprint_module: Any, setting: str, end_page: int) -> str:
    parts = [p.strip() for p in setting.split(",")]
    page_indices = myprint_module.extract_page_selector_indices(parts)
    if not page_indices:
        parts.insert(1 if parts else 0, str(end_page))
        return ",".join(parts)

    idx = page_indices[-1]
    parsed = myprint_module.parse_page_token(parts[idx])
    if parsed[0] == "range":
        parts[idx] = f"{parsed[1]}-{end_page}"
    elif parsed[0] == "single":
        parts[idx] = f"{parsed[1]}-{end_page}"
    return ",".join(parts)


def prepare_task_for_batch_manual_2sided(
    *,
    myprint_module: Any,
    print_settings: Dict[str, List[str]],
    task: Print360ManualTask,
    temp_dir: Path,
) -> None:
    original_start_s, original_end_s = task.page_range.split("-", 1)
    original_start = int(original_start_s)
    original_end = min(int(original_end_s), task.original_pages)

    default_setting = f"color,1-{task.original_pages},duplex,fit,paper=letter"
    source_settings = print_settings.get(task.pdf.base.lower(), [default_setting])
    clipped_settings: List[str] = []
    for setting in source_settings:
        clipped = myprint_module.clip_setting_to_custom_range(setting, original_start, original_end)
        if clipped is not None:
            clipped_settings.append(clipped)

    simplex_pages = set()
    for setting in clipped_settings:
        if not (myprint_module.is_duplex_setting(setting) and myprint_module.setting_needs_manual_2sided(setting)):
            simplex_pages.update(pages_from_setting(myprint_module, setting, original_end))
    short_edge = myprint_module.has_short_edge_setting(clipped_settings)

    mapping: Dict[int, int] = {}
    new_page_no = 1
    for old_page in range(original_start, original_end + 1):
        mapping[old_page] = new_page_no
        new_page_no += 1
        if old_page in simplex_pages:
            new_page_no += 1

    new_total = new_page_no - 1
    needs_final_blank = new_total % 2 == 1
    if needs_final_blank:
        new_total += 1

    needs_temp_pdf = (
        original_start != 1
        or original_end != task.original_pages
        or bool(simplex_pages)
        or needs_final_blank
        or short_edge
    )

    if needs_temp_pdf:
        try:
            from pypdf import PdfReader, PdfWriter  # type: ignore
        except Exception:
            from PyPDF2 import PdfReader, PdfWriter  # type: ignore

        reader = PdfReader(str(task.pdf.path))
        writer = PdfWriter()
        output_page_no = 1
        last_selected_page = None
        for page_index in range(original_start, original_end + 1):
            page = reader.pages[page_index - 1]
            last_selected_page = page
            if short_edge and output_page_no % 2 == 1:
                page = myprint_module.rotate_page_180(page)
            writer.add_page(page)
            output_page_no += 1
            if page_index in simplex_pages:
                box = page.mediabox
                writer.add_blank_page(width=float(box.width), height=float(box.height))
                output_page_no += 1
        if needs_final_blank:
            blank_source = last_selected_page or reader.pages[original_end - 1]
            box = blank_source.mediabox
            writer.add_blank_page(width=float(box.width), height=float(box.height))

        safe_range = task.page_range.replace("-", "_")
        out_path = temp_dir / f"{task.order_index}_{task.pdf.path.stem}_{safe_range}__batch_manual2sided.pdf"
        with out_path.open("wb") as f:
            writer.write(f)
        task.print_path = out_path

    remapped_settings: List[str] = []
    for setting in clipped_settings:
        parts = [p.strip() for p in setting.split(",")]
        replacements: Dict[int, str] = {}
        page_indices = myprint_module.extract_page_selector_indices(parts)
        for idx in page_indices:
            parsed = myprint_module.parse_page_token(parts[idx])
            if parsed[0] == "single":
                p = parsed[1]
                start = mapping[p]
                replacements[idx] = f"{start}-{start + 1}" if p in simplex_pages else str(start)
            elif parsed[0] == "range":
                a, b = parsed[1], parsed[2]
                range_pages = list(range(a, b + 1))
                mapped_start = mapping[a]
                mapped_end = mapping[b] + (1 if any(p in simplex_pages for p in range_pages) else 0)
                replacements[idx] = f"{mapped_start}-{mapped_end}"

        remapped = replace_setting_page_tokens(myprint_module, setting, replacements)
        if any(p in simplex_pages for p in pages_from_setting(myprint_module, setting, original_end)):
            remapped = make_batch_pair_setting(myprint_module, remapped)
        remapped_settings.append(remapped)

    if needs_final_blank and remapped_settings:
        remapped_settings[-1] = make_batch_pair_setting(
            myprint_module,
            extend_setting_to_page(myprint_module, remapped_settings[-1], new_total),
        )

    task.padded_pages = new_total
    task.page_range = f"1-{new_total}"
    task.padded = needs_temp_pdf
    task.effective_settings = remapped_settings


def prepare_tasks_for_batch_manual_2sided(
    *,
    myprint_module: Any,
    print_settings: Dict[str, List[str]],
    tasks: List[Print360ManualTask],
    temp_dir: Path,
) -> None:
    for task in tasks:
        prepare_task_for_batch_manual_2sided(
            myprint_module=myprint_module,
            print_settings=print_settings,
            task=task,
            temp_dir=temp_dir,
        )


def settings_for_print360_manual_task(myprint_module: Any, print_settings: Dict[str, List[str]], task: Print360ManualTask) -> List[str]:
    if task.effective_settings is not None:
        return list(task.effective_settings)

    default_setting = f"color,1-{task.padded_pages},duplex,fit,paper=letter"
    settings = print_settings.get(task.pdf.base.lower(), [default_setting])
    start_s, end_s = task.page_range.split("-", 1)
    start_page, end_page = int(start_s), int(end_s)
    effective: List[str] = []
    for setting in settings:
        clipped = myprint_module.clip_setting_to_custom_range(setting, start_page, min(end_page, task.original_pages))
        if clipped is not None:
            effective.append(clipped)

    if task.padded and start_page <= task.padded_pages <= end_page:
        base_setting = effective[-1] if effective else settings[-1]
        effective.append(make_padding_blank_setting(myprint_module, base_setting, task.padded_pages))

    return effective


def split_manual_2sided_settings(myprint_module: Any, settings: List[str]) -> Tuple[List[str], List[str], List[str]]:
    first_pass: List[str] = []
    second_pass: List[str] = []
    simplex_only: List[str] = []
    for setting in settings:
        if myprint_module.is_duplex_setting(setting) and myprint_module.setting_needs_manual_2sided(setting):
            first_pass.append(myprint_module.make_manual_2sided_setting(setting, "even"))
            second_pass.append(myprint_module.make_manual_2sided_setting(setting, "odd"))
        else:
            pair_setting = myprint_module.make_batch_pair_setting(setting)
            first_pass.append(myprint_module.make_manual_2sided_setting(pair_setting, "even"))
            second_pass.append(myprint_module.make_manual_2sided_setting(pair_setting, "odd"))
    return first_pass, second_pass, simplex_only


def is_padding_blank_setting(myprint_module: Any, task: Print360ManualTask, setting: str) -> bool:
    parts = [p.strip() for p in setting.split(",")]
    page_idx = myprint_module.extract_page_selector_index(parts)
    if page_idx is None:
        return False
    parsed = myprint_module.parse_page_token(parts[page_idx])
    return parsed[0] == "single" and parsed[1] == task.padded_pages and task.padded_pages > task.original_pages


def execute_print360_manual_first_pass_batch(
    *,
    myprint_module: Any,
    print_settings: Dict[str, List[str]],
    tasks: List[Print360ManualTask],
    printer_name: str,
    batch_no: int,
    label: str = "print360manual2sided",
) -> Tuple[List[Tuple[Print360ManualTask, List[str]]], List[str]]:
    second_pass_jobs: List[Tuple[Print360ManualTask, List[str]]] = []
    simplex_pages: List[str] = []

    print(f"\n[{label}] FIRST PASS batch {batch_no} on {printer_name}")
    for task in tasks:
        settings = settings_for_print360_manual_task(myprint_module, print_settings, task)
        first_pass, second_pass, simplex_only = split_manual_2sided_settings(myprint_module, settings)
        warning_simplex = [s for s in simplex_only if not is_padding_blank_setting(myprint_module, task, s)]
        if warning_simplex:
            simplex_pages.append(f"{task.pdf.base}: " + ", ".join(myprint_module.describe_setting_pages(s) for s in warning_simplex))
        if second_pass:
            second_pass_jobs.append((task, second_pass))
        for setting in first_pass:
            myprint_module.print_one_setting(
                str(task.print_path),
                setting,
                printer_name,
                batch_size=70,
                small_range_no_wait_threshold=10,
                delay_between_batches=60,
            )

    return second_pass_jobs, simplex_pages


def execute_print360_manual_second_pass(
    *,
    myprint_module: Any,
    second_pass_jobs: List[Tuple[Print360ManualTask, List[str]]],
    simplex_pages: List[str],
    quiet_printer_name: str,
    second_pass_only: bool = False,
) -> None:
    if not second_pass_jobs:
        print("\n[print360manual2sided] No second pass is needed.")
        return

    if second_pass_only:
        print("\n[print360manual2sided] Second-pass-only mode.")
        print("Load the paper from the completed even-page first pass.")
    else:
        print("\n[print360manual2sided] First pass complete.")
        print("Put the paper back in the tray: even pages face up, top of the paper down.")
    if simplex_pages:
        print("Do NOT put back these real one-sided pages:")
        for item in simplex_pages:
            print(f"  {item}")

    print(f"\n[print360manual2sided] Second pass commands that will be used on {quiet_printer_name}:")
    for task, settings in second_pass_jobs:
        myprint_module.display_sumatra_commands_for_settings(str(task.print_path), settings, quiet_printer_name, batch_size=70)

    input(f"Press Enter when {quiet_printer_name} is loaded and ready for the odd-page second pass...")
    if not myprint_module.countdown_allow_cancel(15):
        return

    print(f"\n[print360manual2sided] SECOND PASS on {quiet_printer_name}")
    for task, settings in second_pass_jobs:
        for setting in settings:
            myprint_module.print_one_setting(
                str(task.print_path),
                setting,
                quiet_printer_name,
                batch_size=70,
                small_range_no_wait_threshold=10,
                delay_between_batches=90,
            )


def execute_print720_manual_first_pass_pair(
    *,
    myprint_module: Any,
    print_settings: Dict[str, List[str]],
    tasks_p1: List[Print360ManualTask],
    tasks_p2: List[Print360ManualTask],
    printer1_name: str,
    printer2_name: str,
    batch_no: int,
) -> Tuple[List[Tuple[str, Print360ManualTask, List[str]]], List[str]]:
    second_pass_jobs: List[Tuple[str, Print360ManualTask, List[str]]] = []
    simplex_pages: List[str] = []

    def run_one(printer_name: str, tasks: List[Print360ManualTask], tag: str):
        jobs, simplex = execute_print360_manual_first_pass_batch(
            myprint_module=myprint_module,
            print_settings=print_settings,
            tasks=tasks,
            printer_name=printer_name,
            batch_no=batch_no,
            label="print720manual2sided",
        )
        return tag, jobs, simplex

    if tasks_p1 and tasks_p2:
        print(f"\n[print720manual2sided] FIRST PASS batch {batch_no} concerns both printers:")
        print(f"  Printer 1: {printer1_name}")
        print(f"  Printer 2: {printer2_name}")
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [
                ex.submit(run_one, printer1_name, tasks_p1, "p1"),
                ex.submit(run_one, printer2_name, tasks_p2, "p2"),
            ]
            for fut in as_completed(futs):
                tag, jobs, simplex = fut.result()
                quiet_tag = "p1" if tag == "p1" else "p2"
                for task, settings in jobs:
                    second_pass_jobs.append((quiet_tag, task, settings))
                simplex_pages.extend(simplex)
        return second_pass_jobs, simplex_pages

    if tasks_p1:
        print(f"\n[print720manual2sided] FIRST PASS batch {batch_no} concerns printer: {printer1_name}")
        jobs, simplex = execute_print360_manual_first_pass_batch(
            myprint_module=myprint_module,
            print_settings=print_settings,
            tasks=tasks_p1,
            printer_name=printer1_name,
            batch_no=batch_no,
            label="print720manual2sided",
        )
        second_pass_jobs.extend(("p1", task, settings) for task, settings in jobs)
        simplex_pages.extend(simplex)
        return second_pass_jobs, simplex_pages

    if tasks_p2:
        print(f"\n[print720manual2sided] FIRST PASS batch {batch_no} concerns printer: {printer2_name}")
        jobs, simplex = execute_print360_manual_first_pass_batch(
            myprint_module=myprint_module,
            print_settings=print_settings,
            tasks=tasks_p2,
            printer_name=printer2_name,
            batch_no=batch_no,
            label="print720manual2sided",
        )
        second_pass_jobs.extend(("p2", task, settings) for task, settings in jobs)
        simplex_pages.extend(simplex)
    return second_pass_jobs, simplex_pages


def collect_print720_manual_second_pass_jobs(
    *,
    myprint_module: Any,
    print_settings: Dict[str, List[str]],
    tasks_p1: List[Print360ManualTask],
    tasks_p2: List[Print360ManualTask],
) -> Tuple[List[Tuple[str, Print360ManualTask, List[str]]], List[str]]:
    second_pass_jobs: List[Tuple[str, Print360ManualTask, List[str]]] = []
    simplex_pages: List[str] = []

    jobs1, simplex1 = collect_print360_manual_second_pass_jobs(
        myprint_module=myprint_module,
        print_settings=print_settings,
        tasks=tasks_p1,
    )
    jobs2, simplex2 = collect_print360_manual_second_pass_jobs(
        myprint_module=myprint_module,
        print_settings=print_settings,
        tasks=tasks_p2,
    )
    second_pass_jobs.extend(("p1", task, settings) for task, settings in jobs1)
    second_pass_jobs.extend(("p2", task, settings) for task, settings in jobs2)
    simplex_pages.extend(simplex1)
    simplex_pages.extend(simplex2)
    return second_pass_jobs, simplex_pages


def collect_print360_manual_second_pass_jobs(
    *,
    myprint_module: Any,
    print_settings: Dict[str, List[str]],
    tasks: List[Print360ManualTask],
) -> Tuple[List[Tuple[Print360ManualTask, List[str]]], List[str]]:
    second_pass_jobs: List[Tuple[Print360ManualTask, List[str]]] = []
    simplex_pages: List[str] = []

    for task in tasks:
        settings = settings_for_print360_manual_task(myprint_module, print_settings, task)
        _, second_pass, simplex_only = split_manual_2sided_settings(myprint_module, settings)
        warning_simplex = [s for s in simplex_only if not is_padding_blank_setting(myprint_module, task, s)]
        if warning_simplex:
            simplex_pages.append(f"{task.pdf.base}: " + ", ".join(myprint_module.describe_setting_pages(s) for s in warning_simplex))
        if second_pass:
            second_pass_jobs.append((task, second_pass))

    return second_pass_jobs, simplex_pages


def print360_jobs_have_short_edge(myprint_module: Any, jobs: List[Tuple[Print360ManualTask, List[str]]]) -> bool:
    for task, settings in jobs:
        if myprint_module.has_short_edge_setting(settings):
            return True
        if task.effective_settings is not None and myprint_module.has_short_edge_setting(task.effective_settings):
            return True
    return False


def print720_jobs_have_short_edge(myprint_module: Any, jobs: List[Tuple[str, Print360ManualTask, List[str]]]) -> bool:
    for _, task, settings in jobs:
        if myprint_module.has_short_edge_setting(settings):
            return True
        if task.effective_settings is not None and myprint_module.has_short_edge_setting(task.effective_settings):
            return True
    return False


def execute_print720_manual_second_pass(
    *,
    myprint_module: Any,
    second_pass_jobs: List[Tuple[str, Print360ManualTask, List[str]]],
    simplex_pages: List[str],
    quiet_printer1_name: str,
    quiet_printer2_name: str,
    second_pass_only: bool = False,
) -> None:
    if not second_pass_jobs:
        print("\n[print720manual2sided] No second pass is needed.")
        return

    has_p1 = any(tag == "p1" for tag, _, _ in second_pass_jobs)
    has_p2 = any(tag == "p2" for tag, _, _ in second_pass_jobs)
    if has_p1 and has_p2:
        if second_pass_only:
            print("\n[print720manual2sided] Second-pass-only mode for both printers.")
            print(f"Load paper from the completed even-page first pass into: {quiet_printer1_name} and {quiet_printer2_name}.")
        else:
            print("\n[print720manual2sided] First pass complete for both printers.")
            print(f"Reload paper for both second-pass printers: {quiet_printer1_name} and {quiet_printer2_name}.")
    elif has_p1:
        if second_pass_only:
            print(f"\n[print720manual2sided] Second-pass-only mode for printer: {quiet_printer1_name}")
            print(f"Load paper from the completed even-page first pass into: {quiet_printer1_name}.")
        else:
            print(f"\n[print720manual2sided] First pass complete for printer: {quiet_printer1_name}")
            print(f"Reload paper for second-pass printer: {quiet_printer1_name}.")
    else:
        if second_pass_only:
            print(f"\n[print720manual2sided] Second-pass-only mode for printer: {quiet_printer2_name}")
            print(f"Load paper from the completed even-page first pass into: {quiet_printer2_name}.")
        else:
            print(f"\n[print720manual2sided] First pass complete for printer: {quiet_printer2_name}")
            print(f"Reload paper for second-pass printer: {quiet_printer2_name}.")
    if not second_pass_only:
        print("Put the paper back in the tray: even pages face up, top of the paper down.")

    if simplex_pages:
        print("Do NOT put back these real one-sided pages:")
        for item in simplex_pages:
            print(f"  {item}")

    print("\n[print720manual2sided] Second pass commands that will be used:")
    for tag, task, settings in second_pass_jobs:
        quiet_name = quiet_printer1_name if tag == "p1" else quiet_printer2_name
        print(f"\nFor printer: {quiet_name}")
        myprint_module.display_sumatra_commands_for_settings(str(task.print_path), settings, quiet_name, batch_size=70)

    if has_p1 and has_p2:
        ready_target = f"{quiet_printer1_name} and {quiet_printer2_name} are loaded"
    elif has_p1:
        ready_target = f"{quiet_printer1_name} is loaded"
    else:
        ready_target = f"{quiet_printer2_name} is loaded"
    input(f"Press Enter when {ready_target} and ready for the odd-page second pass...")
    if not myprint_module.countdown_allow_cancel(15):
        return

    def run_jobs(tag: str, printer_name: str):
        for job_tag, task, settings in second_pass_jobs:
            if job_tag != tag:
                continue
            for setting in settings:
                myprint_module.print_one_setting(
                    str(task.print_path),
                    setting,
                    printer_name,
                    batch_size=70,
                    small_range_no_wait_threshold=10,
                    delay_between_batches=90,
                )

    if has_p1 and has_p2:
        print(f"\n[print720manual2sided] SECOND PASS concerns both printers: {quiet_printer1_name} and {quiet_printer2_name}")
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(run_jobs, "p1", quiet_printer1_name), ex.submit(run_jobs, "p2", quiet_printer2_name)]
            for fut in as_completed(futs):
                fut.result()
    elif has_p1:
        print(f"\n[print720manual2sided] SECOND PASS concerns printer: {quiet_printer1_name}")
        run_jobs("p1", quiet_printer1_name)
    else:
        print(f"\n[print720manual2sided] SECOND PASS concerns printer: {quiet_printer2_name}")
        run_jobs("p2", quiet_printer2_name)


def run_print360_batch(
    *,
    orders: List[Dict[str, str]],
    start_index: int,
    start_resume: Optional[Print360Resume] = None,
    itemid_index: Dict[str, str],
    pdf_by_normbase: Dict[str, PdfEntry],
    pdfs: List[PdfEntry],
    printer: str,
    myprint_path: str,
    python_exe: Optional[str],
    page_limit: int = 360,
    inventory: Optional[ManualsInventory] = None,
    skip_collector: Optional[InventorySkipCollector] = None,
) -> Tuple[int, int, Optional[Print360Resume]]:
    """Print one print360 batch and return the next position.

    The batch stops when approximately ``page_limit`` pages have been printed.
    If a manual is split across batches, ``resume`` points to the same order and
    the next page to print. The caller can pass that resume back into this
    function to continue the next 360-page batch without switching to normal
    interactive mode.
    """
    pages_printed = 0
    idx = start_index
    resume: Optional[Print360Resume] = None

    while idx < len(orders) and pages_printed < page_limit:
        row = orders[idx]
        title = (row.get("title") or "").strip()
        item_id = order_item_id(row)
        url = (row.get("item_url") or "").strip()

        if not title or not url:
            idx += 1
            start_resume = None
            continue

        if not item_id or item_id not in itemid_index:
            print(f"\n[print360] SKIP (not in links DB): item_id={item_id!r}  title={title}")
            idx += 1
            start_resume = None
            continue

        pdf_base = itemid_index[item_id]
        pdf = pdf_by_normbase.get(_norm(pdf_base))
        if not pdf:
            print(f"\n[print360] SKIP (PDF not found): item_id={item_id}  pdf_base={pdf_base!r}")
            idx += 1
            start_resume = None
            continue

        total_pages = get_pdf_pagecount(pdf.path)
        if not total_pages or total_pages <= 0:
            print(f"\n[print360] SKIP (cannot read page count): {pdf.path}")
            idx += 1
            start_resume = None
            continue

        start_page = 1
        if start_resume is not None and start_resume.order_index == idx:
            start_page = max(1, min(start_resume.next_page, total_pages + 1))

        if start_page > total_pages:
            idx += 1
            start_resume = None
            continue

        remaining_capacity = page_limit - pages_printed
        if remaining_capacity <= 0:
            break

        remaining_pages = total_pages - start_page + 1

        if remaining_pages <= remaining_capacity:
            end_page = total_pages
            pr = f"{start_page}-{end_page}"
            print(f"\n[print360] PRINT: {pdf.base}  pages={pr}  (total={total_pages})")
            result = myprint_auto_print_range(
                pdfs=pdfs,
                chosen_pdf=pdf,
                printer=printer,
                page_range=pr,
                myprint_path=myprint_path,
                python_exe=python_exe,
                inventory=inventory,
                skip_collector=skip_collector,
            )
            if result.exit_code != 0:
                print(f"[print360] WARNING: myprint exit code {result.exit_code} (continuing)")
            elif not result.skipped_in_inventory:
                pages_printed += remaining_pages
            idx += 1
            start_resume = None
            continue

        end_page = start_page + remaining_capacity - 1
        if end_page % 2 == 1:
            end_page += 1

        if end_page > total_pages:
            end_page = total_pages
            if end_page % 2 == 1 and end_page - 1 >= start_page:
                end_page -= 1

        pr = f"{start_page}-{end_page}"
        printed_now = (end_page - start_page + 1) if end_page >= start_page else 0

        print(f"\n[print360] PRINT PARTIAL (even-ended): {pdf.base}  pages={pr}  (total={total_pages})")
        result = myprint_auto_print_range(
            pdfs=pdfs,
            chosen_pdf=pdf,
            printer=printer,
            page_range=pr,
            myprint_path=myprint_path,
            python_exe=python_exe,
            inventory=inventory,
            skip_collector=skip_collector,
        )
        if result.exit_code != 0:
            print(f"[print360] WARNING: myprint exit code {result.exit_code} (continuing)")
            resume = Print360Resume(order_index=idx, pdf=pdf, total_pages=total_pages, next_page=start_page)
            break
        elif not result.skipped_in_inventory:
            pages_printed += printed_now
            if end_page < total_pages:
                resume = Print360Resume(order_index=idx, pdf=pdf, total_pages=total_pages, next_page=end_page + 1)
                break

        idx += 1
        start_resume = None

    return idx, pages_printed, resume

def finish_resume_manual(
    *,
    resume: Print360Resume,
    printer: str,
    pdfs: List[PdfEntry],
    myprint_path: str,
    python_exe: Optional[str],
    inventory: Optional[ManualsInventory] = None,
    skip_collector: Optional[InventorySkipCollector] = None,
) -> None:
    if resume.next_page > resume.total_pages:
        return
    pr = f"{resume.next_page}-{resume.total_pages}"
    print(f"\n[resume] FINISH MANUAL: {resume.pdf.base}  pages={pr}  (total={resume.total_pages})")
    result = myprint_auto_print_range(
        pdfs=pdfs,
        chosen_pdf=resume.pdf,
        printer=printer,
        page_range=pr,
        myprint_path=myprint_path,
        python_exe=python_exe,
        inventory=inventory,
        skip_collector=skip_collector,
    )
    if result.exit_code != 0:
        print(f"[resume] WARNING: myprint exit code {result.exit_code} (continuing)")


# =============================================================================
# print720 mode (typewriter-aware, dry run split + concurrent execution + persistent state)
# =============================================================================

@dataclass
class EligibleDoc:
    order_index: int
    pdf: PdfEntry
    total_pages: int


@dataclass
class PrintTask:
    pdf: PdfEntry
    start_page: int
    end_page: int

    @property
    def page_range(self) -> str:
        return f"{self.start_page}-{self.end_page}"

    @property
    def pages(self) -> int:
        return max(0, self.end_page - self.start_page + 1)


@dataclass
class PrintStreamPos:
    doc_list_index: int
    next_page: int


@dataclass
class Print720Plan:
    tasks_p1: List[PrintTask]
    tasks_p2: List[PrintTask]
    printed_p1: int
    printed_p2: int
    end_pos_normal: PrintStreamPos
    end_pos_typewriter: PrintStreamPos
    has_more_normal: bool
    has_more_typewriter: bool


@dataclass
class Print720State:
    normal_doc_list_index: int = 0
    normal_next_page: int = 1
    typewriter_doc_list_index: int = 0
    typewriter_next_page: int = 1

    def normal_pos(self) -> PrintStreamPos:
        return PrintStreamPos(self.normal_doc_list_index, self.normal_next_page)

    def typewriter_pos(self) -> PrintStreamPos:
        return PrintStreamPos(self.typewriter_doc_list_index, self.typewriter_next_page)

    @classmethod
    def from_positions(cls, normal: PrintStreamPos, typewriter: PrintStreamPos) -> "Print720State":
        return cls(
            normal_doc_list_index=normal.doc_list_index,
            normal_next_page=normal.next_page,
            typewriter_doc_list_index=typewriter.doc_list_index,
            typewriter_next_page=typewriter.next_page,
        )


def load_print720_state(path: Path) -> Print720State:
    if not path.exists():
        return Print720State()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return Print720State()
        return Print720State(
            normal_doc_list_index=int(data.get("normal_doc_list_index", 0)),
            normal_next_page=int(data.get("normal_next_page", 1)),
            typewriter_doc_list_index=int(data.get("typewriter_doc_list_index", 0)),
            typewriter_next_page=int(data.get("typewriter_next_page", 1)),
        )
    except Exception as e:
        print(f"[print720] WARNING: failed to load state file {path}: {e}")
        return Print720State()


def save_print720_state(path: Path, state: Print720State) -> None:
    try:
        payload = {
            "normal_doc_list_index": int(state.normal_doc_list_index),
            "normal_next_page": int(state.normal_next_page),
            "typewriter_doc_list_index": int(state.typewriter_doc_list_index),
            "typewriter_next_page": int(state.typewriter_next_page),
            "saved_at": int(time.time()),
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"[print720] Saved state: {path}")
    except Exception as e:
        print(f"[print720] WARNING: failed to save state file {path}: {e}")


def reset_print720_state(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
            print(f"[print720] Reset state (deleted): {path}")
    except Exception as e:
        print(f"[print720] WARNING: failed to delete state file {path}: {e}")


def _build_eligible_docs(
    *,
    orders: List[Dict[str, str]],
    itemid_index: Dict[str, str],
    itemid_typewriter: Dict[str, bool],
    pdf_by_normbase: Dict[str, PdfEntry],
    want_typewriter: bool,
) -> List[EligibleDoc]:
    out: List[EligibleDoc] = []
    for i, row in enumerate(orders):
        title = (row.get("title") or "").strip()
        url = (row.get("item_url") or "").strip()
        item_id = order_item_id(row)

        if not title or not url:
            continue
        if not item_id or item_id not in itemid_index:
            continue

        is_tw = bool(itemid_typewriter.get(item_id, False))
        if want_typewriter != is_tw:
            continue

        pdf_base = itemid_index[item_id]
        pdf = pdf_by_normbase.get(_norm(pdf_base))
        if not pdf:
            continue

        total_pages = get_pdf_pagecount(pdf.path)
        if not total_pages or total_pages <= 0:
            continue

        out.append(EligibleDoc(order_index=i, pdf=pdf, total_pages=total_pages))
    return out


def _advance_pos(docs: List[EligibleDoc], pos: PrintStreamPos) -> PrintStreamPos:
    while pos.doc_list_index < len(docs):
        d = docs[pos.doc_list_index]
        if pos.next_page <= d.total_pages:
            return pos
        pos = PrintStreamPos(doc_list_index=pos.doc_list_index + 1, next_page=1)
    return pos


def _plan_for_one_printer(
    *,
    docs: List[EligibleDoc],
    start_pos: PrintStreamPos,
    page_limit: int,
    force_even_end_if_cut: bool = True,
) -> Tuple[List[PrintTask], int, PrintStreamPos]:
    tasks: List[PrintTask] = []
    allocated = 0
    pos = _advance_pos(docs, start_pos)

    while pos.doc_list_index < len(docs) and allocated < page_limit:
        d = docs[pos.doc_list_index]
        start_page = pos.next_page
        remaining_in_doc = d.total_pages - start_page + 1
        remaining_capacity = page_limit - allocated

        if remaining_in_doc <= remaining_capacity:
            end_page = d.total_pages
            tasks.append(PrintTask(pdf=d.pdf, start_page=start_page, end_page=end_page))
            allocated += (end_page - start_page + 1)
            pos = PrintStreamPos(doc_list_index=pos.doc_list_index + 1, next_page=1)
            pos = _advance_pos(docs, pos)
            continue

        end_page = start_page + remaining_capacity - 1
        if force_even_end_if_cut and (end_page % 2 == 1):
            end_page += 1

        if end_page > d.total_pages:
            end_page = d.total_pages
            if force_even_end_if_cut and (end_page % 2 == 1) and (end_page - 1 >= start_page):
                end_page -= 1

        tasks.append(PrintTask(pdf=d.pdf, start_page=start_page, end_page=end_page))
        allocated += max(0, end_page - start_page + 1)
        pos = PrintStreamPos(doc_list_index=pos.doc_list_index, next_page=end_page + 1)
        pos = _advance_pos(docs, pos)
        break

    return tasks, allocated, pos


def plan_print720(
    *,
    orders: List[Dict[str, str]],
    itemid_index: Dict[str, str],
    itemid_typewriter: Dict[str, bool],
    pdf_by_normbase: Dict[str, PdfEntry],
    start_pos_normal: PrintStreamPos,
    start_pos_typewriter: PrintStreamPos,
    limit_each: int = 360,
    typewriter_printer: int = 0,
) -> Print720Plan:
    docs_normal = _build_eligible_docs(
        orders=orders,
        itemid_index=itemid_index,
        itemid_typewriter=itemid_typewriter,
        pdf_by_normbase=pdf_by_normbase,
        want_typewriter=False,
    )
    docs_tw = _build_eligible_docs(
        orders=orders,
        itemid_index=itemid_index,
        itemid_typewriter=itemid_typewriter,
        pdf_by_normbase=pdf_by_normbase,
        want_typewriter=True,
    )

    posN0 = _advance_pos(docs_normal, start_pos_normal)
    posT0 = _advance_pos(docs_tw, start_pos_typewriter)

    if typewriter_printer == 1:
        t1, p1, posT1 = _plan_for_one_printer(docs=docs_tw, start_pos=posT0, page_limit=limit_each, force_even_end_if_cut=True)
        t2, p2, posN1 = _plan_for_one_printer(docs=docs_normal, start_pos=posN0, page_limit=limit_each, force_even_end_if_cut=True)
        endN = posN1
        endT = posT1
    elif typewriter_printer == 2:
        t1, p1, posN1 = _plan_for_one_printer(docs=docs_normal, start_pos=posN0, page_limit=limit_each, force_even_end_if_cut=True)
        t2, p2, posT1 = _plan_for_one_printer(docs=docs_tw, start_pos=posT0, page_limit=limit_each, force_even_end_if_cut=True)
        endN = posN1
        endT = posT1
    else:
        t1, p1, posN1 = _plan_for_one_printer(docs=docs_normal, start_pos=posN0, page_limit=limit_each, force_even_end_if_cut=True)
        t2, p2, posN2 = _plan_for_one_printer(docs=docs_normal, start_pos=posN1, page_limit=limit_each, force_even_end_if_cut=True)
        endN = posN2
        endT = posT0

    endN = _advance_pos(docs_normal, endN)
    endT = _advance_pos(docs_tw, endT)

    has_more_normal = endN.doc_list_index < len(docs_normal)
    has_more_typewriter = endT.doc_list_index < len(docs_tw)

    return Print720Plan(
        tasks_p1=t1,
        tasks_p2=t2,
        printed_p1=p1,
        printed_p2=p2,
        end_pos_normal=endN,
        end_pos_typewriter=endT,
        has_more_normal=has_more_normal,
        has_more_typewriter=has_more_typewriter,
    )


def _print_plan_summary(plan: Print720Plan, typewriter_printer: int) -> None:
    tw_note = {0: "none", 1: "printer1", 2: "printer2"}.get(typewriter_printer, "none")
    print("\n[print720] Dry run plan:")
    print(f"  Typewriter printer: {tw_note}")
    print(f"  Printer 1 pages: {plan.printed_p1} (target ~360, may be 361 for duplex)")
    for t in plan.tasks_p1:
        print(f"    - {t.pdf.base}: {t.page_range}  ({t.pages} pages)")
    print(f"  Printer 2 pages: {plan.printed_p2} (target ~360, may be 361 for duplex)")
    for t in plan.tasks_p2:
        print(f"    - {t.pdf.base}: {t.page_range}  ({t.pages} pages)")


def _run_tasks_for_printer(
    *,
    printer: str,
    tasks: List[PrintTask],
    pdfs: List[PdfEntry],
    myprint_path: str,
    python_exe: Optional[str],
    tag: str,
    inventory: Optional[ManualsInventory] = None,
    skip_collector: Optional[InventorySkipCollector] = None,
) -> int:
    last_rc = 0
    for t in tasks:
        print(f"\n[{tag}] PRINT: {t.pdf.base}  pages={t.page_range}  on printer={printer}")
        result = myprint_auto_print_range(
            pdfs=pdfs,
            chosen_pdf=t.pdf,
            printer=printer,
            page_range=t.page_range,
            myprint_path=myprint_path,
            python_exe=python_exe,
            inventory=inventory,
            skip_collector=skip_collector,
        )
        if result.exit_code != 0:
            last_rc = result.exit_code
            print(f"[{tag}] WARNING: myprint exit code {result.exit_code} (continuing)")
    return last_rc


def execute_print720(
    *,
    plan: Print720Plan,
    printer1: str,
    printer2: str,
    pdfs: List[PdfEntry],
    myprint_path: str,
    python_exe: Optional[str],
    inventory: Optional[ManualsInventory] = None,
    skip_collector: Optional[InventorySkipCollector] = None,
) -> None:
    has1 = len(plan.tasks_p1) > 0
    has2 = len(plan.tasks_p2) > 0

    if has1 and has2:
        print("\n[print720] Starting BOTH printers concurrently...")
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [
                ex.submit(
                    _run_tasks_for_printer,
                    printer=printer1,
                    tasks=plan.tasks_p1,
                    pdfs=pdfs,
                    myprint_path=myprint_path,
                    python_exe=python_exe,
                    tag="P1",
                    inventory=inventory,
                    skip_collector=skip_collector,
                ),
                ex.submit(
                    _run_tasks_for_printer,
                    printer=printer2,
                    tasks=plan.tasks_p2,
                    pdfs=pdfs,
                    myprint_path=myprint_path,
                    python_exe=python_exe,
                    tag="P2",
                    inventory=inventory,
                    skip_collector=skip_collector,
                ),
            ]
            for f in as_completed(futs):
                _ = f.result()
        print("\n[print720] Both printer queues completed.")
        return

    if has1:
        print("\n[print720] Only Printer 1 has work; running Printer 1 queue...")
        _run_tasks_for_printer(
            printer=printer1,
            tasks=plan.tasks_p1,
            pdfs=pdfs,
            myprint_path=myprint_path,
            python_exe=python_exe,
            tag="P1",
            inventory=inventory,
            skip_collector=skip_collector,
        )
        return

    if has2:
        print("\n[print720] Only Printer 2 has work; running Printer 2 queue...")
        _run_tasks_for_printer(
            printer=printer2,
            tasks=plan.tasks_p2,
            pdfs=pdfs,
            myprint_path=myprint_path,
            python_exe=python_exe,
            tag="P2",
            inventory=inventory,
            skip_collector=skip_collector,
        )
        return

    print("\n[print720] No eligible pages to print in this batch.")


# =============================================================================
# Reporting helpers
# =============================================================================


def print_inventory_skip_report(skip_collector: InventorySkipCollector) -> None:
    print("\n" + "=" * 78)
    print("MANUALS NOT PRINTED BECAUSE THEY ARE ALREADY IN INVENTORY")
    print("=" * 78)

    if not skip_collector.has_records():
        print("None.")
        return

    for rec in skip_collector.records():
        print(f"- {rec.pdf_base}")
        print(f"    PDF: {rec.pdf_path}")
        print(f"    Location: {rec.location}")


# =============================================================================
# Main
# =============================================================================


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("--orders-csv", required=True, type=Path)
    ap.add_argument("--links-json", required=True, type=Path)
    ap.add_argument("--out-links-json", required=True, type=Path)

    ap.add_argument(
        "--pdf-folder",
        type=Path,
        default=Path(r"c:\Users\Admin\Downloads\ebay_manuals"),
        help="Folder containing PDFs (default: c:\\Users\\Admin\\Downloads\\ebay_manuals)",
    )
    ap.add_argument(
        "--pdf-folder2",
        type=Path,
        default=Path(r"c:\Users\Admin\Downloads\Manuals"),
        help="Optional second PDF folder (default: c:\\Users\\Admin\\Downloads\\Manuals)",
    )
    ap.add_argument("--recursive", action="store_true", help="Scan PDFs recursively under both folders")

    ap.add_argument("--min-score", type=float, default=60.0)
    ap.add_argument("--min-margin", type=float, default=8.0)

    ap.add_argument("--manuals-csv", type=Path, default=Path("manuals.csv"),
                    help="Printed-manual inventory CSV kept for compatibility (default: manuals.csv in current directory)")
    ap.add_argument("--inventory-csv", type=Path, default=DEFAULT_MANUALS_CSV,
                    help="manuals.csv used to detect manuals already in inventory before calling myprint")

    ap.add_argument("--print", dest="do_print", action="store_true",
                    help="After selecting a PDF, run myprint.py using auto-inputs (no changes to myprint.py).")
    ap.add_argument("--myprint", default="myprint.py",
                    help="Path to myprint.py (default: myprint.py in current directory).")
    ap.add_argument("--python", default=None,
                    help="Python executable to run myprint.py (default: current interpreter).")

    ap.add_argument("--printer", type=str, default="", help="Default printer selection (e.g. 1).")
    ap.add_argument("--printer2", type=str, default="", help="Second printer selection (print720 mode).")
    ap.add_argument("--always-ask-printer", action="store_true",
                    help="Ask printer number for every print (normal mode).")

    ap.add_argument("--max-orders", type=int, default=0,
                    help="Optional limit for debugging (0 = no limit).")

    ap.add_argument("--print360", action="store_true",
                    help="Special mode: print up to 360 pages with no user intervention (except choosing printer).")
    ap.add_argument("--print360manual2sided", action="store_true",
                    help="Special mode: print360-style batches using manual two-sided even/odd passes and padded odd-page PDFs.")
    ap.add_argument("--print720", action="store_true",
                    help="Special mode: dry-run split then print ~360 pages on printer1 and ~360 on printer2 concurrently.")
    ap.add_argument("--print720manual2sided", action="store_true",
                    help="Special mode: print720-style manual two-sided batches, assigning whole manuals evenly across two printers.")
    ap.add_argument("--secondpass", action="store_true",
                    help="With --print360manual2sided or --print720manual2sided, run only the odd-page second pass.")
    ap.add_argument(
        "--print720-state",
        type=Path,
        default=Path("print720_state.json"),
        help="print720 persistent state JSON file (default: print720_state.json in current directory)",
    )
    ap.add_argument(
        "--print720-reset",
        action="store_true",
        help="Reset print720 progress (delete state file) and start from the beginning",
    )
    ap.add_argument(
        "--typewriter",
        type=int,
        choices=(0, 1, 2),
        default=0,
        help="For print720 only: select which printer is the 'typewriter' (old toner). "
             "0=none, 1=printer1, 2=printer2. The typewriter printer prints ONLY manuals "
             "with links-json flag {\"typewriter\": true} (optional; default false).",
    )

    args = ap.parse_args()

    orders = read_orders_csv(args.orders_csv)
    if args.max_orders:
        orders = orders[:args.max_orders]

    links = load_links_json(args.links_json)
    itemid_index, itemid_typewriter = build_itemid_index_and_flags(links)

    pdfs_1 = list_pdfs(args.pdf_folder, args.recursive)
    pdfs_2: List[PdfEntry] = []
    if args.pdf_folder2 and args.pdf_folder2.exists():
        pdfs_2 = list_pdfs(args.pdf_folder2, args.recursive)

    pdfs_by_norm: Dict[str, PdfEntry] = {}
    for p in pdfs_1 + pdfs_2:
        key = _norm(p.base)
        if key not in pdfs_by_norm:
            pdfs_by_norm[key] = p
    pdfs = list(pdfs_by_norm.values())

    if not pdfs:
        print(
            "No PDFs found in:\n"
            f"  - {args.pdf_folder}\n"
            f"  - {args.pdf_folder2}\n"
            f"(recursive={args.recursive})"
        )
        sys.exit(2)

    pdf_by_normbase: Dict[str, PdfEntry] = {_norm(p.base): p for p in pdfs}

    _ = load_manuals_from_csv_any(args.manuals_csv)
    inventory = ManualsInventory.load(args.inventory_csv)
    skip_collector = InventorySkipCollector()

    print(f"Loaded {len(orders)} orders from: {args.orders_csv}")
    print(f"Loaded {len(links)} existing link entries from: {args.links_json}")
    print(
        f"Indexed {len(pdfs)} unique PDF base names from:\n"
        f"  - {args.pdf_folder}\n"
        f"  - {args.pdf_folder2}\n"
        f"(recursive={args.recursive})"
    )
    print(f"Inventory CSV for skip detection: {inventory.csv_path}")

    default_printer = (args.printer or "").strip()

    try:
        if args.print360manual2sided:
            if not default_printer:
                default_printer = input("\n[print360manual2sided] Printer number (e.g. 1 or 2): ").strip()
            if not default_printer:
                print("[print360manual2sided] ERROR: printer is required.")
                sys.exit(2)

            myprint_module = load_myprint_module(args.myprint)
            printer_name = resolve_printer_name(myprint_module, default_printer)
            if not printer_name:
                print(f"[print360manual2sided] ERROR: unknown printer {default_printer!r}")
                sys.exit(2)
            quiet_printer_name = f"{printer_name} Quiet"
            if not myprint_module.printer_exists(quiet_printer_name):
                print("\n[print360manual2sided] Manual two-sided mode requires a quiet printer named:")
                print(quiet_printer_name)
                print("No matching quiet printer was found, so the first pass will not start.")
                save_links_json(args.out_links_json, links)
                return

            print_settings = load_print_settings_for_myprint(myprint_module)
            next_idx = 0
            resume: Optional[Print360Resume] = None
            batch_no = 1
            all_second_pass_jobs: List[Tuple[Print360ManualTask, List[str]]] = []
            all_simplex_pages: List[str] = []
            printed_any = False

            with tempfile.TemporaryDirectory(prefix="print360manual2sided_") as td:
                temp_dir = Path(td)
                padding_futures: Dict[Path, Any] = {}
                with ThreadPoolExecutor(max_workers=2) as padding_executor:
                    while True:
                        next_idx, pages_planned, resume, tasks = plan_print360_manual_batch(
                            orders=orders,
                            start_index=next_idx,
                            start_resume=resume,
                            itemid_index=itemid_index,
                            pdf_by_normbase=pdf_by_normbase,
                            page_limit=360,
                            temp_dir=temp_dir,
                            padding_executor=padding_executor,
                            padding_futures=padding_futures,
                            queue_padding=False,
                            inventory=inventory,
                            skip_collector=skip_collector,
                        )

                        if not tasks:
                            if not printed_any:
                                print("\n[print360manual2sided] Nothing eligible to print. Exiting.")
                            else:
                                print("\n[print360manual2sided] No more eligible orders/pages after this batch.")
                            break

                        prepare_tasks_for_batch_manual_2sided(
                            myprint_module=myprint_module,
                            print_settings=print_settings,
                            tasks=tasks,
                            temp_dir=temp_dir,
                        )
                        pass_label = "Second-pass" if args.secondpass else "First-pass"
                        actual_pages = sum(manual_task_page_count(t) for t in tasks)
                        print(f"\n[print360manual2sided] {pass_label} batch {batch_no} prepared: {actual_pages} pages (planned before blank backs: {pages_planned}/360)")
                        summarize_manual_tasks("print360manual2sided", tasks, printer_name)
                        if args.secondpass:
                            second_jobs, simplex_pages = collect_print360_manual_second_pass_jobs(
                                myprint_module=myprint_module,
                                print_settings=print_settings,
                                tasks=tasks,
                            )
                        else:
                            second_jobs, simplex_pages = execute_print360_manual_first_pass_batch(
                                myprint_module=myprint_module,
                                print_settings=print_settings,
                                tasks=tasks,
                                printer_name=printer_name,
                                batch_no=batch_no,
                            )
                        all_second_pass_jobs.extend(second_jobs)
                        all_simplex_pages.extend(simplex_pages)
                        printed_any = True

                        has_more_orders = (resume is not None) or (next_idx < len(orders))
                        if not has_more_orders:
                            break

                        if args.secondpass:
                            prompt = (
                                f"\n[print360manual2sided] Second-pass batch {batch_no} is planned for printer: {printer_name}. "
                                "Add the second-pass batch before starting odd-page printing? [y/N]: "
                            )
                        else:
                            prompt = (
                                f"\n[print360manual2sided] First-pass batch complete for printer: {printer_name}. "
                                "Add the next first-pass batch before printing? [y/N]: "
                            )
                        ans = input(prompt).strip().lower()
                        if not ans.startswith("y"):
                            print(f"[print360manual2sided] Using the planned {pass_label.lower()} batches.")
                            if resume is not None:
                                print(
                                    f"[print360manual2sided] Next run should resume order index {resume.order_index}, "
                                    f"manual '{resume.pdf.base}', page {resume.next_page}."
                                )
                            break

                        batch_no += 1

                    if printed_any:
                        execute_print360_manual_second_pass(
                            myprint_module=myprint_module,
                            second_pass_jobs=all_second_pass_jobs,
                            simplex_pages=all_simplex_pages,
                            quiet_printer_name=quiet_printer_name,
                            second_pass_only=args.secondpass,
                        )

            save_links_json(args.out_links_json, links)
            return

        if args.print720manual2sided:
            printer1 = default_printer
            printer2 = (args.printer2 or "").strip()

            if not printer1:
                printer1 = input("\n[print720manual2sided] Printer 1 number (e.g. 1): ").strip()
            if not printer2:
                printer2 = input("[print720manual2sided] Printer 2 number (e.g. 2): ").strip()
            if not printer1:
                print("[print720manual2sided] ERROR: printer1 is required.")
                sys.exit(2)
            if not printer2:
                print("[print720manual2sided] ERROR: printer2 is required.")
                sys.exit(2)

            myprint_module = load_myprint_module(args.myprint)
            printer1_name = resolve_printer_name(myprint_module, printer1)
            printer2_name = resolve_printer_name(myprint_module, printer2)
            if not printer1_name or not printer2_name:
                print("[print720manual2sided] ERROR: unknown printer selection.")
                sys.exit(2)

            quiet_printer1_name = f"{printer1_name} Quiet"
            quiet_printer2_name = f"{printer2_name} Quiet"
            missing_quiet = [p for p in (quiet_printer1_name, quiet_printer2_name) if not myprint_module.printer_exists(p)]
            if missing_quiet:
                print("\n[print720manual2sided] Manual two-sided mode requires these quiet printers:")
                print(quiet_printer1_name)
                print(quiet_printer2_name)
                print("Missing quiet printer(s):")
                for p in missing_quiet:
                    print(p)
                print("Printing will not start.")
                save_links_json(args.out_links_json, links)
                return

            print_settings = load_print_settings_for_myprint(myprint_module)
            next_idx = 0
            batch_no = 1
            all_second_pass_jobs: List[Tuple[str, Print360ManualTask, List[str]]] = []
            all_simplex_pages: List[str] = []
            printed_any = False

            with tempfile.TemporaryDirectory(prefix="print720manual2sided_") as td:
                temp_dir = Path(td)
                padding_futures: Dict[Path, Any] = {}
                with ThreadPoolExecutor(max_workers=2) as padding_executor:
                    while True:
                        next_idx, selected_tasks = plan_print720_manual_batch(
                            orders=orders,
                            start_index=next_idx,
                            itemid_index=itemid_index,
                            pdf_by_normbase=pdf_by_normbase,
                            page_limit_each=360,
                            temp_dir=temp_dir,
                            padding_executor=padding_executor,
                            padding_futures=padding_futures,
                            queue_padding=False,
                            inventory=inventory,
                            skip_collector=skip_collector,
                        )

                        if not selected_tasks:
                            if not printed_any:
                                print("\n[print720manual2sided] Nothing eligible to print. Exiting.")
                            else:
                                print("\n[print720manual2sided] No more eligible orders/pages after this batch.")
                            break

                        prepare_tasks_for_batch_manual_2sided(
                            myprint_module=myprint_module,
                            print_settings=print_settings,
                            tasks=selected_tasks,
                            temp_dir=temp_dir,
                        )
                        tasks_p1, tasks_p2 = partition_tasks_evenly(selected_tasks)

                        pass_label = "Second-pass" if args.secondpass else "First-pass"
                        print(f"\n[print720manual2sided] Batch {batch_no} assignment summary before {pass_label.lower()} printing:")
                        summarize_manual_tasks("print720manual2sided", tasks_p1, printer1_name)
                        summarize_manual_tasks("print720manual2sided", tasks_p2, printer2_name)
                        print(
                            f"[print720manual2sided] Batch {batch_no} total pages: "
                            f"{sum(t.padded_pages for t in selected_tasks)}"
                        )

                        if args.secondpass:
                            second_jobs, simplex_pages = collect_print720_manual_second_pass_jobs(
                                myprint_module=myprint_module,
                                print_settings=print_settings,
                                tasks_p1=tasks_p1,
                                tasks_p2=tasks_p2,
                            )
                        else:
                            second_jobs, simplex_pages = execute_print720_manual_first_pass_pair(
                                myprint_module=myprint_module,
                                print_settings=print_settings,
                                tasks_p1=tasks_p1,
                                tasks_p2=tasks_p2,
                                printer1_name=printer1_name,
                                printer2_name=printer2_name,
                                batch_no=batch_no,
                            )
                        all_second_pass_jobs.extend(second_jobs)
                        all_simplex_pages.extend(simplex_pages)
                        printed_any = True

                        has_more_orders = next_idx < len(orders)
                        if not has_more_orders:
                            break

                        if tasks_p1 and tasks_p2:
                            concern = f"both printers: {printer1_name} and {printer2_name}"
                        elif tasks_p1:
                            concern = f"printer: {printer1_name}"
                        else:
                            concern = f"printer: {printer2_name}"
                        if args.secondpass:
                            prompt = (
                                f"\n[print720manual2sided] Second-pass batch {batch_no} is planned for {concern}. "
                                "Add the second-pass batch before starting odd-page printing? [y/N]: "
                            )
                        else:
                            prompt = (
                                f"\n[print720manual2sided] First-pass batch complete for {concern}. "
                                "Add the next first-pass batch before printing? [y/N]: "
                            )
                        ans = input(prompt).strip().lower()
                        if not ans.startswith("y"):
                            print(f"[print720manual2sided] Using the planned {pass_label.lower()} batches.")
                            break

                        batch_no += 1

                    if printed_any:
                        execute_print720_manual_second_pass(
                            myprint_module=myprint_module,
                            second_pass_jobs=all_second_pass_jobs,
                            simplex_pages=all_simplex_pages,
                            quiet_printer1_name=quiet_printer1_name,
                            quiet_printer2_name=quiet_printer2_name,
                            second_pass_only=args.secondpass,
                        )

            save_links_json(args.out_links_json, links)
            return

        if args.print720:
            printer1 = default_printer
            printer2 = (args.printer2 or "").strip()

            if not printer1:
                printer1 = input("\n[print720] Printer 1 number (e.g. 1): ").strip()
            if not printer2:
                printer2 = input("[print720] Printer 2 number (e.g. 2): ").strip()

            if not printer1:
                print("[print720] ERROR: printer1 is required.")
                sys.exit(2)
            if not printer2:
                print("[print720] ERROR: printer2 is required.")
                sys.exit(2)

            typewriter_printer = int(args.typewriter or 0)
            state_path: Path = args.print720_state

            if args.print720_reset:
                reset_print720_state(state_path)

            st = load_print720_state(state_path)
            posN = st.normal_pos()
            posT = st.typewriter_pos()

            print(
                f"\n[print720] Starting from state:"
                f"\n  NORMAL:     doc_list_index={posN.doc_list_index}, next_page={posN.next_page}"
                f"\n  TYPEWRITER: doc_list_index={posT.doc_list_index}, next_page={posT.next_page}"
            )
            print(f"[print720] State file: {state_path.resolve()}")

            while True:
                plan = plan_print720(
                    orders=orders,
                    itemid_index=itemid_index,
                    itemid_typewriter=itemid_typewriter,
                    pdf_by_normbase=pdf_by_normbase,
                    start_pos_normal=posN,
                    start_pos_typewriter=posT,
                    limit_each=360,
                    typewriter_printer=typewriter_printer,
                )

                _print_plan_summary(plan, typewriter_printer)
                total_pages = plan.printed_p1 + plan.printed_p2

                if total_pages <= 0:
                    print("\n[print720] Nothing eligible to print. Exiting.")
                    save_print720_state(state_path, Print720State.from_positions(posN, posT))
                    break

                execute_print720(
                    plan=plan,
                    printer1=printer1,
                    printer2=printer2,
                    pdfs=pdfs,
                    myprint_path=args.myprint,
                    python_exe=args.python,
                    inventory=inventory,
                    skip_collector=skip_collector,
                )

                posN = plan.end_pos_normal
                posT = plan.end_pos_typewriter
                save_print720_state(state_path, Print720State.from_positions(posN, posT))

                has_more = plan.has_more_normal or plan.has_more_typewriter
                if has_more:
                    ans = input("\n[print720] Do you want to continue printing the next batch? [y/N]: ").strip().lower()
                    if not ans.startswith("y"):
                        print("[print720] Stopping now; progress saved for next run.")
                        break
                else:
                    print("\n[print720] No more eligible pages after this batch. Done.")
                    try:
                        if state_path.exists():
                            state_path.unlink()
                    except Exception as e:
                        print(f"[print720] WARNING: failed to delete state file {state_path}: {e}")
                    break

            save_links_json(args.out_links_json, links)
            return

        if args.print360:
            if not default_printer:
                default_printer = input("\n[print360] Printer number (e.g. 1 or 2): ").strip()
            if not default_printer:
                print("[print360] ERROR: printer is required.")
                sys.exit(2)

            next_idx = 0
            resume: Optional[Print360Resume] = None
            batch_no = 1

            while True:
                next_idx, pages_printed, resume = run_print360_batch(
                    orders=orders,
                    start_index=next_idx,
                    start_resume=resume,
                    itemid_index=itemid_index,
                    pdf_by_normbase=pdf_by_normbase,
                    pdfs=pdfs,
                    printer=default_printer,
                    myprint_path=args.myprint,
                    python_exe=args.python,
                    page_limit=360,
                    inventory=inventory,
                    skip_collector=skip_collector,
                )

                print(f"\n[print360] Batch {batch_no} complete. Pages printed in this batch: {pages_printed}/360")

                has_more_orders = (resume is not None) or (next_idx < len(orders))
                if not has_more_orders:
                    print("\n[print360] No more eligible orders/pages after this batch. Done.")
                    save_links_json(args.out_links_json, links)
                    return

                if pages_printed <= 0:
                    print("\n[print360] No pages were printed in this batch. Stopping to avoid an infinite loop.")
                    save_links_json(args.out_links_json, links)
                    return

                ans = input(
                    "\n[print360] 360-page batch complete. Change paper if needed. "
                    "Continue with the next 360-page batch? [y/N]: "
                ).strip().lower()
                if not ans.startswith("y"):
                    print("[print360] Stopping now.")
                    if resume is not None:
                        print(
                            f"[print360] Next run should resume order index {resume.order_index}, "
                            f"manual '{resume.pdf.base}', page {resume.next_page}."
                        )
                    save_links_json(args.out_links_json, links)
                    return

                batch_no += 1

        else:
            start_index_for_normal = 0
            if args.do_print and not default_printer and not args.always_ask_printer:
                default_printer = input("\nDefault printer number for this run (e.g. 1 or 2): ").strip()

        updated = 0
        processed = 0

        for i in range(start_index_for_normal, len(orders)):
            row = orders[i]
            processed += 1

            title = (row.get("title") or "").strip()
            url = (row.get("item_url") or "").strip()
            item_id = order_item_id(row)

            if not title or not url:
                continue

            chosen_pdf: Optional[PdfEntry] = None

            if item_id and item_id in itemid_index:
                known_pdf_base = itemid_index[item_id]
                chosen_pdf = pdf_by_normbase.get(_norm(known_pdf_base))

                print("\nOrder title:")
                print(f"  {title}")
                if chosen_pdf:
                    print(f"\nKnown item_id {item_id} already linked to PDF: {chosen_pdf.base} (skipping fuzzy match)")
                else:
                    print(
                        f"\nKnown item_id {item_id} is linked to '{known_pdf_base}' in links JSON, "
                        f"but that PDF was not found in the scanned folder. Falling back to fuzzy match."
                    )
                    chosen_pdf = None

            if chosen_pdf is None:
                cands = top_candidates(title, pdfs, k=0)
                chosen_pdf = choose_match_interactive(title, cands, args.min_score, args.min_margin)
                if not chosen_pdf:
                    print("No match selected. Moving on.")
                    continue

            links.setdefault(chosen_pdf.base, {})
            links[chosen_pdf.base]["url"] = url
            if item_id:
                links[chosen_pdf.base]["item_id"] = item_id
                itemid_index[item_id] = chosen_pdf.base
                rec = links.get(chosen_pdf.base, {})
                itemid_typewriter[item_id] = _as_bool(rec.get("typewriter", False))

            updated += 1
            print(f"Linked: {chosen_pdf.base}  ->  {url}   (item_id={item_id})")

            if args.do_print:
                act = input("Print now? [P]rint / [S]kip / [Q]uit printing: ").strip().lower()
                if act == "":
                    act = "p"
                if act.startswith("q"):
                    print("Printing disabled for the remainder of this run.")
                    args.do_print = False
                    continue
                if act.startswith("s"):
                    print("Skipped printing; moving to next order.")
                    continue

                prn = default_printer
                if args.always_ask_printer or not prn:
                    prn = input("Printer number (e.g. 1 or 2): ").strip()

                page_range = input("Page range for myprint (blank = default): ").strip()

                result = myprint_auto_print_range(
                    pdfs=pdfs,
                    chosen_pdf=chosen_pdf,
                    printer=prn,
                    page_range=page_range,
                    myprint_path=args.myprint,
                    python_exe=args.python,
                    inventory=inventory,
                    skip_collector=skip_collector,
                )
                if result.skipped_in_inventory:
                    print("Manual already exists in inventory. Not printed.")
                elif result.exit_code != 0:
                    print(f"WARNING: myprint.py returned exit code {result.exit_code}. Continuing.")

        save_links_json(args.out_links_json, links)
        print(f"\nDone. Updated/added {updated} links. Processed {processed} order rows.")
    finally:
        print_inventory_skip_report(skip_collector)


if __name__ == "__main__":
    main()
