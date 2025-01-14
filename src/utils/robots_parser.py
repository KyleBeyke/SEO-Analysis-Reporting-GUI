import logging
import requests
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser


class RobotsParser:
    """
    A utility class to handle robots.txt parsing and rule enforcement.
    """

    def __init__(self, base_url):
        """
        Initialize the RobotsParser with a base URL.

        :param base_url: The base URL of the site to fetch and parse robots.txt.
        """
        self.base_url = base_url
        self.robot_parser = RobotFileParser()
        self.user_agent = "*"
        self.load_robots_txt()

    def load_robots_txt(self):
        """
        Load the robots.txt file from the base URL.
        """
        try:
            robots_url = urljoin(self.base_url, "/robots.txt")
            self.robot_parser.set_url(robots_url)
            self.robot_parser.read()
            logging.info(f"Robots.txt loaded from {robots_url}")
        except Exception as e:
            logging.error(f"Failed to load robots.txt: {e}")

    def is_url_allowed(self, url):
        """
        Check if a URL is allowed to be crawled based on robots.txt.

        :param url: The URL to check.
        :return: True if the URL is allowed, False otherwise.
        """
        try:
            result = self.robot_parser.can_fetch(self.user_agent, url)
            logging.debug(f"URL {url} is {'allowed' if result else 'disallowed'} by robots.txt")
            return result
        except Exception as e:
            logging.error(f"Failed to evaluate robots.txt rules for {url}: {e}")
            return False

    def filter_urls(self, urls):
        """
        Filter a list of URLs to only include those allowed by robots.txt.

        :param urls: List of URLs to filter.
        :return: List of allowed URLs.
        """
        allowed_urls = [url for url in urls if self.is_url_allowed(url)]
        logging.info(f"Filtered {len(urls) - len(allowed_urls)} disallowed URLs out of {len(urls)}")
        return allowed_urls


# Example Usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    base_url = "https://example.com"
    parser = RobotsParser(base_url)

    test_urls = [
        "https://example.com/page1",
        "https://example.com/disallowed-page"
    ]

    allowed_urls = parser.filter_urls(test_urls)
    print("Allowed URLs:", allowed_urls)
