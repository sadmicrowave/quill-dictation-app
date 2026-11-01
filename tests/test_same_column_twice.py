"""Two values for one column in a single phrase: the first is kept and the second is reported, not silently lost."""
import datetime as dt
import unittest

from quill.parser.phrase_parser import parse
from quill.parser.vocab import Vocabulary


class TestSameColumnTwice(unittest.TestCase):
    def setUp(self):
        self.vocab = Vocabulary()
        self.vocab.load({"Category": ["Jeans", "Other"], "Color": ["Black"]}, ["Category", "Color"])

    def test_the_first_value_is_kept_and_the_second_is_reported(self):
        result = parse("jeans and other stuff", self.vocab, dt.date(2026, 1, 1))
        self.assertEqual(result.updates["Category"], "Jeans")
        self.assertTrue(any("other" in note and "Jeans" in note for note in result.assumptions))

    def test_different_columns_are_unaffected(self):
        result = parse("jeans black", self.vocab, dt.date(2026, 1, 1))
        self.assertEqual(result.updates, {"Category": "Jeans", "Color": "Black"})

    def test_naming_the_column_still_sets_it(self):
        result = parse("category other", self.vocab, dt.date(2026, 1, 1))
        self.assertEqual(result.updates["Category"], "Other")


from tests.test_sorting import SENTENCE, DemoCase  # noqa: E402


class TestStartListeningEndsVoiceSorting(DemoCase):
    def test_words_after_pressing_start_go_to_the_row_not_the_term_helper(self):
        self.say("start listening", SENTENCE, "next row")
        self.assertTrue(self.ctl.start_voice_sort())               # the Term Helper is answering by voice
        self.say("stop listening")
        self.ctl.set_listening(True)                               # the Start button
        self.assertIsNone(self.ctl.voice_sorter)
        self.say("black jeans")
        self.assertIn("Color", self.ctl.session.record)
