#!/usr/bin/env python
import time
import argparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


ORDER_TEXT_DEFAULT = "Hewlett Packard HP 41C 41CV 41CX Calculator Repair service"


def create_driver(profile_dir=None):
    options = Options()

    # Keeps the browser open after the script ends, useful for debugging
    options.add_experimental_option("detach", True)

    # Optional persistent Chrome profile so you don't need to log in every time
    if profile_dir:
        options.add_argument(f"--user-data-dir={profile_dir}")

    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def wait_for_orders_page(driver, timeout=120):
    """
    Wait until the user is on the orders page and the page has loaded enough.
    This allows manual login if Stamps.com asks for it.
    """
    print("Waiting for Stamps.com orders page to load...")
    print("If login is required, log in manually in the browser.")

    WebDriverWait(driver, timeout).until(
        lambda d: "print.stamps.com" in d.current_url
    )

    # Wait until body exists
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    time.sleep(5)


def click_refresh_button(driver, timeout=30):
    """
    Tries several common ways to identify the refresh button.
    """
    print("Looking for refresh button...")

    refresh_xpaths = [
        "//button[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'refresh')]",
        "//button[contains(translate(@title, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'refresh')]",
        "//*[self::button or self::a][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'refresh')]",
        "//*[contains(@class, 'refresh') and (self::button or self::a or @role='button')]",
        "//*[@role='button' and contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'refresh')]",
    ]

    for xpath in refresh_xpaths:
        try:
            button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
            time.sleep(0.5)
            button.click()
            print("Refresh button clicked.")
            time.sleep(5)
            return True
        except Exception:
            pass

    print("Could not find a refresh button. Continuing without clicking it.")
    return False


def find_order_row(driver, order_text, timeout=30):
    """
    Finds a row or container containing the order item name.
    """
    print(f"Searching for order containing:\n{order_text}")

    # Case-insensitive partial match using XPath translate()
    lower_text = order_text.lower()

    xpath = (
        "//*[contains("
        "translate(normalize-space(.), "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        "'abcdefghijklmnopqrstuvwxyz'), "
        f"{repr(lower_text)}"
        ")]"
    )

    matching_element = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, xpath))
    )

    print("Found matching text on page.")

    # Try to climb to a likely row/container
    row_xpaths = [
        "./ancestor::tr[1]",
        "./ancestor::*[@role='row'][1]",
        "./ancestor::*[contains(@class, 'row')][1]",
        "./ancestor::*[contains(@class, 'order')][1]",
    ]

    for row_xpath in row_xpaths:
        try:
            row = matching_element.find_element(By.XPATH, row_xpath)
            return row
        except Exception:
            pass

    # Fallback: return the element itself
    return matching_element


def select_order_row(driver, row):
    """
    Selects an order by clicking a checkbox inside the row.
    If no checkbox exists, clicks the row itself.
    """
    print("Trying to select the order...")

    checkbox_xpaths = [
        ".//input[@type='checkbox']",
        ".//*[@role='checkbox']",
        ".//button[contains(@aria-label, 'Select')]",
        ".//button[contains(@title, 'Select')]",
    ]

    for xpath in checkbox_xpaths:
        try:
            checkbox = row.find_element(By.XPATH, xpath)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", checkbox)
            time.sleep(0.5)
            checkbox.click()
            print("Order selected using checkbox/select control.")
            return True
        except Exception:
            pass

    # Fallback: click the row
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
        time.sleep(0.5)
        row.click()
        print("Order row clicked.")
        return True
    except Exception as e:
        print(f"Could not select the order: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Open Stamps.com orders page, refresh, and select a specific order."
    )

    parser.add_argument(
        "--order-text",
        default=ORDER_TEXT_DEFAULT,
        help="Text contained in the order item name to search for."
    )

    parser.add_argument(
        "--profile-dir",
        default="chrome_profile_stamps",
        help="Chrome user profile directory. Keeps login session between runs."
    )

    parser.add_argument(
        "--no-profile",
        action="store_true",
        help="Do not use a persistent Chrome profile."
    )

    args = parser.parse_args()

    profile_dir = None if args.no_profile else args.profile_dir

    driver = create_driver(profile_dir=profile_dir)

    try:
        driver.get("https://print.stamps.com/orders/")

        wait_for_orders_page(driver)

        click_refresh_button(driver)

        row = find_order_row(driver, args.order_text)

        selected = select_order_row(driver, row)

        if selected:
            print("Done.")
        else:
            print("Order was found but could not be selected automatically.")

    except Exception as e:
        print(f"Error: {e}")
        print("The order may not be visible, or the page structure may have changed.")


if __name__ == "__main__":
    main()
