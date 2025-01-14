from multiprocessing import Pool, cpu_count
import requests
import logging

class PageAnalyzer:
    """Analyze web pages in parallel using multiprocessing."""

    def __init__(self, urls, max_workers=None):
        self.urls = urls
        self.max_workers = max_workers or max(1, int(0.75 * cpu_count()))

    def analyze_page(self, url):
        """Analyze a single page."""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return {"url": url, "status": "success", "content": response.text}
        except Exception as e:
            logging.warning(f"Error analyzing page {url}: {e}")
            return {"url": url, "status": "error", "error": str(e)}

    def analyze_pages(self):
        """Analyze pages in parallel."""
        with Pool(self.max_workers) as pool:
            results = pool.map(self.analyze_page, self.urls)
        return results
