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
# FUNCTIONS FOR ROBOTS.TXT HANDLING
###############################################################################
def fetch_robots_txt(base_url):
    """Fetch the robots.txt file for a domain."""
    try:
        robots_url = urljoin(base_url, "/robots.txt")
        response = requests.get(robots_url, timeout=10)
        if response.status_code == 200:
            return response.text
        logging.warning(f"robots.txt not found for {base_url}")
    except Exception as e:
        logging.error(f"Error fetching robots.txt: {e}")
    return ""

def parse_robots_txt(robots_txt):
    """Parse the robots.txt content and extract disallowed paths."""
    disallowed_paths = set()
    for line in robots_txt.splitlines():
        line = line.strip()
        if line.lower().startswith("disallow:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                path = parts[1].strip()
                if path:
                    disallowed_paths.add(path)
    return disallowed_paths

def is_path_allowed(url, disallowed_paths):
    """Check if a URL path is allowed based on robots.txt disallowed paths."""
    parsed_url = urlparse(url)
    for disallowed in disallowed_paths:
        if parsed_url.path.startswith(disallowed):
            return False
    return True

###############################################################################
# FUNCTIONS FOR LINK FILTERING
###############################################################################
def filter_links(links, base_url, disallowed_paths):
    """Filter links based on robots.txt rules and ignored extensions."""
    filtered_links = []
    for link in links:
        if not any(link.lower().endswith(ext) for ext in IGNORED_EXTENSIONS):
            if is_path_allowed(link, disallowed_paths):
                filtered_links.append(link)
    return filtered_links

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
# ADVANCED KEYWORD EXTRACTION
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
    for tok in tokens:
        lower_tok = tok.lower()
        if re.match(r"^[a-z]+$", lower_tok):
            # Simple Porter stemming
            stem = stemmer.stem(lower_tok)
            if stem not in STOP_WORDS:
                final_tokens.append(stem)
    return Counter(final_tokens)
