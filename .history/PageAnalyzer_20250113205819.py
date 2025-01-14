from collections import Counter
import requests
import re
import time
from nltk.tokenize import word_tokenize
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium import webdriver
from bs4 import BeautifulSoup
import logging


class PageAnalyzer:
    """Analyzes a single web page for SEO elements, performance, and keyword insights."""
    def __init__(self, driver_path=None, stop_words=None, pagespeed_api_key=None):
        self.driver_path = driver_path or "/usr/local/bin/chromedriver"
        self.stop_words = stop_words or set()
        self.pagespeed_api_key = pagespeed_api_key

    def configure_driver(self):
        """Configure Selenium WebDriver with headless Chrome."""
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        return webdriver.Chrome(service=Service(self.driver_path), options=options)

    def extract_keywords(self, text):
        """Extracts and stems keywords from the page content."""
        tokens = word_tokenize(text)
        filtered_tokens = [
            word.lower()
            for word in tokens
            if word.isalnum() and word.lower() not in self.stop_words
        ]
        return Counter(filtered_tokens)

    def check_page_speed_insights(self, url, strategy="mobile"):
        """Fetches Google PageSpeed Insights data."""
        if not self.pagespeed_api_key:
            logging.info("No PageSpeed API key provided. Skipping performance analysis.")
            return None

        endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        params = {
            "url": url,
            "key": self.pagespeed_api_key,
            "strategy": strategy,
        }

        try:
            response = requests.get(endpoint, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            score = data.get("lighthouseResult", {}).get("categories", {}).get(
                "performance", {}
            ).get("score", None)
            return int(score * 100) if score else None
        except Exception as e:
            logging.error(f"PageSpeed API error for {url}: {e}")
            return None

    def analyze_page(self, url):
        """Analyzes the page for SEO and performance metrics."""
        driver = self.configure_driver()
        results = {
            "URL": url,
            "Title": "",
            "MetaDescription": "",
            "H1Count": 0,
            "H2Count": 0,
            "WordCount": 0,
            "Keywords": "",
            "Canonical": "",
            "Noindex": False,
            "ImageCount": 0,
            "ImagesWithoutAlt": 0,
            "PerformanceMobile": None,
            "PerformanceDesktop": None,
        }

        try:
            driver.get(url)
            time.sleep(2)  # Allow the page to load

            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")

            # Extract title
            title_tag = soup.find("title")
            results["Title"] = title_tag.get_text(strip=True) if title_tag else ""

            # Extract meta description
            meta_desc = soup.find("meta", attrs={"name": "description"})
            results["MetaDescription"] = (
                meta_desc.get("content", "").strip() if meta_desc else ""
            )

            # Count headings
            results["H1Count"] = len(soup.find_all("h1"))
            results["H2Count"] = len(soup.find_all("h2"))

            # Extract canonical link
            canonical_tag = soup.find("link", rel="canonical")
            results["Canonical"] = canonical_tag.get("href", "").strip() if canonical_tag else ""

            # Check for noindex directive
            robots_meta = soup.find("meta", attrs={"name": re.compile(r"robots", re.I)})
            robots_content = robots_meta.get("content", "").lower() if robots_meta else ""
            results["Noindex"] = "noindex" in robots_content

            # Count images and missing alt texts
            images = soup.find_all("img")
            results["ImageCount"] = len(images)
            results["ImagesWithoutAlt"] = sum(1 for img in images if not img.get("alt"))

            # Extract and analyze text content
            text_content = soup.get_text(separator=" ", strip=True)
            keywords = self.extract_keywords(text_content)
            results["WordCount"] = sum(keywords.values())
            top_keywords = keywords.most_common(10)
            results["Keywords"] = ", ".join(f"{k}({v})" for k, v in top_keywords)

            # PageSpeed Insights
            results["PerformanceMobile"] = self.check_page_speed_insights(url, "mobile")
            results["PerformanceDesktop"] = self.check_page_speed_insights(url, "desktop")

        except Exception as e:
            logging.error(f"Error analyzing page {url}: {e}")
        finally:
            driver.quit()

        return results
