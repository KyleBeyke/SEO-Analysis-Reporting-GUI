import logging
import os
from urllib.parse import urlparse
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import pandas as pd

from sitemap_parser import SitemapParser  # Assumes `SitemapParser` is implemented
from bfs_collector import BFSLinkCollector  # Assumes `BFSLinkCollector` is implemented
from page_analyzer import PageAnalyzer  # Uses the previously defined `PageAnalyzer`


class ScraperWorker(QObject):
    """
    ScraperWorker integrates the full process of crawling and analyzing web pages.
    It uses signals to communicate progress and results to the GUI.
    """
    finished = pyqtSignal(str, str)  # Signal for completion (CSV and HTML paths)
    error = pyqtSignal(str)  # Signal for errors
    status_update = pyqtSignal(str)  # Signal for status updates
    analysis_progress = pyqtSignal(int, int)  # Signal for progress (current, total)

    def __init__(self, domain, max_pages, driver_path, output_dir, site_password, pagespeed_api):
        super().__init__()
        self.domain = domain.strip()
        self.max_pages = max_pages
        self.driver_path = driver_path
        self.output_dir = output_dir
        self.site_password = site_password
        self.pagespeed_api = pagespeed_api.strip() if pagespeed_api else None

        self.sitewide_word_counts = Counter()
        self.current_count = 0
        self.total_count = 0

    @pyqtSlot()
    def run(self):
        """
        Main workflow for crawling and analyzing pages.
        """
        try:
            base_url = self._normalize_domain(self.domain)
            self.status_update.emit(f"Starting analysis for {base_url}")

            # Step 1: Link Collection
            links = self._collect_links(base_url)

            # Step 2: Analyze Pages
            self.current_count = 0
            self.total_count = len(links)
            results = self._analyze_pages(links)

            # Step 3: Final Summary and Export
            self._generate_reports(base_url, results)

        except Exception as e:
            logging.exception(f"ScraperWorker encountered an error: {e}")
            self.error.emit(str(e))

    def _normalize_domain(self, domain):
        """
        Ensures the domain includes a scheme (http/https).
        """
        if not domain.startswith(("http://", "https://")):
            domain = f"https://{domain}"
        return domain

    def _collect_links(self, base_url):
        """
        Collects links using sitemaps or BFS fallback.
        """
        self.status_update.emit("Attempting to parse sitemaps...")
        sitemap_parser = SitemapParser(base_url, self.max_pages, self.site_password, self.driver_path)
        try:
            links = sitemap_parser.parse_sitemap()
        except Exception as e:
            logging.warning(f"Sitemap parsing failed: {e}")
            self.status_update.emit(f"Sitemap parsing failed, falling back to BFS...")
            bfs_collector = BFSLinkCollector(base_url, self.max_pages, self.site_password, self.driver_path)
            links = bfs_collector.collect_links()

        unique_links = list(dict.fromkeys(links))
        self.status_update.emit(f"Collected {len(unique_links)} unique links.")
        return unique_links[:self.max_pages]

    def _analyze_pages(self, links):
        """
        Analyzes pages concurrently and updates progress.
        """
        analyzer = PageAnalyzer(api_key=self.pagespeed_api)
        results = []

        def analyze_page_chunk(chunk):
            chunk_results = []
            for link in chunk:
                self.status_update.emit(f"Analyzing page: {link}")
                result = analyzer.analyze_page(link)
                results.append(result)
                self.sitewide_word_counts.update(result.get("keywords", {}))
                self.current_count += 1
                self.analysis_progress.emit(self.current_count, self.total_count)
            return chunk_results

        chunk_size = max(1, len(links) // os.cpu_count())
        chunks = [links[i:i + chunk_size] for i in range(0, len(links), chunk_size)]

        with ThreadPoolExecutor() as executor:
            executor.map(analyze_page_chunk, chunks)

        return results

    def _generate_reports(self, base_url, results):
        """
        Generates CSV and HTML reports based on the analysis results.
        """
        self.status_update.emit("Generating reports...")
        domain_name = self._sanitize_domain(urlparse(base_url).netloc)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        csv_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{timestamp}.csv")
        html_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{timestamp}.html")

        # Add a final row for sitewide keywords
        sitewide_keywords = ", ".join(f"{k}({v})" for k, v in self.sitewide_word_counts.most_common(10))
        sitewide_summary = {
            "URL": "SITEWIDE",
            "Title": "",
            "TitleLength": 0,
            "MetaDescriptionLength": 0,
            "H1Count": 0,
            "H2Count": 0,
            "WordCount": sum(self.sitewide_word_counts.values()),
            "Keywords": sitewide_keywords,
            "Canonical": "",
            "Noindex": False,
            "ImagesWithoutAlt": 0,
            "ImageCount": 0,
            "StructuredDataCount": 0,
            "MicrodataCount": 0,
            "PerformanceScoreMobile": None,
            "PerformanceScoreDesktop": None,
            "Score": 0,
            "Recommendations": "",
            "Error": "",
        }
        results.append(sitewide_summary)

        # Export results
        df = pd.DataFrame(results)
        df.to_csv(csv_file, index=False)
        df.to_html(html_file, index=False)

        self.status_update.emit("Reports generated successfully.")
        self.finished.emit(csv_file, html_file)

    def _sanitize_domain(self, domain):
        """
        Sanitize domain names for use in filenames.
        """
        return re.sub(r"[^a-zA-Z0-9.-]", "_", domain)
