import sys
import os
import re
import webbrowser
from datetime import datetime
from urllib.parse import urlparse
from collections import Counter

# PyQt5 imports
from PyQt5.QtCore import (
    Qt, QObject, pyqtSignal, pyqtSlot, QThread
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit, QVBoxLayout,
    QPushButton, QWidget, QSpinBox, QMessageBox, QFileDialog
)

# Selenium & related imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# BeautifulSoup, concurrency, data analysis
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

# For sitemap parsing
import requests
import xml.etree.ElementTree as ET

###############################################################################
# CONSTANTS
###############################################################################
STOP_WORDS = {'the', 'and', 'is', 'in', 'it', 'to', 'for', 'with', 'on', 'this'}
IGNORED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
    ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz"
)

###############################################################################
# HELPER FUNCTIONS
###############################################################################
def append_https(domain: str) -> str:
    """
    Ensure the domain has an HTTP/HTTPS scheme.
    """
    domain = domain.strip()
    if not domain.startswith("http://") and not domain.startswith("https://"):
        return "https://" + domain
    return domain

def sanitize_domain(netloc: str) -> str:
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
        drivers.append(configure_driver(driver_path))
    return drivers

def gather_links_from_sitemap(base_url, max_pages, status_callback=None):
    """
    Fetch links from sitemap.xml at `base_url/sitemap.xml`.
    If the site has multiple or nested sitemaps, you will need to adapt this.
    """
    sitemap_url = base_url.rstrip('/') + "/sitemap.xml"
    if status_callback:
        status_callback(f"Fetching sitemap from: {sitemap_url}")

    try:
        resp = requests.get(sitemap_url, timeout=10)
        resp.raise_for_status()  # Raise an HTTPError if not 200
    except Exception as e:
        raise RuntimeError(f"Failed to fetch sitemap: {e}")

    # Parse XML
    try:
        root = ET.fromstring(resp.text)
    except Exception as e:
        raise RuntimeError(f"Error parsing sitemap XML: {e}")

    # Typically, sitemap.xml has <urlset><url><loc>... or <sitemapindex> structures.
    # We'll handle the simplest case: <urlset><url><loc>....
    # For more complex sitemaps or <sitemapindex>, adjust as needed.
    found_links = []
    for url_tag in root.findall(".//{*}url"):
        loc_tag = url_tag.find("{*}loc")
        if loc_tag is not None:
            found_links.append(loc_tag.text.strip())

    # Filter out ignored extensions
    filtered_links = []
    for link in found_links:
        if not any(link.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
            filtered_links.append(link)

    # Limit to max_pages if desired
    if len(filtered_links) > max_pages:
        filtered_links = filtered_links[:max_pages]

    return filtered_links

def analyze_page(driver, url, status_callback, current_idx, total_count):
    """
    Analyze a single page with Selenium + BeautifulSoup.
    Replace with your actual SEO checks or other analysis.
    """
    try:
        driver.get(url)
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # Example: Count words minus STOP_WORDS
        words = re.findall(r'\w+', soup.get_text().lower())
        filtered_words = [w for w in words if w not in STOP_WORDS]
        word_count = Counter(filtered_words)

        if status_callback:
            status_callback(f"Analyzing page {current_idx}/{total_count}: {url}")

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

def analyze_pages_in_pool(urls, driver_pool, status_callback):
    """
    Distribute the URL list among a pool of WebDrivers for concurrency.
    """
    def worker(driver, chunk, offset):
        results = []
        for i, url in enumerate(chunk):
            results.append(analyze_page(driver, url, status_callback, offset + i + 1, len(urls)))
        return results

    n_drivers = len(driver_pool)
    if not n_drivers:
        return []

    chunk_size = max(1, len(urls) // n_drivers + 1)
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
                print(f"Error in thread: {e}")

    return results

###############################################################################
# WORKER CLASS (Runs in a separate QThread)
###############################################################################
class ScraperWorker(QObject):
    """
    Worker class that performs:
      1) Gathering links from sitemap.xml
      2) Creating a Selenium driver pool
      3) Concurrently analyzing each page
      4) Saving CSV and HTML reports
    Signals are emitted to safely update the GUI in the main thread.
    """
    finished = pyqtSignal(str, str)  # On success: (csv_file, html_file)
    error = pyqtSignal(str)          # On error: (error_msg)
    statusUpdate = pyqtSignal(str)   # For live status updates

    def __init__(self, domain, max_pages, driver_path, output_dir):
        super().__init__()
        self.domain = domain
        self.max_pages = max_pages
        self.driver_path = driver_path
        self.output_dir = output_dir

    @pyqtSlot()
    def run(self):
        """
        Main worker method, executed in a separate thread.
        """
        try:
            # 1) Prepare base URL
            base_url = append_https(self.domain)

            # 2) Gather links from sitemap.xml
            self.statusUpdate.emit("Gathering links from sitemap...")
            links = gather_links_from_sitemap(
                base_url,
                self.max_pages,
                status_callback=self.statusUpdate.emit
            )
            self.statusUpdate.emit(f"Found {len(links)} links. Starting analysis...")

            # 3) Create a pool of drivers & analyze concurrently
            driver_pool = create_driver_pool(n=5, driver_path=self.driver_path)
            try:
                results = analyze_pages_in_pool(
                    list(links),
                    driver_pool,
                    status_callback=self.statusUpdate.emit
                )
            finally:
                for drv in driver_pool:
                    drv.quit()

            self.statusUpdate.emit("Generating reports...")

            # 4) Save CSV & HTML
            domain_name = sanitize_domain(urlparse(base_url).netloc)
            current_date = datetime.now().strftime("%m%d%Y")
            csv_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{current_date}.csv")
            html_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{current_date}.html")

            df = pd.DataFrame(results)
            df.to_csv(csv_file, index=False)
            df.to_html(html_file, index=False)

            # 5) Emit success signal
            self.finished.emit(csv_file, html_file)

        except Exception as e:
            self.error.emit(str(e))

###############################################################################
# MAIN WINDOW (GUI)
###############################################################################
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SEO Scraper & Analyzer (Sitemap Edition)")

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

        # We'll keep a reference to the worker thread to manage or cleanup if necessary.
        self.scraper_thread = None

    def select_output_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.output_dir = folder

    def start_scraping(self):
        self.start_button.setEnabled(False)
        self.status_label.setText("Initializing...")

        domain = self.domain_input.text().strip()
        max_pages = self.max_pages_spin.value()
        driver_path = self.driver_path_input.text().strip() or None

        # Create worker and thread
        self.scraper_thread = QThread()
        self.worker = ScraperWorker(domain, max_pages, driver_path, self.output_dir)

        # Move the worker to the thread
        self.worker.moveToThread(self.scraper_thread)

        # Connect signals
        self.scraper_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_scraper_finished)
        self.worker.error.connect(self.on_scraper_error)
        self.worker.statusUpdate.connect(self.on_status_update)

        # When the worker finishes (or errors), we quit the thread
        self.worker.finished.connect(self.scraper_thread.quit)
        self.worker.error.connect(self.scraper_thread.quit)

        # Once the thread is finished, delete the worker and re-enable the button
        self.scraper_thread.finished.connect(self.cleanup_after_scraping)

        # Start the thread
        self.scraper_thread.start()

    @pyqtSlot(str, str)
    def on_scraper_finished(self, csv_file, html_file):
        """
        Called when the worker signals it finished successfully.
        """
        # Show success message
        QMessageBox.information(
            self,
            "Success",
            f"Report generated!\nCSV: {csv_file}\nHTML: {html_file}"
        )
        # Optionally open HTML report in browser
        webbrowser.open(html_file)

        # Update status
        self.status_label.setText("Process complete. Ready for another run.")

    @pyqtSlot(str)
    def on_scraper_error(self, error_msg):
        """
        Called when the worker signals an error.
        """
        QMessageBox.critical(self, "Error", f"An error occurred: {error_msg}")
        self.status_label.setText("Error occurred. Check logs or try again.")

    @pyqtSlot()
    def cleanup_after_scraping(self):
        """
        Cleanup references and re-enable the UI after the thread finishes.
        """
        self.scraper_thread = None
        self.worker = None
        self.start_button.setEnabled(True)

    @pyqtSlot(str)
    def on_status_update(self, message):
        """
        Update the status label from worker signals.
        """
        self.status_label.setText(message)

###############################################################################
# MAIN ENTRY POINT
###############################################################################
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
