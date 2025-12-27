#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


URL_FIN_SUMMARY = "https://www.ebay.com/sh/fin/summary"
RE_MONEY = re.compile(r"[-]?\$?\s*([0-9][0-9,]*\.[0-9]{2})")


def ensure_logged_in_or_pause(driver: webdriver.Chrome, *, headless: bool) -> None:
    cur = (driver.current_url or "").lower()
    if "signin" in cur or "login" in cur:
        if headless:
            raise RuntimeError(
                "Redirected to sign-in while running headless.\n"
                "Run once with --noheadless to log in interactively, then rerun headless.\n"
                "Your session is stored in chrome_profile_selenium next to this script."
            )
        print("Redirected to sign-in. Please log in in the Chrome window, then press Enter here.")
        input()


def parse_money(text: str) -> float | None:
    if not text:
        return None
    m = RE_MONEY.search(text.strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--noheadless", action="store_true", help="Run Chrome visually (disable headless)")
    ap.add_argument("--timeout", type=int, default=30, help="Wait timeout (seconds)")
    args = ap.parse_args()

    headless = not args.noheadless

    options = webdriver.ChromeOptions()

    # Reuse a dedicated profile so you stay logged in between runs
    profile_dir = Path(__file__).with_name("chrome_profile_selenium").resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={str(profile_dir)}")

    # Headless by default
    if headless:
        options.add_argument("--headless=new")
        # Common flags to improve reliability in headless environments
        options.add_argument("--window-size=1400,1000")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)
    try:
        driver.get(URL_FIN_SUMMARY)
        ensure_logged_in_or_pause(driver, headless=headless)

        # Reload after login / redirect resolution
        driver.get(URL_FIN_SUMMARY)

        wait = WebDriverWait(driver, args.timeout)

        # Targets: <div class="total-funds-value"><div>$1,005.50</div></div>
        inner = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.total-funds-value > div"))
        )

        text = (inner.text or "").strip()
        amount = parse_money(text)

        if amount is None:
            raise RuntimeError(f"Could not parse total funds from text: {text!r}")

        print(f"Total funds: {amount:.2f}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
