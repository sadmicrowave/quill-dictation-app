"""Tests for the shared bridge logic via the file-based XlsxBridge (S1, S4)."""
import pathlib
import tempfile
import unittest

import openpyxl

from quill.bridge.base import BridgeError
from quill.bridge.xlsx_bridge import XlsxBridge
from tests.fixtures import HEALTH, LIGHT, POT, SPECIES, make_workbook


class BridgeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = make_workbook(pathlib.Path(self._tmp.name) / "plants.xlsx")
        self.bridge = XlsxBridge(self.path)
        self.bridge.connect()

    def tearDown(self):
        self._tmp.cleanup()

    def reopened(self):
        return openpyxl.load_workbook(self.path)


class TestConnect(BridgeCase):
    def test_name(self):
        self.assertEqual(self.bridge.workbook_name, "plants.xlsx")

    def test_missing_file(self):
        with self.assertRaises(BridgeError):
            XlsxBridge(self.path.with_name("nope.xlsx")).connect()

    def test_no_path(self):
        with self.assertRaises(BridgeError):
            XlsxBridge().connect()

    def test_not_connected(self):
        self.bridge.disconnect()
        with self.assertRaises(BridgeError):
            self.bridge.get_lists()
        with self.assertRaises(BridgeError):
            _ = self.bridge.workbook_name

    def test_reconnect_by_name_uses_known_path(self):
        self.bridge.disconnect()
        self.bridge.connect("plants.xlsx")
        self.assertEqual(self.bridge.workbook_name, "plants.xlsx")

    def test_open_workbooks(self):
        self.assertEqual(self.bridge.open_workbooks(), ["plants.xlsx"])

    def test_active_sheet(self):
        self.assertEqual(self.bridge.active_sheet_name(), "Inventory")


class TestGetLists(BridgeCase):
    def test_values_for_each_source_style(self):
        lists = self.bridge.get_lists()
        self.assertEqual(lists["Species"], SPECIES)        # range with blank slots skipped
        self.assertEqual(lists["Pot Size"], POT)           # inline
        self.assertEqual(lists["Light"], LIGHT)            # named range
        self.assertEqual(lists["Health"], HEALTH)          # same-sheet range
        self.assertEqual(lists["Season"], ["Spring", "Summer"])  # *_list convention

    def test_headers_skip_title_row(self):
        self.assertEqual(
            self.bridge.get_headers(),
            ["Species", "Pot Size", "Light", "Health", "Price", "Acquired", "Notes", "Tag"],
        )

    def test_headers_of_other_sheet(self):
        self.assertEqual(self.bridge.get_headers("Config"), ["Species", "Light", "Season_list"])

    def test_refresh_picks_up_external_edit(self):
        wb = self.reopened()
        wb["Config"]["A6"] = "Palm"
        wb.save(self.path)
        self.bridge.refresh()
        self.assertIn("Palm", self.bridge.get_lists()["Species"])


class TestAppendRow(BridgeCase):
    def test_writes_below_header_into_matching_columns(self):
        row = self.bridge.append_row("Inventory", {"species": "Fern", "Price": 12.5, "Notes": "x"})
        self.assertEqual(row, 4)  # header on 3; row 4 only holds a Tag formula, so it is free
        ws = self.reopened()["Inventory"]
        self.assertEqual((ws["A4"].value, ws["E4"].value, ws["G4"].value), ("Fern", 12.5, "x"))

    def test_second_append_goes_to_next_row(self):
        self.bridge.append_row("Inventory", {"Species": "Fern"})
        self.assertEqual(self.bridge.append_row("Inventory", {"Species": "Cactus"}), 5)

    def test_row_after_data_in_gap_free_sheet(self):
        for name in ("Fern", "Cactus", "Orchid"):
            last = self.bridge.append_row("Inventory", {"Species": name})
        self.assertEqual(last, 6)

    def test_unknown_column_raises_and_writes_nothing(self):
        with self.assertRaises(BridgeError):
            self.bridge.append_row("Inventory", {"Species": "Fern", "Bogus": 1})
        self.assertIsNone(self.reopened()["Inventory"]["A4"].value)

    def test_unknown_sheet_raises(self):
        with self.assertRaises(BridgeError):
            self.bridge.append_row("Nope", {"Species": "Fern"})

    def test_none_values_skipped(self):
        self.bridge.append_row("Inventory", {"Species": "Fern", "Price": None})
        self.assertIsNone(self.reopened()["Inventory"]["E4"].value)

    def test_date_value_written(self):
        import datetime as dt
        self.bridge.append_row("Inventory", {"Acquired": dt.date(2026, 10, 30)})
        self.assertEqual(self.reopened()["Inventory"]["F4"].value.date(), dt.date(2026, 10, 30))


class TestAddToList(BridgeCase):
    def test_range_with_spare_slot(self):
        self.bridge.add_to_list("Species", "Palm")
        self.assertEqual(self.reopened()["Config"]["A6"].value, "Palm")
        self.assertIn("Palm", self.bridge.get_lists()["Species"])

    def test_case_insensitive_duplicate_is_noop(self):
        self.bridge.add_to_list("Species", "FERN")
        self.assertIsNone(self.reopened()["Config"]["A6"].value)

    def test_column_name_lookup_is_forgiving(self):
        self.bridge.add_to_list("  species ", "Palm")
        self.assertIn("Palm", self.bridge.get_lists()["Species"])

    def test_full_fixed_range_raises(self):
        with self.assertRaises(BridgeError) as ctx:
            self.bridge.add_to_list("Light", "Dim")
        self.assertIn("full", str(ctx.exception))

    def test_growable_config_list_extends_downward(self):
        self.bridge.add_to_list("Season", "Autumn")
        self.bridge.add_to_list("Season", "Winter")
        self.assertEqual(
            self.bridge.get_lists()["Season"], ["Spring", "Summer", "Autumn", "Winter"]
        )

    def test_inline_list_is_rewritten(self):
        self.bridge.add_to_list("Pot Size", "Huge")
        self.assertEqual(self.bridge.get_lists()["Pot Size"], POT + ["Huge"])
        dvs = [d.formula1 for d in self.reopened()["Inventory"].data_validations.dataValidation]
        self.assertIn('"Small,Medium,Large,Huge"', dvs)

    def test_inline_list_too_long(self):
        with self.assertRaises(BridgeError):
            self.bridge.add_to_list("Pot Size", "x" * 300)

    def test_unknown_column_raises(self):
        with self.assertRaises(BridgeError):
            self.bridge.add_to_list("Nope", "x")

    def test_blank_value_ignored(self):
        self.bridge.add_to_list("Species", "   ")
        self.assertEqual(self.bridge.get_lists()["Species"], SPECIES)


if __name__ == "__main__":
    unittest.main()
