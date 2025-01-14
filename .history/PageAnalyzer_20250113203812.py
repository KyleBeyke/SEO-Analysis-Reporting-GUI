import re
import requests
from collections import Counter
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from nltk.tokenize import word_tokenize
from nltk.stem import PorterStemmer
import logging

# Constants
STOP_WORDS = {"a", "an", "the", "and", "is", "to", "of", "for", "with", "on", "by", "at", "from"}
IGNORED_EXTENSIONS = {".jpg", ".png", ".gif", ".pdf", ".zip", ".exe", ".mp4", ".mov", ".doc", ".xls"}


class PageAnalyzer:
    """
    Analyzes individual pages for SEO-relevant data, including keywords, meta tags, and performance scores.
    """

    def __init__(self, api_key=None):
        """
        Initialize the PageAnalyzer.
        :param api_key: Google PageSpeed Insights API key (optional).
        """
        self.api_key = api_key
        self.stemmer = PorterStemmer()

    def tokenize_and_stem(self, text):
        """
        Tokenize and stem text for keyword extraction.
        :param text: The raw text to process.
        """
        tokens = word_tokenize(text)
        filtered_tokens = [
            self.stemmer.stem(token.lower())
            for token in tokens
            if token.isalpha() and token.lower() not in STOP_WORDS
        ]
        return Counter(filtered_tokens)

    def fetch_page_content(self, url):
        """
        Fetch the HTML content of a given page.
        :param url: The URL of the page to fetch.
        """
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logging.error(f"Error fetching page content: {url} -> {e}")
            return None

    def analyze_keywords(self, text):
        """
        Extract keywords from the page text using stemming and tokenization.
        :param text: The raw text to analyze.
        """
        word_counts = self.tokenize_and_stem(text)
        return word_counts.most_common(10)

    def analyze_meta_tags(self, soup):
        """
        Analyze meta tags and headers in the page content.
        :param soup: BeautifulSoup object for the HTML content.
        """
        meta_data = {
            "title": "",
            "meta_description": "",
            "title_length": 0,
            "meta_description_length": 0,
            "h1_count": 0,
            "h2_count": 0,
            "h3_count": 0,
        }

        # Title
        title_tag = soup.find("title")
        if title_tag:
            meta_data["title"] = title_tag.text.strip()
            meta_data["title_length"] = len(meta_data["title"])

        # Meta Description
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        if meta_desc_tag and meta_desc_tag.get("content"):
            meta_data["meta_description"] = meta_desc_tag["content"].strip()
            meta_data["meta_description_length"] = len(meta_data["meta_description"])

        # Header Tags
        meta_data["h1_count"] = len(soup.find_all("h1"))
        meta_data["h2_count"] = len(soup.find_all("h2"))
        meta_data["h3_count"] = len(soup.find_all("h3"))

        return meta_data

    def analyze_images(self, soup):
        """
        Analyze images for alt attributes.
        :param soup: BeautifulSoup object for the HTML content.
        """
        images = soup.find_all("img")
        total_images = len(images)
        missing_alt = sum(1 for img in images if not img.get("alt"))
        return {
            "total_images": total_images,
            "images_missing_alt": missing_alt,
        }

    def analyze_structured_data(self, soup):
        """
        Analyze structured data on the page.
        :param soup: BeautifulSoup object for the HTML content.
        """
        ld_json = soup.find_all("script", type="application/ld+json")
        microdata = soup.find_all(attrs={"itemscope": True})
        return {
            "ld_json_count": len(ld_json),
            "microdata_count": len(microdata),
        }

    def fetch_page_speed(self, url, strategy="mobile"):
        """
        Fetch performance scores using Google PageSpeed Insights API.
        :param url: The URL to analyze.
        :param strategy: Strategy ('mobile' or 'desktop').
        """
        if not self.api_key:
            return {"performance_score": None, "error": "No API key provided"}

        endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        params = {"url": url, "strategy": strategy, "key": self.api_key}

        try:
            response = requests.get(endpoint, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            performance_score = data.get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score")
            return {"performance_score": int(performance_score * 100) if performance_score else None}
        except Exception as e:
            logging.error(f"Error fetching PageSpeed Insights for {url}: {e}")
            return {"performance_score": None, "error": str(e)}

    def analyze_page(self, url):
        """
        Perform a full analysis of a single page.
        :param url: The URL of the page to analyze.
        """
        content = self.fetch_page_content(url)
        if not content:
            return {"error": "Failed to fetch page content"}

        soup = BeautifulSoup(content, "html.parser")

        meta_data = self.analyze_meta_tags(soup)
        keyword_data = self.analyze_keywords(soup.get_text())
        image_data = self.analyze_images(soup)
        structured_data = self.analyze_structured_data(soup)

        mobile_speed = self.fetch_page_speed(url, "mobile")
        desktop_speed = self.fetch_page_speed(url, "desktop")

        return {
            "url": url,
            **meta_data,
            "keywords": keyword_data,
            **image_data,
            **structured_data,
            "mobile_performance_score": mobile_speed["performance_score"],
            "desktop_performance_score": desktop_speed["performance_score"],
            "errors": {
                "page_speed_mobile": mobile_speed.get("error"),
                "page_speed_desktop": desktop_speed.get("error"),
            },
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example Usage
    api_key = "YOUR_GOOGLE_PAGESPEED_API_KEY"
    url = "https://example.com"
    analyzer = PageAnalyzer(api_key=api_key)

    result = analyzer.analyze_page(url)
    print("Page Analysis Results:")
    for key, value in result.items():
        print(f"{key}: {value}")
