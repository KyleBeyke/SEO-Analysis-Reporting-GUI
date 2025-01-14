import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

class SitemapParser:
    """Utility class for parsing and processing sitemaps."""

    @staticmethod
    def fetch_sitemap(url):
        """Fetch the sitemap from the given URL."""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to fetch sitemap from {url}: {e}")

    @staticmethod
    def parse_xml_sitemap(xml_text):
        """Parse an XML sitemap and extract URLs."""
        try:
            root = ET.fromstring(xml_text)
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            urls = []
            for url in root.findall(f"{ns}url/{ns}loc"):
                if url.text:
                    urls.append(url.text.strip())
            return urls
        except ET.ParseError as e:
            raise Exception(f"Failed to parse XML sitemap: {e}")

    @staticmethod
    def parse_html_sitemap(html_text, base_url):
        """Parse an HTML sitemap and extract URLs."""
        soup = BeautifulSoup(html_text, "html.parser")
        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            # Convert relative URLs to absolute
            full_url = urljoin(base_url, href)
            links.append(full_url)
        return links

    @staticmethod
    def parse_sitemap(url):
        """Fetch and parse the sitemap, supporting both XML and HTML formats."""
        sitemap_content = SitemapParser.fetch_sitemap(url)
        # Try parsing as XML; fallback to HTML if XML fails
        try:
            return SitemapParser.parse_xml_sitemap(sitemap_content)
        except Exception:
            return SitemapParser.parse_html_sitemap(sitemap_content, base_url=url)

# Example usage (for testing purposes):
if __name__ == "__main__":
    sitemap_url = "https://example.com/sitemap.xml"
    try:
        parser = SitemapParser()
        urls = parser.parse_sitemap(sitemap_url)
        print(f"Extracted {len(urls)} URLs from {sitemap_url}")
    except Exception as e:
        print(f"Error: {e}")
