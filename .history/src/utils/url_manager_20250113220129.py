import re
from urllib.parse import urlparse, urlunparse

def validate_url(url):
    """Validate if a URL is properly formatted."""
    parsed = urlparse(url)
    return bool(parsed.netloc and parsed.scheme)

def normalize_url(url):
    """Normalize a URL by stripping query parameters, fragments, and trailing slashes."""
    parsed = urlparse(url)
    normalized = parsed._replace(query="", fragment="")
    return urlunparse(normalized).rstrip('/')

def deduplicate_urls(urls):
    """Deduplicate a list of URLs and ensure they are valid."""
    seen = set()
    unique_urls = []
    for url in urls:
        if validate_url(url):
            normalized = normalize_url(url)
            if normalized not in seen:
                seen.add(normalized)
                unique_urls.append(normalized)
    return unique_urls

def filter_urls(urls, base_domain):
    """Filter URLs to keep only those within the base domain."""
    filtered = []
    for url in urls:
        parsed = urlparse(url)
        if base_domain in parsed.netloc:
            filtered.append(url)
    return filtered

# Example usage (for testing purposes):
if __name__ == "__main__":
    sample_urls = [
        "https://example.com/page?query=123#fragment",
        "https://example.com/page",
        "http://example.com/other-page",
        "https://otherdomain.com/page",
    ]
    print("Validated and Deduplicated URLs:", deduplicate_urls(sample_urls))
    print("Filtered URLs:", filter_urls(sample_urls, "example.com"))
