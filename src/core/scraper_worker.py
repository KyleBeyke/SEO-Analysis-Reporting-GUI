import os
import re
import time
import requests
import logging
from queue import Queue
from threading import Thread
from urllib.parse import urlparse
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from xml.etree.ElementTree import fromstring, ParseError
from collections import Counter
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed


class ScraperWorker:
    """Performs sitemap parsing, BFS crawling, and concurrent page analysis."""

    def __init__(self, base_url, max_pages=100, stop_words=None, driver_path=None, api_key=None):
        self.base_url = base_url.rstrip("/")
        self.max_pages = max_pages
        self.stop_words = stop_words or set()
        self.driver_path = driver_path or ChromeDriverManager().install()
        self.api_key = api_key
        self.visited_links = set()
        self.queue = Queue()
        self.word_counts = Counter()
        self.results = []

    def start(self):
        """Starts the scraping process."""
        logging.info(f"Starting scraping process for {self.base_url}")

        # Step 1: Gather links via sitemap
        links = self.gather_links_from_sitemap()
        if not links:
            logging.warning("No sitemap found, falling back to BFS crawling.")
            links = self.bfs_crawl()

        # Step 2: Filter links
        filtered_links = self.filter_links(links)
        logging.info(f"Collected {len(filtered_links)} valid links.")

        # Step 3: Analyze pages concurrently
        self.analyze_pages_concurrently(filtered_links)

    def gather_links_from_sitemap(self):
        """Attempts to gather links from a sitemap."""
        sitemaps = [f"{self.base_url}/sitemap.xml", f"{self.base_url}/sitemap_index.xml"]
        links = set()

        for sitemap in sitemaps:
            logging.info(f"Fetching sitemap: {sitemap}")
            try:
                response = requests.get(sitemap, timeout=10)
                response.raise_for_status()
                links.update(self.parse_sitemap(response.text))
            except (requests.RequestException, ParseError) as e:
                logging.warning(f"Failed to fetch or parse {sitemap}: {e}")

        return links

    @staticmethod
    def parse_sitemap(xml_content):
        """Parses sitemap XML content to extract links."""
        try:
            root = fromstring(xml_content)
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            links = {url.text.strip() for url in root.findall(f"{ns}url/{ns}loc")}
            return links
        except ParseError:
            return set()

    def bfs_crawl(self, max_depth=2):
        """Performs BFS crawling to gather links."""
        logging.info("Starting BFS crawling.")
        self.queue.put((self.base_url, 0))

        links = set()

        while not self.queue.empty() and len(links) < self.max_pages:
            current_url, depth = self.queue.get()

            if depth > max_depth or current_url in self.visited_links:
                continue

            self.visited_links.add(current_url)
            links.add(current_url)

            logging.info(f"Crawling: {current_url} (Depth: {depth})")
            try:
                driver = self.configure_driver()
                driver.get(current_url)
                soup = BeautifulSoup(driver.page_source, "html.parser")
                driver.quit()

                for anchor in soup.find_all("a", href=True):
                    href = anchor["href"]
                    full_url = self.normalize_url(href)
                    if full_url and self.is_internal_link(full_url):
                        self.queue.put((full_url, depth + 1))
            except Exception as e:
                logging.warning(f"Error during BFS crawl of {current_url}: {e}")

        return links

    def analyze_pages_concurrently(self, links):
        """Analyzes pages using multithreading."""
        logging.info("Starting page analysis with multithreading.")
        num_workers = max(1, int(0.75 * os.cpu_count()))

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            future_to_url = {executor.submit(self.analyze_page, url): url for url in links}

            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result = future.result()
                    self.results.append(result)
                    logging.info(f"Completed analysis for {url}")
                except Exception as e:
                    logging.warning(f"Error analyzing {url}: {e}")

    def analyze_page(self, url):
        """Analyzes a single page."""
        analyzer = PageAnalyzer(self.stop_words)
        return analyzer.analyze_page(url)

    def configure_driver(self):
        """Configures and returns a Selenium driver."""
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        return webdriver.Chrome(service=Service(self.driver_path), options=options)

    def filter_links(self, links):
        """Filters links based on SEO-friendly logic."""
        def is_valid_link(link):
            parsed = urlparse(link)
            if not parsed.scheme.startswith("http"):
                return False
            if any(link.lower().endswith(ext) for ext in (".jpg", ".png", ".pdf", ".zip")):
                return False
            return True

        return {link for link in links if is_valid_link(link)}

    @staticmethod
    def normalize_url(href):
        """Normalizes relative URLs to absolute ones."""
        try:
            return requests.compat.urljoin(self.base_url, href)
        except Exception:
            return None

    @staticmethod
    def is_internal_link(link, base_netloc=None):
        """Checks if a link is internal to the base domain."""
        base_netloc = base_netloc or urlparse(link).netloc
        return urlparse(link).netloc == base_netloc
