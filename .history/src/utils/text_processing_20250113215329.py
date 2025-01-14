import re
from collections import Counter
from nltk.tokenize import word_tokenize
from nltk.stem import PorterStemmer
from .stopwords import get_stop_words_instance


class TextProcessor:
    """
    A class for text processing, including tokenization, stemming, and keyword extraction.
    """

    def __init__(self):
        """
        Initializes the TextProcessor with a PorterStemmer and a StopWords instance.
        """
        self.stemmer = PorterStemmer()
        self.stop_words = get_stop_words_instance()

    def preprocess_text(self, text):
        """
        Preprocesses text by removing possessive apostrophes, expanding contractions, and normalizing punctuation.

        :param text: Input text.
        :return: Preprocessed text.
        """
        text = re.sub(r"'s\b", "", text)  # Remove possessive 's
        text = re.sub(r"n't\b", " not", text)  # Expand contractions like "don't" to "do not"
        text = re.sub(r"'re\b", " are", text)
        text = re.sub(r"'ve\b", " have", text)
        text = re.sub(r"'ll\b", " will", text)
        text = re.sub(r"'d\b", " would", text)
        text = re.sub(r"'m\b", " am", text)
        text = re.sub(r"[^\w\s']", " ", text)  # Remove all punctuation except apostrophes
        return text

    def tokenize_and_filter(self, text):
        """
        Tokenizes text, removes stop words, and applies stemming.

        :param text: Input text.
        :return: List of processed tokens.
        """
        tokens = word_tokenize(text)
        processed_tokens = []
        total_tokens = 0
        filtered_tokens = 0

        for token in tokens:
            total_tokens += 1
            lower_token = token.lower()

            if not re.match(r"^[a-z]+$", lower_token):  # Skip non-alphabetic tokens
                continue

            stemmed_token = self.stemmer.stem(lower_token)
            if not self.stop_words.is_stop_word(stemmed_token):
                processed_tokens.append(stemmed_token)
            else:
                filtered_tokens += 1

        return processed_tokens, total_tokens, filtered_tokens

    def extract_keywords(self, text):
        """
        Extracts keywords from the text using tokenization and filtering.

        :param text: Input text.
        :return: Counter object of keyword frequencies.
        """
        preprocessed_text = self.preprocess_text(text)
        tokens, _, _ = self.tokenize_and_filter(preprocessed_text)
        return Counter(tokens)

    def summarize_tokens(self, text):
        """
        Provides a summary of tokenization results.

        :param text: Input text.
        :return: Dictionary with token summary data.
        """
        preprocessed_text = self.preprocess_text(text)
        tokens, total, filtered = self.tokenize_and_filter(preprocessed_text)
        return {
            "total_tokens": total,
            "filtered_tokens": filtered,
            "valid_tokens": len(tokens),
            "keywords": Counter(tokens).most_common(10),
        }


# Example Usage
if __name__ == "__main__":
    sample_text = """
    Don't forget that Python's simplicity is its strength. We've done a lot
    to ensure the tool's usability while keeping performance.
    """
    processor = TextProcessor()
    keywords = processor.extract_keywords(sample_text)
    summary = processor.summarize_tokens(sample_text)

    print("Extracted Keywords:", keywords)
    print("Summary:", summary)

