import sys
import os
import re
import threading
import queue
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
    "with", "on", "this", "a", "of", "at", "by"
}
IGNORED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
    ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz"
)
MAX_LIMIT = 999  # Hard cap on number of links

###############################################################################
# OPTIONAL: PAGE SPEED INSIGHTS (PLACEHOLDER)
###############################################################################
def check_page_speed_insights(url, api_key="AIzaSyB8R9HLyxA6cvv2PLzhh4fWXxlXlSopnpg'):
    """
    Placeholder for calling Google's PageSpeed Insights API.
    You need to provide a valid 'api_key' and 'strategy' (e.g., 'mobile' or 'desktop').
    If you want to integrate real performance or mobile-friendliness metrics,
    uncomment and adapt this function.

    Docs: https://developers.google.com/speed/docs/insights/overview
    Example usage:
        endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        params = {
            'url': url,
            'key': api_key,
            'strategy': 'mobile'  # or 'desktop'
        }
        r = requests.get(endpoint, params=params)
        data = r.json()
        # Extract relevant fields from data...
    """
    if not api_key:
        return None  # we can't proceed
    # Example stub return:
    return {
        "performance_score": 0,     # 0..100
        "mobile_friendliness": "unknown"
    }

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
      loads them, collects links, and enqueues new ones if under max_pages.
    - We DO allow JS-based links, as modern search engines can interpret them.
    - We skip file extensions in IGNORE.
    """
    if status_callback:
        status_callback("Sitemap not found or empty. Falling back to CONCURRENT BFS with Selenium...")

    visited = set()
    q = queue.Queue()
    base_netloc = normalize_netloc(urlparse(base_url).netloc)

    # Initialize queue
    q.put(base_url)

    # Worker function
    def bfs_worker(driver):
        while True:
            try:
                current_url = q.get(timeout=3)  # wait up to 3s
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
                # Gather links
                a_tags = driver.find_elements(By.TAG_NAME, "a")
                for a in a_tags:
                    href = a.get_attribute("href") or ""
                    if not href:
                        continue
                    # skip if extension is in IGNORE
                    if any(href.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
                        continue

                    # same domain
                    link_netloc = normalize_netloc(urlparse(href).netloc)
                    if link_netloc == base_netloc:
                        if len(visited) + q.qsize() < max_pages:
                            if href not in visited:
                                q.put(href)

            except Exception:
                pass
            finally:
                q.task_done()

    # Launch driver_count threads
    drivers = [configure_driver(driver_path) for _ in range(driver_count)]
    threads = []
    for d in drivers:
        t = threading.Thread(target=bfs_worker, args=(d,), daemon=True)
        threads.append(t)
        t.start()

    # Wait until queue is empty or we've visited max_pages
    q.join()  # block until all tasks done

    # Cleanup
    for d in drivers:
        try:
            d.quit()
        except:
            pass

    return list(visited)[:max_pages]

###############################################################################
# ON-PAGE SEO ANALYSIS + SCORING
###############################################################################
def analyze_on_page_seo(html, url, pagespeed_data=None):
    """
    Parse HTML with BeautifulSoup and extract key on-page SEO factors.
    Optionally integrate pagespeed_data for scoring (if we have it).
    """
    soup = BeautifulSoup(html, "html.parser")
    results = {}

    # 1) Title & Meta Description
    title_tag = soup.find("title")
    title_text = title_tag.get_text().strip() if title_tag else ""
    results["Title"] = title_text
    results["TitleLength"] = len(title_text)

    meta_desc = ""
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    if meta_desc_tag and meta_desc_tag.get("content"):
        meta_desc = meta_desc_tag["content"].strip()
    results["MetaDescription"] = meta_desc
    results["MetaDescriptionLength"] = len(meta_desc)

    # 2) Headings
    h1_tags = soup.find_all("h1")
    h2_tags = soup.find_all("h2")
    results["H1Count"] = len(h1_tags)
    results["H2Count"] = len(h2_tags)

    # 3) Word Count
    text_content = soup.get_text(separator=" ", strip=True)
    words = re.findall(r"\w+", text_content.lower())
    filtered_words = [w for w in words if w not in STOP_WORDS]
    results["WordCount"] = len(filtered_words)

    # 4) Images & alt text
    images = soup.find_all("img")
    results["ImageCount"] = len(images)
    alt_missing = sum(1 for img in images if not img.get("alt"))
    results["ImagesWithoutAlt"] = alt_missing

    # 5) Canonical
    canonical_tag = soup.find("link", rel="canonical")
    canonical_href = canonical_tag["href"].strip() if canonical_tag and canonical_tag.get("href") else ""
    results["Canonical"] = canonical_href

    # 6) noindex check
    robots_meta = soup.find("meta", attrs={"name": re.compile(r"robots", re.I)})
    robots_content = (robots_meta["content"].lower() if (robots_meta and robots_meta.get("content")) else "")
    results["Noindex"] = "noindex" in robots_content

    # 7) Mobile responsiveness (basic check: viewport meta)
    viewport_tag = soup.find("meta", attrs={"name": "viewport"})
    results["HasViewportMeta"] = bool(viewport_tag)

    # 8) Structured Data
    ld_json = soup.find_all("script", attrs={"type": "application/ld+json"})
    results["StructuredDataCount"] = len(ld_json)
    microdata = soup.find_all(attrs={"itemtype": True})
    results["MicrodataCount"] = len(microdata)

    # 9) Social tags
    og_title = soup.find("meta", property="og:title")
    results["OpenGraphTitle"] = og_title["content"].strip() if og_title and og_title.get("content") else ""
    tw_card = soup.find("meta", attrs={"name": "twitter:card"})
    results["TwitterCard"] = tw_card["content"].strip() if tw_card and tw_card.get("content") else ""

    # 10) PageSpeed data (if available)
    if pagespeed_data:
        # Suppose pagespeed_data = {"performance_score": 85, "mobile_friendliness": "PASS"}
        results["PerformanceScore"] = pagespeed_data.get("performance_score", 0)
        results["MobileFriendlinessCheck"] = pagespeed_data.get("mobile_friendliness", "N/A")
    else:
        results["PerformanceScore"] = None
        results["MobileFriendlinessCheck"] = None

    # 11) Final URL
    results["URL"] = url

    # SCORING + RECOMMENDATIONS
    score, recs = compute_score_and_recommendations(results)
    results["Score"] = score
    results["Recommendations"] = recs

    return results

def compute_score_and_recommendations(data):
    """
    Weighted system for SEO + page speed + mobile:
      1) Title length ~50-60 => +10
      2) Meta desc ~120-160 => +10
      3) H1 => +10
      4) H2 => +5
      5) 300+ words => +10
      6) Good image alt coverage => +10
      7) Canonical => +5
      8) no noindex => +10
      9) structured data => +5
      10) social tags => +5
      11) synergy => +10
      12) mobile-friendly => +5
      13) performance => up to +5
    """
    score = 0.0
    recs = []

    # 1) Title
    tl = data.get("TitleLength", 0)
    if 50 <= tl <= 60:
        score += 10
    else:
        recs.append("Optimize title length (50-60 chars).")

    # 2) Meta desc
    md_len = data.get("MetaDescriptionLength", 0)
    if 120 <= md_len <= 160:
        score += 10
    else:
        recs.append("Optimize meta description (120-160 chars).")

    # 3) H1
    h1_count = data.get("H1Count", 0)
    if h1_count > 0:
        score += 10
    else:
        recs.append("Include at least one <h1> tag with keywords.")

    # 4) H2
    h2_count = data.get("H2Count", 0)
    if h2_count >= 1:
        score += 5
    else:
        recs.append("Add <h2> tags for subtopics/structure.")

    # 5) WordCount
    wc = data.get("WordCount", 0)
    if wc >= 300:
        score += 10
    else:
        recs.append("Add more content (300+ words).")

    # 6) Image alt coverage
    img_count = data.get("ImageCount", 0)
    alt_missing = data.get("ImagesWithoutAlt", 0)
    if img_count > 0:
        coverage = (img_count - alt_missing) / img_count
        if coverage >= 0.8:
            score += 10
        else:
            recs.append("Add alt text to most images.")
    else:
        recs.append("Consider adding images with alt text.")

    # 7) Canonical
    canonical = data.get("Canonical", "")
    if canonical:
        score += 5
    else:
        recs.append("Include a canonical link to avoid duplicates.")

    # 8) Noindex
    noindex = data.get("Noindex", False)
    if not noindex:
        score += 10
    else:
        recs.append("Remove 'noindex' unless blocking indexing is intentional.")

    # 9) Structured data
    sd_count = data.get("StructuredDataCount", 0)
    microdata_count = data.get("MicrodataCount", 0)
    if sd_count > 0 or microdata_count > 0:
        score += 5
    else:
        recs.append("Add structured data (JSON-LD or microdata).")

    # 10) Social
    og = data.get("OpenGraphTitle", "")
    twc = data.get("TwitterCard", "")
    if og or twc:
        score += 5
    else:
        recs.append("Add Open Graph / Twitter Card tags for social previews.")

    # 11) Synergy
    if tl and md_len and not noindex:
        score += 10

    # 12) Mobile-friendly
    if data.get("HasViewportMeta"):
        score += 5
    else:
        recs.append("Add <meta name='viewport'> for mobile responsiveness.")

    # 13) Performance (if we have PerformanceScore)
    perf_score = data.get("PerformanceScore", None)
    if isinstance(perf_score, int):
        # Suppose 90+ => +5, 70+ => +3, else => +0
        if perf_score >= 90:
            score += 5
        elif perf_score >= 70:
            score += 3
        else:
            recs.append("Improve performance per PageSpeed insights.")
    else:
        recs.append("Consider measuring site performance (PageSpeed).")

    if score > 100:
        score = 100
    final_score = int(score)

    if not recs:
        recs_str = "Fully optimized!"
    else:
        recs_str = "; ".join(recs)

    return final_score, recs_str

def analyze_page(driver, url, status_callback, current_idx, total_count, api_key=None):
    """
    Load a page with Selenium, optionally fetch PageSpeed data,
    then do on-page SEO analysis & scoring.
    """
    try:
        driver.get(url)
        html = driver.page_source
        if status_callback:
            status_callback(f"Analyzing ({current_idx}/{total_count}): {url}")

        # Optionally integrate PageSpeed data (requires an API key, if you have it)
        pagespeed_info = None
        # pagespeed_info = check_page_speed_insights(url, api_key=api_key)

        return analyze_on_page_seo(html, url, pagespeed_data=pagespeed_info)

    except Exception as e:
        print(f"Error analyzing {url}: {e}")
        return {
            "URL": url,
            "Error": str(e),
            "Score": 0,
            "Recommendations": "Failed to load or parse"
        }

def analyze_pages_in_pool(urls, driver_path, status_callback, api_key=None, progress_callback=None):
    """
    Distribute analysis among multiple Selenium drivers.
    Also calls progress_callback to update progress bar, if available.
    """
    def worker(driver, chunk, offset):
        local_results = []
        for i, url in enumerate(chunk):
            result = analyze_page(
                driver=driver,
                url=url,
                status_callback=status_callback,
                current_idx=offset + i + 1,
                total_count=len(urls),
                api_key=api_key
            )
            local_results.append(result)

            # Update progress bar if available
            if progress_callback:
                progress_callback(1)  # increment by 1
        return local_results

    if not urls:
        return []

    n_drivers = 5
    drivers = [configure_driver(driver_path) for _ in range(n_drivers)]

    results = []
    chunk_size = max(1, len(urls) // n_drivers + 1)
    chunks = [urls[i:i + chunk_size] for i in range(0, len(urls), chunk_size)]

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

    # Cleanup
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
    2) If no links, do concurrent BFS with multiple Selenium drivers (JS-based).
    3) Analyze pages with SEO checks & optional PageSpeed.
    4) Provide a progress update for analysis, if possible.
    5) Output CSV & HTML.
    """
    finished = pyqtSignal(str, str)  # on success: (csv_file, html_file)
    error = pyqtSignal(str)          # on error: (err_msg)
    statusUpdate = pyqtSignal(str)   # for textual status
    analysisProgress = pyqtSignal(int, int)
    # for setting progress: (current_value, total)

    def __init__(self, domain, max_pages, driver_path, output_dir):
        super().__init__()
        self.domain = domain
        self.max_pages = min(max_pages, MAX_LIMIT)
        self.driver_path = driver_path
        self.output_dir = output_dir
        self.api_key = None  # set your Google PageSpeed API key if you wish

        self.current_analysis_count = 0
        self.total_analysis_count = 0

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

            # 2) If no links, do concurrency BFS
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

            self.current_analysis_count = 0
            self.total_analysis_count = len(unique_links)

            # 3) Analyze pages
            # We'll define a small callback to increment our count and emit a signal
            def increment_analysis_progress(num=1):
                self.current_analysis_count += num
                # Emit (current_value, total)
                self.analysisProgress.emit(self.current_analysis_count, self.total_analysis_count)

            results = analyze_pages_in_pool(
                urls=unique_links,
                driver_path=self.driver_path,
                status_callback=self.statusUpdate.emit,
                api_key=self.api_key,
                progress_callback=increment_analysis_progress
            )

            self.statusUpdate.emit("Generating reports...")

            # 4) Save CSV & HTML
            domain_name = sanitize_domain(urlparse(base_url).netloc)
            current_date = datetime.now().strftime("%m%d%Y")
            csv_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{current_date}.csv")
            html_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{current_date}.html")

            df = pd.DataFrame(results)
            df.to_csv(csv_file, index=False)
            df.to_html(html_file, index=False)

            # 5) Done
            self.finished.emit(csv_file, html_file)

        except Exception as e:
            self.error.emit(str(e))

###############################################################################
# MAIN WINDOW (GUI)
###############################################################################
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Advanced On-Page SEO (Progress Bar, BFS, PageSpeed, Mobile)")

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

        self.start_button = QPushButton("Start Analysis")
        self.start_button.clicked.connect(self.start_scraping)

        self.status_label = QLabel("Ready.")
        self.status_label.setAlignment(Qt.AlignCenter)

        # PROGRESS BAR
        # We'll do indefinite progress during BFS or link collection,
        # and a definite progress (0..N) during analysis.
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        # We'll dynamically set range to (0,0) for indefinite, or (0,N) for analysis.

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

    def start_scraping(self):
        self.start_button.setEnabled(False)
        self.status_label.setText("Initializing...")

        # Indefinite progress while collecting links
        self.progress_bar.setRange(0, 0)

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
        self.worker.analysisProgress.connect(self.on_analysis_progress)

        self.worker.finished.connect(self.scraper_thread.quit)
        self.worker.error.connect(self.scraper_thread.quit)
        self.scraper_thread.finished.connect(self.cleanup_after_scraping)

        # Start
        self.scraper_thread.start()

    @pyqtSlot(int, int)
    def on_analysis_progress(self, current_val, total_val):
        """
        Called during analysis. We'll set the progress bar to (0..total_val)
        and update as each page is analyzed.
        """
        # If the progress bar is indefinite (0..0), switch it to definite
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

