import threading
from queue import Queue
import requests
import xml.etree.ElementTree as ET

class SitemapParser:
    """Fetch and parse sitemap.xml with multithreading."""

    def __init__(self, base_url, max_pages):
        self.base_url = base_url.rstrip("/")
        self.max_pages = max_pages
        self.links = set()
        self.queue = Queue()
        self.lock = threading.Lock()

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
                self.links.update(links)
                for sub in subs:
                    self.queue.put(sub)
        except Exception as e:
            logging.warning(f"Error fetching sitemap {url}: {e}")

    def gather_links(self):
        # Initial sitemap
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

        # Filter links
        filtered_links = [link for link in self.links if len(self.links) < self.max_pages]
        return filtered_links[:self.max_pages]
