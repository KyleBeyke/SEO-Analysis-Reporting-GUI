import threading
from queue import Queue
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin
import logging

class SitemapParser:
    """Fetch and parse sitemap.xml with multithreading and robots.txt support."""

    IGNORED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
                          ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz")

    def __init__(self, base_url, max_pages):
        self.base_url = base_url.rstrip("/")
        self.max_pages = max_pages
        self.links = set()
        self.queue = Queue()
        self.lock = threading.Lock()
        self.disallowed_paths = self.fetch_robots_txt()

    def fetch_robots_txt(self):
        """Fetch and parse disallowed paths from robots.txt."""
        robots_url = urljoin(self.base_url, "/robots.txt")
        disallowed_paths = set()
        try:
            response = requests.get(robots_url, timeout=10)
            response.raise_for_status()
            for line in response.text.splitlines():
                if line.strip().lower().startswith("disallow:"):
                    path = line.split(":", 1)[1].strip()
                    disallowed_paths.add(path)
        except Exception as e:
            logging.warning(f"Error fetching robots.txt: {e}")
        return disallowed_paths

    def is_allowed(self, url):
        """Check if a URL is allowed based on robots.txt rules."""
        parsed = urlparse(url)
        for disallowed in self.disallowed_paths:
            if parsed.path.startswith(disallowed):
                return False
        return True

    def parse_sitemap_xml(self, xml_text):
        root = ET.fromstring(xml_text)
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        sub_sitemaps = []
        links = []

        if "sitemapindex" in root.tag.lower():
            for sitemap_tag in root.findall(f"{ns}sitemap"):
                loc_tag = sitemap_tag.find(f"{ns}loc")
                if loc_tag is not None and loc_tag.text:
                    sub_sitemaps.append(loc_tag.text.strip())
        elif "urlset" in root.tag.lower():
            for url_tag in root.findall(f"{ns}url"):
                loc_tag = url_tag.find(f"{ns}loc")
                if loc_tag is not None and loc_tag.text:
                    links.append(loc_tag.text.strip())
        return sub_sitemaps, links

    def fetch_and_parse(self, url):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            subs, links = self.parse_sitemap_xml(response.text)
            with self.lock:
                for link in links:
                    if len(self.links) < self.max_pages and self.is_allowed(link) and not any(link.lower().endswith(ext) for ext in self.IGNORED_EXTENSIONS):
                        self.links.add(link)
                for sub in subs:
                    self.queue.put(sub)
        except Exception as e:
            logging.warning(f"Error fetching sitemap {url}: {e}")

    def gather_links(self):
        """Gather links from the sitemap and sub-sitemaps."""
        self.queue.put(f"{self.base_url}/sitemap.xml")
        threads = []

        while not self.queue.empty() and len(self.links) < self.max_pages:
            url = self.queue.get()
            t = threading.Thread(target=self.fetch_and_parse, args=(url,))
            threads.append(t)
            t.start()

            # Limit active threads to 10
            if len(threads) >= 10:
                for t in threads:
                    t.join()
                threads = []

        # Wait for remaining threads
        for t in threads:
            t.join()

        return list(self.links)[:self.max_pages]
