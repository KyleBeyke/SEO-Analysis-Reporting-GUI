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

# NLTK for advanced tokenization & lemmatization
import nltk
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt")

try:
    nltk.data.find("corpora/wordnet")
except LookupError:
    nltk.download("wordnet")

from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer

# PyQt5
from PyQt5.QtCore import (
    Qt, QObject, pyqtSignal, pyqtSlot, QThread
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit,
    QVBoxLayout, QPushButton, QWidget, QSpinBox,
    QMessageBox, QFileDialog, QProgressBar, QCheckBox, QHBoxLayout
)

# Selenium
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
# STOP WORDS (CASE-INSENSITIVE, EXCEPT FOR "I")
###############################################################################
print("[LOG] Initializing stop words...")

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
EXTRA_STOP_WORDS = {
    "another", "also", "be", "is", "was", "were", "do", "does", "did",
}
STOP_WORDS = BASE_STOP_WORDS.union(EXTRA_STOP_WORDS)
if "i" in STOP_WORDS:
    STOP_WORDS.remove("i")

IGNORED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
    ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz"
)
MAX_LIMIT = 999

###############################################################################
# PAGE SPEED INSIGHTS
###############################################################################
def check_page_speed_insights(url, api_key=None, strategy="mobile"):
    if not api_key:
        print(f"[LOG] No API key, skipping PageSpeed for {url}, strategy={strategy}")
        return {"performance_score": None, "error": "No API key"}

    endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {"url": url, "key": api_key, "strategy": strategy}
    print(f"[LOG] PageSpeed call for {url}, strategy={strategy}")
    try:
        r = requests.get(endpoint, params=params, timeout=15)
        if r.status_code != 200:
            print(f"[LOG] PageSpeed error {r.status_code} for {url}, strategy={strategy}")
            return {
                "performance_score": None,
                "error": f"HTTP {r.status_code}"
            }
        data = r.json()
        perf = None
        try:
            perf_raw = data["lighthouseResult"]["categories"]["performance"]["score"]
            perf = int(perf_raw * 100)
        except:
            print(f"[LOG] Could not parse performance score from PageSpeed for {url}, strategy={strategy}")
        return {
            "performance_score": perf,
            "error": None
        }
    except Exception as e:
        print(f"[LOG] Exception calling PageSpeed for {url}, strategy={strategy}: {e}")
        return {"performance_score": None, "error": str(e)}

###############################################################################
# HELPER
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
# PASSWORD PROTECTED
###############################################################################
def attempt_password_login_if_needed(driver, base_url, site_password):
    print(f"[LOG] attempt_password_login_if_needed called for {base_url}")
    if not site_password:
        print("[LOG] No password provided, skipping login flow.")
        return

    try:
        driver.get(base_url)
        time.sleep(2)
        print("[LOG] Loaded base URL, checking for password form...")

        # We'll do up to 2 attempts
        for attempt_number in range(2):
            print(f"[LOG] Attempt #{attempt_number+1} to find password form.")
            forms = driver.find_elements(By.CSS_SELECTOR, "form[action*='password-protected=login']")
            pass_input = None
            if forms:
                print(f"[LOG] Found {len(forms)} form(s) with action*='password-protected=login'.")
                try:
                    pass_input = forms[0].find_element(By.NAME, "password_protected_pwd")
                    print("[LOG] Found input name='password_protected_pwd' inside form.")
                except:
                    print("[LOG] Could not find 'password_protected_pwd' inside the form.")
            else:
                print("[LOG] No form found with 'password-protected=login', trying fallback.")
                try:
                    pass_input = driver.find_element(By.NAME, "password_protected_pwd")
                    print("[LOG] Found input name='password_protected_pwd' outside of form.")
                except:
                    print("[LOG] Could not find input name='password_protected_pwd' fallback either.")

            if pass_input:
                print("[LOG] Filling password.")
                pass_input.clear()
                pass_input.send_keys(site_password)
                time.sleep(1)
                print("[LOG] Trying to find name='wp-submit' button.")
                try:
                    submit_btn = driver.find_element(By.NAME, "wp-submit")
                    print("[LOG] Found wp-submit button, clicking.")
                    submit_btn.click()
                except:
                    print("[LOG] Could not find wp-submit, pressing ENTER.")
                    pass_input.send_keys(Keys.RETURN)

                time.sleep(2)
                # forcibly re-get
                print("[LOG] Re-getting base_url to ensure login is recognized.")
                driver.get(base_url)
                time.sleep(2)
            else:
                print("[LOG] No password input found in this attempt, skipping further login.")
                break
    except Exception as e:
        print(f"[LOG] Exception in password login logic: {e}")

###############################################################################
# SITEMAP
###############################################################################
def parse_sitemap_xml(xml_text):
    print("[LOG] Parsing sitemap XML.")
    root = ET.fromstring(xml_text)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    tag_name = root.tag.lower()
    sub_sitemaps = []
    links = []

    if "sitemapindex" in tag_name:
        print("[LOG] Detected sitemapindex.")
        for sitemap_tag in root.findall(f"{ns}sitemap"):
            loc_tag = sitemap_tag.find(f"{ns}loc")
            if loc_tag is not None and loc_tag.text:
                sub_sitemaps.append(loc_tag.text.strip())
    elif "urlset" in tag_name:
        print("[LOG] Detected urlset.")
        for url_tag in root.findall(f"{ns}url"):
            loc_tag = url_tag.find(f"{ns}loc")
            if loc_tag is not None and loc_tag.text:
                links.append(loc_tag.text.strip())
    return sub_sitemaps, links

def gather_links_from_sitemap(base_url, max_pages, status_callback=None, site_password=""):
    if site_password:
        print("[LOG] gather_links_from_sitemap calling password login if needed.")
        d = configure_driver()
        attempt_password_login_if_needed(d, base_url, site_password)
        d.quit()

    sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
    if status_callback:
        status_callback(f"Attempting to fetch sitemap: {sitemap_url}")
    print(f"[LOG] Fetching sitemap at {sitemap_url}.")

    resp = requests.get(sitemap_url, timeout=10, allow_redirects=True)
    resp.raise_for_status()

    subs, links = parse_sitemap_xml(resp.text)
    visited = set(links)
    queue_ = list(subs)

    while queue_ and len(visited) < max_pages:
        smap = queue_.pop()
        if status_callback:
            status_callback(f"Fetching sub-sitemap: {smap}")
        print(f"[LOG] Attempting to fetch sub-sitemap: {smap}")
        try:
            r = requests.get(smap, timeout=10, allow_redirects=True)
            r.raise_for_status()
            s2, l2 = parse_sitemap_xml(r.text)
            queue_.extend(s2)
            for lk in l2:
                visited.add(lk)
                if len(visited) >= max_pages:
                    break
        except Exception as e:
            if status_callback:
                status_callback(f"Warning: Failed {smap}: {e}")
            print(f"[LOG] Warning: Failed {smap}: {e}")

    filtered = []
    for lk in visited:
        if not any(lk.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
            filtered.append(lk)
    return filtered[:max_pages]

###############################################################################
# BFS
###############################################################################
def selenium_bfs_concurrent(base_url, max_pages, status_callback=None,
                            driver_path=None, site_password=""):
    if site_password:
        print("[LOG] BFS calling password login if needed.")
        d = configure_driver(driver_path)
        attempt_password_login_if_needed(d, base_url, site_password)
        d.quit()

    if status_callback:
        status_callback("Sitemap not found or empty. BFS with advanced concurrency...")
    print("[LOG] Starting BFS concurrency...")

    visited = set()
    q = queue.Queue()
    base_netloc = normalize_netloc(urlparse(base_url).netloc)
    q.put(base_url)

    cores = multiprocessing.cpu_count()
    n_workers = max(int(0.75 * cores), 1)
    print(f"[LOG] BFS concurrency with {n_workers} workers (75% of {cores} cores).")

    def bfs_worker(drv):
        while True:
            try:
                url_ = q.get(timeout=3)
            except queue.Empty:
                return
            if url_ in visited:
                q.task_done()
                continue
            visited.add(url_)
            idx = len(visited)
            if status_callback:
                status_callback(f"[BFS] Visiting {url_} ({idx}/{max_pages})")
            print(f"[LOG] BFS Worker visiting {url_}")

            try:
                drv.get(url_)
                a_tags = drv.find_elements(By.TAG_NAME, "a")
                for a_ in a_tags:
                    href = a_.get_attribute("href") or ""
                    if not href:
                        continue
                    if any(href.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
                        continue
                    link_netloc = normalize_netloc(urlparse(href).netloc)
                    if link_netloc == base_netloc:
                        if len(visited) + q.qsize() < max_pages:
                            if href not in visited:
                                q.put(href)
            except Exception as e:
                print(f"[LOG] BFS Worker exception visiting {url_}: {e}")
            finally:
                q.task_done()

    drivers = [configure_driver(driver_path) for _ in range(n_workers)]
    threads = []
    for d_ in drivers:
        t = threading.Thread(target=bfs_worker, args=(d_,), daemon=True)
        threads.append(t)
        t.start()

    q.join()
    print("[LOG] BFS concurrency finished, cleaning up drivers.")
    for d_ in drivers:
        try:
            d_.quit()
        except:
            pass
    return list(visited)[:max_pages]

###############################################################################
# ADVANCED KEYWORD EXTRACTION
###############################################################################
print("[LOG] Setting up NLTK lemmatizer.")
lemmatizer = WordNetLemmatizer()

def advanced_keyword_extraction(text):
    tokens = word_tokenize(text)
    final_tokens = []
    for tok in tokens:
        if tok == "I":
            final_tokens.append("I")
            continue
        lower_tok = tok.lower()
        if re.match(r"^[a-z]+$", lower_tok):
            lemma = lemmatizer.lemmatize(lower_tok)
            if lemma not in STOP_WORDS:
                final_tokens.append(lemma)
    return Counter(final_tokens)

###############################################################################
# SCORING
###############################################################################
def compute_score_and_recommendations(data):
    from urllib.parse import urlparse
    score = 0.0
    recs = []

    tl = data.get("TitleLength", 0)
    if 50 <= tl <= 60:
        score += 10
    else:
        recs.append("Adjust Title length to ~50-60 chars.")

    mdl = data.get("MetaDescriptionLength", 0)
    if 120 <= mdl <= 160:
        score += 10
    else:
        recs.append("Adjust Meta Description to ~120-160 chars.")

    h1_count = data.get("H1Count", 0)
    if h1_count > 0:
        score += 10
    else:
        recs.append("Include at least 1 H1 tag.")

    h2_count = data.get("H2Count", 0)
    if h2_count >= 1:
        score += 5
    else:
        recs.append("Add H2 tags for subtopics.")

    wc = data.get("WordCount", 0)
    if wc >= 300:
        score += 10
    else:
        recs.append("Add more textual content (300+ words).")

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

    noindex = data.get("Noindex", False)
    if not noindex:
        score += 10
    else:
        recs.append("Remove 'noindex' unless intentionally blocking search engines.")

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
    print(f"[LOG] Analyzing page: {url}, index={current_idx}, total={total_count}")
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
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        # Title
        title_tag = soup.find("title")
        title_text = title_tag.get_text().strip() if title_tag else ""
        data["Title"] = title_text
        data["TitleLength"] = len(title_text)

        # meta desc length
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = meta_desc_tag.get("content").strip() if (meta_desc_tag and meta_desc_tag.get("content")) else ""
        data["MetaDescriptionLength"] = len(meta_desc)

        # h1, h2
        h1_tags = soup.find_all("h1")
        h2_tags = soup.find_all("h2")
        data["H1Count"] = len(h1_tags)
        data["H2Count"] = len(h2_tags)

        # canonical
        canonical_tag = soup.find("link", rel="canonical")
        canonical_href = canonical_tag.get("href").strip() if (canonical_tag and canonical_tag.get("href")) else ""
        data["Canonical"] = canonical_href

        # noindex
        robots_meta = soup.find("meta", attrs={"name": re.compile(r"robots", re.I)})
        robots_content = robots_meta.get("content").lower() if (robots_meta and robots_meta.get("content")) else ""
        data["Noindex"] = ("noindex" in robots_content)

        # images
        images = soup.find_all("img")
        data["ImageCount"] = len(images)
        alt_missing = sum(1 for i_ in images if not i_.get("alt"))
        data["ImagesWithoutAlt"] = alt_missing

        # structured
        ld_json = soup.find_all("script", attrs={"type": "application/ld+json"})
        data["StructuredDataCount"] = len(ld_json)
        microdata = soup.find_all(attrs={"itemtype": True})
        data["MicrodataCount"] = len(microdata)

        # keywords
        text_content = soup.get_text(separator=" ", strip=True)
        word_counts = advanced_keyword_extraction(text_content)
        data["WordCount"] = sum(word_counts.values())
        sitewide_word_counts.update(word_counts)
        top_5 = word_counts.most_common(5)
        data["Keywords"] = ", ".join(f"{k}({v})" for (k, v) in top_5)

        # PageSpeed: mobile + desktop
        if api_key:
            print(f"[LOG] Doing PageSpeed mobile for {url}")
            ps_mobile = check_page_speed_insights(url, api_key=api_key, strategy="mobile")
            data["PerformanceScoreMobile"] = ps_mobile["performance_score"]

            print(f"[LOG] Doing PageSpeed desktop for {url}")
            ps_desktop = check_page_speed_insights(url, api_key=api_key, strategy="desktop")
            data["PerformanceScoreDesktop"] = ps_desktop["performance_score"]

        # final score
        final_score, recs = compute_score_and_recommendations(data)
        data["Score"] = final_score
        data["Recommendations"] = recs

    except Exception as e:
        data["Error"] = str(e)
        print(f"[LOG] Exception analyzing page {url}: {e}")

    return data

###############################################################################
# ANALYZE PAGES
###############################################################################
def analyze_pages_in_pool(urls, driver_path, status_callback, progress_callback,
                          sitewide_word_counts, api_key=None):
    cores = multiprocessing.cpu_count()
    n_workers = max(int(0.75 * cores), 1)
    print(f"[LOG] analyze_pages_in_pool with {n_workers} workers from {cores} cores.")

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
        print("[LOG] No URLs to analyze, returning empty.")
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
                print(f"[LOG] analyze_pages_in_pool thread error: {e}")

    print("[LOG] Analyzing done, cleaning up drivers.")
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
            print(f"[LOG] Worker started for base_url={base_url}")

            # 1) Attempt sitemap
            links = []
            try:
                links = gather_links_from_sitemap(
                    base_url,
                    self.max_pages,
                    status_callback=self.statusUpdate.emit,
                    site_password=self.site_password
                )
            except Exception as e:
                msg = f"Sitemap attempt failed: {e}"
                print(f"[LOG] {msg}")
                self.statusUpdate.emit(msg)

            if not links:
                print("[LOG] No links from sitemap, fallback BFS.")
                links = selenium_bfs_concurrent(
                    base_url,
                    self.max_pages,
                    status_callback=self.statusUpdate.emit,
                    driver_path=self.driver_path,
                    site_password=self.site_password
                )

            unique_links = list(dict.fromkeys(links))
            if len(unique_links) > self.max_pages:
                unique_links = unique_links[:self.max_pages]

            msg_collect = f"Collected {len(unique_links)} URLs. Starting analysis..."
            print(f"[LOG] {msg_collect}")
            self.statusUpdate.emit(msg_collect)

            self.current_count = 0
            self.total_count = len(unique_links)

            def increment_analysis(x=1):
                self.current_count += x
                self.analysisProgress.emit(self.current_count, self.total_count)

            print("[LOG] analyze_pages_in_pool starting.")
            results = analyze_pages_in_pool(
                urls=unique_links,
                driver_path=self.driver_path,
                status_callback=self.statusUpdate.emit,
                progress_callback=increment_analysis,
                sitewide_word_counts=self.sitewide_word_counts,
                api_key=self.api_key
            )

            self.statusUpdate.emit("Generating final keywords row...")

            # final row
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

            print(f"[LOG] Saving CSV => {csv_file}")
            print(f"[LOG] Saving HTML => {html_file}")
            df = pd.DataFrame(results)
            df.to_csv(csv_file, index=False)
            df.to_html(html_file, index=False)

            self.finished.emit(csv_file, html_file)
        except Exception as e:
            print(f"[LOG] Exception in Worker run: {e}")
            self.error.emit(str(e))

###############################################################################
# MAIN WINDOW
###############################################################################
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BeykeTechnik SEO Analyzer")
        self.resize(500, 500)

        self.domain_label = QLabel("Domain / URL:")
        self.domain_input = QLineEdit("example.com")

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

        self.pagespeed_label = QLabel("PageSpeed API Key:")
        self.pagespeed_input = QLineEdit("AIzaSyB8R9HLyxA6cvv2PLzhh4fWXxlXlSopnpg")
        self.pagespeed_input.setEchoMode(QLineEdit.Password)
        self.pagespeed_show_btn = QPushButton("Show")
        self.pagespeed_show_btn.setCheckable(True)
        self.pagespeed_show_btn.clicked.connect(self.toggle_pagespeed_visibility)

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
        print("[LOG] Starting scraping logic from GUI.")
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

        print(f"[LOG] Domain={domain}, MaxPages={max_pages}, DriverPath={driver_path}, PasswordLen={len(site_password)}, PageSpeedKeyLen={len(pagespeed_api)}")

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
        print("[LOG] on_scraper_finished called.")
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
        print(f"[LOG] on_scraper_error: {error_msg}")
        QMessageBox.critical(self, "Error", f"An error occurred: {error_msg}")
        self.status_label.setText("Error. Check logs or try again.")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)

    @pyqtSlot()
    def cleanup_after_scraping(self):
        print("[LOG] cleanup_after_scraping called.")
        self.scraper_thread = None
        self.worker = None
        self.start_button.setEnabled(True)

    @pyqtSlot(str)
    def on_status_update(self, message):
        print(f"[LOG] statusUpdate: {message}")
        self.status_label.setText(message)

###############################################################################
# MAIN
###############################################################################
if __name__ == "__main__":
    print("[LOG] BeykeTechnik SEO Analyzer starting.")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
