import queue
from urllib.parse import urljoin, urlparse
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium import webdriver
from concurrent.futures import ThreadPoolExecutor
import time
import logging


class BFSWorker:
    """Performs breadth-first search for link gathering when sitemaps are unavailable."""
    def __init__(self, base_url, max_pages=100, ignored_extensions=None, stop_words=None, bfs_depth=2, driver_path=None):
        self.base_url = base_url.rstrip("/")
        self.max_pages = max_pages
        self.ignored_extensions = ignored_extensions or (
            ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".pdf",
            ".zip", ".exe", ".rar", ".gz", ".tgz", ".mp4", ".avi"
        )
        self.stop_words = stop_words or {"terms", "privacy", "login", "signup"}
        self.bfs_depth = bfs_depth
        self.driver_path = driver_path or "/usr/local/bin/chromedriver"
        self.visited = set()
        self.queue = queue.Queue()

    def configure_driver(self):
        """Configure Selenium WebDriver with headless Chrome."""
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        return webdriver.Chrome(service=Service(self.driver_path), options=options)

    def scroll_and_collect_links(self, driver):
        """Scroll the page to load dynamic content and collect links."""
        try:
            for _ in range(2):  # Adjust the number of scrolls if needed
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
            links = driver.find_elements(By.TAG_NAME, "a")
            return [link.get_attribute("href") for link in links if link.get_attribute("href")]
        except Exception as e:
            logging.error(f"Error while scrolling and collecting links: {e}")
            return []

    def filter_links(self, links):
        """Filter links based on ignored extensions, stop words, and domain matching."""
        filtered_links = []
        for link in links:
            if not link:
                continue
            parsed_url = urlparse(link)
            # Ignore links with certain file extensions
            if any(link.lower().endswith(ext) for ext in self.ignored_extensions):
                continue
            # Ignore links containing stop words
            if any(stop_word in parsed_url.path.lower() for stop_word in self.stop_words):
                continue
            # Ensure the link is within the same domain
            if parsed_url.netloc and parsed_url.netloc != urlparse(self.base_url).netloc:
                continue
            filtered_links.append(link)
        return filtered_links

    def bfs_worker(self, driver):
        """Worker function for BFS traversal."""
        while not self.queue.empty() and len(self.visited) < self.max_pages:
            try:
                current_url, current_depth = self.queue.get(timeout=3)
                if current_url in self.visited or current_depth > self.bfs_depth:
                    continue
                self.visited.add(current_url)
                logging.info(f"Visiting URL: {current_url} (Depth: {current_depth})")

                driver.get(current_url)
                time.sleep(1)
                links = self.scroll_and_collect_links(driver)
                filtered_links = self.filter_links(links)

                for link in filtered_links:
                    if link not in self.visited:
                        self.queue.put((link, current_depth + 1))
            except Exception as e:
                logging.error(f"BFS worker encountered an error: {e}")
            finally:
                self.queue.task_done()

    def bfs_concurrent(self):
        """Perform BFS traversal using concurrent workers."""
        logging.info("Starting BFS traversal...")
        self.queue.put((self.base_url, 0))
        drivers = [self.configure_driver() for _ in range(min(4, self.max_pages))]  # Adjust based on cores
        with ThreadPoolExecutor(max_workers=len(drivers)) as executor:
            futures = [executor.submit(self.bfs_worker, driver) for driver in drivers]
            for future in futures:
                future.result()  # Wait for all threads to complete

        # Close all drivers
        for driver in drivers:
            try:
                driver.quit()
            except Exception as e:
                logging.warning(f"Error while quitting driver: {e}")

        return list(self.visited)[:self.max_pages]
