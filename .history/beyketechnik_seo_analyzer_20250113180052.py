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
