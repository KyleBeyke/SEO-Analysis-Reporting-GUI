import threading
from collections import Counter

class KeywordExtractor:
    """Extract keywords from text using multithreading."""

    def __init__(self, texts):
        self.texts = texts
        self.results = []
        self.lock = threading.Lock()

    def extract_keywords(self, text):
        """Extract keywords from a single text."""
        words = text.split()  # Simplistic tokenization
        keywords = Counter(words).most_common(10)
        with self.lock:
            self.results.append(keywords)

    def extract_all(self):
        """Extract keywords from all texts."""
        threads = []

        for text in self.texts:
            t = threading.Thread(target=self.extract_keywords, args=(text,))
            threads.append(t)
            t.start()

            # Limit active threads to 10
            if len(threads) >= 10:
                for t in threads:
                    t.join()
                threads = []

        for t in threads:
            t.join()
        return self.results
