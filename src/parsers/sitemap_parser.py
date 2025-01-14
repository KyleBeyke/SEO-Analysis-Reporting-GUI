import os
import re
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from urllib.parse import urljoin
from utils.logger import get_logger

logger = get_logger("SitemapParser")

class SitemapParser:
    """
    Handles sitemap parsing, including fetching and processing nested sitemaps,
    and applying multithreading or multiprocessing for large files.
    """

    def __init__(self, base_url, max_urls=1000, max_threads=4):
        self.base_url = base_url.rstrip("/")
        self.max_urls = max_urls
        self.max_threads = max_threads
        self.visited_urls = set()
        self.collected_urls = []

    def fetch_sitemap(self, url):
        """Fetch the sitemap content from the given URL."""
        try:
            logger.info(f"Fetching sitemap: {url}")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch sitemap at {url}: {e}")
            return None

    def parse_sitemap(self, content):
        """Parse sitemap XML content to extract URLs and nested sitemaps."""
        try:
            root = ET.fromstring(content)
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

            if root.tag.endswith("sitemapindex"):
                return [elem.find(f"{ns}loc").text.strip() for elem in root.findall(f"{ns}sitemap") if elem.find(f"{ns}loc")]
            elif root.tag.endswith("urlset"):
                return [elem.find(f"{ns}loc").text.strip() for elem in root.findall(f"{ns}url") if elem.find(f"{ns}loc")]
            else:
                logger.warning("Unrecognized sitemap format.")
                return []
        except ET.ParseError as e:
            logger.warning(f"Failed to parse sitemap XML: {e}")
            return []

    def process_sitemaps(self, urls):
        """Process multiple sitemaps concurrently using threading."""
        nested_sitemaps = []

        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {executor.submit(self.fetch_and_parse_sitemap, url): url for url in urls}
            for future in as_completed(futures):
                nested_sitemaps.extend(future.result() or [])

        return nested_sitemaps

    def fetch_and_parse_sitemap(self, url):
        """Fetch and parse a single sitemap."""
        content = self.fetch_sitemap(url)
        if content:
            return self.parse_sitemap(content)
        return []

    def process_large_sitemap(self, urls):
        """Process large sets of URLs using multiprocessing."""
        def chunkify(data, size):
            for i in range(0, len(data), size):
                yield data[i:i + size]

        chunks = list(chunkify(urls, len(urls) // self.max_threads + 1))
        results = []

        with ProcessPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {executor.submit(self.filter_urls, chunk): chunk for chunk in chunks}
            for future in as_completed(futures):
                results.extend(future.result())

        return results

    def filter_urls(self, urls):
        """Filter URLs based on extensions and SEO logic."""
        valid_urls = []
        ignored_extensions = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz")
        for url in urls:
            parsed_url = urljoin(self.base_url, url)
            if not any(parsed_url.lower().endswith(ext) for ext in ignored_extensions):
                valid_urls.append(parsed_url)
        return valid_urls

    def collect_urls(self):
        """Collect URLs by fetching and parsing the root sitemap."""
        root_sitemap_url = f"{self.base_url}/sitemap.xml"
        logger.info(f"Starting sitemap collection from {root_sitemap_url}")

        root_content = self.fetch_sitemap(root_sitemap_url)
        if not root_content:
            logger.error("Failed to fetch root sitemap. Aborting collection.")
            return []

        initial_urls = self.parse_sitemap(root_content)
        nested_sitemaps = self.process_sitemaps(initial_urls)
        all_urls = self.process_large_sitemap(nested_sitemaps)

        # Apply final filtering and deduplication
        self.collected_urls = list(set(all_urls) - self.visited_urls)
        return self.collected_urls

# Example usage
if __name__ == "__main__":
    parser = SitemapParser("https://example.com", max_urls=500, max_threads=4)
    urls = parser.collect_urls()
    print(f"Collected {len(urls)} URLs:")
    for url in urls:
        print(url)
