import queue
import time
import threading
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from urllib.parse import urlparse
import logging
from webdriver_manager.chrome import ChromeDriverManager


class BFSLinkCollector:
    """
    Performs BFS crawling to collect links from a site.
    Uses Selenium for JavaScript-heavy sites and respects robots.txt rules.
    """

    def __init__(self, base_url, sitemap_parser, max_pages=100, driver_path=None, bfs_depth=2):
        """
        Initialize the BFSLinkCollector.
        :param base_url: The base URL of the site.
        :param sitemap_parser: An instance of SitemapParser to handle robots.txt rules.
        :param max_pages: Maximum number of pages to crawl.
        :param driver_path: Path to ChromeDriver (optional, defaults to auto-install).
        :param bfs_depth: Maximum BFS depth to crawl.
        """
        self.base_url = base_url.rstrip("/")
        self.sitemap_parser = sitemap_parser
        self.max_pages = max_pages
        self.bfs_depth = bfs_depth
        self.visited = set()
        self.queue = queue.Queue()
        self.queue.put((self.base_url, 0))
        self.driver_path = driver_path or ChromeDriverManager().install()

    def configure_driver(self):
        """
        Configure a headless ChromeDriver for Selenium.
        """
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        driver = webdriver.Chrome(service=Service(self.driver_path), options=options)
        driver.set_page_load_timeout(15)
        return driver

    def scroll_and_collect(self, driver):
        """
        Scroll down the page and collect <a> tags for links.
        :param driver: The Selenium WebDriver instance.
        """
        for _ in range(2):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        return driver.find_elements(By.TAG_NAME, "a")

    def is_allowed(self, url):
        """
        Check if the given URL is allowed based on SitemapParser and extension rules.
        :param url: The URL to check.
        """
        return (
            url not in self.visited
            and self.sitemap_parser.is_allowed(url)
            and not any(url.lower().endswith(ext) for ext in self.sitemap_parser.IGNORED_EXTENSIONS)
        )

    def bfs_worker(self, driver):
        """
        Worker thread for BFS crawling.
        :param driver: The Selenium WebDriver instance.
        """
        while True:
            try:
                url, depth = self.queue.get(timeout=3)
            except queue.Empty:
                return

            if url in self.visited or depth > self.bfs_depth:
                self.queue.task_done()
                continue

            self.visited.add(url)
            logging.info(f"[BFS] Visiting: {url}, Depth: {depth}, Visited: {len(self.visited)}")

            try:
                driver.get(url)
                time.sleep(1)
                a_tags = self.scroll_and_collect(driver)
                for a in a_tags:
                    href = a.get_attribute("href") or ""
                    if href and self.is_allowed(href):
                        self.queue.put((href, depth + 1))
                        if len(self.visited) + self.queue.qsize() >= self.max_pages:
                            break
            except Exception as e:
                logging.warning(f"[BFS] Error visiting {url}: {e}")
            finally:
                self.queue.task_done()

    def collect_links(self):
        """
        Perform BFS crawling using Selenium and collect links.
        """
        cores = max(1, threading.active_count() // 2)
        drivers = [self.configure_driver() for _ in range(cores)]
        threads = []

        for driver in drivers:
            thread = threading.Thread(target=self.bfs_worker, args=(driver,), daemon=True)
            threads.append(thread)
            thread.start()

        self.queue.join()

        for driver in drivers:
            driver.quit()

        return list(self.visited)[: self.max_pages]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example Usage
    base_url = "https://example.com"
    sitemap_parser = SitemapParser(base_url, max_pages=100)
    sitemap_parser.gather_links()  # Initialize sitemap parser to populate disallowed URLs

    bfs_collector = BFSLinkCollector(base_url, sitemap_parser, max_pages=100, bfs_depth=2)
    links = bfs_collector.collect_links()

    print(f"Collected {len(links)} links via BFS:")
    for link in links:
        print(link)
