import logging
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

class SitemapParser:
    """A utility class to parse and retrieve URLs from sitemaps."""

    def __init__(self):
        self.logger = logging.getLogger("SitemapParser")

    def fetch_sitemap(self, base_url):
        """Fetch the sitemap.xml or sitemap_index.xml from the given base URL."""
        possible_endpoints = ["sitemap.xml", "sitemap_index.xml"]
        for endpoint in possible_endpoints:
            sitemap_url = urljoin(base_url, endpoint)
            try:
                self.logger.info(f"Fetching sitemap: {sitemap_url}")
                response = requests.get(sitemap_url, timeout=10)
                response.raise_for_status()
                if response.headers.get("Content-Type", "").startswith("application/xml") or "xml" in response.text:
                    self.logger.info(f"Successfully fetched sitemap: {sitemap_url}")
                    return response.text
            except Exception as e:
                self.logger.warning(f"Failed to fetch sitemap at {sitemap_url}: {e}")
        raise Exception("Failed to retrieve any sitemaps.")

    def parse_sitemap(self, sitemap_text):
        """Parse a sitemap or sitemap index and return a list of URLs."""
        try:
            root = ET.fromstring(sitemap_text)
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            urls = []
            if root.tag.endswith("sitemapindex"):
                self.logger.info("Parsing sitemap index...")
                for sitemap in root.findall(f"{ns}sitemap"):
                    loc = sitemap.find(f"{ns}loc")
                    if loc is not None and loc.text:
                        urls.append(loc.text.strip())
            elif root.tag.endswith("urlset"):
                self.logger.info("Parsing URL set...")
                for url in root.findall(f"{ns}url"):
                    loc = url.find(f"{ns}loc")
                    if loc is not None and loc.text:
                        urls.append(loc.text.strip())
            return urls
        except ET.ParseError as e:
            self.logger.error(f"Error parsing sitemap XML: {e}")
            raise

    def gather_urls(self, base_url, max_urls=1000):
        """Retrieve URLs from the sitemap, respecting the maximum limit."""
        urls = set()
        try:
            sitemap_text = self.fetch_sitemap(base_url)
            parsed_urls = self.parse_sitemap(sitemap_text)

            while parsed_urls and len(urls) < max_urls:
                url = parsed_urls.pop(0)
                if url.endswith(".xml"):
                    self.logger.info(f"Fetching nested sitemap: {url}")
                    try:
                        nested_sitemap = self.fetch_sitemap(url)
                        parsed_urls.extend(self.parse_sitemap(nested_sitemap))
                    except Exception as e:
                        self.logger.warning(f"Failed to fetch nested sitemap: {e}")
                else:
                    urls.add(url)

                if len(urls) >= max_urls:
                    break

            self.logger.info(f"Collected {len(urls)} URLs from sitemaps.")
        except Exception as e:
            self.logger.error(f"Error during sitemap processing: {e}")
        return list(urls)

    def filter_urls(self, urls, ignored_extensions=(".jpg", ".png", ".pdf")):
        """Filter out URLs based on ignored extensions."""
        filtered_urls = [url for url in urls if not any(url.lower().endswith(ext) for ext in ignored_extensions)]
        self.logger.info(f"Filtered URLs: {len(filtered_urls)} out of {len(urls)}")
        return filtered_urls

# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = SitemapParser()
    base_url = "https://example.com"
    urls = parser.gather_urls(base_url)
    filtered_urls = parser.filter_urls(urls)
    print(filtered_urls)
