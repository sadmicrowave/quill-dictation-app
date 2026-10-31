"""Spoken dates: what the parser understands, and which date column the value goes into."""
import datetime as dt
import pathlib
import tempfile
import unittest

import openpyxl

from quill.bridge.xlsx_bridge import XlsxBridge
from quill.parser.numbers import parse_date, parse_ordinal, parse_year
from quill.parser.phrase_parser import parse
from quill.parser.tokens import tokenize
from quill.parser.vocab import Vocabulary

TODAY = dt.date(2026, 10, 31)          # a Saturday


def date_of(text, today=TODAY):
    tokens = tokenize(text)
    value, used = parse_date(tokens, 0, today)
    return value, used == len(tokens)


class TestSpokenDates(unittest.TestCase):
    def test_relative_days(self):
        cases = {"today": TODAY, "tonight": TODAY, "yesterday": dt.date(2026, 10, 30),
                 "tomorrow": dt.date(2026, 11, 1), "day before yesterday": dt.date(2026, 10, 29),
                 "day after tomorrow": dt.date(2026, 11, 2), "yesterday morning": dt.date(2026, 10, 30)}
        for text, expected in cases.items():
            self.assertEqual(date_of(text), (expected, True), text)

    def test_amounts_of_time_ago(self):
        cases = {"three days ago": dt.date(2026, 10, 28), "a week ago": dt.date(2026, 10, 24),
                 "two weeks ago": dt.date(2026, 10, 17), "a month ago": dt.date(2026, 9, 30),
                 "six months ago": dt.date(2026, 4, 30), "a year ago": dt.date(2025, 10, 31),
                 "a couple of days ago": dt.date(2026, 10, 29), "an hour ago": None}
        for text, expected in cases.items():
            self.assertEqual(date_of(text)[0], expected, text)

    def test_month_ends_are_trimmed_not_rejected(self):
        self.assertEqual(date_of("a month ago", dt.date(2026, 3, 31))[0], dt.date(2026, 2, 28))
        self.assertEqual(date_of("a year ago", dt.date(2024, 2, 29))[0], dt.date(2023, 2, 28))

    def test_weekdays(self):
        cases = {"friday": dt.date(2026, 10, 30), "saturday": TODAY, "last saturday": dt.date(2026, 10, 24),
                 "last friday": dt.date(2026, 10, 30), "next monday": dt.date(2026, 11, 2),
                 "this friday": dt.date(2026, 11, 6), "last week": dt.date(2026, 10, 24),
                 "next week": dt.date(2026, 11, 7), "last month": dt.date(2026, 9, 30), "last year": dt.date(2025, 10, 31)}
        for text, expected in cases.items():
            self.assertEqual(date_of(text), (expected, True), text)

    def test_calendar_dates_in_either_order(self):
        cases = {"october thirty": dt.date(2026, 10, 30), "march 3rd 2026": dt.date(2026, 3, 3),
                 "march third twenty twenty four": dt.date(2024, 3, 3), "3 march 2026": dt.date(2026, 3, 3),
                 "twenty first of june twenty twenty five": dt.date(2025, 6, 21),
                 "fourth of july nineteen ninety nine": dt.date(1999, 7, 4),
                 "january first two thousand and five": dt.date(2005, 1, 1)}
        for text, expected in cases.items():
            self.assertEqual(date_of(text), (expected, True), text)

    def test_a_month_and_day_without_a_year_is_this_year_or_last_if_far_ahead(self):
        self.assertEqual(date_of("march 3")[0], dt.date(2026, 3, 3))
        self.assertEqual(date_of("december 25")[0], dt.date(2025, 12, 25))        # eight weeks ahead: last year's
        self.assertEqual(date_of("november 15")[0], dt.date(2026, 11, 15))        # two weeks ahead: coming up

    def test_things_that_only_look_like_dates_are_not(self):
        for text in ("may", "march", "february thirty", "second", "last", "this", "a", "an hour ago", "twenty"):
            self.assertIsNone(date_of(text)[0], text)

    def test_ordinals_and_years(self):
        self.assertEqual(parse_ordinal(["twenty", "first"], 0), (21, 2))
        self.assertEqual(parse_ordinal(["3rd"], 0), (3, 1))
        self.assertEqual(parse_ordinal(["32"], 0), (None, 0))
        self.assertEqual(parse_year(["twenty", "twenty", "six"], 0), (2026, 3))
        self.assertEqual(parse_year(["nineteen", "ninety"], 0), (1990, 2))
        self.assertEqual(parse_year(["2026"], 0), (2026, 1))


class TestWhichColumnTheDateGoesIn(unittest.TestCase):
    """The choice comes from the spreadsheet's own headers, never from a built-in list of verbs for any subject."""

    def setUp(self):
        self.v = Vocabulary()
        self.v.load({"Species": ["Humpback", "Orca"]}, ["Observation Date", "Departure Date", "Notes"])
        self.v.date_columns = ["Observation Date", "Departure Date"]

    def parse(self, text):
        return parse(text, self.v, TODAY)

    def test_a_word_that_is_a_form_of_a_header_word_picks_that_column(self):
        self.assertIn("Departure Date", self.parse("orca departed yesterday").updates)
        self.assertIn("Observation Date", self.parse("orca observed friday").updates)
        self.assertEqual(self.parse("humpback departed last friday").updates["Departure Date"], dt.date(2026, 10, 30))

    def test_the_real_date_is_stored_not_the_words(self):
        self.assertEqual(self.parse("orca observed three weeks ago").updates["Observation Date"], dt.date(2026, 10, 10))

    def test_words_with_no_link_to_any_header_fall_back_to_sheet_order_and_say_so(self):
        result = self.parse("orca spotted yesterday")
        self.assertEqual(result.updates["Observation Date"], dt.date(2026, 10, 30))
        self.assertTrue(any("Observation Date" in note and "Departure Date" in note for note in result.assumptions))

    def test_a_second_bare_date_goes_to_the_next_empty_date_column(self):
        result = self.parse("orca yesterday today")
        self.assertEqual(result.updates["Observation Date"], dt.date(2026, 10, 30))
        self.assertEqual(result.updates["Departure Date"], TODAY)

    def test_both_dates_in_one_breath(self):
        result = self.parse("orca observed last friday and departed yesterday")
        self.assertEqual(result.updates["Observation Date"], dt.date(2026, 10, 30))
        self.assertEqual(result.updates["Departure Date"], dt.date(2026, 10, 30))

    def test_naming_the_column_still_works_and_beats_any_nearby_word(self):
        result = self.parse("orca departed observation date yesterday")
        self.assertEqual(result.updates["Observation Date"], dt.date(2026, 10, 30))

    def test_nothing_about_buying_or_selling_is_built_in(self):
        v = Vocabulary()
        v.load({}, ["Purchase Date", "Sale Date"])
        v.date_columns = ["Purchase Date", "Sale Date"]
        result = parse("it sold yesterday", v, TODAY)
        self.assertEqual(list(result.updates), ["Purchase Date"])           # "sold" has no link to "Sale": sheet order
        result = parse("it purchased yesterday", v, TODAY)
        self.assertEqual(list(result.updates), ["Purchase Date"])           # "purchased" is a form of "Purchase"
        result = parse("it was on sale yesterday", v, TODAY)
        self.assertEqual(list(result.updates), ["Sale Date"])               # the header's own word

    def test_the_words_of_a_date_are_never_sorted_as_new_values(self):
        self.assertEqual(self.parse("orca observed yesterday morning").candidates, [])

    def test_with_no_date_column_in_the_sheet_the_words_are_skipped_not_sorted(self):
        self.v.date_columns = []
        result = self.parse("orca observed yesterday")
        self.assertEqual(result.candidates, [])
        self.assertEqual(list(result.updates), ["Species"])

    def test_the_spans_cover_the_date_words(self):
        result = self.parse("orca observed three weeks ago")
        self.assertIn((2, 5, "Observation Date"), result.spans)


class TestFindingDateColumns(unittest.TestCase):
    def test_columns_of_dates_and_empty_columns_headed_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "a.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Item", "Bought", "Sale Date", "Price"])
            ws.append(["Fern", dt.datetime(2026, 1, 5), None, 5])
            ws.append(["Palm", dt.datetime(2026, 2, 6), None, 8])
            wb.save(path)
            bridge = XlsxBridge(path)
            bridge.connect()
            self.assertEqual(bridge.date_columns(), ["Bought", "Sale Date"])


if __name__ == "__main__":
    unittest.main()


class TestEndToEnd(unittest.TestCase):
    def test_a_spoken_date_becomes_a_real_date_in_the_sheet(self):
        from quill.config.settings import Settings
        from quill.controller import Controller
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "a.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Inventory"
            ws.append(["Item", "Purchase Date", "Sale Date"])
            ws.append(["Fern", dt.datetime(2026, 1, 5), None])
            wb.save(path)
            controller = Controller(XlsxBridge(path), Settings.load(pathlib.Path(tmp) / "cfg"), None,
                                    on_event=lambda event: None)
            controller.session.today = lambda: TODAY
            controller.connect()
            for phrase in ("start listening", "item palm bought it yesterday", "next row"):
                controller.handle_transcript(phrase)
            row = openpyxl.load_workbook(path)["Inventory"][3]
            self.assertEqual(row[1].value, dt.datetime(2026, 10, 30))
            self.assertTrue(row[1].is_date)
