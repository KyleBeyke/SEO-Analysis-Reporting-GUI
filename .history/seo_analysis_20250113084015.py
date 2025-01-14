import sys
import os
import re
import threading
import queue
import webbrowser
from datetime import datetime
from urllib.parse import urlparse
from collections import Counter

# PyQt5 imports
from PyQt5.QtCore import (
    Qt, QObject, pyqtSignal, pyqtSlot, QThread
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit,
    QVBoxLayout, QPushButton, QWidget, QSpinBox,
    QMessageBox, QFileDialog, QProgressBar
)

# Selenium & related imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service

# For auto-installing/updating ChromeDriver if desired
from webdriver_manager.chrome import ChromeDriverManager

# Networking / parsing
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

###############################################################################
# GLOBAL CONFIG & CONSTANTS
###############################################################################
STOP_WORDS = {
    "the", "and", "is", "in", "it", "to", "for",
    "with", "on", "this", "a", "of", "at", "by",
    "be", "are", "that", "from", "or", "as", "an",
    "was", "were", "can", "could", "would", "should",
    "will", "their", "they", "them", "he", "she",
    "we", "you", "your", "i", "am", "my", "me"
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
    """Ensure the domain has an HTTP/HTTPS scheme."""
    domain = domain.strip()
    if not domain.startswith("http://") and not domain.startswith("https://"):
        return "https://" + domain
    return domain

def sanitize_domain(netloc: str) -> str:
    """Remove invalid filesystem characters from the domain."""
    return re.sub(r'[^a-zA-Z0-9.-]', '_', netloc)

def normalize_netloc(netloc: str) -> str:
    """Remove 'www.' prefix to unify domain checks if desired."""
    return netloc.lower().replace("www.", "")

def configure_driver(driver_path=None):
    """Configure and return a Selenium WebDriver with a timeout."""
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

###############################################################################
# SITEMAP PARSING (supports sitemap index or urlset)
###############################################################################
def parse_sitemap_xml(xml_content):
    """
    Parse a sitemap or sitemap index. Return:
      - sub_sitemaps: list of child sitemaps if it's a sitemapindex
      - links: list of URLs if it's a urlset
    """
    root = ET.fromstring(xml_content)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    tag_name = root.tag.lower()

    sub_sitemaps = []
    links = []

    if "sitemapindex" in tag_name:  # <sitemapindex>...</sitemapindex>
        for sitemap_tag in root.findall(f"{ns}sitemap"):
            loc_tag = sitemap_tag.find(f"{ns}loc")
            if loc_tag is not None and loc_tag.text:
                sub_sitemaps.append(loc_tag.text.strip())
    elif "urlset" in tag_name:  # <urlset>...</urlset>
        for url_tag in root.findall(f"{ns}url"):
            loc_tag = url_tag.find(f"{ns}loc")
            if loc_tag is not None and loc_tag.text:
                links.append(loc_tag.text.strip())

    return sub_sitemaps, links

def gather_links_from_sitemap(base_url, max_pages, status_callback=None):
    """
    1) Fetch /sitemap.xml.
    2) If it's a sitemap index, parse each sub-sitemap recursively.
    3) If it's a urlset, gather those links.
    4) Return up to max_pages unique links.
    """
    main_sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
    if status_callback:
        status_callback(f"Attempting to fetch sitemap: {main_sitemap_url}")

    resp = requests.get(main_sitemap_url, timeout=10, allow_redirects=True)
    resp.raise_for_status()

    sub_sitemaps, links = parse_sitemap_xml(resp.text)
    collected_links = set()
    to_process = sub_sitemaps[:]

    for link in links:
        collected_links.add(link)
    if len(collected_links) >= max_pages:
        return list(collected_links)[:max_pages]

    # BFS or DFS over sub-sitemaps
    while to_process and len(collected_links) < max_pages:
        sitemap_url = to_process.pop()
        if status_callback:
            status_callback(f"Fetching sub-sitemap: {sitemap_url}")
        try:
            r = requests.get(sitemap_url, timeout=10, allow_redirects=True)
            r.raise_for_status()
            subs, sublinks = parse_sitemap_xml(r.text)
            to_process.extend(subs)
            for link in sublinks:
                collected_links.add(link)
                if len(collected_links) >= max_pages:
                    break
        except Exception as e:
            if status_callback:
                status_callback(f"Warning: Failed {sitemap_url}: {e}")

    # Filter out ignored
    filtered = []
    for link in collected_links:
        if not any(link.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
            filtered.append(link)

    return filtered[:max_pages]

###############################################################################
# CONCURRENT BFS USING MULTIPLE SELENIUM DRIVERS (CAPTURES JS LINKS)
###############################################################################
def selenium_bfs_concurrent(base_url, max_pages, status_callback, driver_count=3, driver_path=None):
    """
    A concurrent BFS approach using multiple Selenium WebDrivers.
    - We maintain a shared queue of URLs to visit, plus a visited set.
    - Each driver in a thread continuously pops URLs from the queue,
      loads them, collects <a> links, and enqueues new ones if under max_pages.
    """
    if status_callback:
        status_callback("Sitemap not found or empty. Falling back to CONCURRENT BFS with Selenium...")

    visited = set()
    q = queue.Queue()
    base_netloc = normalize_netloc(urlparse(base_url).netloc)
    q.put(base_url)

    def bfs_worker(driver):
        while True:
            try:
                current_url = q.get(timeout=3)
            except queue.Empty:
                return  # no more URLs

            if current_url in visited:
                q.task_done()
                continue

            visited.add(current_url)
            idx = len(visited)
            if status_callback:
                status_callback(f"[BFS] Visiting {current_url} ({idx}/{max_pages})")

            try:
                driver.get(current_url)
                a_tags = driver.find_elements(By.TAG_NAME, "a")
                for a in a_tags:
                    href = a.get_attribute("href") or ""
                    if not href:
                        continue
                    if any(href.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
                        continue

                    link_netloc = normalize_netloc(urlparse(href).netloc)
                    if link_netloc == base_netloc:
                        if len(visited) + q.qsize() < max_pages:
                            if href not in visited:
                                q.put(href)
            except Exception:
                pass
            finally:
                q.task_done()

    # Launch multiple drivers/threads
    drivers = [configure_driver(driver_path) for _ in range(driver_count)]
    threads = []
    for d in drivers:
        t = threading.Thread(target=bfs_worker, args=(d,), daemon=True)
        threads.append(t)
        t.start()

    q.join()  # wait until queue is empty
    for d in drivers:
        try:
            d.quit()
        except:
            pass

    return list(visited)[:max_pages]

###############################################################################
# ON-PAGE ANALYSIS: SEO + KEYWORDS
###############################################################################
def extract_keywords_from_text(text):
    """
    Extract words from text, ignoring STOP_WORDS.
    Return a Counter of keywords (descending frequency).
    Approach is simplistic, but tries to mimic "keywords" logic by ignoring common words.
    """
    words = re.findall(r"\w+", text.lower())
    filtered = [w for w in words if w not in STOP_WORDS]
    return Counter(filtered)

def analyze_page(driver, url, status_callback, current_idx, total_count, sitewide_word_counts):
    """
    Load a page in Selenium, parse HTML, do minimal SEO checks, and extract top keywords.
    * sitewide_word_counts is a global (shared) Counter that we'll update for each page.
    """
    data = {
        "URL": url,
        "Title": "",
        "TitleLength": 0,
        "MetaDescription": "",
        "MetaDescriptionLength": 0,
        "H1Count": 0,
        "H2Count": 0,
        "WordCount": 0,
        "Keywords": "",
        "Error": ""
    }

    try:
        driver.get(url)
        if status_callback:
            status_callback(f"Analyzing ({current_idx}/{total_count}): {url}")

        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        # Title
        title_tag = soup.find("title")
        title_text = title_tag.get_text().strip() if title_tag else ""
        data["Title"] = title_text
        data["TitleLength"] = len(title_text)

        # Meta description
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = ""
        if meta_desc_tag and meta_desc_tag.get("content"):
            meta_desc = meta_desc_tag["content"].strip()
        data["MetaDescription"] = meta_desc
        data["MetaDescriptionLength"] = len(meta_desc)

        # H1, H2
        h1_tags = soup.find_all("h1")
        h2_tags = soup.find_all("h2")
        data["H1Count"] = len(h1_tags)
        data["H2Count"] = len(h2_tags)

        # Text-based keyword extraction
        text_content = soup.get_text(separator=" ", strip=True)
        word_counts = extract_keywords_from_text(text_content)
        data["WordCount"] = sum(word_counts.values())

        # Update global sitewide counter
        sitewide_word_counts.update(word_counts)

        # Top 5 keywords for this page
        top_5 = word_counts.most_common(5)
        # Format them as "keyword(count)" ...
        formatted = [f"{k}({v})" for (k, v) in top_5]
        data["Keywords"] = ", ".join(formatted)

    except Exception as e:
        data["Error"] = str(e)

    return data

def analyze_pages_in_pool(urls, driver_path, status_callback, progress_callback, sitewide_word_counts):
    """
    Distribute the list of URLs among multiple Selenium drivers.
    Each page is analyzed for Title, MetaDesc, H1/H2, top 5 keywords, etc.
    Also updates a sitewide_word_counts Counter to capture all keywords across pages.
    """
    def worker(driver, chunk, offset):
        results_local = []
        for i, url in enumerate(chunk):
            page_data = analyze_page(
                driver=driver,
                url=url,
                status_callback=status_callback,
                current_idx=offset + i + 1,
                total_count=len(urls),
                sitewide_word_counts=sitewide_word_counts
            )
            results_local.append(page_data)
            if progress_callback:
                progress_callback(1)
        return results_local

    if not urls:
        return []

    n_drivers = 5
    drivers = [configure_driver(driver_path) for _ in range(n_drivers)]

    chunk_size = max(1, len(urls) // n_drivers + 1)
    chunks = [urls[i:i + chunk_size] for i in range(0, len(urls), chunk_size)]
    results = []

    with ThreadPoolExecutor(max_workers=n_drivers) as executor:
        future_map = {}
        offset = 0
        for drv, chunk in zip(drivers, chunks):
            fut = executor.submit(worker, drv, chunk, offset)
            future_map[fut] = drv
            offset += len(chunk)

        for fut in as_completed(future_map):
            try:
                results.extend(fut.result())
            except Exception as e:
                print(f"Error in thread: {e}")

    for d in drivers:
        try:
            d.quit()
        except:
            pass

    return results

###############################################################################
# WORKER CLASS (Runs in a separate QThread)
###############################################################################
class ScraperWorker(QObject):
    """
    1) Attempt sitemap.
    2) If no links, do concurrent BFS (Selenium).
    3) Analyze pages (Title, Desc, H1, H2, top 5 keywords).
    4) Collect sitewide keywords => top 10 => final row "SITEWIDE".
    5) Output CSV & HTML.
    6) Provide indefinite progress for link collection, then definite progress for analysis.
    """
    finished = pyqtSignal(str, str)      # (csv_file, html_file)
    error = pyqtSignal(str)             # error message
    statusUpdate = pyqtSignal(str)      # textual status
    analysisProgress = pyqtSignal(int, int)  # (current, total) for progress bar

    def __init__(self, domain, max_pages, driver_path, output_dir):
        super().__init__()
        self.domain = domain
        self.max_pages = min(max_pages, MAX_LIMIT)
        self.driver_path = driver_path
        self.output_dir = output_dir

        self.sitewide_word_counts = Counter()  # accumulate across all pages

        self.current_count = 0
        self.total_count = 0

    @pyqtSlot()
    def run(self):
        try:
            base_url = append_https(self.domain)

            # 1) Try sitemap
            links = []
            try:
                links = gather_links_from_sitemap(
                    base_url,
                    self.max_pages,
                    status_callback=self.statusUpdate.emit
                )
            except Exception as e:
                self.statusUpdate.emit(f"Sitemap attempt failed: {e}")

            # 2) If no links found, fallback to BFS
            if not links:
                links = selenium_bfs_concurrent(
                    base_url,
                    self.max_pages,
                    status_callback=self.statusUpdate.emit,
                    driver_count=3,
                    driver_path=self.driver_path
                )

            unique_links = list(dict.fromkeys(links))  # preserve order, remove duplicates
            if len(unique_links) > self.max_pages:
                unique_links = unique_links[:self.max_pages]

            self.statusUpdate.emit(f"Collected {len(unique_links)} URLs. Starting analysis...")

            self.current_count = 0
            self.total_count = len(unique_links)

            # Indefinite -> definite progress
            def increment_analysis_progress(x=1):
                self.current_count += x
                self.analysisProgress.emit(self.current_count, self.total_count)

            # 3) Analyze pages in concurrency
            results = analyze_pages_in_pool(
                urls=unique_links,
                driver_path=self.driver_path,
                status_callback=self.statusUpdate.emit,
                progress_callback=increment_analysis_progress,
                sitewide_word_counts=self.sitewide_word_counts
            )

            self.statusUpdate.emit("Generating final keywords...")

            # 4) Create a final row with "SITEWIDE" top 10 keywords
            top_10_sitewide = self.sitewide_word_counts.most_common(10)
            top_10_str = [f"{k}({v})" for (k, v) in top_10_sitewide]
            sitewide_row = {
                "URL": "SITEWIDE",
                "Title": "",
                "TitleLength": 0,
                "MetaDescription": "",
                "MetaDescriptionLength": 0,
                "H1Count": 0,
                "H2Count": 0,
                "WordCount": sum(self.sitewide_word_counts.values()),
                "Keywords": ", ".join(top_10_str),
                "Error": ""
            }
            results.append(sitewide_row)

            self.statusUpdate.emit("Writing reports...")

            # 5) Write CSV & HTML
            domain_name = sanitize_domain(urlparse(base_url).netloc)
            date_str = datetime.now().strftime("%Y%m%d_%H%M")
            csv_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{date_str}.csv")
            html_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{date_str}.html")

            df = pd.DataFrame(results)
            df.to_csv(csv_file, index=False)
            df.to_html(html_file, index=False)

            # 6) Done
            self.finished.emit(csv_file, html_file)

        except Exception as e:
            self.error.emit(str(e))

###############################################################################
# MAIN WINDOW (GUI)
###############################################################################
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("On-Page SEO & Keyword Analyzer")

        # Widgets
        self.domain_label = QLabel("Domain / URL:")
        self.domain_input = QLineEdit("example.com")

        self.max_pages_label = QLabel("Max Pages (up to 999):")
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setValue(10)
        self.max_pages_spin.setRange(1, 999)

        self.driver_path_label = QLabel("ChromeDriver Path (optional):")
        self.driver_path_input = QLineEdit("/usr/local/bin/chromedriver")

        self.output_dir_label = QLabel("Output Directory:")
        self.output_dir_button = QPushButton("Select...")
        self.output_dir_button.clicked.connect(self.select_output_directory)

        # Show chosen directory in a label
        self.chosen_dir_label = QLabel(os.getcwd())

        self.start_button = QPushButton("Start Analysis")
        self.start_button.clicked.connect(self.start_scraping)

        self.status_label = QLabel("Ready.")
        self.status_label.setAlignment(Qt.AlignCenter)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setAlignment(Qt.AlignCenter)

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
        layout.addWidget(self.chosen_dir_label)

        layout.addWidget(self.start_button)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.resize(700, 400)

        self.scraper_thread = None

    def select_output_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.output_dir = folder
            self.chosen_dir_label.setText(folder)

    def start_scraping(self):
        self.start_button.setEnabled(False)
        self.status_label.setText("Initializing...")

        # Indefinite progress bar while collecting links
        self.progress_bar.setRange(0, 0)

        domain = self.domain_input.text().strip()
        max_pages = self.max_pages_spin.value()
        driver_path = self.driver_path_input.text().strip()

        # Worker + thread
        self.scraper_thread = QThread()
        self.worker = ScraperWorker(domain, max_pages, driver_path, self.output_dir)
        self.worker.moveToThread(self.scraper_thread)

        # Connect signals
        self.scraper_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_scraper_finished)
        self.worker.error.connect(self.on_scraper_error)
        self.worker.statusUpdate.connect(self.on_status_update)
        self.worker.analysisProgress.connect(self.on_analysis_progress)

        self.worker.finished.connect(self.scraper_thread.quit)
        self.worker.error.connect(self.scraper_thread.quit)
        self.scraper_thread.finished.connect(self.cleanup_after_scraping)

        # Start
        self.scraper_thread.start()

    @pyqtSlot(int, int)
    def on_analysis_progress(self, current_val, total_val):
        """
        Switch from indefinite to definite range for progress bar
        once we know total_val. Update current progress.
        """
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, total_val)
        self.progress_bar.setValue(current_val)

    @pyqtSlot(str, str)
    def on_scraper_finished(self, csv_file, html_file):
        QMessageBox.information(
            self,
            "Success",
            f"Report generated!\nCSV: {csv_file}\nHTML: {html_file}"
        )
        webbrowser.open(html_file)
        self.status_label.setText("Process complete. Ready for another run.")
        self.progress_bar.setValue(self.progress_bar.maximum())

    @pyqtSlot(str)
    def on_scraper_error(self, error_msg):
        QMessageBox.critical(self, "Error", f"An error occurred: {error_msg}")
        self.status_label.setText("Error. Check logs or try again.")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)

    @pyqtSlot()
    def cleanup_after_scraping(self):
        self.scraper_thread = None
        self.worker = None
        self.start_button.setEnabled(True)

    @pyqtSlot(str)
    def on_status_update(self, message):
        self.status_label.setText(message)

###############################################################################
# MAIN ENTRY POINT
###############################################################################
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
