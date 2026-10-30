"""Parser tests (S2). The fixture is a plant inventory; the parser has no
built-in knowledge of plants, apparel or anything else."""
import datetime as dt
import unittest

from quill.parser.phrase_parser import parse
from quill.parser.vocab import Vocabulary

LISTS = {
    "Species": ["Fern", "Cactus", "Orchid", "Venus Flytrap", "Peace Lily"],
    "Pot Size": ["Small", "Medium", "Large", "10"],
    "Light": ["Low", "Medium", "Bright"],
    "Era": ["1980s", "1990s", "2000s"],
}
HEADERS = ["Species", "Pot Size", "Light", "Era", "Price", "Acquired", "Notes", "Sale Price"]
TODAY = dt.date(2026, 10, 30)


def run(text, lists=LISTS, filled=None):
    vocab = Vocabulary()
    vocab.load(lists, HEADERS)
    return parse(text, vocab, TODAY, filled)


class TestKnownValues(unittest.TestCase):
    def test_values_without_field_words(self):
        self.assertEqual(run("fern bright").updates, {"Species": "Fern", "Light": "Bright"})

    def test_multiword_value(self):
        self.assertEqual(run("venus flytrap").updates, {"Species": "Venus Flytrap"})

    def test_ambiguous_value_goes_to_earlier_column_with_assumption(self):
        result = run("medium")
        self.assertEqual(result.updates, {"Pot Size": "Medium"})
        self.assertEqual(result.assumptions, ["'medium' taken as Pot Size"])

    def test_field_word_disambiguates(self):
        result = run("light medium")
        self.assertEqual(result.updates, {"Light": "Medium"})
        self.assertEqual(result.assumptions, [])

    def test_longest_value_wins(self):
        self.assertEqual(run("peace lily").updates, {"Species": "Peace Lily"})

    def test_filler_words_are_ignored_not_candidates(self):
        result = run("a fern with bright")
        self.assertEqual(result.updates, {"Species": "Fern", "Light": "Bright"})
        self.assertEqual(result.candidates, [])

    def test_numeric_list_value_after_field_word(self):
        self.assertEqual(run("pot size ten").updates, {"Pot Size": "10"})


class TestAmounts(unittest.TestCase):
    def test_digits(self):
        self.assertEqual(run("price 25").updates, {"Price": 25.0})

    def test_spoken_dollars_and_cents(self):
        self.assertEqual(run("price twelve dollars and fifty cents").updates, {"Price": 12.5})

    def test_filler_between_field_and_amount(self):
        self.assertEqual(run("price of 30").updates, {"Price": 30.0})

    def test_two_amount_columns(self):
        self.assertEqual(run("price 10 sale price 15").updates, {"Price": 10.0, "Sale Price": 15.0})

    def test_longest_field_word_wins(self):
        # "sale price" must not be read as "price" plus stray word "sale".
        result = run("sale price 15")
        self.assertEqual(result.updates, {"Sale Price": 15.0})
        self.assertEqual(result.unmatched, [])


class TestDates(unittest.TestCase):
    def test_today(self):
        self.assertEqual(run("acquired today").updates, {"Acquired": TODAY})

    def test_month_day(self):
        self.assertEqual(run("acquired march 3").updates, {"Acquired": dt.date(2026, 3, 3)})


class TestTextColumns(unittest.TestCase):
    def test_notes_run_to_next_field_word(self):
        result = run("notes needs repotting soon price 5")
        self.assertEqual(result.updates, {"Notes": "needs repotting soon", "Price": 5.0})

    def test_notes_may_contain_known_values_and_numbers(self):
        self.assertEqual(run("notes 3 leaves fern").updates, {"Notes": "3 leaves fern"})

    def test_field_word_with_no_value_is_unmatched(self):
        result = run("price")
        self.assertEqual(result.updates, {})
        self.assertEqual(result.unmatched, ["price"])

    def test_free_text_for_non_text_hint_column_without_number(self):
        # A non-list column named without a "notes" hint still takes plain text.
        vocab = Vocabulary()
        vocab.load({}, ["Source"])
        self.assertEqual(parse("source garden center", vocab, TODAY).updates,
                         {"Source": "garden center"})


class TestUnknownValues(unittest.TestCase):
    def test_hinted_unknown_is_certain(self):
        result = run("light dim")
        self.assertEqual(result.updates, {})
        cand = result.candidates[0]
        self.assertEqual((cand.term, cand.column, cand.hinted), ("dim", "Light", True))

    def test_hinted_unknown_multiword(self):
        self.assertEqual(run("species snake plant").candidates[0].term, "snake plant")

    def test_close_spelling_maps_to_known_value(self):
        self.assertEqual(run("species orchd").updates, {"Species": "Orchid"})
        self.assertEqual(run("orchidd").updates, {"Species": "Orchid"})

    def test_unhinted_unknown_guessed_by_shape(self):
        # "2010s" looks like the Era values (digits then letters), and nothing else.
        cand = run("fern 2010s").candidates[0]
        self.assertEqual((cand.term, cand.column, cand.hinted), ("2010s", "Era", False))

    def test_unhinted_word_guessed_by_elimination(self):
        # Only Light is still unfilled once Species, Pot Size and Era are set.
        result = run("fern small 1990s dim")
        cand = result.candidates[0]
        self.assertEqual((cand.term, cand.column, cand.hinted), ("dim", "Light", False))

    def test_unhinted_word_with_several_open_columns_is_not_guessed(self):
        cand = run("zorblax").candidates[0]
        self.assertIsNone(cand.column)

    def test_filled_columns_passed_in_count(self):
        result = run("dim", filled={"Species", "Pot Size", "Era"})
        self.assertEqual(result.candidates[0].column, "Light")

    def test_unknown_run_split_around_fuzzy_match(self):
        result = run("zorblax fernn")
        self.assertEqual(result.updates, {"Species": "Fern"})
        self.assertEqual(result.candidates[0].term, "zorblax")

    def test_numbers_and_common_words_are_not_candidates(self):
        result = run("the 42 and")
        self.assertEqual(result.candidates, [])

    def test_unknown_not_reported_as_unmatched_too(self):
        result = run("zorblax")
        self.assertNotIn("zorblax", result.unmatched)


class TestEdges(unittest.TestCase):
    def test_empty_text(self):
        result = run("")
        self.assertEqual((result.updates, result.candidates), ({}, []))

    def test_no_vocab(self):
        self.assertEqual(parse("anything goes", Vocabulary(), TODAY).updates, {})

    def test_default_today_used_when_omitted(self):
        vocab = Vocabulary()
        vocab.load({}, ["Acquired"])
        self.assertEqual(parse("acquired today", vocab).updates["Acquired"], dt.date.today())


if __name__ == "__main__":
    unittest.main()
