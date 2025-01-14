import re
import logging
from collections import Counter
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from nltk.tokenize import word_tokenize
from nltk.stem import PorterStemmer

class PageAnalyzer:
    """Handles page analysis, including keyword extraction, metadata parsing, and scoring."""

    def __init__(self, stop_words=None):
        if stop_words is None:
            stop_words = self.default_stop_words()
        self.stop_words = stop_words
        self.stemmer = PorterStemmer()

    @staticmethod
    def default_stop_words():
        """Default set of stop words for keyword filtering."""
        raw_stop_words = """
        a about above after again against all am an and any are as at be because been before
        being below between both but by can could did do does doing down during each few for from
        further had has have having he her here hers herself him himself his how i if in into is
        it its itself just me more most my myself no nor not now of off on once only or other our
        ours ourselves out over own same she should so some such than that the their theirs them
        themselves then there these they this those through to too under until up very was we well were
        what when where which while who whom why with would you your yours yourself yourselves
        """
        return set(w.strip().lower() for w in raw_stop_words.split() if w.strip())

    def analyze_page(self, url):
        """Analyzes a single page for SEO data."""
        try:
            logging.info(f"Analyzing URL: {url}")
            driver = self.configure_driver()
            driver.get(url)
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")

            data = {
                "URL": url,
                "Title": self.extract_title(soup),
                "MetaDescription": self.extract_meta_description(soup),
                "H1Count": len(soup.find_all("h1")),
                "H2Count": len(soup.find_all("h2")),
                "WordCount": 0,
                "Keywords": "",
                "Score": 0,
                "Recommendations": "",
            }

            text_content = soup.get_text(separator=" ", strip=True)
            word_counts = self.extract_keywords(text_content)
            data["WordCount"] = sum(word_counts.values())
            data["Keywords"] = ", ".join(f"{k}({v})" for k, v in word_counts.most_common(5))

            score, recommendations = self.calculate_score(data)
            data["Score"] = score
            data["Recommendations"] = recommendations

            driver.quit()
            return data
        except Exception as e:
            logging.error(f"Error analyzing {url}: {e}")
            return {"URL": url, "Error": str(e)}

    def extract_title(self, soup):
        """Extracts the title from a BeautifulSoup object."""
        title_tag = soup.find("title")
        return title_tag.get_text().strip() if title_tag else ""

    def extract_meta_description(self, soup):
        """Extracts the meta description."""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        return meta_tag["content"].strip() if meta_tag and "content" in meta_tag.attrs else ""

    def extract_keywords(self, text):
        """Extracts keywords from text using tokenization and stemming."""
        tokens = word_tokenize(text)
        filtered_tokens = [
            self.stemmer.stem(tok.lower())
            for tok in tokens if tok.isalpha() and tok.lower() not in self.stop_words
        ]
        return Counter(filtered_tokens)

    def calculate_score(self, data):
        """Calculates SEO score and provides recommendations."""
        score = 0
        recommendations = []

        # Title
        if 50 <= len(data["Title"]) <= 60:
            score += 10
        else:
            recommendations.append("Title should be 50-60 characters.")

        # Meta description
        if 120 <= len(data["MetaDescription"]) <= 160:
            score += 10
        else:
            recommendations.append("Meta description should be 120-160 characters.")

        # Word count
        if data["WordCount"] >= 300:
            score += 10
        else:
            recommendations.append("Content should have at least 300 words.")

        # Headings
        if data["H1Count"] > 0:
            score += 10
        else:
            recommendations.append("Add at least one H1 tag.")
        if data["H2Count"] > 0:
            score += 5
        else:
            recommendations.append("Add at least one H2 tag.")

        return score, "; ".join(recommendations)

    @staticmethod
    def configure_driver():
        """Configures and returns a headless Chrome driver."""
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        return driver
