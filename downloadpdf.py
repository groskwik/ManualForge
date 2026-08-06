import os
import re
import time
import requests
from urllib.parse import quote_plus, urljoin
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options


DOWNLOAD_DIR = "downloaded_manuals"
MIN_PDF_BYTES = 20 * 1024

# Selenium Chrome profile stored locally beside script
CHROME_USER_DATA_DIR = os.path.abspath("chrome_selenium_profile")
CHROME_PROFILE_DIR = "Default"


def clean_ebay_title(title):
    """
    Extract meaningful title from eBay listing title.
    """

    cleaned = title.strip()

    remove_patterns = [
        r':.*$',
        r'\s*-\s*premium card stock covers?\s*&\s*\d+\s*lb\s*paper!?\s*$',
        r'\b11"\s*X\s*17".*$',
        r'\bcolor foldout.*$',
        r'\bboard layouts?.*$',
        r'\bdiagrams?.*$',
        r'\bprinted manual.*$',
        r'\breprint.*$',
        r'\bcopy\b.*$',
        r'\bnew\b.*$',
    ]

    for pat in remove_patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned


def safe_filename(name):
    """
    Convert title into valid filename.
    """

    name = re.sub(r'[\\/*?:"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()

    return name + ".pdf"


def validate_downloaded_pdf(output_path):
    """
    Reject tiny error pages and non-PDF downloads so callers can try the next link.
    """

    if not os.path.exists(output_path):
        return False

    size = os.path.getsize(output_path)
    if size < MIN_PDF_BYTES:
        print(
            f"Downloaded file is too small ({size} bytes); "
            f"trying another link."
        )
        os.remove(output_path)
        return False

    try:
        with open(output_path, "rb") as f:
            header = f.read(5)
    except Exception:
        return False

    if header != b"%PDF-":
        print("Downloaded file is not a PDF; trying another link.")
        os.remove(output_path)
        return False

    return True


def setup_driver(download_dir):
    """
    Create Selenium Chrome driver with persistent local profile.
    """

    os.makedirs(CHROME_USER_DATA_DIR, exist_ok=True)

    options = Options()

    options.add_argument("--start-maximized")

    # Persistent local Selenium profile
    options.add_argument(
        f"--user-data-dir={CHROME_USER_DATA_DIR}"
    )

    options.add_argument(
        f"--profile-directory={CHROME_PROFILE_DIR}"
    )

    # Reduce Selenium detection
    options.add_argument(
        "--disable-blink-features=AutomationControlled"
    )

    options.add_experimental_option(
        "excludeSwitches",
        ["enable-automation"]
    )

    options.add_experimental_option(
        "useAutomationExtension",
        False
    )

    prefs = {
        "download.default_directory": os.path.abspath(download_dir),
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
    }

    options.add_experimental_option("prefs", prefs)

    print("Starting Chrome...")

    driver = webdriver.Chrome(options=options)

    print("Chrome started.")

    # Hide webdriver flag
    driver.execute_script("""
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    })
    """)

    return driver


def google_search(driver, query, max_results=10):
    """
    Perform Google search and extract links.
    """

    url = "https://www.google.com/search?q=" + quote_plus(query)

    print()
    print("Opening Google search:")
    print(url)

    driver.get(url)

    print("Opened:", driver.current_url)

    time.sleep(3)

    links = []

    anchors = driver.find_elements(By.CSS_SELECTOR, "a")

    for a in anchors:
        href = a.get_attribute("href")

        if not href:
            continue

        if not href.startswith("http"):
            continue

        if "google.com" in href:
            continue

        if href not in links:
            links.append(href)

        if len(links) >= max_results:
            break

    return links


def is_pdf_url(url):
    """
    Check if URL directly points to PDF.
    """

    return ".pdf" in url.lower().split("?")[0]


def download_pdf_with_requests(url, output_path):
    """
    Attempt PDF download with requests first.
    """

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    r.raise_for_status()

    content_type = r.headers.get(
        "Content-Type",
        ""
    ).lower()

    if (
        "pdf" not in content_type
        and not url.lower().endswith(".pdf")
    ):
        print(
            f"Warning: URL may not be PDF "
            f"(Content-Type={content_type})"
        )

    with open(output_path, "wb") as f:
        f.write(r.content)

    if not validate_downloaded_pdf(output_path):
        return False

    print()
    print(f"Downloaded with requests:")
    print(output_path)

    return True


def download_pdf_with_selenium(driver, pdf_url, output_path):
    """
    Download PDF using Chrome browser.
    Useful when requests gets HTTP 403.
    """

    download_dir = os.path.dirname(output_path)

    os.makedirs(download_dir, exist_ok=True)

    before = set(os.listdir(download_dir))

    print()
    print("Opening PDF in Chrome:")
    print(pdf_url)

    driver.get(pdf_url)

    # Wait for download to start
    time.sleep(10)

    # Wait for partial download to finish
    for _ in range(30):

        partial_files = [
            f for f in os.listdir(download_dir)
            if f.lower().endswith(".crdownload")
        ]

        if not partial_files:
            break

        time.sleep(1)

    after = set(os.listdir(download_dir))

    new_files = list(after - before)

    pdf_files = [
        f for f in new_files
        if f.lower().endswith(".pdf")
    ]

    if not pdf_files:
        print("No PDF downloaded by Chrome.")
        return False

    downloaded_file = os.path.join(
        download_dir,
        pdf_files[0]
    )

    if os.path.exists(output_path):
        os.remove(output_path)

    os.rename(downloaded_file, output_path)

    if not validate_downloaded_pdf(output_path):
        return False

    print()
    print("Downloaded with Chrome:")
    print(output_path)

    return True


def download_pdf(driver, url, output_path):
    """
    Download PDF.
    First try requests.
    Fallback to Selenium browser download.
    """

    try:
        return download_pdf_with_requests(
            url,
            output_path
        )

    except Exception as e:

        print()
        print(f"Requests download failed:")
        print(e)

        print("Trying Chrome download instead...")

        return download_pdf_with_selenium(
            driver,
            url,
            output_path
        )


def find_pdf_links_on_page(url):
    """
    Find PDF links inside webpage.
    """

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:

        r = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        r.raise_for_status()

    except Exception as e:

        print()
        print("Could not open page:")
        print(url)
        print(e)

        return []

    soup = BeautifulSoup(r.text, "html.parser")

    pdf_links = []

    for a in soup.find_all("a", href=True):

        href = a["href"]

        if ".pdf" in href.lower():

            full_url = urljoin(url, href)

            if full_url not in pdf_links:
                pdf_links.append(full_url)

    return pdf_links


def main():

    ebay_title = input(
        "Enter eBay listing title:\n> "
    ).strip()

    meaningful_title = clean_ebay_title(
        ebay_title
    )

    search_query = meaningful_title + " pdf"

    print()
    print("=" * 60)
    print("Meaningful title:")
    print(meaningful_title)

    print()
    print("Google search query:")
    print(search_query)
    print("=" * 60)

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    output_file = os.path.join(
        DOWNLOAD_DIR,
        safe_filename(meaningful_title)
    )

    driver = setup_driver(DOWNLOAD_DIR)

    try:

        results = google_search(
            driver,
            search_query,
            max_results=10
        )

        print()
        print("=" * 60)
        print("Google Results")
        print("=" * 60)

        for i, link in enumerate(results, 1):
            print(f"{i}. {link}")

        print()
        print("=" * 60)
        print("Searching for PDF")
        print("=" * 60)

        for link in results:

            print()
            print(f"Checking:")
            print(link)

            # Direct PDF
            if is_pdf_url(link):

                if download_pdf(
                    driver,
                    link,
                    output_file
                ):
                    return

            # Search PDFs inside page
            pdf_links = find_pdf_links_on_page(link)

            if pdf_links:

                print()
                print("PDF links found:")

                for pdf in pdf_links:
                    print(f"  {pdf}")

                for pdf in pdf_links:

                    if download_pdf(
                        driver,
                        pdf,
                        output_file
                    ):
                        return

        print()
        print("No PDF found automatically.")

    finally:

        print()
        print("Closing Chrome...")

        driver.quit()


if __name__ == "__main__":
    main()
