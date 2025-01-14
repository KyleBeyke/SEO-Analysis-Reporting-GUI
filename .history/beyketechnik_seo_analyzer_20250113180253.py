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
