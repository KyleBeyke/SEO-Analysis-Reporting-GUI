import re


class StopWords:
    """
    Manages the stop words list for text processing.
    """

    RAW_STOP_WORDS = """
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
    EXTRA_STOP_WORDS = {"another", "also", "be", "is", "was", "were", "do", "does", "did"}

    def __init__(self):
        """
        Initializes and compiles the full stop words list.
        """
        base_stop_words = {
            word.strip().lower()
            for word in self.RAW_STOP_WORDS.split()
            if word.strip()
        }
        self.stop_words = (
            base_stop_words
            .union(self.ADDITIONAL_SINGLE_LETTER_STOP_WORDS)
            .union(self.EXTRA_STOP_WORDS)
        )

        # Always retain "I" if present
        if "i" in self.stop_words:
            self.stop_words.remove("i")

    def is_stop_word(self, word):
        """
        Checks if a word is a stop word.

        :param word: The word to check.
        :return: True if the word is a stop word, False otherwise.
        """
        return word.lower() in self.stop_words

    def filter_stop_words(self, tokens):
        """
        Filters out stop words from a list of tokens.

        :param tokens: List of tokens to filter.
        :return: Filtered list of tokens.
        """
        return [token for token in tokens if not self.is_stop_word(token)]

    def get_stop_words(self):
        """
        Returns the full list of stop words.

        :return: Set of stop words.
        """
        return self.stop_words


# Singleton instance for global usage
stop_words_instance = StopWords()

def get_stop_words_instance():
    """
    Provides a global stop words instance.

    :return: StopWords instance.
    """
    return stop_words_instance
