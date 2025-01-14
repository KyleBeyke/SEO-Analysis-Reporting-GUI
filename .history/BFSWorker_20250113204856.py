from selenium.webdriver.common.by import By
from concurrent.futures import ThreadPoolExecutor
import time

class BFSWorker:
    """Perform BFS traversal with thread pooling."""

    def __init__(self, driver, base_url, max_pages, bfs_depth=2):
        self.driver = driver
        self.base_url = base_url
        self.max_pages = max_pages
        self.bfs_depth = bfs_depth
        self.visited = set()
        self.executor = ThreadPoolExecutor(max_workers=10)

    def scroll_and_collect(self):
        """Scroll and collect links."""
        for _ in range(2):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        return self.driver.find_elements(By.TAG_NAME, "a")

    def bfs_task(self, url, depth):
        if url in self.visited or depth > self.bfs_depth:
            return
        self.visited.add(url)
        self.driver.get(url)
        links = self.scroll_and_collect()

        for link in links:
            href = link.get_attribute("href")
            if href and len(self.visited) < self.max_pages:
                self.executor.submit(self.bfs_task, href, depth + 1)

    def start_bfs(self):
        self.executor.submit(self.bfs_task, self.base_url, 0)
        self.executor.shutdown(wait=True)
        return list(self.visited)[:self.max_pages]
