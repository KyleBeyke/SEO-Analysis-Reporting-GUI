import re
import requests
from urllib.parse import urljoin
from multiprocessing.pool import ThreadPool
import logging


class RobotsParser:
    """
    A class to parse and handle robots.txt directives.
    """

    DEFAULT_USER_AGENT = "*"
    ALLOWED_DIRECTIVES = {"allow", "disallow", "crawl-delay"}
    MAX_THREADS = 4

    def __init__(self, user_agent=DEFAULT_USER_AGENT, thread_pool_size=MAX_THREADS):
        self.user_agent = user_agent
        self.thread_pool_size = thread_pool_size
        self.cached_robots = {}

    def fetch_robots(self, base_url):
        """
        Fetches the robots.txt file from a given base URL.
        Caches the content for reuse.
        """
        if base_url in self.cached_robots:
            logging.info(f"Robots.txt cached for {base_url}")
            return self.cached_robots[base_url]

        robots_url = urljoin(base_url.rstrip("/") + "/", "robots.txt")
        try:
            response = requests.get(robots_url, timeout=10)
            if response.status_code == 200:
                logging.info(f"Fetched robots.txt for {base_url}")
                content = response.text
                self.cached_robots[base_url] = content
                return content
            else:
                logging.warning(f"Failed to fetch robots.txt for {base_url} (Status: {response.status_code})")
        except requests.RequestException as e:
            logging.error(f"Error fetching robots.txt for {base_url}: {e}")
        return None

    def parse_robots(self, base_url):
        """
        Parses the robots.txt file and extracts directives for the specified user-agent.
        """
        content = self.fetch_robots(base_url)
        if not content:
            return {}

        directives = {}
        user_agent_block = False
        current_user_agent = None

        for line in content.splitlines():
            # Remove comments and whitespace
            line = re.sub(r"#.*$", "", line).strip()
            if not line:
                continue

            # Match User-agent
            user_agent_match = re.match(r"(?i)^User-agent:\s*(.*)$", line)
            if user_agent_match:
                current_user_agent = user_agent_match.group(1).strip()
                user_agent_block = (
                    current_user_agent == self.user_agent or current_user_agent == self.DEFAULT_USER_AGENT
                )
                continue

            # Match Allow/Disallow/Crawl-delay
            directive_match = re.match(r"(?i)^(Allow|Disallow|Crawl-delay):\s*(.*)$", line)
            if directive_match and user_agent_block:
                directive, value = directive_match.groups()
                directive = directive.lower()
                if directive in self.ALLOWED_DIRECTIVES:
                    directives.setdefault(directive, []).append(value.strip())

        logging.info(f"Parsed robots.txt directives for {base_url}: {directives}")
        return directives

    def is_allowed(self, base_url, path):
        """
        Checks if the given path is allowed to be crawled based on the robots.txt directives.
        """
        directives = self.parse_robots(base_url)
        if not directives:
            return True

        path = path.lstrip("/")  # Normalize path
        for disallowed in directives.get("disallow", []):
            if re.match(f"^{re.escape(disallowed)}", path):
                return False

        for allowed in directives.get("allow", []):
            if re.match(f"^{re.escape(allowed)}", path):
                return True

        return True

    def batch_process(self, urls):
        """
        Processes multiple URLs in parallel to determine their crawl permissions.
        """
        def process_url(url):
            base_url, path = self._split_url(url)
            return url, self.is_allowed(base_url, path)

        with ThreadPool(min(len(urls), self.thread_pool_size)) as pool:
            results = pool.map(process_url, urls)

        return dict(results)

    def _split_url(self, url):
        """
        Splits a URL into base URL and path.
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/"
        return base_url, path
