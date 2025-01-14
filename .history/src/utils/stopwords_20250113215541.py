import re
import logging


class StopWords:
    """
    A utility class for managing and applying stop words in text processing.
    """

    DEFAULT_STOP_WORDS = """
    a about above actually after again against all almost also although always
    am an and any are as at
    be became become because been before being below between both but by
    can could
    did do does doing down during
    each either else
    few for from further
    had has have having he he'd he'll hence he's her here here's hers herself him himself his
    how how's
    I I'd I'll I'm I've if in into is it it's its itself
    just
    let's
    may maybe me might mine more most must my myself
    neither nor not
    of oh on once only ok or other ought our ours ourselves out over own
    same she she'd she'll she's should so some such
    than that that's the their theirs them themselves then there there's these they they'd they'll they're they've this
    those through to too
    under until up
    very
    was we we'd we'll we're we've were what what's when whenever when's where whereas wherever where's whether which while who whoever who's whose whom why why's will with within would
    yes yet you you'd you'll you're you've your yours yourself yourselves
    """

    ADDITIONAL_SINGLE_LETTER_STOP_WORDS = {"s", "t", "u", "v", "w", "x", "y", "z"}

    def __init__(self):
        """
        Initializes the StopWords instance with a combined set of default and custom stop words.
        """
        self.base_stop_words = self._prepare_stop_words(self.DEFAULT_STOP_WORDS)
        self.extra_stop_words = set()
        self.stop_words = self.base_stop_words.union(self.ADDITIONAL_SINGLE_LETTER_STOP_WORDS)

    @staticmethod
    def _prepare_stop_words(raw_stop_words):
        """
        Converts a raw string of stop words into a set for efficient lookup.

        :param raw_stop_words: A string containing stop words separated by spaces or newlines.
        :return: A set of stop words.
        """
        return set(w.strip().lower() for w in raw_stop_words.split() if w.strip())

    def add_stop_words(self, words):
        """
        Adds custom stop words to the existing set.

        :param words: A list or set of stop words to add.
        """
        if not isinstance(words, (list, set)):
            raise ValueError("Stop words must be provided as a list or set.")
        self.extra_stop_words.update(map(str.lower, words))
        self.stop_words.update(self.extra_stop_words)
        logging.info(f"Added custom stop words: {words}")

    def remove_stop_words(self, words):
        """
        Removes specific words from the stop words set.

        :param words: A list or set of stop words to remove.
        """
        if not isinstance(words, (list, set)):
            raise ValueError("Stop words must be provided as a list or set.")
        for word in words:
            self.stop_words.discard(word.lower())
        logging.info(f"Removed stop words: {words}")

    def is_stop_word(self, word):
        """
        Checks if a word is a stop word.

        :param word: The word to check.
        :return: True if the word is a stop word, False otherwise.
        """
        return word.lower() in self.stop_words

    def filter_stop_words(self, tokens):
        """
        Filters stop words from a list of tokens.

        :param tokens: A list of tokens (words).
        :return: A list of tokens with stop words removed.
        """
        return [token for token in tokens if token.lower() not in self.stop_words]

    def __len__(self):
        """
        Returns the total number of stop words.

        :return: The size of the stop words set.
        """
        return len(self.stop_words)


# Example Usage
if __name__ == "__main__":
    stop_words_manager = StopWords()

    # Add extra stop words
    stop_words_manager.add_stop_words({"example", "test"})

    # Remove a stop word
    stop_words_manager.remove_stop_words({"a"})

    # Check if a word is a stop word
    print("Is 'example' a stop word?", stop_words_manager.is_stop_word("example"))

    # Filter tokens
    sample_tokens = ["This", "is", "an", "example", "sentence", "for", "testing."]
    filtered_tokens = stop_words_manager.filter_stop_words(sample_tokens)
    print("Filtered Tokens:", filtered_tokens)

    # Total stop words
    print("Total Stop Words:", len(stop_words_manager.stop_words))
