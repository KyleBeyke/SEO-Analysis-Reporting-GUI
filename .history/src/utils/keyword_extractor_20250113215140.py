import re
from collections import Counter
from nltk.tokenize import word_tokenize
from nltk.stem import PorterStemmer
from utils.stopwords import get_stop_words_instance


class KeywordExtractor:
    """
    Extracts keywords from text using tokenization, stemming, and stop word filtering.
    """

    def __init__(self):
        """
        Initializes the keyword extractor with a stemmer and stop words instance.
        """
        self.stemmer = PorterStemmer()
        self.stop_words = get_stop_words_instance()

    def preprocess_text(self, text):
        """
        Preprocesses text by removing possessive apostrophes and contractions,
        expanding common contractions, and removing punctuation.

        :param text: Raw text input.
        :return: Preprocessed text.
        """
        # Handle possessive and contractions
        text = re.sub(r"'s\b", "", text)  # Remove possessive 's
        text = re.sub(r"n't\b", " not", text)  # Expand contractions like "don't"
        text = re.sub(r"'re\b", " are", text)
        text = re.sub(r"'ve\b", " have", text)
        text = re.sub(r"'ll\b", " will", text)
        text = re.sub(r"'d\b", " would", text)
        text = re.sub(r"'m\b", " am", text)

        # Remove remaining punctuation except apostrophes
        text = re.sub(r"[^\w\s']", " ", text)
        return text

    def extract_keywords(self, text):
        """
        Extracts keywords from text using stemming and stop word filtering.

        :param text: The text to analyze.
        :return: Counter of keywords with their frequencies.
        """
        preprocessed_text = self.preprocess_text(text)
        tokens = word_tokenize(preprocessed_text)
        keywords = []

        for token in tokens:
            if token == "I":  # Keep "I" capitalized
                keywords.append(token)
                continue

            stemmed = self.stemmer.stem(token.lower())
            if len(stemmed) > 1 or stemmed == "i":  # Skip single letters except "I"
                if not self.stop_words.is_stop_word(stemmed):
                    keywords.append(stemmed)

        return Counter(keywords)

    def top_keywords(self, text, top_n=10):
        """
        Extracts the top N keywords by frequency.

        :param text: The text to analyze.
        :param top_n: The number of top keywords to return.
        :return: List of tuples (keyword, frequency).
        """
        keyword_counts = self.extract_keywords(text)
        return keyword_counts.most_common(top_n)


# Example Usage
if __name__ == "__main__":
    extractor = KeywordExtractor()
    sample_text = """
    This is a sample text with various words. It's designed to test the keyword extraction process.
    Let's see how well it handles contractions, possessive forms, and stop words.
    """

    print("Extracted Keywords:")
    print(extractor.extract_keywords(sample_text))

    print("\nTop 5 Keywords:")
    print(extractor.top_keywords(sample_text, top_n=5))
