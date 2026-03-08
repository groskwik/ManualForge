#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ebay_sell.py

Automate eBay "Sell similar" draft edits:
- choose a "seed" itemId from ebay_links.json based on the new title
  (so Brand is correct automatically, without touching the Brand widget)
- delete existing photos (best effort, robust)
- upload a new cover via <input type=file> (NO OS file dialog)
- set title
- update pages count inside raw HTML description textarea
- set price
- set shipping weight (lb/oz)
- finish by clicking Preview/Review (safe) or List it (creates listing)

Usage examples:

  # Normal: pick seed itemId from ebay_links.json based on --title tokens
  python ebay_sell.py --cover "C:\\path\\cover.png" --title "Canon EOS 6D User Manual" \
    --pages 454 --price 19.85 --lb 3 --oz 3 --profile-dir "chrome_profile_selenium" --debug --preview

  # Override: explicitly choose seed itemId
  python ebay_sell.py ... --seed-item-id 357955849382

  # Override: choose seed by matching a specific phrase instead of the new title
  python ebay_sell.py ... --seed-title "Olympus"

Notes:
- Brand is skipped by default, because seed listing should already have correct Brand.
- Seed selection behavior:
    1) substring match (case-insensitive) against ebay_links.json keys
    2) if multiple: prompt user to choose
    3) if none: show fuzzy + token-overlap suggestions, prompt user to choose
    4) if user cancels (or nothing found) then fallback to DEFAULT_SEED_ITEM_ID unless --strict-seed
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import time
from pathlib import Path
from typing import Optional, Tuple, List, Dict

import psutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    NoSuchElementException,
    ElementNotInteractableException,
)

DEFAULT_SEED_ITEM_ID = "356000157685"
SELL_SIMILAR_FMT = "https://www.ebay.com/lstng?mode=SellSimilarItem&itemId={item_id}&sr=wn"

RE_PAGES = re.compile(r"(\b)(\d+)\s*(page|pages)\b", re.IGNORECASE)


# ----------------------------
# Seed selection from links json (interactive, find_pdf-style + suggestions)
# ----------------------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _pretty_key(k: str, maxlen: int = 90) -> str:
    k = (k or "").strip()
    if len(k) <= maxlen:
        return k
    return k[: maxlen - 3] + "..."


def seed_query_from_title(title: str) -> str:
    """
    Reduce a full title to a shorter substring query to get better matches in links json.
    Removes generic words that appear in almost all listings.
    """
    stop = {
        "manual", "instruction", "instructions", "owner", "owners", "owner's",
        "operating", "operation", "user", "users", "guide", "reference",
        "for", "the", "and", "with", "pages", "page", "pdf", "book",
        "service", "repair", "workshop", "parts", "catalog", "catalogue",
    }
    toks = re.findall(r"[A-Za-z0-9]+", title or "")
    cleaned: List[str] = []
    for t in toks:
        t0 = _norm(t)
        if not t0 or t0 in stop:
            continue
        cleaned.append(t)

    # Keep first ~6 significant tokens (usually brand + model)
    cleaned = cleaned[:6]
    return " ".join(cleaned) if cleaned else (title or "").strip()


def pick_seed_item_id_interactive(
    links: Dict,
    query: str,
    debug: bool = False,
    max_suggestions: int = 15,
) -> Optional[Tuple[str, str]]:
    """
    Seed selection:
      1) Case-insensitive substring match on JSON keys (titles).
      2) If multiple matches, prompt user to choose.
      3) If no matches: show fuzzy suggestions + token-overlap suggestions, then prompt user.

    Returns:
        (seed_key, item_id) or None
    """
    q_raw = (query or "").strip()
    q = _norm(q_raw)
    if not q:
        return None

    # Build candidate list (only entries with numeric item_id)
    candidates: List[Tuple[str, str]] = []
    for key, obj in (links or {}).items():
        try:
            item_id = str(obj.get("item_id", "")).strip()
        except Exception:
            item_id = ""
        if item_id.isdigit():
            candidates.append((str(key), item_id))

    if not candidates:
        if debug:
            print("[WARN] No valid item_id entries found in links json.")
        return None

    # 1) Substring matches
    matches: List[Tuple[str, str]] = []
    for key, item_id in candidates:
        if q in _norm(key):
            matches.append((key, item_id))

    if len(matches) == 1:
        if debug:
            print(f"[INFO] Seed match: query='{q_raw}' -> unique match key='{matches[0][0]}' item_id={matches[0][1]}")
        return matches[0]

    if len(matches) > 1:
        print("\nMultiple seed matches found in ebay_links.json (substring match):")
        for idx, (k, item_id) in enumerate(matches, start=1):
            print(f"{idx:>2}. item_id={item_id} | {_pretty_key(k)}")

        while True:
            choice = input("\nEnter the number of the seed listing to use (or 'q' to cancel): ").strip().lower()
            if choice in ("q", "quit", "exit"):
                return None
            if choice.isdigit():
                i = int(choice)
                if 1 <= i <= len(matches):
                    sel = matches[i - 1]
                    if debug:
                        print(f"[INFO] Selected seed: key='{sel[0]}' item_id={sel[1]}")
                    return sel
            print("Invalid choice. Try again.")

    # 2) No substring matches -> suggest near matches and ask user
    keys = [k for k, _ in candidates]
    keys_norm = [_norm(k) for k in keys]

    # 2a) Fuzzy suggestions using difflib on normalized keys
    fuzzy_norm = difflib.get_close_matches(q, keys_norm, n=max_suggestions, cutoff=0.25)
    fuzzy: List[Tuple[str, str, float]] = []
    # map normalized key -> indices (could be duplicates; keep all)
    norm_to_idxs: Dict[str, List[int]] = {}
    for i, kn in enumerate(keys_norm):
        norm_to_idxs.setdefault(kn, []).append(i)

    for kn in fuzzy_norm:
        for i in norm_to_idxs.get(kn, []):
            ratio = difflib.SequenceMatcher(None, q, kn).ratio()
            fuzzy.append((keys[i], candidates[i][1], ratio))

    # 2b) Token overlap suggestions
    def toks(s: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", _norm(s))

    stop = {
        "manual", "instruction", "instructions", "owner", "owners", "owner's",
        "operating", "operation", "user", "users", "guide", "reference",
        "workshop", "service", "repair", "parts", "catalog", "catalogue",
        "pdf", "book", "pages", "page", "for", "the", "and", "with",
    }

    q_toks = [t for t in toks(q) if len(t) >= 3 and t not in stop]
    q_set = set(q_toks)

    scored: List[Tuple[str, str, int]] = []
    if q_set:
        for key, item_id in candidates:
            k_set = set([t for t in toks(key) if len(t) >= 3 and t not in stop])
            overlap = len(q_set & k_set)
            if overlap > 0:
                scored.append((key, item_id, overlap))
        scored.sort(key=lambda t: t[2], reverse=True)
        scored = scored[:max_suggestions]

    # Merge suggestions (dedupe by item_id)
    merged: List[Tuple[str, str, str]] = []
    seen = set()

    for k, item_id, ratio in sorted(fuzzy, key=lambda t: t[2], reverse=True):
        if item_id in seen:
            continue
        merged.append((k, item_id, f"fuzzy {ratio:.2f}"))
        seen.add(item_id)

    for k, item_id, ov in scored:
        if item_id in seen:
            continue
        merged.append((k, item_id, f"token overlap {ov}"))
        seen.add(item_id)

    if not merged:
        print(f"\nNo seed matches found for: '{q_raw}'")
        print("Tip: try --seed-title with a shorter phrase (e.g. brand/model), or fix typos.")
        return None

    print(f"\nNo exact substring matches for: '{q_raw}'")
    print("Closest candidates:")
    for idx, (k, item_id, why) in enumerate(merged, start=1):
        print(f"{idx:>2}. item_id={item_id} | {_pretty_key(k)}   [{why}]")

    while True:
        choice = input("\nEnter the number of the seed listing to use (or 'q' to cancel): ").strip().lower()
        if choice in ("q", "quit", "exit"):
            return None
        if choice.isdigit():
            i = int(choice)
            if 1 <= i <= len(merged):
                sel = merged[i - 1]
                if debug:
                    print(f"[INFO] Selected seed (suggestion): key='{sel[0]}' item_id={sel[1]}")
                return (sel[0], sel[1])
        print("Invalid choice. Try again.")


def load_links_json(path: Path, debug: bool = False) -> Dict:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if debug:
            print(f"[WARN] links json not found: {path}")
        return {}
    except Exception as e:
        if debug:
            print(f"[WARN] could not read links json '{path}': {e}")
        return {}


def build_sell_similar_url(seed_item_id: str) -> str:
    return SELL_SIMILAR_FMT.format(item_id=str(seed_item_id).strip())


# ----------------------------
# Process helpers
# ----------------------------
def kill_chrome_using_profile(profile_dir: Path, debug: bool = True) -> None:
    profile_dir_abs = str(profile_dir.resolve())
    killed = 0
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "chrome" not in name:
                continue
            cmdline_list = proc.info.get("cmdline") or []
            if not cmdline_list:
                continue
            cmdline = " ".join(cmdline_list)
            if profile_dir_abs in cmdline:
                killed += 1
                if debug:
                    print(f"[INFO] Killing stale Chrome PID={proc.pid} using profile: {profile_dir_abs}")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    time.sleep(0.5)
    if debug:
        if killed == 0:
            print(f"[INFO] No stale Chrome found for profile: {profile_dir_abs}")
        else:
            print(f"[INFO] Killed {killed} stale Chrome process(es) for profile: {profile_dir_abs}")


# ----------------------------
# Selenium helpers
# ----------------------------
def ensure_logged_in_or_pause(driver) -> None:
    cur = (driver.current_url or "").lower()
    if "signin" in cur or "login" in cur:
        print("Redirected to sign-in. Please log in in the Chrome window, then press Enter here.")
        input()


def js_click(driver, el) -> None:
    driver.execute_script("arguments[0].click();", el)


def safe_click(driver, el) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    try:
        el.click()
    except Exception:
        js_click(driver, el)


def wait_dom_ready(driver, timeout: int = 25) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            rs = driver.execute_script("return document.readyState;")
            if rs == "complete":
                return
        except Exception:
            pass
        time.sleep(0.15)


def wait_for_possible_redirect(driver, prev_url: str, timeout: int = 25, debug: bool = False) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            cur = driver.current_url or ""
            if cur and cur != prev_url:
                if debug:
                    print(f"[INFO] URL changed (likely draft): {cur}")
                wait_dom_ready(driver, timeout=20)
                time.sleep(0.8)
                return
        except Exception:
            pass
        time.sleep(0.2)


def nuke_snackbar_overlays(driver, debug: bool = False) -> None:
    try:
        WebDriverWait(driver, 2).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.snackbar-dialog"))
        )
        return
    except TimeoutException:
        pass

    if debug:
        print("[WARN] Snackbar overlay still present; disabling/removing via JS.")

    try:
        driver.execute_script(
            """
            document.querySelectorAll('div.snackbar-dialog').forEach(el => {
              el.style.pointerEvents = 'none';
              el.style.opacity = '0.0';
            });
            document.querySelectorAll('div.snackbar-dialog').forEach(el => el.remove());
            """
        )
    except Exception:
        pass


def dispatch_input_change(driver, el) -> None:
    driver.execute_script(
        """
        const el = arguments[0];
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        el,
    )


def set_value_js(driver, el, value: str) -> None:
    driver.execute_script("arguments[0].value = arguments[1];", el, value)
    dispatch_input_change(driver, el)


def find_element_fresh(driver, locator: Tuple[By, str], tries: int = 15):
    by, sel = locator
    last_exc = None
    for _ in range(tries):
        try:
            return driver.find_element(by, sel)
        except (StaleElementReferenceException, NoSuchElementException) as e:
            last_exc = e
            time.sleep(0.15)
    raise last_exc if last_exc else RuntimeError(f"Could not find element: {locator}")


def clear_and_type_el(driver, el, value: str, press_enter: bool = False):
    el.send_keys(Keys.CONTROL, "a")
    el.send_keys(Keys.BACKSPACE)
    el.send_keys(value)
    if press_enter:
        el.send_keys(Keys.ENTER)
    dispatch_input_change(driver, el)


def clear_and_type_locator(
    driver,
    locator: Tuple[By, str],
    value: str,
    debug: bool = False,
    press_enter: bool = False,
    max_attempts: int = 7,
) -> None:
    if value is None:
        value = ""

    last_exc: Optional[Exception] = None

    for attempt in range(max_attempts):
        try:
            el = find_element_fresh(driver, locator)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.05)

            try:
                el.click()
            except ElementClickInterceptedException:
                nuke_snackbar_overlays(driver, debug=debug)
                time.sleep(0.2)
                el = find_element_fresh(driver, locator)
                safe_click(driver, el)

            clear_and_type_el(driver, el, value, press_enter=press_enter)
            return

        except (StaleElementReferenceException, NoSuchElementException) as e:
            last_exc = e
            if debug:
                print(f"[WARN] Element missing/stale (attempt {attempt+1}/{max_attempts}); retrying...")
            time.sleep(0.25)

        except ElementNotInteractableException as e:
            last_exc = e
            if debug:
                print(f"[WARN] Element not interactable; JS-set will be used. ({locator})")
            try:
                el = find_element_fresh(driver, locator)
                set_value_js(driver, el, value)
                if press_enter:
                    try:
                        el.send_keys(Keys.ENTER)
                    except Exception:
                        pass
                return
            except Exception:
                time.sleep(0.25)

        except Exception as e:
            last_exc = e
            if debug:
                print(f"[WARN] Typing failed (attempt {attempt+1}/{max_attempts}): {e}")
            time.sleep(0.25)

    if debug:
        print("[INFO] Falling back to JS value set for:", locator)
        if last_exc:
            print("[INFO] Last exception before JS fallback:", repr(last_exc))

    el = find_element_fresh(driver, locator)
    set_value_js(driver, el, value)
    if press_enter:
        try:
            el.send_keys(Keys.ENTER)
        except Exception:
            pass


def build_driver(profile_dir: Path, headless: bool, chrome_binary: str | None = None):
    options = webdriver.ChromeOptions()
    profile_dir.mkdir(parents=True, exist_ok=True)

    options.add_argument(f"--user-data-dir={str(profile_dir)}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-notifications")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("--window-size=1400,900")

    if chrome_binary:
        options.binary_location = chrome_binary

    if headless:
        options.add_argument("--headless=new")

    return webdriver.Chrome(options=options)


# ----------------------------
# Photos: robust delete + robust upload verification
# ----------------------------
def count_delete_photo_buttons(driver) -> int:
    try:
        btns = driver.find_elements(By.CSS_SELECTOR, "button[aria-label^='Delete photo']")
        return len(btns)
    except Exception:
        return 0


def find_photo_tiles(driver) -> List:
    tile_locators = [
        (By.CSS_SELECTOR, "[data-testid*='photo']"),
        (By.CSS_SELECTOR, "div[class*='photo']"),
        (By.CSS_SELECTOR, "div[class*='picture']"),
        (By.CSS_SELECTOR, "li[class*='photo']"),
    ]
    tiles: List = []
    for loc in tile_locators:
        try:
            els = driver.find_elements(loc[0], loc[1])
            els = [e for e in els if e.is_displayed()]
            pruned = []
            for e in els:
                try:
                    r = e.rect
                    if r and 40 <= r.get("height", 0) <= 800 and 40 <= r.get("width", 0) <= 1200:
                        pruned.append(e)
                except Exception:
                    pass
            if pruned:
                tiles = pruned
                break
        except Exception:
            continue
    return tiles


def _click_delete_buttons_anywhere(driver, debug: bool = False) -> int:
    try:
        btns = driver.find_elements(By.CSS_SELECTOR, "button[aria-label^='Delete photo']")
    except Exception:
        return 0

    def sort_key(b):
        try:
            aria = (b.get_attribute("aria-label") or "").strip().lower()
            m = re.search(r"delete photo\s+(\d+)", aria)
            return int(m.group(1)) if m else 999
        except Exception:
            return 999

    btns = sorted(btns, key=sort_key)

    for b in btns:
        try:
            aria = (b.get_attribute("aria-label") or "").strip()
        except Exception:
            aria = ""

        try:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", b)
            except Exception:
                pass

            nuke_snackbar_overlays(driver, debug=debug)

            try:
                b.click()
            except Exception:
                js_click(driver, b)

            if debug:
                print(f"[INFO] Clicked delete button: {aria or '(no aria)'}")
            time.sleep(0.6)
            wait_dom_ready(driver, timeout=20)
            return 1

        except StaleElementReferenceException:
            continue
        except Exception:
            continue

    return 0


def _hover_photo_tiles(driver, debug: bool = False) -> None:
    tiles = find_photo_tiles(driver)
    if debug:
        print(f"[INFO] Hovering {len(tiles)} photo tiles (best effort)")
    for t in tiles:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", t)
            ActionChains(driver).move_to_element(t).perform()
            time.sleep(0.12)
        except Exception:
            continue


def delete_all_photos_best_effort(driver, wait: WebDriverWait, debug: bool = False, max_deletes: int = 10) -> None:
    nuke_snackbar_overlays(driver, debug=debug)

    total = 0
    for _ in range(max_deletes):
        n = _click_delete_buttons_anywhere(driver, debug=debug)
        if n > 0:
            total += n
            continue

        _hover_photo_tiles(driver, debug=debug)
        n = _click_delete_buttons_anywhere(driver, debug=debug)
        if n > 0:
            total += n
            continue

        try:
            b = driver.find_element(By.CSS_SELECTOR, "button[aria-label='Delete photo 1']")
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", b)
            except Exception:
                pass
            nuke_snackbar_overlays(driver, debug=debug)
            try:
                b.click()
            except Exception:
                js_click(driver, b)
            total += 1
            if debug:
                print("[INFO] Clicked exact 'Delete photo 1' fallback.")
            time.sleep(0.6)
            wait_dom_ready(driver, timeout=20)
            continue
        except Exception:
            pass

        if debug:
            print("[INFO] No deletable photo button found. Continuing (this is OK).")
        break

    if debug:
        print(f"[INFO] Deleted photos count (best effort): {total}")


def upload_cover_image(
    driver,
    wait: WebDriverWait,
    cover_path: Path,
    debug: bool = False,
    upload_wait: int = 35,
    upload_retries: int = 1,
) -> None:
    cover_path = cover_path.expanduser().resolve()
    if not cover_path.exists():
        raise FileNotFoundError(f"Cover image not found: {cover_path}")

    if debug:
        print(f"[INFO] Uploading cover: {cover_path}")

    nuke_snackbar_overlays(driver, debug=debug)

    before_del = count_delete_photo_buttons(driver)
    if debug:
        print(f"[INFO] Delete-photo button count (before upload): {before_del}")

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))

    def pick_best_file_input():
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        scored = []
        for inp in inputs:
            try:
                if inp.get_attribute("disabled"):
                    continue
                accept = (inp.get_attribute("accept") or "").lower()
                score = 0
                if "image" in accept:
                    score += 100
                if "png" in accept or "jpg" in accept or "jpeg" in accept:
                    score += 20
                if inp.get_attribute("multiple") is not None:
                    score += 5
                scored.append((score, inp, accept))
            except Exception:
                continue
        if not scored:
            raise RuntimeError("No usable <input type='file'> found on the page.")
        scored.sort(key=lambda t: t[0], reverse=True)
        return scored[0]

    last_exc = None

    for attempt in range(upload_retries + 1):
        try:
            score, file_inp, accept = pick_best_file_input()
            if debug:
                print(f"[INFO] Upload input pick attempt {attempt+1}/{upload_retries+1}: score={score}, accept='{accept}'")

            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", file_inp)
            except Exception:
                pass

            nuke_snackbar_overlays(driver, debug=debug)

            prev_url = driver.current_url or ""
            file_inp.send_keys(str(cover_path))

            wait_for_possible_redirect(driver, prev_url, timeout=25, debug=debug)
            time.sleep(0.8)
            nuke_snackbar_overlays(driver, debug=debug)

            def uploaded(_):
                now = count_delete_photo_buttons(driver)
                if now > before_del:
                    return True
                if before_del == 0 and now >= 1:
                    return True
                return False

            WebDriverWait(driver, upload_wait).until(uploaded)
            after_del = count_delete_photo_buttons(driver)
            if debug:
                print(f"[INFO] Upload verified. Delete-photo button count (after upload): {after_del}")
            return

        except TimeoutException as e:
            last_exc = e
            after_del = count_delete_photo_buttons(driver)
            if debug:
                print(f"[WARN] Upload verification timed out. delete-buttons after={after_del}, before={before_del}.")
            if after_del > before_del or (before_del == 0 and after_del >= 1):
                if debug:
                    print("[INFO] Upload appears complete despite timeout; continuing.")
                return
            if attempt < upload_retries:
                if debug:
                    print("[WARN] Retrying upload due to missing verification (possible DOM re-render).")
                time.sleep(0.8)
                continue
            raise RuntimeError("Upload could not be verified (no new photo detected).")

        except (StaleElementReferenceException, ElementNotInteractableException) as e:
            last_exc = e
            if debug:
                print(f"[WARN] Upload attempt {attempt+1} failed due to stale/not-interactable: {e}")
            if attempt < upload_retries:
                time.sleep(0.8)
                continue
            break

        except Exception as e:
            last_exc = e
            if debug:
                print(f"[WARN] Upload attempt {attempt+1} failed: {e}")
            if attempt < upload_retries:
                time.sleep(0.8)
                continue
            break

    raise RuntimeError(f"Upload failed. Last error: {repr(last_exc)}")


# ----------------------------
# Description/pages
# ----------------------------
def set_pages_in_description(driver, wait: WebDriverWait, pages: int, debug: bool = False) -> None:
    """
    Ensure eBay description is in HTML/raw mode, then update the "X Pages" snippet
    inside the raw HTML textarea. Works with both escaped HTML (&lt;p&gt;) and plain.

    Strategy:
      1) Toggle HTML mode checkbox ON (best-effort).
      2) Locate the raw textarea (id contains 'rawEditor' OR class '...__html').
      3) Replace first occurrence of '<number> page(s)' or 'Pages' text.
      4) If not found, prepend a bold pages line.
      5) Use React-friendly native setter + input/change dispatch.
      6) Verify result; retry once if needed.
    """
    pages_str = str(int(pages))

    # ---------- helper: React-friendly value set ----------
    def set_textarea_value_react(el, value: str):
        driver.execute_script(
            """
            const el = arguments[0];
            const value = arguments[1];

            // Use the native setter so React sees it
            const proto = Object.getPrototypeOf(el);
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            const setter = desc && desc.set;
            if (setter) setter.call(el, value);
            else el.value = value;

            el.dispatchEvent(new Event('input',  { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            el,
            value,
        )

    # ---------- 1) Force HTML mode ----------
    # eBay uses a checkbox to switch to HTML editor mode.
    # We'll click it if present and not already checked.
    checkbox_candidates = [
        (By.CSS_SELECTOR, "input[name='descriptionEditorMode'][type='checkbox']"),
        (By.CSS_SELECTOR, "input[data-testid='checkbox'][name='descriptionEditorMode']"),
        (By.CSS_SELECTOR, "input[id*='descriptionEditorMode'][type='checkbox']"),
    ]

    cb = None
    for loc in checkbox_candidates:
        try:
            cb = driver.find_element(loc[0], loc[1])
            if cb:
                break
        except Exception:
            cb = None

    if cb is not None:
        try:
            # scroll + click only if not already enabled
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cb)
            time.sleep(0.1)
            checked = cb.is_selected()
            if debug:
                print(f"[INFO] Description HTML-mode checkbox found. is_selected={checked}")
            if not checked:
                nuke_snackbar_overlays(driver, debug=debug)
                try:
                    cb.click()
                except Exception:
                    js_click(driver, cb)
                time.sleep(0.5)
                wait_dom_ready(driver, timeout=15)
        except Exception as e:
            if debug:
                print(f"[WARN] Could not toggle HTML-mode checkbox: {e}")

    # ---------- 2) Find RAW HTML textarea ----------
    # When HTML mode is on, the raw textarea usually has id containing 'rawEditor'
    # and/or class 'se-rte__button-group-editor__html'.
    raw_locators = [
        (By.CSS_SELECTOR, "textarea#*"),  # placeholder; we’ll refine below
    ]

    # We’ll search explicitly with robust selectors:
    candidates = [
        (By.CSS_SELECTOR, "textarea[id*='rawEditor']"),
        (By.CSS_SELECTOR, "textarea.se-rte__button-group-editor__html"),
        (By.CSS_SELECTOR, "textarea[name='description']"),  # fallback
        (By.CSS_SELECTOR, "textarea[data-testid='richEditor']"),  # fallback
    ]

    el = None
    last_err = None
    for loc in candidates:
        try:
            el = wait.until(EC.presence_of_element_located(loc))
            if el:
                break
        except Exception as e:
            last_err = e
            el = None

    if not el:
        raise RuntimeError(f"Could not find description textarea (raw editor). Last error: {last_err!r}")

    # Make sure it's in view
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass

    nuke_snackbar_overlays(driver, debug=debug)

    # ---------- 3) Read current content ----------
    current = el.get_attribute("value") or ""
    if debug:
        print("[INFO] Current description length:", len(current))

    # ---------- 4) Update pages line ----------
    def apply_update(text: str) -> str:
        # Replace first "123 page(s)" anywhere
        if RE_PAGES.search(text):
            return RE_PAGES.sub(lambda m: f"{m.group(1)}{pages_str} Pages", text, count=1)

        # If not found, prepend a bold pages block.
        # Handle both escaped HTML and plain HTML/editor text.
        # Most of your templates use escaped tags (&lt;p&gt;...).
        if "&lt;" in text and "&gt;" in text:
            prefix = f"&lt;p&gt;&lt;strong&gt;{pages_str} Pages&lt;/strong&gt;&lt;/p&gt;"
        else:
            prefix = f"<p><strong>{pages_str} Pages</strong></p>"

        return prefix + text

    updated = apply_update(current)

    if updated == current:
        # Extremely unlikely, but keep safe
        if debug:
            print("[WARN] Pages update produced no changes; forcing prepend.")
        if "&lt;" in current and "&gt;" in current:
            updated = f"&lt;p&gt;&lt;strong&gt;{pages_str} Pages&lt;/strong&gt;&lt;/p&gt;" + current
        else:
            updated = f"<p><strong>{pages_str} Pages</strong></p>" + current

    # ---------- 5) Set value + verify (retry once) ----------
    for attempt in range(2):
        set_textarea_value_react(el, updated)
        time.sleep(0.3)

        # Verify: read back textarea value
        back = el.get_attribute("value") or ""
        ok = (pages_str in back) and (back != current)

        if debug:
            print(f"[INFO] Pages update attempt {attempt+1}/2: ok={ok} back_len={len(back)}")

        if ok:
            return

        # If not ok, try to re-find element (React re-render)
        try:
            el = find_element_fresh(driver, (By.CSS_SELECTOR, "textarea[id*='rawEditor']"))
        except Exception:
            # fallback: keep using same element
            pass

    raise RuntimeError("Failed to update pages in description (textarea value did not stick).")

# ----------------------------
# End actions
# ----------------------------
def click_preview(driver, wait: WebDriverWait, debug: bool = False) -> None:
    candidates = [
        (By.XPATH, "//button[normalize-space()='Preview']"),
        (By.XPATH, "//button[contains(@aria-label,'Preview')]"),
        (By.XPATH, "//button[normalize-space()='Review']"),
        (By.XPATH, "//button[contains(@aria-label,'Review')]"),
        (By.XPATH, "//button[contains(normalize-space(.),'Preview')]"),
        (By.XPATH, "//button[contains(normalize-space(.),'Review')]"),
    ]

    btn = None
    for loc in candidates:
        try:
            btn = wait.until(EC.element_to_be_clickable(loc))
            break
        except Exception:
            btn = None

    if not btn:
        raise RuntimeError("Could not find a clickable 'Preview'/'Review' control.")

    nuke_snackbar_overlays(driver, debug=debug)
    if debug:
        print("[INFO] Clicking 'Preview/Review'")
    safe_click(driver, btn)
    time.sleep(1.0)


def click_list_it(driver, wait: WebDriverWait, debug: bool = False) -> None:
    candidates = [
        (By.XPATH, "//button[normalize-space()='List it']"),
        (By.XPATH, "//button[@aria-label='List it']"),
        (By.XPATH, "//button[contains(@aria-label,'List it')]"),
        (By.CSS_SELECTOR, "button.btn.btn--large.btn--primary"),
    ]

    btn = None
    for loc in candidates:
        try:
            btn = wait.until(EC.element_to_be_clickable(loc))
            break
        except Exception:
            btn = None

    if not btn:
        raise RuntimeError("Could not find 'List it' button.")

    nuke_snackbar_overlays(driver, debug=debug)
    if debug:
        print("[INFO] Clicking 'List it'")
    safe_click(driver, btn)
    time.sleep(1.0)


# ----------------------------
# Main
# ----------------------------
def main():
    ap = argparse.ArgumentParser(description="Automate eBay 'Sell similar' edits using seed itemId from links json.")
    ap.add_argument("--cover", required=True, help="Path to cover image file (PNG/JPG).")
    ap.add_argument("--title", required=True, help="New listing title.")
    ap.add_argument("--pages", required=True, type=int, help="Number of pages (integer).")
    ap.add_argument("--price", required=True, type=float, help="Item price (e.g., 39.85).")
    ap.add_argument("--lb", required=True, type=int, help="Shipping weight pounds (integer).")
    ap.add_argument("--oz", required=True, type=int, help="Shipping weight ounces (integer, <16).")

    # Seed selection
    ap.add_argument("--links-json", default="",
                    help="Path to ebay_links.json (default: ./ebay_links.json if exists).")
    ap.add_argument("--seed-title", default="",
                    help="Override query used to select seed from links json (default: reduced query from --title).")
    ap.add_argument("--seed-item-id", default="",
                    help="Force seed itemId directly (bypasses links json).")
    ap.add_argument("--strict-seed", action="store_true",
                    help="Fail if no seed can be resolved from links json / seed id.")

    # Brand widget is skipped by default (seed listing should already have correct brand)
    ap.add_argument("--no-brand", action="store_true", help="Skip brand setting (default behavior).")

    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--debug", action="store_true")

    ap.add_argument("--profile-dir", default=None,
                    help="Chrome user-data-dir for Selenium profile. Default: ./chrome_profile_selenium")
    ap.add_argument("--chrome-binary", default=None,
                    help="Optional path to Chrome/Chromium binary.")
    ap.add_argument("--no-kill-profile", action="store_true",
                    help="Do NOT kill stale Chrome processes using this profile before starting.")

    ap.add_argument("--preview", action="store_true", help="Click Preview/Review (safe).")
    ap.add_argument("--list", dest="do_list", action="store_true", help="Click List it (creates listing).")
    ap.add_argument("--pause", action="store_true", help="Do not click preview/list; keep browser open.")

    ap.add_argument("--no-delete-photos", action="store_true",
                    help="Do not attempt to delete existing photos before upload.")

    ap.add_argument("--upload-wait", type=int, default=35,
                    help="Seconds to wait for upload verification after send_keys.")
    ap.add_argument("--upload-retries", type=int, default=1,
                    help="Max additional upload attempts if upload cannot be verified (default=1). "
                         "Set 0 to force single-shot upload (no duplicates).")

    args = ap.parse_args()

    # default behavior: skip brand
    if not args.no_brand:
        args.no_brand = True

    # SAFE DEFAULT end action
    if not args.preview and not args.do_list and not args.pause:
        args.preview = True

    cover_path = Path(args.cover).expanduser().resolve()
    if not cover_path.exists():
        raise FileNotFoundError(f"--cover does not exist: {cover_path}")

    if args.oz < 0 or args.oz >= 16:
        raise ValueError("--oz must be between 0 and 15")
    if args.lb < 0:
        raise ValueError("--lb must be >= 0")
    if args.price <= 0:
        raise ValueError("--price must be > 0")
    if args.pages <= 0:
        raise ValueError("--pages must be > 0")
    if args.upload_retries < 0:
        raise ValueError("--upload-retries must be >= 0")

    script_dir = Path(__file__).resolve().parent
    profile_dir = Path(args.profile_dir).expanduser().resolve() if args.profile_dir else (script_dir / "chrome_profile_selenium")
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Resolve links json path
    links_path = None
    if args.links_json.strip():
        links_path = Path(args.links_json).expanduser().resolve()
    else:
        candidate = script_dir / "ebay_links.json"
        if candidate.exists():
            links_path = candidate

    # Resolve seed itemId
    seed_item_id = ""
    used_query = ""

    if args.seed_item_id.strip():
        seed_item_id = args.seed_item_id.strip()
    else:
        links = load_links_json(links_path, debug=args.debug) if links_path else {}

        # Prefer explicit seed-title; otherwise use reduced query from title
        if (args.seed_title or "").strip():
            used_query = args.seed_title.strip()
        else:
            used_query = seed_query_from_title(args.title.strip())

        if args.debug:
            print(f"[INFO] Seed selection query: '{used_query}'")

        best = pick_seed_item_id_interactive(links, query=used_query, debug=args.debug)
        if best:
            seed_item_id = best[1]

    if not seed_item_id:
        if args.strict_seed:
            raise RuntimeError(
                "Could not resolve seed itemId (strict). Provide --seed-item-id or a better --seed-title/--links-json."
            )
        print(f"[WARN] No seed match found for query '{used_query}'. Falling back to DEFAULT_SEED_ITEM_ID={DEFAULT_SEED_ITEM_ID}")
        print("[WARN] Tip: use --seed-title 'Kubota' (or similar) to force a good match, or use --strict-seed to prevent fallback.")
        seed_item_id = DEFAULT_SEED_ITEM_ID

    url = build_sell_similar_url(seed_item_id)

    if not args.no_kill_profile:
        kill_chrome_using_profile(profile_dir, debug=args.debug)

    driver = build_driver(profile_dir, headless=args.headless, chrome_binary=args.chrome_binary)
    wait = WebDriverWait(driver, args.timeout)

    try:
        if args.debug:
            print(f"[INFO] Opening URL: {url}")
            print(f"[INFO] Seed itemId: {seed_item_id}")
            print(f"[INFO] Profile dir: {profile_dir}")
            print(f"[INFO] Headless: {args.headless}")

        driver.get(url)
        ensure_logged_in_or_pause(driver)
        driver.get(url)

        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        wait_dom_ready(driver, timeout=25)
        time.sleep(1.0)

        if not args.no_delete_photos:
            tiles = find_photo_tiles(driver)
            if args.debug:
                print(f"[INFO] Photo tile candidates: {len(tiles)} (informational)")
            delete_all_photos_best_effort(driver, wait, debug=args.debug, max_deletes=12)

        prev_url = driver.current_url or ""
        upload_cover_image(
            driver,
            wait,
            cover_path,
            debug=args.debug,
            upload_wait=args.upload_wait,
            upload_retries=args.upload_retries,
        )
        wait_for_possible_redirect(driver, prev_url, timeout=30, debug=args.debug)

        if args.debug:
            print(f"[INFO] Setting title: {args.title}")
        clear_and_type_locator(
            driver,
            (By.CSS_SELECTOR, "input[name='title']"),
            args.title,
            debug=args.debug,
            press_enter=False,
        )

        if args.no_brand and args.debug:
            print("[INFO] --no-brand active (default): skipping brand (seed listing should already have it).")

        set_pages_in_description(driver, wait, args.pages, debug=args.debug)

        price_str = f"{args.price:.2f}"
        if args.debug:
            print(f"[INFO] Setting price: {price_str}")
        clear_and_type_locator(
            driver,
            (By.CSS_SELECTOR, "input[name='price']"),
            price_str,
            debug=args.debug,
            press_enter=False,
        )

        if args.debug:
            print(f"[INFO] Setting weight: {args.lb} lb, {args.oz} oz")
        clear_and_type_locator(driver, (By.CSS_SELECTOR, "input[name='majorWeight']"), str(args.lb), debug=args.debug)
        clear_and_type_locator(driver, (By.CSS_SELECTOR, "input[name='minorWeight']"), str(args.oz), debug=args.debug)

        if args.pause:
            print("\n[PAUSE] No preview/list click performed. Browser remains open.")
        elif args.do_list:
            click_list_it(driver, wait, debug=args.debug)
            print("\nDone: clicked 'List it'.")
        else:
            click_preview(driver, wait, debug=args.debug)
            print("\nDone: clicked 'Preview/Review' (safe).")

        if not args.headless:
            input("\nPress Enter to quit...")

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

