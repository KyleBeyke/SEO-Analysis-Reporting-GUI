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

# NLTK for advanced tokenization & lemmatization (including 'punkt_tab')
import nltk

###############################################################################
# NLTK Setup (WordNet fallback)
###############################################################################
# Attempt to ensure 'punkt_tab', 'punkt', and 'wordnet' are installed.
# If there's a mismatch or partial install, we do a fallback in code below.
nltk.download("punkt_tab", quiet=True)
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt", quiet=True)

try:
    nltk.data.find("corpora/wordnet")
except LookupError:
    nltk.download("wordnet", quiet=True)

try:
    nltk.data.find("corpora/omw-1.4")
except LookupError:
    # sometimes needed for lemmatization synonyms
    nltk.download("omw-1.4", quiet=True)

from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer, PorterStemmer

###############################################################################
# PyQt5
###############################################################################
from PyQt5.QtCore import (
    Qt, QObject, pyqtSignal, pyqtSlot, QThread
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit,
    QVBoxLayout, QPushButton, QWidget, QSpinBox,
    QMessageBox, QFileDialog, QProgressBar, QCheckBox, QHBoxLayout
)

# Selenium & related
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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
# GLOBAL CONSTANTS
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

IGNORED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
    ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz"
)

MAX_LIMIT = 999
lemmatizer = WordNetLemmatizer()
stemmer = PorterStemmer()  # fallback if WordNet fails

###############################################################################
# PageSpeed Calls
###############################################################################
def check_page_speed_insights(url, api_key=None, strategy="mobile"):
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
        except:
            logging.warning(f"Couldn't parse PageSpeed perf for {url} ({strategy})")
        return {"performance_score": perf, "error": None}
    except Exception as e:
        logging.error(f"Exception calling PageSpeed for {url}, {strategy}: {e}")
        return {"performance_score": None, "error": str(e)}

###############################################################################
# Helper Functions
###############################################################################
def append_https(domain: str) -> str:
    domain = domain.strip()
    if not domain.startswith(("http://", "https://")):
        return "https://" + domain
    return domain

def sanitize_domain(netloc: str) -> str:
    return re.sub(r'[^a-zA-Z0-9.-]', '_', netloc)

def normalize_netloc(netloc: str) -> str:
    return netloc.lower().replace("www.", "")

def configure_driver(driver_path=None):
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    if not driver_path:
        driver_path = "/usr/local/bin/chromedriver"
    driver = webdriver.Chrome(
        service=Service(driver_path),
        options=options
    )
    driver.set_page_load_timeout(15)
    return driver

###############################################################################
# Password-Protection
###############################################################################
def attempt_password_login_if_needed(driver, base_url, site_password):
    logging.info(f"attempt_password_login_if_needed -> {base_url}")
    if not site_password:
        logging.info("No password => skipping login.")
        return

    try:
        # 1) Go to base, check form
        driver.get(base_url)
        time.sleep(2)  # wait
        logging.info("Loaded base URL => searching WP password form.")
        for attempt in range(2):
            logging.info(f"Attempt #{attempt+1} for WP password form.")
            forms = driver.find_elements(By.CSS_SELECTOR, "form[action*='password-protected=login']")
            pass_input = None
            if forms:
                logging.info(f"Found {len(forms)} form(s) with 'password-protected=login'.")
                try:
                    pass_input = forms[0].find_element(By.NAME, "password_protected_pwd")
                    logging.info("Found input 'password_protected_pwd' in form.")
                except:
                    logging.info("Couldn't find 'password_protected_pwd' in that form.")
            else:
                logging.info("No form found -> fallback outside form.")
                try:
                    pass_input = driver.find_element(By.NAME, "password_protected_pwd")
                    logging.info("Found fallback 'password_protected_pwd'.")
                except:
                    logging.info("Fallback also didn't see the input.")

            if pass_input:
                logging.info("Filling password, clicking submit.")
                pass_input.clear()
                pass_input.send_keys(site_password)
                time.sleep(1)
                try:
                    btn = driver.find_element(By.NAME, "wp-submit")
                    logging.info("Found 'wp-submit' => clicking.")
                    btn.click()
                except:
                    logging.info("No 'wp-submit' => pressing ENTER.")
                    pass_input.send_keys(Keys.RETURN)

                time.sleep(2)
                # 2) Re-get base to confirm login
                logging.info("Re-get base URL to confirm login.")
                driver.get(base_url)
                time.sleep(2)
            else:
                logging.info("No password input => skipping next attempt.")
                break
    except Exception as e:
        logging.exception(f"Exception in password login: {e}")

###############################################################################
# Sitemaps
###############################################################################
def parse_sitemap_xml(xml_text):
    logging.info("Parsing sitemap XML content.")
    root = ET.fromstring(xml_text)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    tag_name = root.tag.lower()

    sub_sitemaps = []
    links = []

    if "sitemapindex" in tag_name:
        logging.info("Detected <sitemapindex> from XML content.")
        for sitemap_tag in root.findall(f"{ns}sitemap"):
            loc_tag = sitemap_tag.find(f"{ns}loc")
            if loc_tag is not None and loc_tag.text:
                sub_sitemaps.append(loc_tag.text.strip())
    elif "urlset" in tag_name:
        logging.info("Detected <urlset> from XML content.")
        for url_tag in root.findall(f"{ns}url"):
            loc_tag = url_tag.find(f"{ns}loc")
            if loc_tag is not None and loc_tag.text:
                links.append(loc_tag.text.strip())

    return sub_sitemaps, links

def gather_links_from_sitemap(base_url, max_pages, status_callback=None, site_password=""):
    # 1) For the password logic
    driver = configure_driver()
    attempt_password_login_if_needed(driver, base_url, site_password)
    driver.quit()

    # 2) Attempt /sitemap.xml with normal redirects
    sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
    if status_callback:
        status_callback(f"Attempting to fetch {sitemap_url}")
    logging.info(f"Fetching {sitemap_url} with requests.")
    try:
        resp = requests.get(sitemap_url, timeout=10, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logging.warning(f"Error fetching {sitemap_url}: {e}")
        # fallback => sitemap_index.xml
        alt_sitemap_url = base_url.rstrip("/") + "/sitemap_index.xml"
        logging.info(f"Trying alt sitemap => {alt_sitemap_url}")
        if status_callback:
            status_callback(f"Attempting alt sitemap: {alt_sitemap_url}")
        try:
            resp_alt = requests.get(alt_sitemap_url, timeout=10, allow_redirects=True)
            resp_alt.raise_for_status()
            resp = resp_alt
        except Exception as e2:
            raise Exception(f"Both /sitemap.xml & /sitemap_index.xml failed: {e2}")

    # parse
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
                visited.add(lk)
                if len(visited) >= max_pages:
                    break
        except Exception as e:
            logging.warning(f"Failed sub-sitemap {smap}: {e}")
            if status_callback:
                status_callback(f"Warning: {smap} => {e}")

    filtered = []
    for lk in visited:
        if not any(lk.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
            filtered.append(lk)
    return filtered[:max_pages]

###############################################################################
# BFS (Enhanced w/ domain mismatch logs + loadMore logic + BFS depth=2)
###############################################################################
def try_load_more_buttons(drv):
    """
    Attempt to find 'Load More' or 'See More' or 'View More' buttons
    and click them once, letting the page load for 2s each time.
    """
    load_more_candidates = ["load more", "show more", "see more", "view more"]
    clicked_something = False

    # We'll just do a simplistic approach:
    for phrase in load_more_candidates:
        try:
            # find any button that contains the phrase
            btns = drv.find_elements(By.XPATH, f"//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '{phrase}')]")
            if btns:
                logging.info(f"Found {len(btns)} '{phrase}' button(s), clicking first.")
                btns[0].click()
                time.sleep(2)
                clicked_something = True
                break
        except:
            pass
    return clicked_something

def scroll_and_collect(drv):
    """
    Scroll to bottom multiple times, attempt a single 'load more' click,
    then scroll again. BFS Depth approach if needed.
    """
    for _ in range(2):
        drv.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        # Possibly click a 'Load More' if it exists
        clicked = try_load_more_buttons(drv)
        if clicked:
            # re-scroll after loading more content
            drv.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

    return drv.find_elements(By.TAG_NAME, "a")

def selenium_bfs_concurrent(base_url, max_pages, status_callback=None,
                            driver_path=None, site_password="", bfs_depth=2):
    """
    BFS approach with:
      - concurrency
      - password login pre-check
      - domain mismatch logs
      - BFS up to depth=2
    """
    logging.info(f"Starting BFS concurrency => base_url={base_url}, depth={bfs_depth}")

    # login
    d = configure_driver(driver_path)
    attempt_password_login_if_needed(d, base_url, site_password)
    d.quit()

    if status_callback:
        status_callback("Sitemap not found or empty. BFS with advanced concurrency...")

    # We'll store (url, depth) in the queue
    visited = set()
    q = queue.Queue()
    base_netloc = normalize_netloc(urlparse(base_url).netloc)
    q.put((base_url, 0))

    cores = multiprocessing.cpu_count()
    n_workers = max(int(0.75 * cores), 1)
    logging.info(f"BFS concurrency with {n_workers} workers from {cores} cores.")

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

            visited.add(url_)
            idx = len(visited)
            if status_callback:
                status_callback(f"[BFS] Visiting {url_} ({idx}/{max_pages})")
            logging.info(f"[BFS] Visiting => {url_} depth={depth_}")

            try:
                drv.get(url_)
                time.sleep(1)  # small wait
                a_tags = scroll_and_collect(drv)
                for a_ in a_tags:
                    href = a_.get_attribute("href") or ""
                    if not href:
                        logging.debug(f"[BFS] ignoring empty href from {url_}")
                        continue
                    if any(href.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
                        logging.debug(f"[BFS] ignoring file ext => {href}")
                        continue
                    link_netloc = normalize_netloc(urlparse(href).netloc)
                    if link_netloc != base_netloc:
                        logging.debug(f"[BFS] ignoring external domain => {href}")
                        continue

                    if len(visited) + q.qsize() < max_pages:
                        if href not in visited:
                            # Only push if depth < bfs_depth
                            if depth_ < bfs_depth:
                                q.put((href, depth_ + 1))
                            else:
                                logging.debug(f"[BFS] ignoring because max BFS depth => {href}")
            except Exception as e:
                logging.exception(f"BFS Worker exception @ {url_}: {e}")
            finally:
                q.task_done()

    drivers = [configure_driver(driver_path) for _ in range(n_workers)]
    threads = []
    for drv_ in drivers:
        t = threading.Thread(target=bfs_worker, args=(drv_,), daemon=True)
        threads.append(t)
        t.start()

    q.join()
    logging.info("BFS concurrency finished => cleaning up drivers.")
    for drv_ in drivers:
        try:
            drv_.quit()
        except:
            pass

    # Return up to max_pages
    return list(visited)[:max_pages]

###############################################################################
# Keyword Extraction (with fallback if WordNet fails)
###############################################################################
def advanced_keyword_extraction(text):
    tokens = word_tokenize(text)
    final_tokens = []
    for tok in tokens:
        if tok == "I":
            final_tokens.append("I")
            continue
        lower_tok = tok.lower()
        if re.match(r"^[a-z]+$", lower_tok):
            # Attempt WordNet lemmatization, fallback to PorterStemmer if fails
            lemma = None
            try:
                lemma = lemmatizer.lemmatize(lower_tok)
            except Exception as e:
                logging.warning(f"WordNet lemmatize error => fallback to PorterStemmer: {e}")
                lemma = stemmer.stem(lower_tok)
            if lemma not in STOP_WORDS:
                final_tokens.append(lemma)
    return Counter(final_tokens)

###############################################################################
# Scoring
###############################################################################
def compute_score_and_recommendations(data):
    from urllib.parse import urlparse
    score = 0.0
    recs = []

    # Title length
    tl = data.get("TitleLength", 0)
    if 50 <= tl <= 60:
        score += 10
    else:
        recs.append("Adjust Title length to ~50-60 chars.")

    # Meta desc length
    mdl = data.get("MetaDescriptionLength", 0)
    if 120 <= mdl <= 160:
        score += 10
    else:
        recs.append("Adjust Meta Description to ~120-160 chars.")

    # H1
    h1_count = data.get("H1Count", 0)
    if h1_count > 0:
        score += 10
    else:
        recs.append("Include at least 1 H1 tag.")

    # H2
    h2_count = data.get("H2Count", 0)
    if h2_count >= 1:
        score += 5
    else:
        recs.append("Add H2 tags for subtopics.")

    # WordCount
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

    # noindex
    noindex = data.get("Noindex", False)
    if not noindex:
        score += 10
    else:
        recs.append("Remove 'noindex' unless intentionally blocking search engines.")

    # structured data
    sd_count = data.get("StructuredDataCount", 0)
    micro_count = data.get("MicrodataCount", 0)
    if sd_count > 0 or micro_count > 0:
        score += 5
    else:
        recs.append("Add structured data (JSON-LD or microdata).")

    # performance mobile
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

    # performance desktop
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

    # synergy
    if tl and mdl and not noindex:
        score += 10

    # cap at 100
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
# ANALYZE PAGE
###############################################################################
def analyze_page(driver, url, status_callback, current_idx, total_count,
                 sitewide_word_counts, api_key=None):
    logging.info(f"Analyzing => {url} (idx {current_idx}/{total_count})")
    data = {
        "URL": url,
        "Title": "",
        "TitleLength": 0,
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
        "PerformanceScoreMobile": None,
        "PerformanceScoreDesktop": None,
        "Score": 0,
        "Recommendations": "",
        "Error": ""
    }
    try:
        if status_callback:
            status_callback(f"Analyzing ({current_idx}/{total_count}): {url}")
        driver.get(url)
        # short wait
        time.sleep(1)
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        # Title
        title_tag = soup.find("title")
        title_text = title_tag.get_text().strip() if title_tag else ""
        data["Title"] = title_text
        data["TitleLength"] = len(title_text)

        # Meta Desc
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = meta_desc_tag.get("content").strip() if (meta_desc_tag and meta_desc_tag.get("content")) else ""
        data["MetaDescriptionLength"] = len(meta_desc)

        # H1 / H2
        h1_tags = soup.find_all("h1")
        h2_tags = soup.find_all("h2")
        data["H1Count"] = len(h1_tags)
        data["H2Count"] = len(h2_tags)

        # Canonical
        canonical_tag = soup.find("link", rel="canonical")
        canonical_href = (canonical_tag.get("href").strip()
                          if (canonical_tag and canonical_tag.get("href"))
                          else "")
        data["Canonical"] = canonical_href

        # Noindex?
        robots_meta = soup.find("meta", attrs={"name": re.compile(r"robots", re.I)})
        robots_content = (robots_meta.get("content").lower()
                          if (robots_meta and robots_meta.get("content"))
                          else "")
        data["Noindex"] = ("noindex" in robots_content)

        # Images
        images = soup.find_all("img")
        data["ImageCount"] = len(images)
        alt_missing = sum(1 for i_ in images if not i_.get("alt"))
        data["ImagesWithoutAlt"] = alt_missing

        # structured data
        ld_json = soup.find_all("script", attrs={"type": "application/ld+json"})
        data["StructuredDataCount"] = len(ld_json)
        microdata = soup.find_all(attrs={"itemtype": True})
        data["MicrodataCount"] = len(microdata)

        # Keywords
        text_content = soup.get_text(separator=" ", strip=True)
        word_counts = advanced_keyword_extraction(text_content)
        data["WordCount"] = sum(word_counts.values())
        sitewide_word_counts.update(word_counts)
        top_5 = word_counts.most_common(5)
        data["Keywords"] = ", ".join(f"{k}({v})" for (k, v) in top_5)

        # PageSpeed
        if api_key:
            logging.info(f"PageSpeed mobile => {url}")
            ps_mobile = check_page_speed_insights(url, api_key=api_key, strategy="mobile")
            data["PerformanceScoreMobile"] = ps_mobile["performance_score"]

            logging.info(f"PageSpeed desktop => {url}")
            ps_desktop = check_page_speed_insights(url, api_key=api_key, strategy="desktop")
            data["PerformanceScoreDesktop"] = ps_desktop["performance_score"]

        # Score
        final_score, recs = compute_score_and_recommendations(data)
        data["Score"] = final_score
        data["Recommendations"] = recs

    except Exception as e:
        data["Error"] = str(e)
        logging.exception(f"Exception analyzing => {url}: {e}")

    return data

###############################################################################
# ANALYZE PAGES
###############################################################################
def analyze_pages_in_pool(urls, driver_path, status_callback, progress_callback,
                          sitewide_word_counts, api_key=None):
    cores = multiprocessing.cpu_count()
    n_workers = max(int(0.75 * cores), 1)
    logging.info(f"Analyze pages => concurrency = {n_workers} from {cores} cores")

    def worker(drv, chunk, offset):
        local_results = []
        for i, url_ in enumerate(chunk):
            row = analyze_page(
                driver=drv,
                url=url_,
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
        logging.info("No URLs => returning empty results.")
        return []

    drivers = [configure_driver(driver_path) for _ in range(n_workers)]
    chunk_size = max(1, len(urls) // n_workers + 1)
    chunks = [urls[i : i + chunk_size] for i in range(0, len(urls), chunk_size)]

    results = []
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        future_map = {}
        offset = 0
        for drv, chunk_ in zip(drivers, chunks):
            fut = executor.submit(worker, drv, chunk_, offset)
            future_map[fut] = drv
            offset += len(chunk_)

        for fut in as_completed(future_map):
            try:
                results.extend(fut.result())
            except Exception as e:
                logging.exception(f"Thread error => {e}")

    logging.info("Done analyzing pages => cleaning up drivers.")
    for d_ in drivers:
        try:
            d_.quit()
        except:
            pass

    return results

###############################################################################
# WORKER CLASS
###############################################################################
class ScraperWorker(QObject):
    finished = pyqtSignal(str, str)
    error = pyqtSignal(str)
    statusUpdate = pyqtSignal(str)
    analysisProgress = pyqtSignal(int, int)

    def __init__(self, domain, max_pages, driver_path, output_dir, site_password, pagespeed_api):
        super().__init__()
        self.domain = domain
        self.max_pages = min(max_pages, MAX_LIMIT)
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
            logging.info(f"Worker => base_url={base_url}")

            # Attempt sitemaps
            links = []
            try:
                links = gather_links_from_sitemap(
                    base_url,
                    self.max_pages,
                    status_callback=self.statusUpdate.emit,
                    site_password=self.site_password
                )
            except Exception as e:
                msg = f"Sitemap attempt failed => {e}"
                logging.warning(msg)
                self.statusUpdate.emit(msg)

            if not links:
                logging.info("No links from sitemap => fallback BFS concurrency.")
                # BFS with depth=2
                links = selenium_bfs_concurrent(
                    base_url,
                    self.max_pages,
                    status_callback=self.statusUpdate.emit,
                    driver_path=self.driver_path,
                    site_password=self.site_password,
                    bfs_depth=2
                )

            unique_links = list(dict.fromkeys(links))
            if len(unique_links) > self.max_pages:
                unique_links = unique_links[:self.max_pages]

            collect_msg = f"Collected {len(unique_links)} URLs. Starting analysis..."
            logging.info(collect_msg)
            self.statusUpdate.emit(collect_msg)

            self.current_count = 0
            self.total_count = len(unique_links)

            def increment_analysis(x=1):
                self.current_count += x
                self.analysisProgress.emit(self.current_count, self.total_count)

            # Analyze pages concurrency
            logging.info("Analyzing pages in concurrency pool.")
            results = analyze_pages_in_pool(
                urls=unique_links,
                driver_path=self.driver_path,
                status_callback=self.statusUpdate.emit,
                progress_callback=increment_analysis,
                sitewide_word_counts=self.sitewide_word_counts,
                api_key=self.api_key
            )

            self.statusUpdate.emit("Generating final keywords row...")

            # Final row => sitewide
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

            domain_name = sanitize_domain(urlparse(base_url).netloc)
            date_str = datetime.now().strftime("%Y%m%d_%H%M")
            csv_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{date_str}.csv")
            html_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{date_str}.html")

            logging.info(f"Saving CSV => {csv_file}")
            logging.info(f"Saving HTML => {html_file}")
            df = pd.DataFrame(results)
            df.to_csv(csv_file, index=False)
            df.to_html(html_file, index=False)

            self.finished.emit(csv_file, html_file)
        except Exception as e:
            logging.exception(f"Exception in worker run => {e}")
            self.error.emit(str(e))
        finally:
            # Force flush logs at end of run
            logging.info("Run complete => shutting down logs.")
            logging.shutdown()

###############################################################################
# MAIN WINDOW (GUI)
###############################################################################
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BeykeTechnik SEO Analyzer (Enhanced)")

        self.resize(500, 500)

        # Domain
        self.domain_label = QLabel("Domain / URL:")
        self.domain_input = QLineEdit("example.com")

        # Check if password needed
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
        self.pagespeed_input = QLineEdit("AIzaSyB8R9HLyxA6cvv2PLzhh4fWXxlXlSopnpg")
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
        self.driver_path_label = QLabel("ChromeDriver Path (optional):")
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
        # Logging config
        if self.enable_logging_check.isChecked():
            log_file = os.path.join(self.output_dir, "seo_analysis.log")
            # Clear old handlers if any
            for h in logging.root.handlers[:]:
                logging.root.removeHandler(h)
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(message)s",
                handlers=[
                    logging.FileHandler(log_file, mode='w'),
                    logging.StreamHandler(sys.stdout)
                ]
            )
            logging.info("TEST: Logging started! Detailed logging enabled.")
        else:
            for h in logging.root.handlers[:]:
                logging.root.removeHandler(h)
            logging.basicConfig(
                level=logging.WARNING,
                format="%(asctime)s [%(levelname)s] %(message)s",
                handlers=[logging.StreamHandler(sys.stdout)]
            )
            logging.warning("Minimal logging => console only.")

        self.start_button.setEnabled(False)
        self.status_label.setText("Initializing...")
        self.progress_bar.setRange(0, 0)

        domain = self.domain_input.text().strip()
        max_pages = self.max_pages_spin.value()
        driver_path = self.driver_path_input.text().strip()

        site_password = ""
        if self.protected_check.isChecked():
            site_password = self.password_input.text().strip()

        pagespeed_api = self.pagespeed_input.text()

        logging.info(f"start_scraping => domain={domain}, max_pages={max_pages}, driver={driver_path}, "
                     f"pwd_len={len(site_password)}, ps_api_len={len(pagespeed_api)}")

        self.scraper_thread = QThread()
        self.worker = ScraperWorker(domain, max_pages, driver_path, self.output_dir,
                                    site_password, pagespeed_api)
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
        logging.info("on_scraper_finished => displaying messagebox.")
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
        logging.error(f"Scraper error => {error_msg}")
        QMessageBox.critical(self, "Error", f"An error occurred: {error_msg}")
        self.status_label.setText("Error. Check logs or try again.")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)

    @pyqtSlot()
    def cleanup_after_scraping(self):
        logging.info("cleanup_after_scraping => re-enable start_button.")
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
    # Don't configure logging globally yet; we do it inside start_scraping
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
