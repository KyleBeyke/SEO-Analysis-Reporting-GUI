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

# NLTK for tokenization & PorterStemmer (NO WordNet usage)
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
# Optional auto-install
from webdriver_manager.chrome import ChromeDriverManager

import requests
import xml.etree.ElementTree as ET
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

###############################################################################
# CONFIG & CONSTANTS
###############################################################################
IGNORED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
                      ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz")

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

# Additional single-letter tokens to exclude
ADDITIONAL_SINGLE_LETTER_STOP_WORDS = {"s", "t", "u", "v", "w", "x", "y", "z"}

BASE_STOP_WORDS = set(w.strip().lower() for w in RAW_STOP_WORDS.split() if w.strip())
EXTRA_STOP_WORDS = {"another", "also", "be", "is", "was", "were", "do", "does", "did"}.union(ADDITIONAL_SINGLE_LETTER_STOP_WORDS)
STOP_WORDS = BASE_STOP_WORDS.union(EXTRA_STOP_WORDS)
if "i" in STOP_WORDS:
    STOP_WORDS.remove("i")

stemmer = PorterStemmer()

###############################################################################
# PAGE SPEED INSIGHTS
###############################################################################
def check_page_speed_insights(url, api_key=None, strategy="mobile"):
    """Query Google PageSpeed Insights API for the given URL & strategy."""
    if not api_key:
        logging.info(f"No PageSpeed API key -> skipping for {url} ({strategy}).")
        return {"performance_score": None, "error": "No API key"}

    endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {"url": url, "key": api_key, "strategy": strategy}
    logging.info(f"PageSpeed => {url}, strategy={strategy}")
    try:
        r = requests.get(endpoint, params=params, timeout=15)
        if r.status_code != 200:
            logging.warning(f"PageSpeed error {r.status_code} for {url} ({strategy})")
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
            logging.warning(f"Could not parse performance for {url} ({strategy})")
        return {
            "performance_score": perf,
            "error": None
        }
    except Exception as e:
        logging.error(f"Exception calling PageSpeed for {url}, {strategy}: {e}")
        return {"performance_score": None, "error": str(e)}

###############################################################################
# ADVANCED KEYWORD EXTRACTION (NO WORDNET)
###############################################################################
def advanced_keyword_extraction(text):
    """Tokenize text and use PorterStemmer for morphological processing."""
    # Remove possessive apostrophes and other contractions to prevent standalone single-letter tokens
    text = re.sub(r"'s\b", "", text)  # Remove possessive 's
    text = re.sub(r"n't\b", " not", text)  # Expand contractions like "don't" to "do not"
    text = re.sub(r"'re\b", " are", text)
    text = re.sub(r"'ve\b", " have", text)
    text = re.sub(r"'ll\b", " will", text)
    text = re.sub(r"'d\b", " would", text)
    text = re.sub(r"'m\b", " am", text)

    # Remove remaining punctuation except apostrophes (if any)
    text = re.sub(r"[^\w\s']", " ", text)

    tokens = word_tokenize(text)
    final_tokens = []
    filtered_single_letters = 0
    total_tokens = 0
    for tok in tokens:
        total_tokens += 1
        if tok == "I":
            final_tokens.append("I")
            continue
        lower_tok = tok.lower()
        if re.match(r"^[a-z]+$", lower_tok):
            # Simple Porter stemming
            stem = stemmer.stem(lower_tok)
            # Exclude single-letter stems (except 'i') and check STOP_WORDS
            if (len(stem) > 1 or stem == 'i') and stem not in STOP_WORDS:
                final_tokens.append(stem)
            elif len(stem) == 1 and stem not in {"i"}:
                filtered_single_letters += 1
    logging.debug(f"Total tokens: {total_tokens}, Tokens after filtering: {len(final_tokens)}, Single-letter tokens filtered: {filtered_single_letters}")
    return Counter(final_tokens)

###############################################################################
# SCORING
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