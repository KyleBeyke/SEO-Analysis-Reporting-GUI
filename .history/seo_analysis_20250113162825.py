import sys
import os
import re
import time
import threading
import queue
import webbrowser
from datetime import datetime
from urllib.parse import urlparse
from collections import Counter
import multiprocessing
import logging

# NLTK for tokenization & PorterStemmer (no WordNet usage)
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

# For auto-installing/updating ChromeDriver if desired:
# pip install webdriver-manager
from webdriver_manager.chrome import ChromeDriverManager

# Networking / parsing
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

###############################################################################
# STOP WORDS + PORTERSTEMMER
###############################################################################
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
BASE_STOP_WORDS = set(w.strip().lower() for w in RAW_STOP_WORDS.split() if w.strip())
EXTRA_STOP_WORDS = {"another", "also", "be", "is", "was", "were", "do", "does", "did"}
STOP_WORDS = BASE_STOP_WORDS.union(EXTRA_STOP_WORDS)
if "i" in STOP_WORDS:
    STOP_WORDS.remove("i")

stemmer = PorterStemmer()

def advanced_keyword_extraction(text):
    """Use PorterStemmer to avoid WordNet usage."""
    tokens = word_tokenize(text)
    final_tokens = []
    for tok in tokens:
        # Keep "I" if uppercase pronoun
        if tok == "I":
            final_tokens.append("I")
            continue
        lower_tok = tok.lower()
        if re.match(r"^[a-z]+$", lower_tok):
            st = stemmer.stem(lower_tok)
            if st not in STOP_WORDS:
                final_tokens.append(st)
    return Counter(final_tokens)

###############################################################################
# IGNORED EXTENSIONS, BFS, etc.
###############################################################################
IGNORED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
    ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz",
    ".css", ".js", ".ico", ".ttf", ".woff", ".woff2", ".eot"
)

def append_https(domain: str) -> str:
    domain = domain.strip()
    if not domain.startswith(("http://", "https://")):
        return "https://" + domain
    return domain

###############################################################################
# PASSWORD LOGIN
###############################################################################
def attempt_password_login_if_needed(driver, base_url, password):
    """If 'Password protected' is indicated, try a typical WP password form."""
    if not password:
        return
    logging.info(f"attempt_password_login_if_needed -> {base_url}")

    try:
        driver.get(base_url)
        time.sleep(2)  # allow page to load
        # Attempt form approach
        for attempt in range(2):
            try:
                # Common WordPress password-protected form identifiers
                password_input = driver.find_element(By.NAME, "password_protected_pwd")
                submit_button = driver.find_element(By.NAME, "wp-submit")
                password_input.clear()
                password_input.send_keys(password)
                submit_button.click()
                logging.info("Password submitted successfully.")
                time.sleep(2)  # wait for login to process
                break  # exit loop after successful attempt
            except Exception as e:
                logging.warning(f"Password login attempt {attempt + 1} failed: {e}")
                time.sleep(1)
    except Exception as e:
        logging.exception(f"Exception in attempt_password_login: {e}")

###############################################################################
# CONFIGURE DRIVER
###############################################################################
def configure_driver(driver_path=None):
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    if not driver_path:
        # Use webdriver-manager to handle driver
        driver_path = ChromeDriverManager().install()
    driver = webdriver.Chrome(service=Service(driver_path), options=options)
    driver.set_page_load_timeout(15)
    return driver

###############################################################################
# BFS With Selenium
###############################################################################
def scrape_links_with_selenium(driver, base_url, max_pages, status_callback):
    logging.info("Scraping links via BFS with Selenium ...")
    visited = set()
    to_visit = queue.Queue()
    to_visit.put(base_url)
    base_netloc = urlparse(base_url).netloc.lower()

    while not to_visit.empty() and len(visited) < max_pages:
        current_url = to_visit.get()
        if current_url in visited:
            continue
        try:
            if status_callback:
                status_callback(f"[BFS] Visiting {current_url} ({len(visited)+1}/{max_pages})")
            logging.info(f"[BFS] Visiting => {current_url}")
            driver.get(current_url)
            time.sleep(1)  # allow page to load
            visited.add(current_url)

            # gather links
            a_tags = driver.find_elements(By.TAG_NAME, "a")
            for a_ in a_tags:
                href = a_.get_attribute("href")
                if href and urlparse(href).netloc.lower() == base_netloc:
                    if not href.lower().endswith(IGNORED_EXTENSIONS):
                        if href not in visited:
                            to_visit.put(href)
                            if len(visited) + to_visit.qsize() >= max_pages:
                                break
        except Exception as e:
            logging.exception(f"BFS error => {e}")
    return visited

###############################################################################
# PAGE SPEED
###############################################################################
def check_page_speed_insights(url, api_key=None, strategy="mobile"):
    """Checks PageSpeed Insights for a given URL and strategy."""
    if not api_key:
        logging.info(f"No API key -> skipping PageSpeed for {url} ({strategy}).")
        return {"performance_score": None, "error": "No API key"}

    endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {"url": url, "key": api_key, "strategy": strategy}
    logging.info(f"PageSpeed => {url}, strategy={strategy}")
    try:
        r = requests.get(endpoint, params=params, timeout=15)
        if r.status_code != 200:
            logging.warning(f"PageSpeed error {r.status_code} for {url} ({strategy})")
            return {"performance_score": None, "error": f"HTTP {r.status_code}"}
        data = r.json()
        perf = None
        try:
            perf_raw = data["lighthouseResult"]["categories"]["performance"]["score"]
            perf = int(perf_raw * 100)
        except KeyError:
            logging.warning(f"Couldn't parse performance for {url}, strategy={strategy}")
        return {"performance_score": perf, "error": None}
    except Exception as e:
        logging.error(f"Exception calling PageSpeed for {url}, {strategy}: {e}")
        return {"performance_score": None, "error": str(e)}

###############################################################################
# SCORING
###############################################################################
def compute_score_and_recommendations(data):
    score = 0.0
    recs = []
    # Title length
    tl = data.get("TitleLength", 0)
    if 50 <= tl <= 60:
        score += 10
    else:
        recs.append("Adjust Title length to ~50-60 chars.")

    # Meta description length
    mdl = data.get("MetaDescriptionLength", 0)
    if 120 <= mdl <= 160:
        score += 10
    else:
        recs.append("Adjust Meta Description to ~120-160 chars.")

    # H1 count
    h1_count = data.get("H1Count", 0)
    if h1_count > 0:
        score += 10
    else:
        recs.append("Include at least 1 H1 tag.")

    # H2 count
    h2_count = data.get("H2Count", 0)
    if h2_count >= 1:
        score += 5
    else:
        recs.append("Add H2 tags for subtopics.")

    # Word count
    wc = data.get("WordCount", 0)
    if wc >= 300:
        score += 10
    else:
        recs.append("Add more textual content (300+ words).")

    # Images alt coverage
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

    # Canonical
    canonical = data.get("Canonical", "")
    if canonical:
        score += 5
        slug_path = urlparse(canonical).path.lower().strip("/")
        if slug_path:
            slug_words = re.findall(r"[a-z0-9]+", slug_path)
            if len(slug_words) > 0:
                sw_count = sum(1 for w in slug_words if w in STOP_WORDS)
                ratio = sw_count / len(slug_words)
                if ratio > 0.5:
                    score -= 5
                    recs.append("Reduce meaningless/stop words in canonical slug.")
    else:
        recs.append("Include a canonical link if possible.")

    # Noindex
    noindex = data.get("Noindex", False)
    if not noindex:
        score += 10
    else:
        recs.append("Remove 'noindex' unless intentionally blocking search engines.")

    # Structured data
    sd_count = data.get("StructuredDataCount", 0)
    micro_count = data.get("MicrodataCount", 0)
    if sd_count > 0 or micro_count > 0:
        score += 5
    else:
        recs.append("Add structured data (JSON-LD or microdata).")

    # Performance mobile
    perf_mobile = data.get("PerformanceScoreMobile", None)
    if isinstance(perf_mobile, int):
        if perf_mobile >= 90:
            score += 5
        elif perf_mobile >= 70:
            score += 3
        else:
            recs.append("Improve mobile performance per PageSpeed.")
    else:
        recs.append("Consider PageSpeed analysis (mobile).")

    # Performance desktop
    perf_desktop = data.get("PerformanceScoreDesktop", None)
    if isinstance(perf_desktop, int):
        if perf_desktop >= 90:
            score += 5
        elif perf_desktop >= 70:
            score += 3
        else:
            recs.append("Improve desktop performance per PageSpeed.")
    else:
        recs.append("Consider PageSpeed analysis (desktop).")

    # Synergy-based score
    if tl and mdl and not noindex:
        score += 10

    # Cap at 100
    if score > 100:
        score = 100
    if score < 0:
        score = 0
    final_score = int(score)

    if not recs:
        recs_str = "Fully optimized!"
    else:
        recs_str = "; ".join(recs)

    return final_score, recs_str

###############################################################################
# ANALYZE SINGLE PAGE
###############################################################################
def analyze_page(driver, url, status_callback, current_idx, total_count,
                 sitewide_word_counts, api_key=None):
    logging.info(f"Analyzing => {url} (idx {current_idx}/{total_count})")
    data = {
        "URL": url, "Title": "", "TitleLength": 0, "MetaDescriptionLength": 0,
        "H1Count": 0, "H2Count": 0, "WordCount": 0, "Keywords": "",
        "Canonical": "", "Noindex": False,
        "ImagesWithoutAlt": 0, "ImageCount": 0,
        "StructuredDataCount": 0, "MicrodataCount": 0,
        "PerformanceScoreMobile": None, "PerformanceScoreDesktop": None,
        "Score": 0, "Recommendations": "", "Error": ""
    }
    try:
        if status_callback:
            status_callback(f"Analyzing ({current_idx}/{total_count}): {url}")
        driver.get(url)
        time.sleep(1)  # Allow page to load
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        # Title
        title_tag = soup.find("title")
        title_text = title_tag.get_text().strip() if title_tag else ""
        data["Title"] = title_text
        data["TitleLength"] = len(title_text)

        # Meta description
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = meta_desc_tag.get("content").strip() if (meta_desc_tag and meta_desc_tag.get("content")) else ""
        data["MetaDescriptionLength"] = len(meta_desc)

        # H1 and H2 tags
        h1_tags = soup.find_all("h1")
        h2_tags = soup.find_all("h2")
        data["H1Count"] = len(h1_tags)
        data["H2Count"] = len(h2_tags)

        # Canonical link
        canonical_tag = soup.find("link", rel="canonical")
        canonical_href = (canonical_tag.get("href").strip()
                          if (canonical_tag and canonical_tag.get("href"))
                          else "")
        data["Canonical"] = canonical_href

        # Noindex
        robots_meta = soup.find("meta", attrs={"name": re.compile(r"robots", re.I)})
        robots_content = (robots_meta.get("content").lower()
                          if (robots_meta and robots_meta.get("content"))
                          else "")
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

        # Keywords
        text_content = soup.get_text(separator=" ", strip=True)
        wc = advanced_keyword_extraction(text_content)
        data["WordCount"] = sum(wc.values())
        sitewide_word_counts.update(wc)
        top_5 = wc.most_common(5)
        data["Keywords"] = ", ".join(f"{k}({v})" for (k, v) in top_5)

        # PageSpeed
        if api_key:
            logging.info(f"PageSpeed => {url} (mobile)")
            ps_m = check_page_speed_insights(url, api_key, "mobile")
            data["PerformanceScoreMobile"] = ps_m["performance_score"]

            logging.info(f"PageSpeed => {url} (desktop)")
            ps_d = check_page_speed_insights(url, api_key, "desktop")
            data["PerformanceScoreDesktop"] = ps_d["performance_score"]

        # Scoring
        final_score, recs = compute_score_and_recommendations(data)
        data["Score"] = final_score
        data["Recommendations"] = recs

        # Log the extracted data for verification
        logging.info(f"Data for {url}: {data}")

    except Exception as e:
        data["Error"] = str(e)
        logging.exception(f"analyze_page => {url} failed: {e}")

    return data

###############################################################################
# ScraperWorker Class
###############################################################################
class ScraperWorker(QObject):
    finished = pyqtSignal(str, str)
    error = pyqtSignal(str)
    statusUpdate = pyqtSignal(str)
    analysisProgress = pyqtSignal(int, int)

    def __init__(self, domain, max_pages, driver_path, output_dir, site_password, pagespeed_api):
        super().__init__()
        self.domain = domain
        self.max_pages = min(max_pages, 999)
        self.driver_path = driver_path
        self.output_dir = output_dir
        self.site_password = site_password
        self.api_key = pagespeed_api.strip() if pagespeed_api else None

        self.sitewide_word_counts = Counter()
        self.current_count = 0
        self.total_count = 0

    @pyqtSlot()
    def run(self):
        try:
            base_url = append_https(self.domain)
            logging.info(f"[WORKER] Starting BFS for {base_url}")

            driver = configure_driver(self.driver_path)
            # Attempt password if needed
            attempt_password_login_if_needed(driver, base_url, self.site_password)

            # BFS gather
            links = scrape_links_with_selenium(driver, base_url, self.max_pages, self.statusUpdate.emit)
            driver.quit()

            unique_links = list(links)
            logging.info(f"[WORKER] Total unique links collected: {len(unique_links)}")
            self.statusUpdate.emit(f"Collected {len(unique_links)} URLs. Starting analysis...")

            self.current_count = 0
            self.total_count = len(unique_links)

            # Analyze concurrency
            results = self.analyze_pages_in_pool(unique_links, self.statusUpdate.emit)

            # SITEWIDE row
            top_10_sitewide = self.sitewide_word_counts.most_common(10)
            top_10_str = ", ".join(f"{k}({v})" for k, v in top_10_sitewide)

            sitewide_row = {
                "URL": "SITEWIDE",
                "Title": "",
                "TitleLength": 0,
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
                "PerformanceScoreMobile": None,
                "PerformanceScoreDesktop": None,
                "Score": 0,
                "Recommendations": "",
                "Error": ""
            }
            results.append(sitewide_row)

            self.statusUpdate.emit("Writing reports...")
            domain_name = re.sub(r'[^a-zA-Z0-9.-]', '_', urlparse(base_url).netloc)
            date_str = datetime.now().strftime("%Y%m%d_%H%M")
            csv_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{date_str}.csv")
            html_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{date_str}.html")

            logging.info(f"[WORKER] Saving CSV => {csv_file}")
            logging.info(f"[WORKER] Saving HTML => {html_file}")
            df = pd.DataFrame(results)
            df.to_csv(csv_file, index=False)
            df.to_html(html_file, index=False)

            logging.info(f"[WORKER] Reports saved successfully.")
            self.finished.emit(csv_file, html_file)
        except Exception as e:
            logging.exception(f"[WORKER] Exception in BFS + analysis => {e}")
            self.error.emit(str(e))

    def analyze_pages_in_pool(self, urls, progress_callback):
        cores = multiprocessing.cpu_count()
        n_workers = max(int(0.75 * cores), 1)
        logging.info(f"analyze_pages_in_pool => concurrency={n_workers} from {cores} cores")

        def worker(drv, chunk, offset):
            local_results = []
            for i, url_ in enumerate(chunk):
                idx = offset + i + 1
                row = analyze_page(drv, url_, self.statusUpdate.emit, idx, len(urls),
                                   self.sitewide_word_counts, self.api_key)
                local_results.append(row)
                progress_callback(1)
            return local_results

        # Create multiple drivers for concurrency
        drivers = [configure_driver(self.driver_path) for _ in range(n_workers)]
        chunk_size = max(1, len(urls) // n_workers + 1)
        chunks = [urls[i : i + chunk_size] for i in range(0, len(urls), chunk_size)]

        results = []
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            future_map = {}
            offset = 0
            for drv, c_ in zip(drivers, chunks):
                fut = executor.submit(worker, drv, c_, offset)
                future_map[fut] = drv
                offset += len(c_)

            for fut in as_completed(future_map):
                try:
                    results.extend(fut.result())
                except Exception as e:
                    logging.exception(f"analyze_pages_in_pool thread error => {e}")

        logging.info("Analyze concurrency finished, cleaning up drivers.")
        for d_ in drivers:
            try:
                d_.quit()
            except Exception as e:
                logging.warning(f"Error quitting driver: {e}")

        return results

###############################################################################
# MAIN WINDOW (GUI)
###############################################################################
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BeykeTechnik SEO Analyzer (PorterStemmer + BFS)")
        self.resize(600, 600)

        # Domain
        self.domain_label = QLabel("Domain / URL:")
        self.domain_input = QLineEdit("example.com")

        # Password
        self.protected_check = QCheckBox("Password protected?")
        self.protected_check.stateChanged.connect(self.on_protected_toggled)
        self.password_label = QLabel("Password:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_label.setVisible(False)
        self.password_input.setVisible(False)

        self.password_show_btn = QPushButton("Show")
        self.password_show_btn.setCheckable(True)
        self.password_show_btn.clicked.connect(self.toggle_password_visibility)
        self.password_show_btn.setVisible(False)

        # PageSpeed
        self.pagespeed_label = QLabel("PageSpeed API Key:")
        self.pagespeed_input = QLineEdit("YOUR_API_KEY_HERE")
        self.pagespeed_input.setEchoMode(QLineEdit.Password)
        self.pagespeed_show_btn = QPushButton("Show")
        self.pagespeed_show_btn.setCheckable(True)
        self.pagespeed_show_btn.clicked.connect(self.toggle_pagespeed_visibility)

        # Max Pages
        self.max_pages_label = QLabel("Max Pages (up to 999):")
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(1, 999)
        self.max_pages_spin.setValue(10)

        # ChromeDriver
        self.driver_path_label = QLabel("ChromeDriver Path:")
        self.driver_path_input = QLineEdit("/usr/local/bin/chromedriver")

        # Output directory
        self.output_dir_label = QLabel("Output Directory:")
        self.output_dir_button = QPushButton("Select...")
        self.output_dir_button.clicked.connect(self.select_output_directory)
        self.chosen_dir_label = QLabel(os.getcwd())

        # Enable Logging
        self.enable_logging_check = QCheckBox("Enable Detailed Log File?")
        self.enable_logging_check.setChecked(False)

        # Start
        self.start_button = QPushButton("Start Analysis")
        self.start_button.clicked.connect(self.start_scraping)

        # Status & progress
        self.status_label = QLabel("Ready.")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setAlignment(Qt.AlignCenter)

        self.output_dir = os.getcwd()

        # Layout
        layout = QVBoxLayout()

        layout.addWidget(self.domain_label)
        layout.addWidget(self.domain_input)

        layout.addWidget(self.protected_check)
        layout.addWidget(self.password_label)
        pass_layout = QHBoxLayout()
        pass_layout.addWidget(self.password_input)
        pass_layout.addWidget(self.password_show_btn)
        layout.addLayout(pass_layout)

        layout.addWidget(self.pagespeed_label)
        ps_layout = QHBoxLayout()
        ps_layout.addWidget(self.pagespeed_input)
        ps_layout.addWidget(self.pagespeed_show_btn)
        layout.addLayout(ps_layout)

        layout.addWidget(self.max_pages_label)
        layout.addWidget(self.max_pages_spin)

        layout.addWidget(self.driver_path_label)
        layout.addWidget(self.driver_path_input)

        layout.addWidget(self.output_dir_label)
        layout.addWidget(self.output_dir_button)
        layout.addWidget(self.chosen_dir_label)

        layout.addWidget(self.enable_logging_check)

        layout.addWidget(self.start_button)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.scraper_thread = None

    def on_protected_toggled(self, state):
        if state == Qt.Checked:
            self.password_label.setVisible(True)
            self.password_input.setVisible(True)
            self.password_show_btn.setVisible(True)
        else:
            self.password_label.setVisible(False)
            self.password_input.setVisible(False)
            self.password_show_btn.setVisible(False)

    def toggle_password_visibility(self):
        if self.password_show_btn.isChecked():
            self.password_input.setEchoMode(QLineEdit.Normal)
            self.password_show_btn.setText("Hide")
        else:
            self.password_input.setEchoMode(QLineEdit.Password)
            self.password_show_btn.setText("Show")

    def toggle_pagespeed_visibility(self):
        if self.pagespeed_show_btn.isChecked():
            self.pagespeed_input.setEchoMode(QLineEdit.Normal)
            self.pagespeed_show_btn.setText("Hide")
        else:
            self.pagespeed_input.setEchoMode(QLineEdit.Password)
            self.pagespeed_show_btn.setText("Show")

    def select_output_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.output_dir = folder
            self.chosen_dir_label.setText(folder)

    def start_scraping(self):
        # Force remove any existing root handlers
        for h in logging.root.handlers[:]:
            logging.root.removeHandler(h)

        log_file = os.path.join(self.output_dir, "seo_analysis.log")
        try:
            if self.enable_logging_check.isChecked():
                logging.basicConfig(
                    level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[
                        logging.FileHandler(log_file, mode='w'),
                        logging.StreamHandler(sys.stdout)
                    ],
                    force=True  # Only works in Python 3.8+
                )
                logging.info("Detailed logging to file enabled. (force=True approach)")
            else:
                logging.basicConfig(
                    level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)],
                    force=True  # Only works in Python 3.8+
                )
                logging.warning("Minimal logging => console only. (force=True approach)")
        except TypeError:
            # Python < 3.8
            if self.enable_logging_check.isChecked():
                logging.basicConfig(
                    level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[
                        logging.FileHandler(log_file, mode='w'),
                        logging.StreamHandler(sys.stdout)
                    ]
                )
                logging.info("Detailed logging to file enabled. (no force=True fallback)")
            else:
                logging.basicConfig(
                    level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)]
                )
                logging.warning("Minimal logging => console only. (no force=True fallback)")

        logging.info("TEST: Logging is configured. This line must appear in seo_analysis.log if all is well.")
        logging.info(f"Active handlers right now: {logging.root.handlers}")

        self.start_button.setEnabled(False)
        self.status_label.setText("Initializing...")
        self.progress_bar.setRange(0, 0)  # Indeterminate progress

        domain = self.domain_input.text().strip()
        max_pages = self.max_pages_spin.value()
        driver_path = self.driver_path_input.text().strip()

        site_password = ""
        if self.protected_check.isChecked():
            site_password = self.password_input.text().strip()

        pagespeed_api = self.pagespeed_input.text()

        logging.info(f"start_scraping invoked. Domain={domain}, MaxPages={max_pages}, "
                     f"DriverPath={driver_path}, PasswordLen={len(site_password)}, "
                     f"PageSpeedKeyLen={len(pagespeed_api)}")

        self.scraper_thread = QThread()
        self.worker = ScraperWorker(
            domain, max_pages, driver_path, self.output_dir,
            site_password, pagespeed_api
        )
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
        logging.info("Scraper finished -> on_scraper_finished triggered.")
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
        logging.error(f"on_scraper_error => {error_msg}")
        QMessageBox.critical(self, "Error", f"An error occurred: {error_msg}")
        self.status_label.setText("Error. Check logs or try again.")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)

    @pyqtSlot()
    def cleanup_after_scraping(self):
        logging.info("cleanup_after_scraping called.")
        self.scraper_thread = None
        self.worker = None
        self.start_button.setEnabled(True)

    @pyqtSlot(str)
    def on_status_update(self, message):
        logging.info(f"statusUpdate => {message}")
        self.status_label.setText(message)

###############################################################################
# MAIN
###############################################################################
if __name__ == "__main__":
    print("MAIN: Launching BeykeTechnik SEO Analyzer (PorterStemmer + BFS).")

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
