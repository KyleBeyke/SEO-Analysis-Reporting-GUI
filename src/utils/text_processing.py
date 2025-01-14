import re
from collections import Counter
from nltk.tokenize import word_tokenize
from nltk.stem import PorterStemmer

# Define stop words
RAW_STOP_WORDS = """
a about above after again against all am an and any are as at be because been before being below between both but by can could did do does doing down during each few for from further had has have having he her here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only or other our ours ourselves out over own same she should so some such than that the their theirs them themselves then there these they this those through to too under until up very was we were what when where which while who whom why will with you your yours yourself yourselves
"""

ADDITIONAL_SINGLE_LETTER_STOP_WORDS = {"s", "t", "u", "v", "w", "x", "y", "z"}
BASE_STOP_WORDS = set(w.strip().lower() for w in RAW_STOP_WORDS.split() if w.strip())
EXTRA_STOP_WORDS = {"also", "another", "be", "is", "was", "were"}.union(ADDITIONAL_SINGLE_LETTER_STOP_WORDS)
STOP_WORDS = BASE_STOP_WORDS.union(EXTRA_STOP_WORDS)

# Initialize PorterStemmer
stemmer = PorterStemmer()

def tokenize_and_stem(text):
    """Tokenize and stem text content."""
    # Clean contractions and possessives
    text = re.sub(r"'s\b", "", text)
    text = re.sub(r"n't\b", " not", text)
    text = re.sub(r"'re\b", " are", text)
    text = re.sub(r"'ve\b", " have", text)
    text = re.sub(r"'ll\b", " will", text)

    # Remove non-alphanumeric characters
    text = re.sub(r"[^\w\s']", " ", text)

    # Tokenize
    tokens = word_tokenize(text)

    # Filter tokens and apply stemming
    filtered_tokens = [
        stemmer.stem(tok.lower()) for tok in tokens if tok.lower() not in STOP_WORDS and len(tok) > 1
    ]
    return Counter(filtered_tokens)
