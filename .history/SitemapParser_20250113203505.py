import re
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import logging
from time import sleep
from collections import deque

class SitemapParser:
    """
    Handles parsing sitemaps and respecting robots.txt rules for allowed URLs.
    """

    IGNORED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp",
                          ".pdf", ".zip", ".exe", ".rar", ".gz", ".tgz")

    def __init__(self, base_url, max_pages=100):
        self.base_url = base_url.rstrip("/")
        self.max_pages = max_pages
        self.visited_urls = set()
        self.allowed_urls = set()
        self.disallowed_urls = set()

    def fetch_robots_txt(self):
        """
        Fetch and parse the robots.txt file to determine disallowed paths.
        """
        robots_url = f"{self.base_url}/robots.txt"
        logging.info(f"Fetching robots.txt from {robots_url}")
        try:
            response = requests.get(robots_url, timeout=10)
            if response.status_code == 200:
                self.parse_robots_txt(response.text)
            else:
                logging.warning(f"Failed to fetch robots.txt: HTTP {response.status_code}")
        except Exception as e:
            logging.warning(f"Error fetching robots.txt: {e}")

    def parse_robots_txt(self, robots_txt):
        """
        Parse the robots.txt file and populate disallowed paths.
        """
        for line in robots_txt.splitlines():
            line = line.strip()
            if line.startswith("Disallow:"):
                path = line.split(":", 1)[1].strip()
                self.disallowed_urls.add(self.base_url + path)
        logging.info(f"Parsed {len(self.disallowed_urls)} disallowed URLs from robots.txt")

    def parse_sitemap_xml(self, xml_text):
        """
        Parse the sitemap XML and return all links and nested sitemaps.
        """
        root = ET.fromstring(xml_text)
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        sub_sitemaps = []
        links = []

        if "sitemapindex" in root.tag.lower():
            for sitemap in root.findall(f"{ns}sitemap"):
                loc = sitemap.find(f"{ns}loc")
                if loc is not None and loc.text:
                    sub_sitemaps.append(loc.text.strip())
        elif "urlset" in root.tag.lower():
            for url in root.findall(f"{ns}url"):
                loc = url.find(f"{ns}loc")
                if loc is not None and loc.text:
                    links.append(loc.text.strip())
        return sub_sitemaps, links

    def gather_links(self):
        """
        Collect links from the sitemap and respect the robots.txt rules.
        """
        self.fetch_robots_txt()
        sitemap_url = f"{self.base_url}/sitemap.xml"
        links = []
        try:
            logging.info(f"Fetching sitemap from {sitemap_url}")
            response = requests.get(sitemap_url, timeout=10)
            response.raise_for_status()
            sub_sitemaps, links = self.parse_sitemap_xml(response.text)
            for sub_sitemap in sub_sitemaps:
                self.parse_nested_sitemaps(sub_sitemap)
        except Exception as e:
            logging.warning(f"Error fetching sitemap: {e}")

        # Filter links and limit count
        filtered_links = [link for link in links if self.is_allowed(link)]
        return filtered_links[:self.max_pages]

    def parse_nested_sitemaps(self, sitemap_url):
        """
        Recursively parse nested sitemaps.
        """
        try:
            response = requests.get(sitemap_url, timeout=10)
            response.raise_for_status()
            _, links = self.parse_sitemap_xml(response.text)
            self.visited_urls.update(links)
        except Exception as e:
            logging.warning(f"Error fetching nested sitemap {sitemap_url}: {e}")

    def is_allowed(self, url):
        """
        Check if the given URL is allowed based on robots.txt rules.
        """
        return url not in self.disallowed_urls and not any(url.lower().endswith(ext) for ext in self.IGNORED_EXTENSIONS)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = SitemapParser("https://example.com", max_pages=100)
    links = parser.gather_links()
    print(f"Collected {len(links)} links:")
    for link in links:
        print(link)
