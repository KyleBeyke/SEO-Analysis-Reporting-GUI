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

# For auto-installing/updating ChromeDriver if desired
from webdriver_manager.chrome import ChromeDriverManager

# Parsing/Networking
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from bs4 import BeautifulSoup

###############################################################################
# GLOBAL CONFIG & CONSTANTS
###############################################################################
STOP_WORDS = {
    "the", "and", "is", "in", "it", "to", "for",
    "with", "on", "this", "a", "of", "at", "by"
}
IGNORED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
    ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz"
)
MAX_LIMIT = 999  # Hard cap on number of links

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

def normalize_netloc(netloc: str) -> str:
    """
    Remove 'www.' prefix to unify domain checks if desired.
    """
    return netloc.lower().replace("www.", "")

def configure_driver(driver_path=None):
    """
    Configure and return a Selenium WebDriver with a timeout.
    Defaults to /usr/local/bin/chromedriver if none is provided.
    """
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    if not driver_path:
        driver_path = "/usr/local/bin/chromedriver"  # default path

    driver = webdriver.Chrome(
        service=Service(driver_path),
        options=options
    )
    driver.set_page_load_timeout(15)
    return driver

def create_driver_pool(n, driver_path=None):
    """
    Create a pool of n Selenium WebDriver instances.
    """
    drivers = []
    for _ in range(n):
        drivers.append(configure_driver(driver_path))
    return drivers


###############################################################################
# SITEMAP PARSING (handles sitemap index or urlset)
###############################################################################
def parse_sitemap_xml(xml_content):
    """
    Parse a sitemap or sitemap index. Return:
      - sub_sitemaps: list of child sitemaps if it's a sitemapindex
      - links: list of URLs if it's a urlset
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise RuntimeError(f"Error parsing sitemap XML: {e}")

    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    tag_name = root.tag.lower()

    sub_sitemaps = []
    links = []

    # If this is a sitemap index (<sitemapindex>...</sitemapindex>)
    if "sitemapindex" in tag_name:
        for sitemap_tag in root.findall(f"{ns}sitemap"):
            loc_tag = sitemap_tag.find(f"{ns}loc")
            if loc_tag is not None and loc_tag.text:
                sub_sitemaps.append(loc_tag.text.strip())

    # If this is a urlset (<urlset>...</urlset>)
    elif "urlset" in tag_name:
        for url_tag in root.findall(f"{ns}url"):
            loc_tag = url_tag.find(f"{ns}loc")
            if loc_tag is not None and loc_tag.text:
                links.append(loc_tag.text.strip())

    return sub_sitemaps, links

def gather_links_from_sitemap(base_url, max_pages, status_callback=None):
    """
    1) Fetch /sitemap.xml
    2) If it's a sitemap index, parse each sub-sitemap, recursively if needed.
    3) If it's a urlset, gather those links.
    4) Return a list of unique links (up to max_pages).
    Raises an exception if we can't fetch or parse.
    """
    main_sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
    if status_callback:
        status_callback(f"Attempting to fetch sitemap: {main_sitemap_url}")

    resp = requests.get(main_sitemap_url, timeout=10, allow_redirects=True)
    resp.raise_for_status()  # If 4xx or 5xx, this triggers an exception

    sub_sitemaps, links = parse_sitemap_xml(resp.text)

    collected_links = set()
    to_process = sub_sitemaps[:]  # sub-sitemaps from main index

    # If the main doc was a urlset, add those links
    for link in links:
        collected_links.add(link)
    # limit check
    if len(collected_links) >= max_pages:
        return list(collected_links)[:max_pages]

    # BFS over sub-sitemaps
    while to_process and len(collected_links) < max_pages:
        sitemap_url = to_process.pop()
        if status_callback:
            status_callback(f"Fetching sub-sitemap: {sitemap_url}")
        try:
            r = requests.get(sitemap_url, timeout=10, allow_redirects=True)
            r.raise_for_status()
            subs, sublinks = parse_sitemap_xml(r.text)
            # If more sub-sitemaps found, add them
            to_process.extend(subs)
            # If it has <urlset> links
            for link in sublinks:
                collected_links.add(link)
                if len(collected_links) >= max_pages:
                    break

        except Exception as e:
            # One sub-sitemap might fail, we skip it
            if status_callback:
                status_callback(f"Warning: Failed {sitemap_url}: {e}")

    # Filter out ignored extensions
    filtered = []
    for link in collected_links:
        if not any(link.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
            filtered.append(link)

    return filtered[:max_pages]


###############################################################################
# FALLBACK BFS USING SELENIUM
###############################################################################
def gather_links_selenium_bfs(base_url, max_pages, status_callback=None, driver_path=None):
    """
    BFS crawling with Selenium to find internal links if the sitemap approach fails
    or yields zero links.
    - Single-driver BFS. For large sites, you might want concurrency,
      but BFS with a single driver is simpler.
    """
    if status_callback:
        status_callback("Sitemap not found or empty. Falling back to BFS with Selenium...")

    visited = set()
    to_visit = [base_url]
    max_pages = min(max_pages, MAX_LIMIT)
    driver = configure_driver(driver_path)
    try:
        base_netloc = normalize_netloc(urlparse(base_url).netloc)

        while to_visit and len(visited) < max_pages:
            current_url = to_visit.pop()
            if current_url in visited:
                continue
            visited.add(current_url)

            if status_callback:
                status_callback(f"[BFS] Visiting {current_url} ({len(visited)}/{max_pages})")

            try:
                driver.get(current_url)
                a_tags = driver.find_elements(By.TAG_NAME, "a")
                for a in a_tags:
                    href = a.get_attribute("href")
                    if href:
                        # same domain check
                        link_netloc = normalize_netloc(urlparse(href).netloc)
                        if link_netloc == base_netloc:
                            if not any(href.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
                                if len(visited) + len(to_visit) < max_pages:
                                    to_visit.append(href)
            except Exception:
                pass
    finally:
        driver.quit()

    return list(visited)


###############################################################################
# ON-PAGE SEO ANALYSIS
###############################################################################
def analyze_on_page_seo(html, url):
    """
    Parse the HTML with BeautifulSoup and extract key on-page SEO factors.
    (Inspired by SEMrush, HubSpot, Ahrefs, Google's SEO guide, Backlinko, etc.)
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

    # 8) Final URL
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

        return analyze_on_page_seo(html, url)
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
        results_ = []
        for i, url in enumerate(chunk):
            results_.append(analyze_page(driver, url, status_callback, offset + i + 1, len(urls)))
        return results_

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
      1) Tries to parse domain.com/sitemap.xml (following redirect to index, if any).
      2) If sub-sitemaps exist, parse them. Collect up to max_pages links total.
      3) If no sitemaps or no links found, fallback to BFS crawling using Selenium.
      4) Analyze pages concurrently with a pool of Selenium drivers.
      5) Save CSV & HTML reports.
    """
    finished = pyqtSignal(str, str)  # On success: (csv_file, html_file)
    error = pyqtSignal(str)          # On error: (error_msg)
    statusUpdate = pyqtSignal(str)   # For live status updates

    def __init__(self, domain, max_pages, driver_path, output_dir):
        super().__init__()
        self.domain = domain
        self.max_pages = min(max_pages, MAX_LIMIT)
        self.driver_path = driver_path
        self.output_dir = output_dir

    @pyqtSlot()
    def run(self):
        """
        Main worker method, executed in a separate thread.
        """
        try:
            base_url = append_https(self.domain)

            # 1) Try to gather links via sitemap
            links = []
            try:
                links = gather_links_from_sitemap(
                    base_url,
                    self.max_pages,
                    status_callback=self.statusUpdate.emit
                )
            except Exception as e:
                self.statusUpdate.emit(f"Sitemap attempt failed: {e}")
                # We'll do BFS fallback below

            if not links:
                # 2) Fallback BFS with Selenium
                links = gather_links_selenium_bfs(
                    base_url,
                    self.max_pages,
                    status_callback=self.statusUpdate.emit,
                    driver_path=self.driver_path
                )

            # Filter out duplicates and limit
            unique_links = list(dict.fromkeys(links))  # preserve order
            if len(unique_links) > self.max_pages:
                unique_links = unique_links[:self.max_pages]

            self.statusUpdate.emit(f"Collected {len(unique_links)} URLs. Starting analysis...")

            # 3) Create driver pool & analyze
            driver_pool = create_driver_pool(n=5, driver_path=self.driver_path)
            try:
                results = analyze_pages_in_pool(
                    unique_links,
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
            csv_file = os.path.join(self.output_dir, f"on_page_seo_{domain_name}_{current_date}.csv")
            html_file = os.path.join(self.output_dir, f"on_page_seo_{domain_name}_{current_date}.html")

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
        self.setWindowTitle("On-Page SEO Analyzer (Sitemap + Fallback to Selenium BFS)")

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

        self.resize(550, 350)

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
