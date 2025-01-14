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

# Optional: If you have a valid PageSpeed Insights API key, place it here:
PAGESPEED_API_KEY = None  # e.g. "AIzaSyB8R..."

###############################################################################
# PAGE SPEED INSIGHTS (OPTIONAL)
###############################################################################
def check_page_speed_insights(url, api_key=None, strategy="mobile"):
    """
    Call Google's PageSpeed Insights API. Returns a dict with:
      - performance_score (0..100 or None if not found)
      - mobile_friendliness ("PASS"/"SLOW"/"AVERAGE"/"N/A")
      - error (None or string)
    """
    if not api_key:
        return {"performance_score": None, "mobile_friendliness": "N/A", "error": "No API key"}

    endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {
        "url": url,
        "key": api_key,
        "strategy": strategy,
    }
    try:
        r = requests.get(endpoint, params=params, timeout=15)
        if r.status_code != 200:
            return {
                "performance_score": None,
                "mobile_friendliness": "N/A",
                "error": f"HTTP {r.status_code}"
            }
        data = r.json()

        # Attempt to parse Lighthouse performance (0..1 => 0..100)
        perf = None
        try:
            perf_raw = data["lighthouseResult"]["categories"]["performance"]["score"]
            perf = int(perf_raw * 100)
        except:
            pass

        mobile_friendly = "N/A"
        try:
            le = data.get("loadingExperience", {})
            oc = le.get("overall_category")  # FAST, AVERAGE, SLOW
            if oc:
                if oc == "FAST":
                    mobile_friendly = "PASS"
                else:
                    mobile_friendly = oc
        except:
            pass

        return {
            "performance_score": perf,
            "mobile_friendliness": mobile_friendly,
            "error": None
        }
    except Exception as e:
        return {"performance_score": None, "mobile_friendliness": "N/A", "error": str(e)}


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

    if "sitemapindex" in tag_name:
        for sitemap_tag in root.findall(f"{ns}sitemap"):
            loc_tag = sitemap_tag.find(f"{ns}loc")
            if loc_tag is not None and loc_tag.text:
                sub_sitemaps.append(loc_tag.text.strip())
    elif "urlset" in tag_name:
        for url_tag in root.findall(f"{ns}url"):
            loc_tag = url_tag.find(f"{ns}loc")
            if loc_tag is not None and loc_tag.text:
                links.append(loc_tag.text.strip())

    return sub_sitemaps, links

def gather_links_from_sitemap(base_url, max_pages, status_callback=None):
    """
    Attempt to fetch /sitemap.xml. If it's a sitemap index, parse sub-sitemaps.
    Return up to max_pages unique links.
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
def selenium_bfs_concurrent(base_url, max_pages, status_callback=None,
                            driver_count=3, driver_path=None):
    """
    A concurrent BFS approach using multiple Selenium WebDrivers.
    Each driver thread pops URLs from a shared queue, visits them, extracts new <a> links.
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
                return

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
                    # Skip ignored file extensions
                    if any(href.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
                        continue
                    # Same domain
                    link_netloc = normalize_netloc(urlparse(href).netloc)
                    if link_netloc == base_netloc:
                        if len(visited) + q.qsize() < max_pages:
                            if href not in visited:
                                q.put(href)
            except:
                pass
            finally:
                q.task_done()

    drivers = [configure_driver(driver_path) for _ in range(driver_count)]
    threads = []
    for d in drivers:
        t = threading.Thread(target=bfs_worker, args=(d,), daemon=True)
        threads.append(t)
        t.start()

    q.join()
    for d in drivers:
        try:
            d.quit()
        except:
            pass

    return list(visited)[:max_pages]

###############################################################################
# KEYWORD EXTRACTION
###############################################################################
def extract_keywords_from_text(text):
    """
    Basic approach to "keyword" detection: split on word chars, remove stop words,
    count frequencies, return a Counter.
    """
    words = re.findall(r"\w+", text.lower())
    filtered = [w for w in words if w not in STOP_WORDS]
    return Counter(filtered)

###############################################################################
# SCORING + RECOMMENDATIONS
###############################################################################
def compute_score_and_recommendations(data):
    """
    Weighted system for a final 'Score' (0..100) plus 'Recommendations'.
    Some examples below:
      - Title ~50-60 => +10
      - Meta desc ~120-160 => +10
      - 1+ H1 => +10
      - Some H2 => +5
      - WordCount >=300 => +10
      - Good alt coverage => +10
      - Has canonical => +5
      - Not noindex => +10
      - Structured data => +5
      - Performance => up to +5
      - synergy => +10
    """
    score = 0.0
    recs = []

    # 1) Title length
    tl = data.get("TitleLength", 0)
    if 50 <= tl <= 60:
        score += 10
    else:
        recs.append("Adjust Title length to ~50-60 chars.")

    # 2) Meta desc length
    mdl = data.get("MetaDescriptionLength", 0)
    if 120 <= mdl <= 160:
        score += 10
    else:
        recs.append("Adjust Meta Description to ~120-160 chars.")

    # 3) H1
    h1_count = data.get("H1Count", 0)
    if h1_count > 0:
        score += 10
    else:
        recs.append("Include at least 1 H1 tag.")

    # 4) H2
    h2_count = data.get("H2Count", 0)
    if h2_count >= 1:
        score += 5
    else:
        recs.append("Add H2 tags for subtopics.")

    # 5) WordCount
    wc = data.get("WordCount", 0)
    if wc >= 300:
        score += 10
    else:
        recs.append("Add more textual content (300+ words).")

    # 6) Images + alt coverage
    img_count = data.get("ImageCount", 0)
    alt_missing = data.get("ImagesWithoutAlt", 0)
    if img_count > 0:
        coverage = (img_count - alt_missing) / img_count
        if coverage >= 0.8:
            score += 10
        else:
            recs.append("Add alt text to most images.")
    else:
        recs.append("Consider adding relevant images with alt text.")

    # 7) Canonical
    canonical = data.get("Canonical", "")
    if canonical:
        score += 5
    else:
        recs.append("Include a canonical link if possible.")

    # 8) Noindex
    noindex = data.get("Noindex", False)
    if not noindex:
        score += 10
    else:
        recs.append("Remove 'noindex' unless intentionally blocking search engines.")

    # 9) StructuredData + Microdata
    sd_count = data.get("StructuredDataCount", 0)
    micro_count = data.get("MicrodataCount", 0)
    if sd_count > 0 or micro_count > 0:
        score += 5
    else:
        recs.append("Add structured data (JSON-LD or microdata).")

    # 10) PerformanceScore
    perf_score = data.get("PerformanceScore", None)
    if isinstance(perf_score, int):
        if perf_score >= 90:
            score += 5
        elif perf_score >= 70:
            score += 3
        else:
            recs.append("Improve performance per PageSpeed.")
    else:
        recs.append("Consider PageSpeed analysis for performance.")

    # synergy
    if tl and mdl and not noindex:
        score += 10

    if score > 100:
        score = 100
    final_score = int(score)

    if not recs:
        recs_str = "Fully optimized!"
    else:
        recs_str = "; ".join(recs)

    return final_score, recs_str

###############################################################################
# PAGE ANALYSIS
###############################################################################
def analyze_page(driver, url, status_callback, current_idx, total_count,
                 sitewide_word_counts, api_key=None):
    """
    Loads a page. Extracts SEO data + keyword counts. Also calls PageSpeed if api_key is set.
    Returns a dictionary with all columns we want.
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
        "Canonical": "",
        "Noindex": False,
        "ImagesWithoutAlt": 0,
        "ImageCount": 0,
        "StructuredDataCount": 0,
        "MicrodataCount": 0,
        "PerformanceScore": None,
        "Score": 0,
        "Recommendations": "",
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

        # MetaDescription
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = (meta_desc_tag.get("content").strip()
                     if meta_desc_tag and meta_desc_tag.get("content") else "")
        data["MetaDescription"] = meta_desc
        data["MetaDescriptionLength"] = len(meta_desc)

        # H1, H2
        h1_tags = soup.find_all("h1")
        h2_tags = soup.find_all("h2")
        data["H1Count"] = len(h1_tags)
        data["H2Count"] = len(h2_tags)

        # Canonical
        canonical_tag = soup.find("link", rel="canonical")
        canonical_href = (canonical_tag["href"].strip()
                          if canonical_tag and canonical_tag.get("href") else "")
        data["Canonical"] = canonical_href

        # Noindex
        robots_meta = soup.find("meta", attrs={"name": re.compile(r"robots", re.I)})
        robots_content = (robots_meta.get("content").lower()
                          if robots_meta and robots_meta.get("content") else "")
        data["Noindex"] = ("noindex" in robots_content)

        # Images
        images = soup.find_all("img")
        data["ImageCount"] = len(images)
        alt_missing = sum(1 for img in images if not img.get("alt"))
        data["ImagesWithoutAlt"] = alt_missing

        # Structured data
        ld_json = soup.find_all("script", attrs={"type": "application/ld+json"})
        data["StructuredDataCount"] = len(ld_json)
        microdata = soup.find_all(attrs={"itemtype": True})
        data["MicrodataCount"] = len(microdata)

        # Keyword extraction
        text_content = soup.get_text(separator=" ", strip=True)
        word_counts = extract_keywords_from_text(text_content)
        data["WordCount"] = sum(word_counts.values())

        # Update sitewide counter
        sitewide_word_counts.update(word_counts)

        # top 5 for this page
        top_5 = word_counts.most_common(5)
        data["Keywords"] = ", ".join(f"{k}({v})" for k, v in top_5)

        # PageSpeed if we have an api_key
        pagespeed_info = None
        if api_key:
            pagespeed_info = check_page_speed_insights(url, api_key=api_key, strategy="mobile")
            if pagespeed_info:
                data["PerformanceScore"] = pagespeed_info.get("performance_score")

        # Compute final score
        final_score, recs = compute_score_and_recommendations(data)
        data["Score"] = final_score
        data["Recommendations"] = recs

    except Exception as e:
        data["Error"] = str(e)

    return data

###############################################################################
# ANALYZE PAGES WITH MULTIPLE DRIVERS
###############################################################################
def analyze_pages_in_pool(urls, driver_path, status_callback, progress_callback,
                          sitewide_word_counts, api_key=None):
    """
    Distribute page analysis among 5 Selenium drivers.
    Each page: SEO checks, keyword extraction, optional PageSpeed.
    """
    def worker(drv, chunk, offset):
        local_results = []
        for i, url in enumerate(chunk):
            row = analyze_page(
                driver=drv,
                url=url,
                status_callback=status_callback,
                current_idx=offset + i + 1,
                total_count=len(urls),
                sitewide_word_counts=sitewide_word_counts,
                api_key=api_key
            )
            local_results.append(row)
            if progress_callback:
                progress_callback(1)
        return local_results

    if not urls:
        return []

    n_drivers = 5
    drivers = [configure_driver(driver_path) for _ in range(n_drivers)]

    chunk_size = max(1, len(urls) // n_drivers + 1)
    chunks = [urls[i : i + chunk_size] for i in range(0, len(urls), chunk_size)]

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
                print(f"Error in analysis thread: {e}")

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
    1) Attempt sitemap, else BFS.
    2) Analyze pages, gather SEO info + keywords + performance + score.
    3) Insert a final "SITEWIDE" row with top 10 sitewide keywords.
    4) Save CSV & HTML.
    """
    finished = pyqtSignal(str, str)  # (csv_file, html_file)
    error = pyqtSignal(str)
    statusUpdate = pyqtSignal(str)
    analysisProgress = pyqtSignal(int, int)  # (current, total)

    def __init__(self, domain, max_pages, driver_path, output_dir):
        super().__init__()
        self.domain = domain
        self.max_pages = min(max_pages, MAX_LIMIT)
        self.driver_path = driver_path
        self.output_dir = output_dir

        self.sitewide_word_counts = Counter()
        self.current_count = 0
        self.total_count = 0

        # If you want PageSpeed:
        self.api_key = PAGESPEED_API_KEY  # or None

    @pyqtSlot()
    def run(self):
        try:
            base_url = append_https(self.domain)

            # 1) Attempt sitemap
            links = []
            try:
                links = gather_links_from_sitemap(
                    base_url,
                    self.max_pages,
                    status_callback=self.statusUpdate.emit
                )
            except Exception as e:
                self.statusUpdate.emit(f"Sitemap attempt failed: {e}")

            if not links:
                links = selenium_bfs_concurrent(
                    base_url,
                    self.max_pages,
                    status_callback=self.statusUpdate.emit,
                    driver_count=3,
                    driver_path=self.driver_path
                )

            unique_links = list(dict.fromkeys(links))
            if len(unique_links) > self.max_pages:
                unique_links = unique_links[:self.max_pages]

            self.statusUpdate.emit(f"Collected {len(unique_links)} URLs. Starting analysis...")

            self.current_count = 0
            self.total_count = len(unique_links)

            # indefinite -> definite progress
            def increment_analysis(x=1):
                self.current_count += x
                self.analysisProgress.emit(self.current_count, self.total_count)

            # 2) Analyze
            results = analyze_pages_in_pool(
                urls=unique_links,
                driver_path=self.driver_path,
                status_callback=self.statusUpdate.emit,
                progress_callback=increment_analysis,
                sitewide_word_counts=self.sitewide_word_counts,
                api_key=self.api_key
            )

            self.statusUpdate.emit("Generating final keywords row...")

            # 3) Final row with sitewide top 10
            top_10_sitewide = self.sitewide_word_counts.most_common(10)
            top_10_str = ", ".join(f"{k}({v})" for k, v in top_10_sitewide)

            sitewide_row = {
                "URL": "SITEWIDE",
                "Title": "",
                "TitleLength": 0,
                "MetaDescription": "",
                "MetaDescriptionLength": 0,
                "H1Count": 0,
                "H2Count": 0,
                "WordCount": sum(self.sitewide_word_counts.values()),
                "Keywords": top_10_str,
                "Canonical": "",
                "Noindex": False,
                "ImagesWithoutAlt": 0,
                "ImageCount": 0,
                "StructuredDataCount": 0,
                "MicrodataCount": 0,
                "PerformanceScore": None,
                "Score": 0,
                "Recommendations": "",
                "Error": ""
            }

            results.append(sitewide_row)

            self.statusUpdate.emit("Writing reports...")

            # 4) Save CSV & HTML
            domain_name = sanitize_domain(urlparse(base_url).netloc)
            date_str = datetime.now().strftime("%Y%m%d_%H%M")
            csv_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{date_str}.csv")
            html_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{date_str}.html")

            df = pd.DataFrame(results)
            df.to_csv(csv_file, index=False)
            df.to_html(html_file, index=False)

            self.finished.emit(csv_file, html_file)
        except Exception as e:
            self.error.emit(str(e))

###############################################################################
# MAIN WINDOW (GUI)
###############################################################################
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("On-Page SEO & Keyword Analyzer (Extended Columns)")

        self.domain_label = QLabel("Domain / URL:")
        self.domain_input = QLineEdit("example.com")

        self.max_pages_label = QLabel("Max Pages (up to 999):")
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(1, 999)
        self.max_pages_spin.setValue(10)

        self.driver_path_label = QLabel("ChromeDriver Path (optional):")
        self.driver_path_input = QLineEdit("/usr/local/bin/chromedriver")

        self.output_dir_label = QLabel("Output Directory:")
        self.output_dir_button = QPushButton("Select...")
        self.output_dir_button.clicked.connect(self.select_output_directory)

        self.chosen_dir_label = QLabel(os.getcwd())

        self.start_button = QPushButton("Start Analysis")
        self.start_button.clicked.connect(self.start_scraping)

        self.status_label = QLabel("Ready.")
        self.status_label.setAlignment(Qt.AlignCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setAlignment(Qt.AlignCenter)

        self.output_dir = os.getcwd()

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
        self.progress_bar.setRange(0, 0)  # indefinite

        domain = self.domain_input.text().strip()
        max_pages = self.max_pages_spin.value()
        driver_path = self.driver_path_input.text().strip()

        self.scraper_thread = QThread()
        self.worker = ScraperWorker(domain, max_pages, driver_path, self.output_dir)
        self.worker.moveToThread(self.scraper_thread)

        self.scraper_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_scraper_finished)
        self.worker.error.connect(self.on_scraper_error)
        self.worker.statusUpdate.connect(self.on_status_update)
        self.worker.analysisProgress.connect(self.on_analysis_progress)

        self.worker.finished.connect(self.scraper_thread.quit)
        self.worker.error.connect(self.scraper_thread.quit)
        self.scraper_thread.finished.connect(self.cleanup_after_scraping)

        self.scraper_thread.start()

    @pyqtSlot(int, int)
    def on_analysis_progress(self, current_val, total_val):
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
