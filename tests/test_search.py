"""Spoken search: parsing, filtering through the bridge, and clearing (domain-free)."""
import pathlib
import tempfile
import unittest

import openpyxl

from quill.bridge.filters import ColumnFilter
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import Controller
from quill.parser.vocab import Vocabulary
from quill.search import parse_search

LISTS = {
    "Color": ["Black", "White", "Navy Blue"],
    "Type": ["Blouse", "Skirt", "T-Shirt", "Peace Lily"],
    "Size": ["S", "M", "L", "10"],
}
HEADERS = ["Item", "Color", "Type", "Size", "Purchase Price", "Sale Price", "Notes"]


def vocab():
    v = Vocabulary()
    v.load(LISTS, HEADERS)
    return v


def q(text, numeric=("Purchase Price", "Sale Price")):
    return parse_search(text, vocab(), list(numeric))


def described(query):
    return sorted(f.describe() for f in query.filters)


class TestParseSearch(unittest.TestCase):
    def test_the_headline_example(self):
        query = q("black blouses under 50")
        self.assertEqual(described(query),
                         ["Color = Black", "Purchase Price < 50", "Type = Blouse"])

    def test_plural_matching(self):
        self.assertEqual(described(q("skirts")), ["Type = Skirt"])
        self.assertEqual(described(q("t shirts")), ["Type = T-Shirt"])
        self.assertEqual(described(q("peace lilies")), ["Type = Peace Lily"])

    def test_multiple_values_same_column_are_or(self):
        query = q("black or navy blue skirts")
        self.assertEqual(query.filters[0].values, ["Black", "Navy Blue"])

    def test_comparator_phrases(self):
        cases = {
            "less than 20": "<", "below 20": "<", "at most 20": "<=", "up to 20": "<=",
            "over 20": ">", "more than 20": ">", "at least 20": ">=", "exactly 20": "=",
        }
        for phrase, op in cases.items():
            with self.subTest(phrase):
                self.assertEqual(q(phrase).filters[0].comparisons, [(op, 20.0)])

    def test_spoken_number(self):
        self.assertEqual(q("under fifty").filters[0].comparisons, [("<", 50.0)])

    def test_two_bounds_on_one_column(self):
        query = q("purchase price over 20 under 50")
        self.assertEqual(query.filters[0].comparisons, [(">", 20.0), ("<", 50.0)])

    def test_named_column_wins(self):
        query = q("sale price under 30")
        self.assertEqual(described(query), ["Sale Price < 30"])
        self.assertEqual(query.assumptions, [])

    def test_default_numeric_column_is_first_money_column_with_note(self):
        query = q("under 50")
        self.assertEqual(described(query), ["Purchase Price < 50"])
        self.assertIn("Sale Price", query.assumptions[0])

    def test_single_numeric_column_needs_no_note(self):
        query = q("under 50", numeric=("Purchase Price",))
        v = Vocabulary()
        v.load(LISTS, ["Item", "Color", "Type", "Size", "Purchase Price"])
        query = parse_search("under 50", v, ["Purchase Price"])
        self.assertEqual(query.assumptions, [])

    def test_no_numeric_column_is_a_problem(self):
        v = Vocabulary()
        v.load(LISTS, ["Color", "Type"])
        query = parse_search("under 50", v, [])
        self.assertEqual(query.filters, [])
        self.assertTrue(query.problems)

    def test_comparator_without_number_is_unmatched(self):
        self.assertEqual(q("black under").unmatched, ["under"])

    def test_numeric_header_without_data_is_found_by_money_word(self):
        self.assertEqual(described(q("under 9", numeric=())), ["Purchase Price < 9"])

    def test_field_word_prefers_that_column_for_ambiguous_value(self):
        v = Vocabulary()
        v.load({"A": ["Red"], "B": ["Red"]}, ["A", "B"])
        self.assertEqual(parse_search("b red", v, []).filters[0].column, "B")
        query = parse_search("red", v, [])
        self.assertEqual(query.filters[0].column, "A")
        self.assertTrue(query.assumptions)

    def test_unknown_words_reported_filler_ignored(self):
        query = q("the black zorblax blouses")
        self.assertEqual(query.unmatched, ["zorblax"])
        self.assertEqual(len(query.filters), 2)

    def test_empty(self):
        self.assertEqual(q("").filters, [])


class TestColumnFilter(unittest.TestCase):
    def test_values_case_insensitive(self):
        f = ColumnFilter("Color", values=["Black"])
        self.assertTrue(f.matches(" black "))
        self.assertFalse(f.matches("white"))
        self.assertFalse(f.matches(None))

    def test_comparisons(self):
        f = ColumnFilter("P", comparisons=[(">=", 10), ("<", 20)])
        self.assertTrue(f.matches(10))
        self.assertFalse(f.matches(20))
        self.assertFalse(f.matches("15"))      # text is not a number
        self.assertFalse(f.matches(True))

    def test_empty_filter_matches_everything(self):
        self.assertTrue(ColumnFilter("X").matches("anything"))


def make_book(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock"
    ws.append(HEADERS)
    rows = [
        ("a", "Black", "Blouse", "M", 30, 45, ""),
        ("b", "Black", "Blouse", "L", 80, 99, ""),
        ("c", "White", "Blouse", "M", 20, 25, ""),
        ("d", "Black", "Skirt", "S", 10, 15, ""),
        ("e", "Black", "Blouse", "S", 49.5, 60, ""),
    ]
    for r in rows:
        ws.append(r)
    from openpyxl.worksheet.datavalidation import DataValidation
    cfg = wb.create_sheet("Config")
    cfg.append(["Color", "Type"])
    for c, t in zip(["Black", "White", "Navy Blue"], ["Blouse", "Skirt", "T-Shirt"]):
        cfg.append([c, t])
    for col, ref in (("B", "Config!$A$2:$A$4"), ("C", "Config!$B$2:$B$4")):
        dv = DataValidation(type="list", formula1="=" + ref)
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}50")
    wb.save(path)
    return path


class SearchCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.path = make_book(self.dir / "stock.xlsx")
        self.events = []
        self.ctl = Controller(XlsxBridge(self.path), Settings.defaults(), None,
                              on_event=self.events.append)
        self.ctl.connect()
        self.ctl.handle_transcript("start listening")

    def tearDown(self):
        self._tmp.cleanup()

    def say(self, text):
        self.events.clear()
        self.ctl.handle_transcript(text)
        return self.events[-1]

    def hidden_rows(self):
        ws = openpyxl.load_workbook(self.path)["Stock"]
        return sorted(r for r, d in ws.row_dimensions.items() if d.hidden)


class TestSearchEndToEnd(SearchCase):
    def test_numeric_columns_detected_from_data(self):
        self.assertEqual(self.ctl.bridge.numeric_columns(), ["Purchase Price", "Sale Price"])

    def test_headline_search_filters_sheet(self):
        event = self.say("search for black blouses under 50")
        self.assertEqual(event.kind, "searched")
        self.assertIn("Color = Black", event.detail)
        self.assertIn("Type = Blouse", event.detail)
        self.assertIn("Purchase Price < 50", event.detail)
        self.assertIn("2 rows", event.detail)        # rows a and e
        self.assertEqual(self.hidden_rows(), [3, 4, 5])   # b, c, d hidden
        wb = openpyxl.load_workbook(self.path)
        self.assertEqual(wb["Stock"].auto_filter.ref, "A1:G6")

    def test_clear_search_unhides_and_reports_position(self):
        self.say("search for skirts")
        event = self.say("clear search")
        self.assertEqual(event.kind, "cleared")
        self.assertEqual(self.hidden_rows(), [])

    def test_clear_returns_cursor_to_where_user_was(self):
        grid = self.ctl.bridge._grid
        grid.set_cursor("Stock", 5, 3)
        self.say("search for skirts")
        self.assertEqual(grid.get_cursor("Stock"), (2, 1))      # top of the results
        self.say("clear search")
        self.assertEqual(grid.get_cursor("Stock"), (5, 3))

    def test_second_search_keeps_the_original_position(self):
        grid = self.ctl.bridge._grid
        grid.set_cursor("Stock", 4, 2)
        self.say("search for skirts")
        self.say("search for white")
        self.say("clear search")
        self.assertEqual(grid.get_cursor("Stock"), (4, 2))

    def test_new_search_replaces_old_filters(self):
        self.say("search for skirts")
        self.say("search for white")
        self.assertEqual(self.hidden_rows(), [2, 3, 5, 6])

    def test_clear_with_no_search(self):
        event = self.say("clear search")
        self.assertEqual((event.kind, event.detail), ("ignored", "No search is active"))

    def test_nothing_recognised(self):
        event = self.say("search for zorblax")
        self.assertEqual(event.kind, "unsure")
        self.assertEqual(self.hidden_rows(), [])

    def test_empty_search_prompts(self):
        event = self.say("search for")
        self.assertEqual(event.kind, "ignored")
        self.assertIn("Say what to search for", event.detail)

    def test_unrecognised_words_are_mentioned(self):
        self.assertIn("zorblax", self.say("search for black zorblax").detail)

    def test_search_ignored_while_stopped(self):
        self.ctl.handle_transcript("stop listening")
        event = self.say("search for skirts")
        self.assertEqual(event.kind, "ignored")

    def test_default_money_column_assumption_is_reported(self):
        self.assertIn("Sale Price", self.say("search for under 50").detail)

    def test_bridge_error_becomes_error_event(self):
        flt = ColumnFilter("Nope", values=["x"])
        from quill.bridge.base import BridgeError
        with self.assertRaises(BridgeError):
            self.ctl.bridge.apply_filters("Stock", [flt])

    def test_filter_on_unknown_sheet(self):
        from quill.bridge.base import BridgeError
        with self.assertRaises(BridgeError):
            self.ctl.bridge.apply_filters("Ghost", [])

    def test_shipped_defaults_include_clear_search(self):
        s = Settings.defaults()
        self.assertEqual(s.keywords["clear search"].name, "CLEAR_SEARCH")
        self.assertEqual(Settings.validate_keywords(list(s.keywords.items())), [])


if __name__ == "__main__":
    unittest.main()
