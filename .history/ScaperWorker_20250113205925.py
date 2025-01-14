import logging
import requests
import time
import queue
from urllib.parse import urlparse
from collections import Counter
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QThread
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree as ET


class ScraperWorker(QObject):
    """Worker for scraping URLs, analyzing content, and generating reports."""
    finished = pyqtSignal(str, str)  # Emitted when scraping is complete
    error = pyqtSignal(str)  # Emitted when an error occurs
    statusUpdate = pyqtSignal(str)  # Emits status updates
    progressUpdate = pyqtSignal(int, int)  # Emits progress updates (current, total)

    def __init__(self, base_url, max_pages, page_analyzer, output_dir, sitemap_enabled=True):
        super().__init__()
        self.base_url = base_url
        self.max_pages = max_pages
        self.page_analyzer = page_analyzer
        self.output_dir = output_dir
        self.sitemap_enabled = sitemap_enabled
        self.visited_urls = set()
        self.collected_data = []
        self.url_queue = queue.Queue()

    @pyqtSlot()
    def run(self):
        """Main execution method."""
        try:
            self.statusUpdate.emit("Starting scraper...")
            self.visited_urls.clear()
            self.collected_data.clear()

            # Step 1: Collect URLs
            urls = self.collect_urls()
            if not urls:
                raise Exception("No URLs to process.")

            self.statusUpdate.emit(f"Collected {len(urls)} URLs. Starting analysis.")
            self.progressUpdate.emit(0, len(urls))

            # Step 2: Analyze pages
            self.analyze_pages(urls)

            # Step 3: Generate reports
            self.generate_reports()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit("", "")  # No files generated in this example

    def collect_urls(self):
        """Collects URLs using sitemaps and BFS fallback."""
        urls = set()
        try:
            if self.sitemap_enabled:
                self.statusUpdate.emit("Fetching URLs from sitemap...")
                urls = self.fetch_sitemap_urls()
            if not urls:
                self.statusUpdate.emit("Sitemap failed. Falling back to BFS...")
                urls = self.bfs_url_collection()
        except Exception as e:
            logging.error(f"Error during URL collection: {e}")
            self.statusUpdate.emit("Error during URL collection. Check logs.")
        return list(urls)[:self.max_pages]

    def fetch_sitemap_urls(self):
        """Fetches URLs from the sitemap."""
        sitemap_url = f"{self.base_url.rstrip('/')}/sitemap.xml"
        urls = set()
        try:
            response = requests.get(sitemap_url, timeout=10)
            response.raise_for_status()
            urls = self.parse_sitemap(response.text)
        except Exception as e:
            logging.error(f"Error fetching sitemap: {e}")
        return urls

    def parse_sitemap(self, xml_text):
        """Parses sitemap XML and returns URLs."""
        urls = set()
        try:
            root = ET.fromstring(xml_text)
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            for url_tag in root.findall(f"{ns}url"):
                loc_tag = url_tag.find(f"{ns}loc")
                if loc_tag is not None and loc_tag.text:
                    urls.add(loc_tag.text.strip())
        except Exception as e:
            logging.error(f"Error parsing sitemap: {e}")
        return urls

    def bfs_url_collection(self):
        """Performs BFS to collect URLs."""
        from selenium.webdriver.common.by import By

        def scroll_and_collect(driver):
            """Scrolls the page and collects links."""
            for _ in range(2):  # Adjust scroll depth as needed
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
            return [a.get_attribute("href") for a in driver.find_elements(By.TAG_NAME, "a")]

        driver = self.page_analyzer.configure_driver()
        try:
            driver.get(self.base_url)
            for link in scroll_and_collect(driver):
                if link and self.is_valid_url(link):
                    self.url_queue.put(link)
        except Exception as e:
            logging.error(f"BFS URL collection error: {e}")
        finally:
            driver.quit()
        return list(self.url_queue.queue)

    def is_valid_url(self, url):
        """Validates URLs for inclusion in scraping."""
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and parsed.netloc

    def analyze_pages(self, urls):
        """Analyzes pages using multithreading."""
        def worker(url):
            """Worker function for analyzing a single page."""
            try:
                result = self.page_analyzer.analyze_page(url)
                self.collected_data.append(result)
                self.progressUpdate.emit(len(self.collected_data), len(urls))
            except Exception as e:
                logging.error(f"Error analyzing {url}: {e}")

        with ThreadPoolExecutor(max_workers=max(1, min(8, len(urls)))) as executor:
            executor.map(worker, urls)

    def generate_reports(self):
        """Generates CSV and HTML reports."""
        from pandas import DataFrame
        from datetime import datetime
        import os

        if not self.collected_data:
            raise Exception("No data to generate reports.")

        df = DataFrame(self.collected_data)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        base_name = f"seo_report_{timestamp}"
        csv_path = os.path.join(self.output_dir, f"{base_name}.csv")
        html_path = os.path.join(self.output_dir, f"{base_name}.html")

        try:
            df.to_csv(csv_path, index=False)
            df.to_html(html_path, index=False)
            self.statusUpdate.emit(f"Reports saved: {csv_path}, {html_path}")
        except Exception as e:
            logging.error(f"Error saving reports: {e}")
            self.error.emit("Failed to save reports.")
