"""Unit tests for tokenisation, spoken numbers, amounts and dates."""
import datetime as dt
import unittest

from quill.parser.numbers import parse_amount, parse_date, parse_number
from quill.parser.tokens import display_name, tokenize

TODAY = dt.date(2026, 10, 30)


class TestTokenize(unittest.TestCase):
    def test_apostrophes_removed(self):
        self.assertEqual(tokenize("Levi's"), ["levis"])
        self.assertEqual(tokenize("it\u2019s"), ["its"])

    def test_hyphen_splits(self):
        self.assertEqual(tokenize("T-Shirt"), ["t", "shirt"])

    def test_amounts_and_decades_stay_whole(self):
        self.assertEqual(tokenize("$25.50"), ["25.50"])
        self.assertEqual(tokenize("1990s"), ["1990s"])

    def test_unicode_letters(self):
        self.assertEqual(tokenize("Café Crème"), ["café", "crème"])

    def test_empty(self):
        self.assertEqual(tokenize("  ,, "), [])

    def test_display_name(self):
        self.assertEqual(display_name("hugo boss"), "Hugo Boss")


class TestNumber(unittest.TestCase):
    def test_digits(self):
        self.assertEqual(parse_number(["25"], 0), (25.0, 1))
        self.assertEqual(parse_number(["3.5"], 0), (3.5, 1))

    def test_words(self):
        self.assertEqual(parse_number(["twenty", "five"], 0), (25.0, 2))
        self.assertEqual(parse_number(["one", "hundred", "twenty", "three"], 0), (123.0, 4))
        self.assertEqual(parse_number(["two", "thousand", "five"], 0), (2005.0, 3))

    def test_stops_at_non_number(self):
        self.assertEqual(parse_number(["ten", "red"], 0), (10.0, 1))

    def test_none(self):
        self.assertEqual(parse_number(["red"], 0), (None, 0))
        self.assertEqual(parse_number([], 0), (None, 0))


class TestAmount(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_amount(["25"], 0), (25.0, 1))

    def test_dollars(self):
        self.assertEqual(parse_amount(["25", "dollars"], 0), (25.0, 2))

    def test_dollars_and_cents(self):
        self.assertEqual(
            parse_amount(["forty", "two", "dollars", "and", "fifty", "cents"], 0), (42.5, 6)
        )

    def test_dollars_and_without_cents_leaves_and(self):
        self.assertEqual(parse_amount(["five", "dollars", "and", "red"], 0), (5.0, 2))

    def test_cents_only(self):
        self.assertEqual(parse_amount(["50", "cents"], 0), (0.5, 2))

    def test_not_an_amount(self):
        self.assertEqual(parse_amount(["fern"], 0), (None, 0))


class TestDate(unittest.TestCase):
    def test_today_yesterday(self):
        self.assertEqual(parse_date(["today"], 0, TODAY), (TODAY, 1))
        self.assertEqual(parse_date(["yesterday"], 0, TODAY), (dt.date(2026, 10, 29), 1))

    def test_month_day_uses_current_year(self):
        self.assertEqual(parse_date(["march", "3"], 0, TODAY), (dt.date(2026, 3, 3), 2))

    def test_month_day_year(self):
        self.assertEqual(parse_date(["october", "30", "2025"], 0, TODAY),
                         (dt.date(2025, 10, 30), 3))

    def test_ordinal_suffix_and_words(self):
        self.assertEqual(parse_date(["march", "3", "rd"], 0, TODAY), (dt.date(2026, 3, 3), 3))
        self.assertEqual(parse_date(["may", "twenty", "five"], 0, TODAY), (dt.date(2026, 5, 25), 3))

    def test_invalid_day(self):
        self.assertEqual(parse_date(["february", "thirty"], 0, TODAY), (None, 0))

    def test_month_without_day(self):
        self.assertEqual(parse_date(["may"], 0, TODAY), (None, 0))

    def test_not_a_date(self):
        self.assertEqual(parse_date(["fern"], 0, TODAY), (None, 0))
        self.assertEqual(parse_date([], 0, TODAY), (None, 0))


if __name__ == "__main__":
    unittest.main()
