import logging
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor


class HTMLParser:
    """
    A utility class for parsing HTML content and extracting metadata.
    """

    @staticmethod
    def parse_html(html):
        """
        Parse HTML content using BeautifulSoup.

        :param html: Raw HTML content as a string.
        :return: BeautifulSoup object.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            return soup
        except Exception as e:
            logging.error(f"Failed to parse HTML: {e}")
            raise

    @staticmethod
    def extract_metadata(soup):
        """
        Extract metadata like title, meta description, and canonical URL.

        :param soup: BeautifulSoup object.
        :return: Dictionary containing metadata.
        """
        metadata = {
            "title": soup.title.string.strip() if soup.title else "",
            "meta_description": "",
            "canonical": "",
        }

        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            metadata["meta_description"] = meta_tag["content"].strip()

        canonical_tag = soup.find("link", rel="canonical")
        if canonical_tag and canonical_tag.get("href"):
            metadata["canonical"] = canonical_tag["href"].strip()

        logging.debug(f"Extracted metadata: {metadata}")
        return metadata

    @staticmethod
    def extract_links(soup, base_url):
        """
        Extract all valid links from the HTML content.

        :param soup: BeautifulSoup object.
        :param base_url: Base URL to resolve relative links.
        :return: List of absolute URLs.
        """
        links = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            absolute_url = urljoin(base_url, href)
            parsed_url = urlparse(absolute_url)

            # Filter invalid URLs and fragments
            if parsed_url.scheme in {"http", "https"} and not parsed_url.fragment:
                links.add(absolute_url)

        logging.debug(f"Extracted {len(links)} links from {base_url}")
        return list(links)


class SitemapParser:
    """
    A utility class for parsing sitemaps and extracting URLs.
    """

    @staticmethod
    def fetch_sitemap(sitemap_url):
        """
        Fetch sitemap content from a URL.

        :param sitemap_url: URL of the sitemap.
        :return: Raw XML content of the sitemap.
        """
        try:
            response = requests.get(sitemap_url, timeout=10)
            response.raise_for_status()
            logging.info(f"Fetched sitemap from {sitemap_url}")
            return response.text
        except requests.RequestException as e:
            logging.error(f"Failed to fetch sitemap: {e}")
            raise

    @staticmethod
    def parse_sitemap(xml_content):
        """
        Parse a sitemap XML content to extract URLs.

        :param xml_content: Raw XML content as a string.
        :return: List of URLs from the sitemap.
        """
        try:
            root = ET.fromstring(xml_content)
            namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            urls = []

            for url_tag in root.findall(f"{namespace}url/{namespace}loc"):
                if url_tag.text:
                    urls.append(url_tag.text.strip())

            logging.info(f"Extracted {len(urls)} URLs from sitemap")
            return urls
        except ET.ParseError as e:
            logging.error(f"Failed to parse sitemap XML: {e}")
            raise

    @staticmethod
    def parse_sitemap_index(xml_content):
        """
        Parse a sitemap index to extract nested sitemap URLs.

        :param xml_content: Raw XML content as a string.
        :return: List of nested sitemap URLs.
        """
        try:
            root = ET.fromstring(xml_content)
            namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            sitemaps = []

            for sitemap_tag in root.findall(f"{namespace}sitemap/{namespace}loc"):
                if sitemap_tag.text:
                    sitemaps.append(sitemap_tag.text.strip())

            logging.info(f"Extracted {len(sitemaps)} nested sitemaps")
            return sitemaps
        except ET.ParseError as e:
            logging.error(f"Failed to parse sitemap index XML: {e}")
            raise

    def fetch_and_parse(self, sitemap_url, max_urls=100):
        """
        Fetch and parse a sitemap, including nested sitemaps.

        :param sitemap_url: URL of the sitemap.
        :param max_urls: Maximum number of URLs to extract.
        :return: List of extracted URLs.
        """
        urls = set()
        to_process = [sitemap_url]

        while to_process and len(urls) < max_urls:
            current_sitemap = to_process.pop(0)

            try:
                xml_content = self.fetch_sitemap(current_sitemap)
                if "<sitemapindex" in xml_content:
                    nested_sitemaps = self.parse_sitemap_index(xml_content)
                    to_process.extend(nested_sitemaps)
                else:
                    extracted_urls = self.parse_sitemap(xml_content)
                    urls.update(extracted_urls)
            except Exception as e:
                logging.error(f"Error processing sitemap {current_sitemap}: {e}")

        logging.info(f"Total extracted URLs: {len(urls)}")
        return list(urls)[:max_urls]


def extract_page_links(url, max_workers=4):
    """
    Extract links from a page using multithreading for efficiency.

    :param url: The URL of the page to extract links from.
    :param max_workers: Number of worker threads.
    :return: List of extracted links.
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = HTMLParser.parse_html(response.text)
        links = HTMLParser.extract_links(soup, url)
        return links
    except Exception as e:
        logging.error(f"Failed to extract links from {url}: {e}")
        return []


# Example Usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test SitemapParser
    sitemap_url = "https://example.com/sitemap.xml"
    sitemap_parser = SitemapParser()
    urls = sitemap_parser.fetch_and_parse(sitemap_url)
    print("Extracted URLs:", urls)

    # Test HTMLParser
    page_url = "https://example.com"
    links = extract_page_links(page_url)
    print("Extracted Links:", links)
