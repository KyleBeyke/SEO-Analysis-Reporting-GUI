import re
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
import time
import logging

class SitemapParser:
    """Handles sitemap fetching and parsing, including robots.txt support."""
    def __init__(self, base_url, max_pages=100, ignored_extensions=None, stop_words=None):
        self.base_url = base_url.rstrip("/")
        self.max_pages = max_pages
        self.ignored_extensions = ignored_extensions or (
            ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".pdf",
            ".zip", ".exe", ".rar", ".gz", ".tgz", ".mp4", ".avi"
        )
        self.stop_words = stop_words or {"terms", "privacy", "login", "signup"}
        self.visited = set()
        self.to_visit = []
        self.disallowed_paths = self.parse_robots_txt()

    def parse_robots_txt(self):
        """Parse robots.txt and return disallowed paths."""
        robots_url = urljoin(self.base_url, "/robots.txt")
        disallowed_paths = set()
        try:
            response = requests.get(robots_url, timeout=10)
            response.raise_for_status()
            lines = response.text.splitlines()
            for line in lines:
                if line.lower().startswith("disallow:"):
                    path = line.split(":", 1)[1].strip()
                    if path:
                        disallowed_paths.add(urljoin(self.base_url, path))
            logging.info(f"Robots.txt parsed: {len(disallowed_paths)} disallowed paths.")
        except Exception as e:
            logging.warning(f"Failed to fetch robots.txt: {e}")
        return disallowed_paths

    def fetch_sitemap(self, sitemap_url):
        """Fetch a sitemap and return its content."""
        retries = 3
        backoff = 2
        for attempt in range(retries):
            try:
                response = requests.get(sitemap_url, timeout=10)
                response.raise_for_status()
                return response.text
            except Exception as e:
                logging.warning(f"Retry {attempt + 1} for {sitemap_url}: {e}")
                time.sleep(backoff ** attempt)
        logging.error(f"Failed to fetch sitemap after {retries} retries: {sitemap_url}")
        return None

    def parse_sitemap_xml(self, xml_text):
        """Parse the sitemap XML content."""
        links = []
        sub_sitemaps = []
        try:
            root = ET.fromstring(xml_text)
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            if root.tag.lower().endswith("sitemapindex"):
                for sitemap in root.findall(f"{ns}sitemap"):
                    loc = sitemap.find(f"{ns}loc")
                    if loc is not None and loc.text:
                        sub_sitemaps.append(loc.text.strip())
            elif root.tag.lower().endswith("urlset"):
                for url_tag in root.findall(f"{ns}url"):
                    loc = url_tag.find(f"{ns}loc")
                    if loc is not None and loc.text:
                        links.append(loc.text.strip())
        except ET.ParseError as e:
            logging.warning(f"Error parsing sitemap XML: {e}")
        return sub_sitemaps, links

    def filter_links(self, links):
        """Filter links based on stop words, ignored extensions, and robots.txt."""
        filtered = []
        for link in links:
            parsed_url = urlparse(link)
            if any(link.endswith(ext) for ext in self.ignored_extensions):
                continue
            if any(stop_word in parsed_url.path.lower() for stop_word in self.stop_words):
                continue
            if link in self.disallowed_paths:
                continue
            filtered.append(link)
        return filtered

    def gather_links(self):
        """Fetch and parse sitemaps to gather all links."""
        sitemap_urls = [urljoin(self.base_url, "/sitemap.xml")]
        all_links = set()
        try:
            while sitemap_urls and len(all_links) < self.max_pages:
                sitemap_url = sitemap_urls.pop(0)
                logging.info(f"Fetching sitemap: {sitemap_url}")
                xml_text = self.fetch_sitemap(sitemap_url)
                if not xml_text:
                    continue
                sub_sitemaps, links = self.parse_sitemap_xml(xml_text)
                sitemap_urls.extend(sub_sitemaps)
                filtered_links = self.filter_links(links)
                all_links.update(filtered_links)
                if len(all_links) >= self.max_pages:
                    break
            return list(all_links)[:self.max_pages]
        except Exception as e:
            logging.error(f"Error gathering links: {e}")
            return []

    def gather_links_concurrently(self):
        """Fetch and parse sitemaps using multithreading."""
        sitemap_urls = [urljoin(self.base_url, "/sitemap.xml")]
        all_links = set()
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self.fetch_sitemap, url): url for url in sitemap_urls}
            while futures and len(all_links) < self.max_pages:
                for future in as_completed(futures):
                    sitemap_url = futures.pop(future, None)
                    try:
                        xml_text = future.result()
                        if not xml_text:
                            continue
                        sub_sitemaps, links = self.parse_sitemap_xml(xml_text)
                        sitemap_urls.extend(sub_sitemaps)
                        filtered_links = self.filter_links(links)
                        all_links.update(filtered_links)
                        if len(all_links) >= self.max_pages:
                            break
                    except Exception as e:
                        logging.warning(f"Error processing sitemap: {sitemap_url} => {e}")
        return list(all_links)[:self.max_pages]
