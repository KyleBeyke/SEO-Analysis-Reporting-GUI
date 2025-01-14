import sys
import os
import re
import webbrowser
from datetime import datetime
from urllib.parse import urlparse, urljoin
from collections import Counter

# PyQt5 imports
from PyQt5.QtCore import (
    Qt, QObject, pyqtSignal, pyqtSlot, QThread
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit,
    QVBoxLayout, QPushButton, QWidget, QSpinBox,
    QMessageBox, QFileDialog
)

# Selenium & related imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service

# For installing/updating ChromeDriver automatically (if desired)
from webdriver_manager.chrome import ChromeDriverManager

# Networking / parsing
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

###############################################################################
# CONSTANTS & CONFIG
###############################################################################
STOP_WORDS = {
    "the", "and", "is", "in", "it", "to", "for",
    "with", "on", "this", "a", "of", "at", "by"
}
IGNORED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
    ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz"
)
MAX_LIMIT = 999  # Absolute cap on number of links

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
    Defaults to /usr/local/bin/chromedriver if no path is provided.
    """
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    # If driver_path is None or empty, default to /usr/local/bin/chromedriver
    if not driver_path:
        driver_path = "/usr/local/bin/chromedriver"

    # If the user wants webdriver-manager logic, comment out the line below and
    # uncomment the ChromeDriverManager logic.
    driver = webdriver.Chrome(
        service=Service(driver_path),
        options=options
    )

    # Uncomment if you want webdriver-manager to install automatically:
    # driver = webdriver.Chrome(
    #     service=Service(ChromeDriverManager().install()),
    #     options=options
    # )

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
    Attempts to fetch sitemap.xml at `base_url/sitemap.xml`.
    Returns a list of URLs from <urlset><url><loc>...> (basic case).
    Raises an exception if fetching or parsing fails.
    """
    sitemap_url = base_url.rstrip('/') + "/sitemap.xml"
    if status_callback:
        status_callback(f"Trying sitemap: {sitemap_url}")
    resp = requests.get(sitemap_url, timeout=10)
    resp.raise_for_status()  # Raise an HTTPError if not 200

    # Parse the XML
    root = ET.fromstring(resp.text)
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

    # Limit final set
    max_pages = min(max_pages, MAX_LIMIT)
    if len(filtered_links) > max_pages:
        filtered_links = filtered_links[:max_pages]

    return filtered_links

def gather_links_crawl(base_url, max_pages, status_callback=None):
    """
    If no sitemap is found, do a basic BFS crawl using requests + BeautifulSoup.
    Up to `max_pages` or 999 (whichever is smaller).
    """
    visited = set()
    to_visit = [base_url]
    max_pages = min(max_pages, MAX_LIMIT)

    if status_callback:
        status_callback("Sitemap not found. Falling back to BFS crawl...")

    while to_visit and len(visited) < max_pages:
        url = to_visit.pop()
        if url in visited:
            continue
        visited.add(url)

        # Report progress if you like
        if status_callback:
            status_callback(f"Crawling: {url} ({len(visited)}/{max_pages})")

        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if (
                r.status_code == 200 and
                "text/html" in r.headers.get("Content-Type", "")
            ):
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    full_link = urljoin(url, href)
                    # Only internal links
                    if urlparse(full_link).netloc == urlparse(base_url).netloc:
                        if not any(full_link.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
                            if len(visited) + len(to_visit) < max_pages:
                                to_visit.append(full_link)
        except Exception:
            # Skip errors
            pass

    return list(visited)

###############################################################################
# ON-PAGE SEO ANALYSIS
###############################################################################
def analyze_on_page_seo(html, url):
    """
    Parse the HTML with BeautifulSoup and extract key on-page SEO factors,
    inspired by SEMrush, HubSpot, Ahrefs, Google's SEO guide, and Backlinko.
    """

    soup = BeautifulSoup(html, "html.parser")
    results = {}

    # 1) Title Tag
    title_tag = soup.find("title")
    title_text = title_tag.get_text().strip() if title_tag else ""
    results["Title"] = title_text
    results["TitleLength"] = len(title_text)

    # 2) Meta Description
    meta_desc = ""
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    if meta_desc_tag and meta_desc_tag.get("content"):
        meta_desc = meta_desc_tag["content"].strip()
    results["MetaDescription"] = meta_desc
    results["MetaDescriptionLength"] = len(meta_desc)

    # 3) H1, H2 counts
    h1_tags = soup.find_all("h1")
    h2_tags = soup.find_all("h2")
    results["H1Count"] = len(h1_tags)
    results["H2Count"] = len(h2_tags)

    # 4) Word Count (excluding STOP_WORDS)
    text_content = soup.get_text(separator=" ", strip=True)
    words = re.findall(r"\w+", text_content.lower())
    filtered_words = [w for w in words if w not in STOP_WORDS]
    results["WordCount"] = len(filtered_words)

    # 5) Image checks (alt attributes)
    images = soup.find_all("img")
    results["ImageCount"] = len(images)
    alt_missing = sum(1 for img in images if not img.get("alt"))
    results["ImagesWithoutAlt"] = alt_missing

    # 6) Canonical Link
    canonical_tag = soup.find("link", rel="canonical")
    canonical_href = canonical_tag["href"].strip() if canonical_tag and canonical_tag.get("href") else ""
    results["Canonical"] = canonical_href

    # 7) Robots Meta (noindex check)
    robots_meta = soup.find("meta", attrs={"name": re.compile(r"robots", re.I)})
    robots_content = robots_meta["content"].lower() if (robots_meta and robots_meta.get("content")) else ""
    results["Noindex"] = "noindex" in robots_content

    # 8) URL
    results["URL"] = url

    return results

def analyze_page(driver, url, status_callback, current_idx, total_count):
    """
    Loads a page via Selenium and extracts on-page SEO info.
    """
    try:
        driver.get(url)
        html = driver.page_source

        # Update status
        if status_callback:
            status_callback(f"Analyzing ({current_idx}/{total_count}): {url}")

        # Use our on-page SEO analysis function
        seo_data = analyze_on_page_seo(html, url)
        return seo_data
    except Exception as e:
        print(f"Error analyzing {url}: {e}")
        return {
            "URL": url,
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

    if not driver_pool:
        return []

    n_drivers = len(driver_pool)
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
    Worker class that:
      1) Attempts to get URLs from sitemap.xml
      2) Falls back to BFS crawling if sitemap is missing
      3) Pools Selenium drivers
      4) Analyzes pages for on-page SEO signals
      5) Saves CSV & HTML reports
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
            base_url = append_https(self.domain)
            # Ensure we never exceed 999
            max_pages = min(self.max_pages, MAX_LIMIT)

            # 1) Attempt sitemap
            links = []
            try:
                links = gather_links_from_sitemap(
                    base_url,
                    max_pages,
                    status_callback=self.statusUpdate.emit
                )
            except Exception as e:
                # If sitemap fails, fallback to BFS crawling
                self.statusUpdate.emit(f"Sitemap fetch failed: {e}")
                links = gather_links_crawl(
                    base_url,
                    max_pages,
                    status_callback=self.statusUpdate.emit
                )

            self.statusUpdate.emit(f"Collected {len(links)} URLs. Starting analysis...")

            # 2) Create driver pool & analyze
            driver_pool = create_driver_pool(n=5, driver_path=self.driver_path)
            try:
                results = analyze_pages_in_pool(
                    list(links),
                    driver_pool,
                    status_callback=self.statusUpdate.emit
                )
            finally:
                # Clean up drivers
                for drv in driver_pool:
                    drv.quit()

            self.statusUpdate.emit("Generating reports...")

            # 3) Save CSV & HTML
            domain_name = sanitize_domain(urlparse(base_url).netloc)
            current_date = datetime.now().strftime("%m%d%Y")
            csv_file = os.path.join(self.output_dir, f"on_page_seo_{domain_name}_{current_date}.csv")
            html_file = os.path.join(self.output_dir, f"on_page_seo_{domain_name}_{current_date}.html")

            df = pd.DataFrame(results)
            df.to_csv(csv_file, index=False)
            df.to_html(html_file, index=False)

            # 4) Emit success signal
            self.finished.emit(csv_file, html_file)

        except Exception as e:
            self.error.emit(str(e))

###############################################################################
# MAIN WINDOW (GUI)
###############################################################################
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("On-Page SEO Analyzer (Sitemap + Crawl Fallback)")

        # Widgets
        self.domain_label = QLabel("Domain / URL:")
        self.domain_input = QLineEdit("example.com")

        self.max_pages_label = QLabel("Max Pages (up to 999):")
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setValue(10)
        self.max_pages_spin.setRange(1, 999)  # user can pick 1..999

        self.driver_path_label = QLabel("ChromeDriver Path (optional):")
        self.driver_path_input = QLineEdit("/usr/local/bin/chromedriver")

        self.output_dir_label = QLabel("Output Directory:")
        self.output_dir_button = QPushButton("Select...")
        self.output_dir_button.clicked.connect(self.select_output_directory)

        self.start_button = QPushButton("Start Analysis")
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

        self.resize(500, 300)

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
        driver_path = self.driver_path_input.text().strip()

        # Create worker + thread
        self.scraper_thread = QThread()
        self.worker = ScraperWorker(domain, max_pages, driver_path, self.output_dir)
        self.worker.moveToThread(self.scraper_thread)

        # Connect signals
        self.scraper_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_scraper_finished)
        self.worker.error.connect(self.on_scraper_error)
        self.worker.statusUpdate.connect(self.on_status_update)

        self.worker.finished.connect(self.scraper_thread.quit)
        self.worker.error.connect(self.scraper_thread.quit)
        self.scraper_thread.finished.connect(self.cleanup_after_scraping)

        # Start
        self.scraper_thread.start()

    @pyqtSlot(str, str)
    def on_scraper_finished(self, csv_file, html_file):
        """
        Called when the worker signals it finished successfully.
        """
        QMessageBox.information(
            self,
            "Success",
            f"Report generated!\nCSV: {csv_file}\nHTML: {html_file}"
        )
        webbrowser.open(html_file)
        self.status_label.setText("Process complete. Ready for another run.")

    @pyqtSlot(str)
    def on_scraper_error(self, error_msg):
        """
        Called when the worker signals an error.
        """
        QMessageBox.critical(self, "Error", f"An error occurred: {error_msg}")
        self.status_label.setText("Error. Check logs or try again.")

    @pyqtSlot()
    def cleanup_after_scraping(self):
        """
        Cleanup references and re-enable the Start button after the thread finishes.
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
