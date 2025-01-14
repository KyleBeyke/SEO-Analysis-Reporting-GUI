import sys
import os
import re
import time
import threading
import queue
import webbrowser
from datetime import datetime
from urllib.parse import urlparse, urljoin
from collections import Counter
import multiprocessing
import logging
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# NLTK for tokenization & PorterStemmer
import nltk
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt", quiet=True)
from nltk.tokenize import word_tokenize
from nltk.stem import PorterStemmer

# PyQt5
from PyQt5.QtCore import (
    Qt, QObject, pyqtSignal, pyqtSlot, QThread
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit,
    QVBoxLayout, QPushButton, QWidget, QSpinBox,
    QMessageBox, QFileDialog, QProgressBar, QCheckBox,
    QHBoxLayout
)

# Selenium & related
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

###############################################################################
# CONFIGURATION AND CONSTANTS
###############################################################################

# Extensions to ignore during crawling
IGNORED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
                      ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz")

# Basic stop words for filtering during keyword extraction
RAW_STOP_WORDS = """
a about above actually after again against all almost also although always
am an and any are as at
be became become because been before being below between both but by
can could
did do does doing down during
each either else
few for from further
had has have having he he'd he'll hence he's her here here's hers herself him himself his
how how's
I I'd I'll I'm I've if in into is it it's its itself
just
let's
may maybe me might mine more most must my myself
neither nor not
of oh on once only ok or other ought our ours ourselves out over own
same she she'd she'll she's should so some such
than that that's the their theirs them themselves then there there's these they they'd they'll they're they've this
those through to too
under until up
very
was we we'd we'll we're we've were what what's when whenever when's where whereas wherever where's whether which while who whoever who's whose whom why why's will with within would
yes yet you you'd you'll you're you've your yours yourself yourselves
"""

ADDITIONAL_SINGLE_LETTER_STOP_WORDS = {"s", "t", "u", "v", "w", "x", "y", "z"}

BASE_STOP_WORDS = set(w.strip().lower() for w in RAW_STOP_WORDS.split() if w.strip())
EXTRA_STOP_WORDS = {"another", "also", "be", "is", "was", "were", "do", "does", "did"}.union(ADDITIONAL_SINGLE_LETTER_STOP_WORDS)
STOP_WORDS = BASE_STOP_WORDS.union(EXTRA_STOP_WORDS)
if "i" in STOP_WORDS:
    STOP_WORDS.remove("i")

stemmer = PorterStemmer()

###############################################################################
# UTILITY FUNCTIONS
###############################################################################

def exponential_backoff(retries):
    """Compute backoff time with a cap."""
    return min(2 ** retries, 32)

def configure_driver(driver_path=None):
    """Configure Selenium WebDriver with headless Chrome."""
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-extensions")
    options.add_argument("--start-maximized")

    driver = webdriver.Chrome(
        service=Service(driver_path or ChromeDriverManager().install()),
        options=options
    )
    driver.set_page_load_timeout(15)
    return driver

def sanitize_domain(domain):
    """Sanitize domain name for safe file naming."""
    return re.sub(r'[^a-zA-Z0-9.-]', '_', domain)

###############################################################################
# INITIAL LOGGING SETUP
###############################################################################

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logging.info("Script initialized. Basic setup complete.")

###############################################################################
# ROBOTS.TXT PARSING
###############################################################################

def fetch_robots_txt(base_url):
    """Fetch and parse the robots.txt file for the given base URL."""
    robots_url = urljoin(base_url, "/robots.txt")
    logging.info(f"Fetching robots.txt from {robots_url}")
    try:
        response = requests.get(robots_url, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logging.warning(f"Failed to fetch robots.txt: {e}")
        return ""

def parse_robots_txt(base_url, robots_txt):
    """
    Parse robots.txt and return disallowed paths for all user-agents.
    """
    disallowed_paths = set()
    current_user_agent = None
    user_agent_match = False

    base_domain = urlparse(base_url).netloc
    lines = robots_txt.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("user-agent:"):
            current_user_agent = line.split(":", 1)[1].strip().lower()
            user_agent_match = current_user_agent == "*"  # Match all user-agents
        elif user_agent_match and line.lower().startswith("disallow:"):
            disallow_path = line.split(":", 1)[1].strip()
            if disallow_path:
                disallowed_paths.add(urljoin(f"https://{base_domain}", disallow_path))
    logging.info(f"Parsed disallowed paths: {disallowed_paths}")
    return disallowed_paths

def is_allowed_by_robots(base_url, disallowed_paths, url):
    """Check if a given URL is allowed by the robots.txt rules."""
    for disallowed in disallowed_paths:
        if url.startswith(disallowed):
            logging.debug(f"URL disallowed by robots.txt: {url}")
            return False
    return True

def gather_links_from_sitemap(base_url, max_pages, site_password="", status_callback=None):
    """Fetch all links from sitemap.xml or sitemap_index.xml, respecting robots.txt."""
    # Fetch and parse robots.txt
    robots_txt = fetch_robots_txt(base_url)
    disallowed_paths = parse_robots_txt(base_url, robots_txt)

    # Unlock password-protected site
    driver = configure_driver()
    attempt_password_login_if_needed(driver, base_url, site_password)
    driver.quit()

    # Attempt /sitemap.xml
    sitemap_url = urljoin(base_url, "/sitemap.xml")
    if status_callback:
        status_callback(f"Attempting to fetch {sitemap_url}")
    logging.info(f"Fetching {sitemap_url} with requests...")
    try:
        resp = requests.get(sitemap_url, timeout=10, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logging.warning(f"Error fetching {sitemap_url}: {e}")
        # Fallback -> sitemap_index.xml
        alt_sitemap_url = urljoin(base_url, "/sitemap_index.xml")
        logging.info(f"Trying alt => {alt_sitemap_url}")
        if status_callback:
            status_callback(f"Attempting alt sitemap: {alt_sitemap_url}")
        try:
            resp_alt = requests.get(alt_sitemap_url, timeout=10, allow_redirects=True)
            resp_alt.raise_for_status()
            resp = resp_alt
        except Exception as e2:
            raise Exception(f"Sitemap fetch failed: {e2}")

    # Parse sitemap and filter based on robots.txt
    sub_sitemaps, links = parse_sitemap_xml(resp.text)
    visited = set(links)
    queue_ = list(sub_sitemaps)

    while queue_ and len(visited) < max_pages:
        smap = queue_.pop()
        logging.info(f"Fetching sub-sitemap => {smap}")
        if status_callback:
            status_callback(f"Fetching sub-sitemap: {smap}")
        try:
            r = requests.get(smap, timeout=10, allow_redirects=True)
            r.raise_for_status()
            subs, l2 = parse_sitemap_xml(r.text)
            queue_.extend(subs)
            for lk in l2:
                if is_allowed_by_robots(base_url, disallowed_paths, lk):
                    visited.add(lk)
                if len(visited) >= max_pages:
                    break
        except Exception as e:
            logging.warning(f"Sub-sitemap error => {smap}: {e}")
            if status_callback:
                status_callback(f"Warning in sub-sitemap: {smap} => {e}")

    filtered = [lk for lk in visited if not any(lk.lower().endswith(ext) for ext in IGNORED_EXTENSIONS)]
    return filtered[:max_pages]

###############################################################################
# BFS WITH SEO LINK FILTERING & ROBOTS.TXT
###############################################################################

def clean_url_for_seo(url):
    """Clean a URL for SEO purposes by removing query parameters and fragments."""
    parsed_url = urlparse(url)
    cleaned_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
    return cleaned_url.rstrip("/")

def selenium_bfs_concurrent(base_url, max_pages, site_password="", status_callback=None, driver_path=None, bfs_depth=2):
    """
    Perform BFS with concurrency, ignoring external domain links,
    respecting robots.txt, and applying SEO link filtering.
    """
    logging.info(f"[BFS] BFS concurrency => {base_url}, depth={bfs_depth}")

    # Fetch and parse robots.txt
    robots_txt = fetch_robots_txt(base_url)
    disallowed_paths = parse_robots_txt(base_url, robots_txt)

    # Unlock password-protected site
    driver = configure_driver(driver_path)
    attempt_password_login_if_needed(driver, base_url, site_password)
    driver.quit()

    if status_callback:
        status_callback("Sitemap not found or empty -> BFS fallback with concurrency...")

    visited = set()
    from urllib.parse import urlparse
    base_netloc = urlparse(base_url).netloc.lower().replace("www.", "")
    q = queue.Queue()
    q.put((base_url, 0))

    cores = multiprocessing.cpu_count()
    n_workers = max(int(0.75 * cores), 1)
    logging.info(f"[BFS] concurrency with {n_workers} from {cores} cores.")

    def bfs_worker(drv):
        while True:
            try:
                url_, depth_ = q.get(timeout=3)
            except queue.Empty:
                return
            if url_ in visited:
                logging.debug(f"[BFS] Already visited => {url_}")
                q.task_done()
                continue

            cleaned_url = clean_url_for_seo(url_)
            if not is_allowed_by_robots(base_url, disallowed_paths, cleaned_url):
                logging.debug(f"[BFS] Disallowed by robots.txt => {cleaned_url}")
                q.task_done()
                continue

            visited.add(url_)
            idx = len(visited)
            if status_callback:
                status_callback(f"[BFS] Visiting {url_} ({idx}/{max_pages})")
            logging.info(f"[BFS] Visiting => {url_}, depth={depth_}")

            try:
                drv.get(url_)
                time.sleep(1)
                a_tags = scroll_and_collect(drv)
                for a_ in a_tags:
                    href = a_.get_attribute("href") or ""
                    if not href:
                        continue
                    if any(href.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
                        continue
                    link_netloc = urlparse(href).netloc.lower().replace("www.", "")
                    if link_netloc != base_netloc:
                        continue
                    cleaned_href = clean_url_for_seo(href)
                    if len(visited) + q.qsize() < max_pages and cleaned_href not in visited:
                        if depth_ < bfs_depth:
                            q.put((cleaned_href, depth_ + 1))
            except Exception as e:
                logging.exception(f"[BFS] Worker exception @ {url_}: {e}")
            finally:
                q.task_done()

    drivers = [configure_driver(driver_path) for _ in range(n_workers)]
    threads = []
    for drv_ in drivers:
        t = threading.Thread(target=bfs_worker, args=(drv_,), daemon=True)
        threads.append(t)
        t.start()

    q.join()
    logging.info("[BFS] concurrency finished -> cleaning up drivers.")
    for drv_ in drivers:
        try:
            drv_.quit()
        except:
            pass
    return list(visited)[:max_pages]

def fetch_with_retries(url, max_retries=3, backoff_factor=2):
    """
    Fetch a URL with retries and exponential backoff.
    """
    attempt = 0
    while attempt < max_retries:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            attempt += 1
            wait_time = backoff_factor ** attempt
            logging.warning(f"Error fetching {url} (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                logging.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logging.error(f"Max retries reached for {url}.")
                raise
###############################################################################
# INTEGRATION: SITEMAP FETCHING WITH RETRY & SEO LOGGING
###############################################################################

def gather_links_from_sitemap(base_url, max_pages, site_password="", status_callback=None):
    """
    Fetch links from sitemap.xml, with retry logic and robots.txt filtering.
    """
    driver = configure_driver()
    attempt_password_login_if_needed(driver, base_url, site_password)
    driver.quit()

    sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
    alt_sitemap_url = base_url.rstrip("/") + "/sitemap_index.xml"

    if status_callback:
        status_callback(f"Attempting to fetch sitemap from {sitemap_url}")

    try:
        resp = fetch_with_retries(sitemap_url)
        sub_sitemaps, links = parse_sitemap_xml(resp.text)
    except Exception as e:
        logging.warning(f"Primary sitemap fetch failed: {e}")
        if status_callback:
            status_callback(f"Primary sitemap failed; attempting alt: {alt_sitemap_url}")
        try:
            resp = fetch_with_retries(alt_sitemap_url)
            sub_sitemaps, links = parse_sitemap_xml(resp.text)
        except Exception as e2:
            raise Exception(f"Both sitemap and alt failed: {e2}")

    visited = set(links)
    queue_ = list(sub_sitemaps)
    disallowed_paths = parse_robots_txt(base_url, fetch_robots_txt(base_url))

    while queue_ and len(visited) < max_pages:
        smap = queue_.pop()
        if not is_allowed_by_robots(base_url, disallowed_paths, smap):
            logging.info(f"Sitemap disallowed by robots.txt: {smap}")
            continue
        if status_callback:
            status_callback(f"Fetching sub-sitemap: {smap}")
        try:
            resp = fetch_with_retries(smap)
            subs, l2 = parse_sitemap_xml(resp.text)
            queue_.extend(subs)
            for link in l2:
                cleaned_link = clean_url_for_seo(link)
                if cleaned_link not in visited and len(visited) < max_pages:
                    visited.add(cleaned_link)
        except Exception as e:
            logging.warning(f"Error fetching sub-sitemap {smap}: {e}")

    filtered_links = [
        lk for lk in visited if not any(lk.lower().endswith(ext) for ext in IGNORED_EXTENSIONS)
    ]
    logging.info(f"Sitemap fetched {len(filtered_links)} links (filtered).")
    return filtered_links[:max_pages]

###############################################################################
# ROBOTS.TXT PARSING & VALIDATION
###############################################################################

def fetch_robots_txt(base_url):
    """
    Fetch robots.txt content for a given base URL.
    """
    robots_url = base_url.rstrip("/") + "/robots.txt"
    try:
        response = fetch_with_retries(robots_url)
        return response.text
    except Exception as e:
        logging.warning(f"Unable to fetch robots.txt for {base_url}: {e}")
        return ""

def parse_robots_txt(base_url, robots_txt):
    """
    Parse disallowed paths from robots.txt for a specific user-agent.
    """
    disallowed_paths = []
    user_agent = "*"
    base_parsed = urlparse(base_url)
    lines = robots_txt.splitlines()
    is_relevant = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("user-agent:"):
            is_relevant = user_agent in stripped.lower()
        elif is_relevant and stripped.lower().startswith("disallow:"):
            path = stripped[9:].strip()
            if path:
                disallowed_paths.append(base_parsed.scheme + "://" + base_parsed.netloc + path)

    return disallowed_paths

def is_allowed_by_robots(base_url, disallowed_paths, url):
    """
    Check if a URL is allowed by robots.txt directives.
    """
    for disallowed in disallowed_paths:
        if url.startswith(disallowed):
            return False
    return True

###############################################################################
# DETAILED SEO FILTERING LOGGING
###############################################################################

def log_filtered_links(visited_links, filtered_links):
    """
    Log details about filtered links and visited URLs for SEO auditing.
    """
    unfiltered_count = len(visited_links)
    filtered_count = len(filtered_links)
    removed_count = unfiltered_count - filtered_count

    logging.info(f"Total visited links: {unfiltered_count}")
    logging.info(f"Filtered links retained: {filtered_count}")
    logging.info(f"Links removed by SEO filtering: {removed_count}")

    if removed_count > 0:
        removed_links = set(visited_links) - set(filtered_links)
        logging.debug(f"Filtered out URLs: {removed_links}")

###############################################################################
# MODULARIZED ANALYSIS WORKFLOW
###############################################################################

def analyze_links(base_url, max_pages, site_password, driver_path, api_key=None, status_callback=None, progress_callback=None):
    """
    Perform analysis on a list of links, handling sitemap and BFS workflows.
    """
    logging.info(f"Starting analysis workflow for {base_url}")

    # Fetch robots.txt and parse disallowed paths
    robots_txt = fetch_robots_txt(base_url)
    disallowed_paths = parse_robots_txt(base_url, robots_txt)

    # Gather links from sitemap or fallback to BFS
    try:
        links = gather_links_from_sitemap(base_url, max_pages, site_password, status_callback)
    except Exception as e:
        logging.warning(f"Sitemap gathering failed: {e}. Fallback to BFS.")
        links = selenium_bfs_concurrent(
            base_url, max_pages, site_password, status_callback, driver_path, bfs_depth=2
        )

    # Filter links based on robots.txt
    filtered_links = [
        link for link in links if is_allowed_by_robots(base_url, disallowed_paths, link)
    ]
    log_filtered_links(links, filtered_links)

    # Analyze pages concurrently
    sitewide_word_counts = Counter()
    results = analyze_page_concurrently(
        filtered_links, driver_path, sitewide_word_counts, status_callback, progress_callback, api_key
    )

    # Add sitewide keyword summary
    add_sitewide_summary(results, sitewide_word_counts)

    logging.info("Analysis workflow completed.")
    return results

def add_sitewide_summary(results, sitewide_word_counts):
    """
    Append sitewide keyword summary to results.
    """
    top_10 = sitewide_word_counts.most_common(10)
    top_keywords = ", ".join(f"{word}({count})" for word, count in top_10)

    sitewide_row = {
        "URL": "SITEWIDE",
        "Title": "",
        "TitleLength": 0,
        "MetaDescriptionLength": 0,
        "H1Count": 0,
        "H2Count": 0,
        "WordCount": sum(sitewide_word_counts.values()),
        "Keywords": top_keywords,
        "Canonical": "",
        "Noindex": False,
        "ImagesWithoutAlt": 0,
        "ImageCount": 0,
        "StructuredDataCount": 0,
        "MicrodataCount": 0,
        "PerformanceScoreMobile": None,
        "PerformanceScoreDesktop": None,
        "Score": 0,
        "Recommendations": "",
        "Error": ""
    }
    results.append(sitewide_row)

###############################################################################
# INTEGRATED MODULAR ANALYSIS IN MAIN WINDOW
###############################################################################

def start_scraping(self):
    """
    Start the analysis workflow, integrating the modularized functions.
    """
    # Configure logging based on user selection
    self.configure_logging()

    # Prepare UI for the scraping process
    self.start_button.setEnabled(False)
    self.status_label.setText("Initializing...")
    self.progress_bar.setRange(0, 0)  # Indeterminate progress

    # Collect user input
    domain = self.domain_input.text().strip()
    max_pages = self.max_pages_spin.value()
    driver_path = self.driver_path_input.text().strip()
    site_password = self.password_input.text().strip() if self.protected_check.isChecked() else ""
    pagespeed_api = self.pagespeed_input.text().strip()

    # Initialize and start the worker thread
    self.scraper_thread = QThread()
    self.worker = ScraperWorker(domain, max_pages, driver_path, self.output_dir, site_password, pagespeed_api)
    self.worker.moveToThread(self.scraper_thread)

    # Connect worker signals to UI handlers
    self.scraper_thread.started.connect(self.worker.run)
    self.worker.finished.connect(self.on_scraper_finished)
    self.worker.error.connect(self.on_scraper_error)
    self.worker.statusUpdate.connect(self.on_status_update)
    self.worker.analysisProgress.connect(self.on_analysis_progress)

    self.worker.finished.connect(self.scraper_thread.quit)
    self.worker.error.connect(self.scraper_thread.quit)
    self.scraper_thread.finished.connect(self.cleanup_after_scraping)

    # Start the scraping thread
    self.scraper_thread.start()

def configure_logging(self):
    """
    Configure logging based on user input and preferences.
    """
    log_file = os.path.join(self.output_dir, "seo_analysis.log")
    try:
        logging.basicConfig(
            level=logging.INFO if self.enable_logging_check.isChecked() else logging.WARNING,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(log_file, mode='w'),
                logging.StreamHandler(sys.stdout)
            ],
            force=True
        )
        logging.info("Logging configured successfully.")
    except Exception as e:
        logging.error(f"Error configuring logging: {e}")

###############################################################################
# FINAL REPORTING FUNCTIONS
###############################################################################

def save_reports(results, output_dir, base_url):
    """
    Save the analysis results to CSV and HTML formats.
    """
    from urllib.parse import urlparse

    # Sanitize domain name for file naming
    def sanitize_domain(netloc):
        return re.sub(r'[^a-zA-Z0-9.-]', '_', netloc)

    domain_name = sanitize_domain(urlparse(base_url).netloc)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_file = os.path.join(output_dir, f"seo_report_{domain_name}_{timestamp}.csv")
    html_file = os.path.join(output_dir, f"seo_report_{domain_name}_{timestamp}.html")

    # Save results to files
    logging.info(f"Saving results to {csv_file} and {html_file}")
    df = pd.DataFrame(results)
    df.to_csv(csv_file, index=False)
    df.to_html(html_file, index=False)

    logging.info("Reports saved successfully.")
    return csv_file, html_file


###############################################################################
# LOGGING ENHANCEMENTS
###############################################################################

def log_filtered_links(all_links, filtered_links):
    """
    Log the filtering process and summarize the results.
    """
    logging.info(f"Total links found: {len(all_links)}")
    logging.info(f"Total links allowed by robots.txt: {len(filtered_links)}")
    disallowed_links = set(all_links) - set(filtered_links)
    for link in disallowed_links:
        logging.debug(f"Disallowed by robots.txt: {link}")

def log_analysis_start(domain, max_pages, output_dir):
    """
    Log the start of the analysis workflow.
    """
    logging.info(f"Starting analysis for domain: {domain}")
    logging.info(f"Maximum pages to analyze: {max_pages}")
    logging.info(f"Output directory: {output_dir}")


###############################################################################
# UI REPORTING INTEGRATION
###############################################################################

def on_scraper_finished(self, csv_file, html_file):
    """
    Handle the completion of the scraping process and display results to the user.
    """
    logging.info("Scraper finished successfully.")
    QMessageBox.information(
        self,
        "Success",
        f"Reports generated!\n\nCSV: {csv_file}\nHTML: {html_file}"
    )
    webbrowser.open(html_file)
    self.status_label.setText("Process complete. Ready for another run.")
    self.progress_bar.setValue(self.progress_bar.maximum())


###############################################################################
# MAIN WORKER THREAD INTEGRATION
###############################################################################

class ScraperWorker(QObject):
    """
    Enhanced worker for combining all improvements in the analysis workflow.
    """
    finished = pyqtSignal(str, str)
    error = pyqtSignal(str)
    statusUpdate = pyqtSignal(str)
    analysisProgress = pyqtSignal(int, int)

    def __init__(self, domain, max_pages, driver_path, output_dir, site_password, pagespeed_api):
        super().__init__()
        self.domain = domain
        self.max_pages = max_pages
        self.driver_path = driver_path
        self.output_dir = output_dir
        self.site_password = site_password
        self.api_key = pagespeed_api.strip() if pagespeed_api else None

    @pyqtSlot()
    def run(self):
        """
        Main worker logic for analysis and reporting.
        """
        try:
            log_analysis_start(self.domain, self.max_pages, self.output_dir)

            # Execute the analysis workflow
            results = analyze_links(
                base_url=self.domain,
                max_pages=self.max_pages,
                site_password=self.site_password,
                driver_path=self.driver_path,
                api_key=self.api_key,
                status_callback=self.statusUpdate.emit,
                progress_callback=self.analysisProgress.emit,
            )

            # Save the results and emit completion signal
            csv_file, html_file = save_reports(results, self.output_dir, self.domain)
            self.finished.emit(csv_file, html_file)

        except Exception as e:
            logging.exception(f"Error in worker thread: {e}")
            self.error.emit(str(e))

