#!/usr/bin/env python
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


URL = "https://www.ebay.com/sh/ord/?filter=status:AWAITING_SHIPMENT"

CHECKBOX_ID = "grid-table-bulk-checkbox"


def js_click(driver, el):
    driver.execute_script("arguments[0].click();", el)


def js_force_check(driver, el, checked=True):
    # Force state and fire events (React-style UIs usually listen to these)
    driver.execute_script(
        """
        const cb = arguments[0];
        const val = arguments[1];
        cb.checked = val;
        cb.dispatchEvent(new Event('input', { bubbles: true }));
        cb.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        el, checked
    )


def select_all_orders_on_page(driver, timeout=30):
    wait = WebDriverWait(driver, timeout)

    cb = wait.until(EC.presence_of_element_located((By.ID, CHECKBOX_ID)))
    wait.until(lambda d: d.find_element(By.ID, CHECKBOX_ID).is_enabled())
    cb = driver.find_element(By.ID, CHECKBOX_ID)

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cb)

    if cb.is_selected():
        return

    # Prefer label click if present
    labels = driver.find_elements(By.CSS_SELECTOR, f'label[for="{CHECKBOX_ID}"]')
    if labels:
        try:
            ActionChains(driver).move_to_element(labels[0]).pause(0.1).click(labels[0]).perform()
            if driver.find_element(By.ID, CHECKBOX_ID).is_selected():
                return
        except Exception:
            pass

    # Actions click on input
    try:
        cb = driver.find_element(By.ID, CHECKBOX_ID)
        ActionChains(driver).move_to_element(cb).pause(0.1).click(cb).perform()
        if driver.find_element(By.ID, CHECKBOX_ID).is_selected():
            return
    except Exception:
        pass

    # JS click
    try:
        cb = driver.find_element(By.ID, CHECKBOX_ID)
        js_click(driver, cb)
        if driver.find_element(By.ID, CHECKBOX_ID).is_selected():
            return
    except Exception:
        pass

    # Last resort: force-check + events
    cb = driver.find_element(By.ID, CHECKBOX_ID)
    js_force_check(driver, cb, True)


def click_shipping_then_get_label(driver, timeout=30):
    wait = WebDriverWait(driver, timeout)

    # Click the Shipping menu button
    shipping_btn = wait.until(EC.element_to_be_clickable((
        By.XPATH,
        "//button[.//span[normalize-space()='Shipping'] or normalize-space()='Shipping']"
    )))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", shipping_btn)

    try:
        shipping_btn.click()
    except Exception:
        js_click(driver, shipping_btn)

    # Wait until the menu is expanded (aria-expanded becomes true).
    # If the element is re-rendered, reacquire it.
    try:
        wait.until(lambda d: shipping_btn.get_attribute("aria-expanded") == "true")
    except TimeoutException:
        shipping_btn = driver.find_element(
            By.XPATH,
            "//button[.//span[normalize-space()='Shipping'] or normalize-space()='Shipping']"
        )

    # Click the closest clickable ancestor of "Get shipping label"
    item_clickable = wait.until(EC.element_to_be_clickable((
        By.XPATH,
        "//span[contains(@class,'shui-menu-dropdown__primary-text') and normalize-space()='Get shipping label']"
        "/ancestor::*[self::button or self::a][1]"
    )))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", item_clickable)

    try:
        item_clickable.click()
    except Exception:
        js_click(driver, item_clickable)


def click_review_purchase(driver, timeout=30):
    wait = WebDriverWait(driver, timeout)

    btn = wait.until(EC.element_to_be_clickable((
        By.XPATH,
        "//button[contains(@class,'review-and-pay') and normalize-space()='Review purchase']"
    )))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)

    try:
        btn.click()
    except Exception:
        js_click(driver, btn)


def ensure_logged_in_or_pause(driver):
    cur = driver.current_url.lower()
    if "signin" in cur or "login" in cur:
        print("Redirected to sign-in. Please log in in the Chrome window, then press Enter here.")
        input()


def main():
    options = webdriver.ChromeOptions()

    # Dedicated profile folder so you remain logged in between runs
    profile_dir = Path(__file__).with_name("chrome_profile_selenium")
    profile_dir.mkdir(exist_ok=True)
    options.add_argument(f"--user-data-dir={str(profile_dir)}")

    driver = webdriver.Chrome(options=options)

    try:
        # 1) Open shipment page
        driver.get(URL)
        print("Landed URL:", driver.current_url)
        print("Title:", driver.title)

        # 2) If redirected, log in once, then reload the target page
        ensure_logged_in_or_pause(driver)
        driver.get(URL)

        # 3) Select all orders on this page (optional, but kept from the previous code)
        select_all_orders_on_page(driver)
        print("Select-all checkbox state:", driver.find_element(By.ID, CHECKBOX_ID).is_selected())

        # 4) Open Shipping menu, click Get shipping label
        click_shipping_then_get_label(driver)
        print("Clicked Shipping -> Get shipping label")

        # 5) Click Review purchase on the subsequent page/modal
        click_review_purchase(driver)
        print("Clicked Review purchase")

        input("Done. Press Enter to quit...")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()

