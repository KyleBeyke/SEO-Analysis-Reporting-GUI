from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse
import os
import logging
import re
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from .utils import (configure_driver, gather_links_from_sitemap,
                    selenium_bfs_concurrent, analyze_page_concurrently)

class ScraperWorker(QObject):
    """
    Worker class for performing SEO analysis in a background thread.
    Combines link collection and concurrency-based analysis.
    """

    finished = pyqtSignal(str, str)
    error = pyqtSignal(str)
    statusUpdate = pyqtSignal(str)
    analysisProgress = pyqtSignal(int, int)

    def __init__(self, domain, max_pages, driver_path, output_dir, site_password, pagespeed_api):
        super().__init__()
        self.domain = domain
        self.max_pages = min(max_pages, 999)
        self.driver_path = driver_path
        self.output_dir = output_dir
        self.site_password = site_password
        self.api_key = pagespeed_api.strip() if pagespeed_api else None

        self.sitewide_word_counts = Counter()
        self.current_count = 0
        self.total_count = 0

    @pyqtSlot()
    def run(self):
        try:
            # Ensure domain starts with http/https
            base_url = self.domain.strip()
            if not base_url.startswith(("http://", "https://")):
                base_url = "https://" + base_url

            logging.info(f"[WORKER] Starting with base_url={base_url}, max_pages={self.max_pages}")

            # Step 1: Gather links (via sitemap or BFS fallback)
            links = []
            try:
                links = gather_links_from_sitemap(
                    base_url, self.max_pages, site_password=self.site_password,
                    status_callback=self.statusUpdate.emit
                )
            except Exception as e:
                msg = f"Sitemap attempt failed => {e}"
                logging.warning(msg)
                self.statusUpdate.emit(msg)

            if not links:
                logging.info("[WORKER] No links from sitemap -> fallback BFS concurrency.")
                links = selenium_bfs_concurrent(
                    base_url, self.max_pages, site_password=self.site_password,
                    status_callback=self.statusUpdate.emit,
                    driver_path=self.driver_path,
                    bfs_depth=2
                )

            unique_links = list(dict.fromkeys(links))
            if len(unique_links) > self.max_pages:
                unique_links = unique_links[:self.max_pages]

            collect_msg = f"Collected {len(unique_links)} URLs. Starting analysis..."
            logging.info(collect_msg)
            self.statusUpdate.emit(collect_msg)
            self.current_count = 0
            self.total_count = len(unique_links)

            def increment_analysis(x=1):
                self.current_count += x
                self.analysisProgress.emit(self.current_count, self.total_count)

            # Step 2: Perform analysis concurrently
            results = analyze_page_concurrently(
                unique_links,
                driver_path=self.driver_path,
                sitewide_word_counts=self.sitewide_word_counts,
                status_callback=self.statusUpdate.emit,
                progress_callback=increment_analysis,
                api_key=self.api_key
            )

            # Step 3: Generate final sitewide summary
            self.statusUpdate.emit("Generating final keywords row...")
            top_10_sitewide = self.sitewide_word_counts.most_common(10)
            top_10_str = ", ".join(f"{k}({v})" for k, v in top_10_sitewide)
            sitewide_row = {
                "URL": "SITEWIDE",
                "Title": "",
                "TitleLength": 0,
                "MetaDescriptionLength": 0,
                "H1Count": 0,
                "H2Count": 0,
                "WordCount": sum(self.sitewide_word_counts.values()),
                "Keywords": top_10_str,
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
                "Error": ""
            }
            results.append(sitewide_row)

            # Step 4: Write reports
            self.statusUpdate.emit("Writing reports...")
            domain_name = self._sanitize_domain(urlparse(base_url).netloc)
            date_str = datetime.now().strftime("%Y%m%d_%H%M")
            csv_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{date_str}.csv")
            html_file = os.path.join(self.output_dir, f"seo_report_{domain_name}_{date_str}.html")

            logging.info(f"[WORKER] Saving CSV => {csv_file}")
            logging.info(f"[WORKER] Saving HTML => {html_file}")
            df = pd.DataFrame(results)
            df.to_csv(csv_file, index=False)
            df.to_html(html_file, index=False)

            self.finished.emit(csv_file, html_file)

        except Exception as e:
            logging.exception(f"[WORKER] run exception => {e}")
            self.error.emit(str(e))

    @staticmethod
    def _sanitize_domain(netloc):
        """Sanitize domain for use in file names."""
        return re.sub(r'[^a-zA-Z0-9.-]', '_', netloc)
