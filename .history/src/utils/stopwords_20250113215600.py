import re


class StopWords:
    """
    Manages a list of stop words for filtering during text processing.
    """

    def __init__(self):
        """
        Initializes the StopWords instance with a default set of stop words.
        """
        self.base_stop_words = self._load_base_stop_words()
        self.extra_stop_words = {
            "another", "also", "be", "is", "was", "were", "do", "does", "did"
        }
        self.single_letter_exclusions = {"i"}
        self.stop_words = (
            self.base_stop_words.union(self.extra_stop_words) - self.single_letter_exclusions
        )

    def _load_base_stop_words(self):
        """
        Loads the default set of stop words.

        :return: Set of default stop words.
        """
        raw_stop_words = """
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
        return {w.strip().lower() for w in raw_stop_words.split() if w.strip()}

    def is_stop_word(self, word):
        """
        Checks if a word is a stop word.

        :param word: Word to check.
        :return: True if the word is a stop word, False otherwise.
        """
        return word.lower() in self.stop_words

    def add_stop_word(self, word):
        """
        Adds a word to the stop words list.

        :param word: Word to add.
        """
        self.stop_words.add(word.lower())

    def remove_stop_word(self, word):
        """
        Removes a word from the stop words list.

        :param word: Word to remove.
        """
        self.stop_words.discard(word.lower())


# Singleton Instance
_stop_words_instance = StopWords()


def get_stop_words_instance():
    """
    Returns the singleton instance of the StopWords class.

    :return: StopWords instance.
    """
    return _stop_words_instance


# Example Usage
if __name__ == "__main__":
    sw = get_stop_words_instance()
    print("Is 'the' a stop word?", sw.is_stop_word("the"))
    print("Is 'example' a stop word?", sw.is_stop_word("example"))
    sw.add_stop_word("example")
    print("After adding 'example':", sw.is_stop_word("example"))
    sw.remove_stop_word("example")
    print("After removing 'example':", sw.is_stop_word("example"))
