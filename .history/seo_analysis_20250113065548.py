import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import Counter
imimport sys
import os
import re
import threading
import webbrowser
from datetime import datetime
from urllib.parse import urlparse

# PyQt5 imports
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit, QVBoxLayout, QPushButton,
    QWidget, QCheckBox, QFileDialog, QSpinBox, QMessageBox
)
from PyQt5.QtCore import Qt, QMetaObject, Q_ARG

# Selenium & related imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# BeautifulSoup, concurrency, data analysis
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from collections import Counter

###############################################################################
# GLOBALS & CONSTANTS
###############################################################################
STOP_WORDS = {'the', 'and', 'is', 'in', 'it', 'to', 'for', 'with', 'on', 'this'}
IGNORED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".pdf", ".zip", ".exe")

###############################################################################
# HELPER FUNCTIONS (placeholders & actuals)
###############################################################################
def update_status(label, message):
    """
    Safely update a QLabel text from the main thread or a worker thread.
    """
    QMetaObject.invokeMethod(
        label,
        "setText",
        Qt.QueuedConnection,
        Q_ARG(str, message)
    )

def append_https(domain):
    """
    Example placeholder: ensure the domain has an HTTPS scheme.
    Customize as needed for your environment.
    """
    if not domain.startswith("http://") and not domain.startswith("https://"):
        return "https://" + domain
    return domain

def sanitize_domain(netloc):
    """
    Remove invalid filesystem characters from the domain (for file naming).
    """
    return re.sub(r'[^a-zA-Z0-9.-]', '_', netloc)

def configure_driver(driver_path=None):
    """
    Configure and return a Selenium WebDriver with a timeout.
    """
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(
        service=Service(driver_path or ChromeDriverManager().install()),
        options=options
    )
    driver.set_page_load_timeout(15)  # Set timeout for page load
    return driver

def create_driver_pool(n, driver_path=None):
    """
    Create a pool of n Selenium WebDriver instances.
    """
    drivers = []
    for _ in range(n):
        driver = configure_driver(driver_path)
        drivers.append(driver)
    return drivers

def scrape_links_with_selenium(driver, base_url, max_pages, status_label):
    """
    Scrape internal links from the base URL using Selenium.
    Potentially you could do this with requests + BeautifulSoup if you do NOT need JS execution.
    """
    update_status(status_label, "Scraping links...")
    visited = set()
    to_visit = set([base_url])

    while to_visit and len(visited) < max_pages:
        current_url = to_visit.pop()
        if current_url in visited:
            continue

        try:
            driver.get(current_url)
            visited.add(current_url)
            links = driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                href = link.get_attribute("href")
                if href and urlparse(href).netloc == urlparse(base_url).netloc:
                    if not href.endswith(IGNORED_EXTENSIONS):
                        to_visit.add(href)
        except Exception as e:
            print(f"Error scraping {current_url}: {e}")

    return visited

def analyze_page(driver, url, status_label, current_idx, total_count):
    """
    Placeholder for your page analysis logic.
    - Load the page in Selenium
    - Possibly parse HTML with BeautifulSoup
    - Return a dictionary of results

    This is the function you originally had or plan to implement in detail.
    """
    try:
        driver.get(url)
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # Example: just count words (minus STOP_WORDS)
        words = re.findall(r'\w+', soup.get_text().lower())
        filtered_words = [w for w in words if w not in STOP_WORDS]
        word_count = Counter(filtered_words)

        # Update status so user sees progress
        update_status(status_label, f"Analyzing page {current_idx}/{total_count}: {url}")

        # Return a minimal example result dict
        return {
            "URL": url,
            "WordCount": sum(word_count.values()),
            "TopWord": word_count.most_common(1)[0][0] if word_count else ""
        }
    except Exception as e:
        print(f"Error analyzing {url}: {e}")
        return {
            "URL": url,
            "WordCount": 0,
            "TopWord": "",
            "Error": str(e)
        }

def analyze_pages_in_pool(urls, driver_pool, status_label):
    """
    Distribute the URL list among a pool of WebDrivers for concurrency.
    """
    def worker(driver, chunk, offset):
        # offset is used for human-friendly indexing in status updates
        results = []
        for i, url in enumerate(chunk):
            results.append(
                analyze_page(driver, url, status_label, offset + i + 1, len(urls))
            )
        return results

    # Split URLs among drivers
    n_drivers = len(driver_pool)
    chunk_size = len(urls) // n_drivers + 1
    chunks = [urls[i:i + chunk_size] for i in range(0, len(urls), chunk_size)]

    results = []
    with ThreadPoolExecutor(max_workers=n_drivers) as executor:
        future_to_driver = {}
        offset = 0
        for driver, chunk in zip(driver_pool, chunks):
            future = executor.submit(worker, driver, chunk, offset)
            future_to_driver[future] = driver
            offset += len(chunk)

        for future in as_completed(future_to_driver):
            try:
                results.extend(future.result())
            except Exception as e:
                print(f"Error in driver thread: {e}")

    return results

def generate_report(base_url, driver_path, max_pages, output_dir, status_label):
    """
    Generate SEO report with analysis results.

    1) Use a single driver to collect internal links (scrape_links_with_selenium).
    2) Create a pool of drivers to analyze each link concurrently.
    3) Save CSV & HTML reports.
    """
    # Step 1: Use a single driver to gather links quickly
    single_driver = configure_driver(driver_path)
    try:
        links = scrape_links_with_selenium(single_driver, base_url, max_pages, status_label)
    finally:
        single_driver.quit()

    update_status(status_label, f"Found {len(links)} links. Starting analysis...")

    # Step 2: Create a driver pool & analyze concurrently
    driver_pool = create_driver_pool(n=5, driver_path=driver_path)
    try:
        results = analyze_pages_in_pool(list(links), driver_pool, status_label)
    finally:
        # Clean up every driver
        for drv in driver_pool:
            drv.quit()

    update_status(status_label, "Generating reports...")

    # Step 3: Save reports
    domain_name = sanitize_domain(urlparse(base_url).netloc)
    current_date = datetime.now().strftime("%m%d%Y")
    csv_file = os.path.join(output_dir, f"seo_report_{domain_name}_{current_date}.csv")
    html_file = os.path.join(output_dir, f"seo_report_{domain_name}_{current_date}.html")

    df = pd.DataFrame(results)
    df.to_csv(csv_file, index=False)
    df.to_html(html_file, index=False)

    return csv_file, html_file

def start_scraper_thread(domain, max_pages, driver_path, output_dir, status_label):
    """
    Run the scraper in a separate thread so the GUI remains responsive.
    """
    def run_scraper():
        try:
            base_url = append_https(domain)
            csv_file, html_file = generate_report(
                base_url, driver_path, max_pages, output_dir, status_label
            )
            update_status(status_label, "Process complete. Ready for another run.")

            # Show success message (must invoke on main thread)
            QMetaObject.invokeMethod(
                None,
                lambda: QMessageBox.information(
                    None, "Success", f"Report generated!\nCSV: {csv_file}\nHTML: {html_file}"
                ),
                Qt.QueuedConnection
            )
            # Optionally open HTML report in browser
            webbrowser.open(html_file)
        except Exception as e:
            update_status(status_label, f"Error: {e}")
            QMetaObject.invokeMethod(
                None,
                lambda: QMessageBox.critical(None, "Error", f"An error occurred: {e}"),
                Qt.QueuedConnection
            )

    threading.Thread(target=run_scraper, daemon=True).start()

###############################################################################
# MAIN WINDOW (GUI)
###############################################################################
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SEO Scraper & Analyzer")

        # Widgets
        self.domain_label = QLabel("Domain / URL:")
        self.domain_input = QLineEdit("example.com")

        self.max_pages_label = QLabel("Max Pages:")
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setValue(10)

        self.driver_path_label = QLabel("ChromeDriver Path (optional):")
        self.driver_path_input = QLineEdit()

        self.output_dir_label = QLabel("Output Directory:")
        self.output_dir_button = QPushButton("Select...")
        self.output_dir_button.clicked.connect(self.select_output_directory)

        self.start_button = QPushButton("Start Scraping & Analysis")
        self.start_button.clicked.connect(self.start_scraping)

        self.status_label = QLabel("Ready.")
        self.status_label.setAlignment(Qt.AlignCenter)

        self.output_dir = os.getcwd()

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.domain_label)
        layout.addWidget(self.domain_input)

        layout.addWidget(self.max_pages_label)
        layout.addWidget(self.max_pages_spin)

        layout.addWidget(self.driver_path_label)
        layout.addWidget(self.driver_path_input)

        layout.addWidget(self.output_dir_label)
        layout.addWidget(self.output_dir_button)

        layout.addWidget(self.start_button)
        layout.addWidget(self.status_label)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.resize(400, 300)

    def select_output_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.output_dir = folder

    def start_scraping(self):
        self.start_button.setEnabled(False)
        update_status(self.status_label, "Working...")

        domain = self.domain_input.text().strip()
        max_pages = self.max_pages_spin.value()
        driver_path = self.driver_path_input.text().strip() or None

        # Launch worker thread
        threading.Thread(target=self.run_scraper_in_thread, args=(domain, max_pages, driver_path), daemon=True).start()

    def run_scraper_in_thread(self, domain, max_pages, driver_path):
        try:
            start_scraper_thread(domain, max_pages, driver_path, self.output_dir, self.status_label)
        finally:
            # Re-enable the button once the thread for scraping/analysis has actually started
            # (not necessarily finished). If you want to enable only after it's finished,
            # move this line to the end of the run_scraper() function or handle differently.
            QMetaObject.invokeMethod(
                self.start_button,
                "setEnabled",
                Qt.QueuedConnection,
                Q_ARG(bool, True)
            )

###############################################################################
# MAIN ENTRY POINT
###############################################################################
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
