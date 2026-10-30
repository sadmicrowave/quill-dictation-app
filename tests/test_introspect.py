"""Unit tests for workbook introspection (S1): no Excel needed."""
import pathlib
import tempfile
import unittest

import openpyxl

from quill.bridge.introspect import discover, guess_header_row, parse_reference
from tests.fixtures import HEALTH, LIGHT, SPECIES, make_workbook


class TestParseReference(unittest.TestCase):
    def test_sheet_qualified_absolute(self):
        self.assertEqual(parse_reference("=Config!$A$2:$A$8"), ("Config", (1, 2, 1, 8)))

    def test_quoted_sheet_name(self):
        self.assertEqual(parse_reference("'My Sheet'!$B$1:$B$3"), ("My Sheet", (2, 1, 2, 3)))

    def test_escaped_quote_in_sheet_name(self):
        self.assertEqual(parse_reference("'Bob''s'!A1:A2")[0], "Bob's")

    def test_unqualified(self):
        self.assertEqual(parse_reference("$K$4:$K$6"), (None, (11, 4, 11, 6)))

    def test_not_a_range(self):
        self.assertIsNone(parse_reference("INDIRECT(A1)"))
        self.assertIsNone(parse_reference("LightList"))


class TestGuessHeaderRow(unittest.TestCase):
    def test_title_row_above_headers(self):
        rows = [["Title"], [], ["A", "B", "C"], [1, 2, 3]]
        self.assertEqual(guess_header_row(rows), 3)

    def test_first_row_wins_ties(self):
        self.assertEqual(guess_header_row([["A", "B"], ["C", "D"]]), 1)

    def test_formulas_do_not_count(self):
        self.assertEqual(guess_header_row([["=A1", "=B1"], ["x", "y"]]), 2)

    def test_empty_defaults_to_one(self):
        self.assertEqual(guess_header_row([[], []]), 1)


class TestDiscover(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        path = make_workbook(pathlib.Path(cls._tmp.name) / "plants.xlsx")
        cls.found = discover(openpyxl.load_workbook(path))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_header_row_skips_title(self):
        self.assertEqual(self.found.header_rows["Inventory"], 3)

    def test_all_validated_columns_found(self):
        self.assertEqual(
            set(self.found.sources), {"Species", "Pot Size", "Light", "Health", "Season"}
        )

    def test_range_source(self):
        src = self.found.sources["Species"]
        self.assertEqual((src.sheet, src.col, src.first_row, src.last_row), ("Config", 1, 2, 8))
        self.assertFalse(src.growable)

    def test_inline_source(self):
        src = self.found.sources["Pot Size"]
        self.assertTrue(src.is_inline)
        self.assertEqual(src.items, ("Small", "Medium", "Large"))

    def test_named_range_resolved(self):
        src = self.found.sources["Light"]
        self.assertEqual((src.sheet, src.first_row, src.last_row), ("Config", 2, 4))

    def test_same_sheet_range(self):
        self.assertEqual(self.found.sources["Health"].sheet, "Inventory")

    def test_config_list_suffix_convention(self):
        src = self.found.sources["Season"]
        self.assertTrue(src.growable)
        self.assertEqual((src.sheet, src.col), ("Config", 3))

    def test_non_list_columns_ignored(self):
        self.assertNotIn("Price", self.found.sources)
        self.assertNotIn("Notes", self.found.sources)


class TestDiscoverEdgeCases(unittest.TestCase):
    def _wb(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Data"
        ws["A1"] = "Kind"
        return wb, ws

    def _add(self, ws, formula, rng):
        from openpyxl.worksheet.datavalidation import DataValidation
        dv = DataValidation(type="list", formula1=formula)
        ws.add_data_validation(dv)
        dv.add(rng)

    def test_computed_formula_source_skipped(self):
        wb, ws = self._wb()
        self._add(ws, "=INDIRECT(\"X\")", "A2:A9")
        self.assertEqual(discover(wb).sources, {})

    def test_multi_column_range_skipped(self):
        wb, ws = self._wb()
        self._add(ws, "=$C$1:$D$4", "A2:A9")
        self.assertEqual(discover(wb).sources, {})

    def test_non_list_validation_ignored(self):
        from openpyxl.worksheet.datavalidation import DataValidation
        wb, ws = self._wb()
        dv = DataValidation(type="whole", operator="greaterThan", formula1="0")
        ws.add_data_validation(dv)
        dv.add("A2:A9")
        self.assertEqual(discover(wb).sources, {})

    def test_whole_column_validation_uses_header_row(self):
        wb, ws = self._wb()
        self._add(ws, '"x,y"', "A1:A1048576")
        self.assertIn("Kind", discover(wb).sources)

    def test_same_header_on_many_sheets_first_wins(self):
        wb, ws = self._wb()
        self._add(ws, '"a,b"', "A2:A9")
        ws2 = wb.create_sheet("Other")
        ws2["A1"] = "Kind"
        self._add(ws2, '"c,d"', "A2:A9")
        self.assertEqual(discover(wb).sources["Kind"].items, ("a", "b"))

    def test_table_header_row_used(self):
        from openpyxl.worksheet.table import Table
        wb, ws = self._wb()
        ws["A5"], ws["B5"] = "Kind", "Other"
        ws.add_table(Table(displayName="t", ref="A5:B8"))
        self.assertEqual(discover(wb).header_rows["Data"], 5)


if __name__ == "__main__":
    unittest.main()
