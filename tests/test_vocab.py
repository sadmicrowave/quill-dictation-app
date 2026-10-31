"""Unit tests for Vocabulary — no workbook or network needed."""
import unittest
from quill.parser.vocab import Vocabulary

FIXTURE = {
    "Brand":     ["Nike", "Adidas", "The North Face", "Levi's"],
    "Size":      ["XS", "S", "M", "L", "XL"],
    "Color":     ["Black", "White", "Red", "Navy Blue"],
    "Condition": ["New", "Good", "Fair", "Poor"],
}

class TestLoad(unittest.TestCase):
    def setUp(self):
        self.v = Vocabulary()
        self.v.load(FIXTURE)
    def test_len(self):
        self.assertEqual(len(self.v), sum(len(x) for x in FIXTURE.values()))
    def test_columns(self):
        self.assertEqual(set(self.v.columns()), set(FIXTURE.keys()))
    def test_values_for_known(self):
        self.assertIn("Nike", self.v.values_for("Brand"))
    def test_values_for_unknown(self):
        self.assertEqual(self.v.values_for("Nope"), [])

class TestMatch(unittest.TestCase):
    def setUp(self):
        self.v = Vocabulary()
        self.v.load(FIXTURE)
    def test_exact_case_insensitive(self):
        e = self.v.match("nike")
        self.assertIsNotNone(e)
        self.assertEqual(e.canonical, "Nike")
    def test_multiword(self):
        e = self.v.match("the north face")
        self.assertIsNotNone(e)
        self.assertEqual(e.canonical, "The North Face")
    def test_column_assigned(self):
        e = self.v.match("black")
        self.assertIsNotNone(e)
        self.assertEqual(e.column, "Color")
    def test_garbage_returns_none(self):
        self.assertIsNone(self.v.match("xyzzy123"))

class TestAdd(unittest.TestCase):
    def setUp(self):
        self.v = Vocabulary()
        self.v.load(FIXTURE)
    def test_add_existing_column(self):
        before = len(self.v)
        self.v.add("Brand", "Patagonia")
        self.assertEqual(len(self.v), before + 1)
        self.assertIn("Patagonia", self.v.values_for("Brand"))
    def test_add_new_column(self):
        self.v.add("Material", "Cotton")
        self.assertIn("Material", self.v.columns())

if __name__ == "__main__":
    unittest.main()


class TestFieldWordsAndMatching(unittest.TestCase):
    def setUp(self):
        self.v = Vocabulary()
        self.v.load(FIXTURE, headers=["Brand", "Purchase Price", "Notes"])

    def test_list_columns_and_headers_are_field_words(self):
        self.assertEqual(self.v.field_at(["brand"], 0), ("Brand", 1))
        self.assertEqual(self.v.field_at(["purchase", "price"], 0), ("Purchase Price", 2))
        self.assertIsNone(self.v.field_at(["nike"], 0))

    def test_headers_without_lists_are_not_list_columns(self):
        self.assertFalse(self.v.is_list_column("Notes"))
        self.assertTrue(self.v.is_list_column("Brand"))

    def test_matches_at_optional_leading_the(self):
        hits = self.v.matches_at(["north", "face"], 0)
        self.assertEqual(hits, [("Brand", "The North Face", 2)])

    def test_matches_at_possessive_spoken_form(self):
        self.assertEqual(self.v.matches_at(["levis"], 0), [("Brand", "Levi's", 1)])

    def test_matches_at_offset(self):
        self.assertEqual(self.v.matches_at(["x", "nike"], 1)[0][1], "Nike")

    def test_fuzzy_close_spelling(self):
        self.assertEqual(self.v.fuzzy("adidass"), ("Brand", "Adidas"))

    def test_fuzzy_short_words_must_be_exact(self):
        self.assertIsNone(self.v.fuzzy("nik"))

    def test_fuzzy_far_miss(self):
        self.assertIsNone(self.v.fuzzy("zebra"))

    def test_add_is_idempotent_and_case_insensitive(self):
        before = len(self.v)
        self.v.add("Brand", "nike")
        self.assertEqual(len(self.v), before)

    def test_add_registers_new_column_as_field_word(self):
        self.v.add("Material", "Cotton")
        self.assertEqual(self.v.field_at(["material"], 0), ("Material", 1))

    def test_reload_clears_fields(self):
        self.v.load({"Only": ["x"]})
        self.assertIsNone(self.v.field_at(["brand"], 0))


class TestTypeCheckedColumns(unittest.TestCase):
    def setUp(self):
        from quill.parser.vocab import Vocabulary
        self.v = Vocabulary()
        self.v.load({"Color": ["Black", "Navy"], "Year": ["1990", "2001", "2010"], "Acquired": ["2024-01-05", "2025-03-09"],
                     "Era": ["1980s", "1990s"], "Price": ["$5", "$12.50"]}, [])

    def test_columns_are_read_as_number_date_or_text(self):
        kinds = {c: self.v.column_kind(c) for c in self.v.columns()}
        self.assertEqual(kinds, {"Color": "text", "Year": "number", "Acquired": "date", "Era": "text", "Price": "number"})

    def test_a_word_is_never_offered_a_number_or_date_column(self):
        self.assertEqual(self.v.columns_for("teal"), ["Color", "Era"])

    def test_numbers_and_dates_only_go_to_matching_columns_and_to_text_lists(self):
        self.assertEqual(self.v.columns_for("1995"), ["Color", "Year", "Era", "Price"])
        self.assertEqual(self.v.columns_for("2024-06-01"), ["Color", "Acquired", "Era"])
        self.assertEqual(self.v.columns_for("thirty five"), ["Color", "Year", "Era", "Price"])

    def test_the_terms_sorting_window_offers_only_those_columns(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from quill.ui.sorting_window import TermRow
        row = TermRow((None, "teal"), self.v, lambda *a: None)
        offered = [row.combo.itemData(i) for i in range(row.combo.count())]
        self.assertEqual(offered, [None, "Color", "Era"])
        self.assertIn("Color", row._spoken_hint())
        self.assertNotIn("Year", row._spoken_hint())
