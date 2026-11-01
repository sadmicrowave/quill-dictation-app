"""A .csv file works as a spreadsheet: lists are learned from its own columns, rows are appended, search is off."""
import datetime as dt
import pathlib
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.base import BridgeError
from quill.bridge.csv_bridge import CsvBridge
from quill.bridge.factory import get_bridge
from quill.bridge.filters import ColumnFilter
from quill.config.settings import Settings
from tests.test_app import FakeListener, FakeSpeaker

_app = QApplication.instance() or QApplication([])

PLANTS = ("Species,Pot Size,Price,Acquired,Notes\n"
          "Fern,Small,12.50,2026-10-01,from the market stall by the river bridge on a sunny day\n"
          "Palm,Large,40,2026-10-02,\n"
          "Fern,Large,15,2026-10-03,\n")


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)

    def write(self, text, name="plants.csv"):
        path = self.dir / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def bridge(self, text=PLANTS, name="plants.csv"):
        bridge = CsvBridge(self.write(text, name))
        bridge.connect()
        return bridge


class TestReading(Case):
    def test_the_factory_picks_the_csv_bridge_by_suffix(self):
        self.assertIsInstance(get_bridge(self.write(PLANTS)), CsvBridge)

    def test_the_sheet_is_named_after_the_file(self):
        bridge = self.bridge()
        self.assertEqual(bridge.active_sheet_name(), "plants")
        self.assertEqual(bridge.get_headers(), ["Species", "Pot Size", "Price", "Acquired", "Notes"])

    def test_lists_come_from_the_columns_with_duplicates_removed(self):
        lists = self.bridge().get_lists()
        self.assertEqual(lists["Species"], ["Fern", "Palm"])
        self.assertEqual(lists["Pot Size"], ["Small", "Large"])

    def test_numbers_dates_and_free_text_are_not_lists(self):
        lists = self.bridge().get_lists()
        for column in ("Price", "Acquired", "Notes"):
            self.assertNotIn(column, lists)

    def test_numeric_and_date_columns_are_recognised_from_the_text(self):
        bridge = self.bridge()
        self.assertEqual(bridge.numeric_columns(), ["Price"])
        self.assertEqual(bridge.date_columns(), ["Acquired"])

    def test_a_brand_new_file_has_empty_lists_for_its_text_columns(self):
        bridge = self.bridge("Species,Pot Size,Price,Sale Date\n", "new.csv")
        self.assertEqual(bridge.get_lists(), {"Species": [], "Pot Size": []})      # money and date headings are not lists
        self.assertEqual(bridge.date_columns(), ["Sale Date"])

    def test_other_delimiters_and_quotes_are_understood(self):
        bridge = self.bridge('Species;Pot Size\n"Fern, Boston";Small\nPalm;Small\n', "semi.csv")
        self.assertEqual(bridge.get_lists()["Species"], ["Fern, Boston", "Palm"])

    def test_a_missing_or_huge_file_is_reported(self):
        with self.assertRaises(BridgeError):
            CsvBridge(self.dir / "nope.csv").connect()


class TestWriting(Case):
    def test_a_row_is_appended_and_the_rest_of_the_file_is_untouched(self):
        bridge = self.bridge("Code,Name\n007,Fern\n")
        row = bridge.append_row("plants", {"Name": "Palm"})
        self.assertEqual(row, 3)
        self.assertEqual((self.dir / "plants.csv").read_text(), "Code,Name\n007,Fern\n,Palm\n")     # 007 stays 007

    def test_dates_are_written_the_way_the_file_writes_them(self):
        bridge = self.bridge("Item,Sold\nfern,03/04/2026\n")
        bridge.append_row("plants", {"Item": "palm", "Sold": dt.date(2026, 5, 6)})
        self.assertIn("palm,05/06/2026", (self.dir / "plants.csv").read_text())

    def test_a_taught_value_joins_the_list_and_can_be_taken_back(self):
        bridge = self.bridge()
        bridge.add_to_list("Pot Size", "Medium")
        self.assertEqual(bridge.get_lists()["Pot Size"], ["Small", "Large", "Medium"])
        self.assertTrue(bridge.remove_from_list("Pot Size", "Medium"))
        self.assertNotIn("Medium", bridge.get_lists()["Pot Size"])

    def test_the_list_grows_from_new_rows_too(self):
        bridge = self.bridge()
        bridge.append_row("plants", {"Species": "Cactus"})
        self.assertIn("Cactus", bridge.get_lists()["Species"])

    def test_the_file_keeps_its_delimiter_and_line_endings(self):
        path = self.write("A;B\r\n1;2\r\n", "semi.csv")
        bridge = CsvBridge(path)
        bridge.connect()
        bridge.append_row("semi", {"A": "x", "B": "y"})
        self.assertEqual(path.read_bytes(), b"A;B\r\n1;2\r\nx;y\r\n")

    def test_no_temporary_file_is_left_behind(self):
        self.bridge().append_row("plants", {"Species": "Aloe"})
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["plants.csv"])


class TestSearch(Case):
    def test_search_is_not_available_and_says_why(self):
        bridge = self.bridge()
        with self.assertRaisesRegex(BridgeError, "can't be searched"):
            bridge.apply_filters("plants", [ColumnFilter("Species", values=("Fern",))])
        with self.assertRaises(BridgeError):
            bridge.clear_filters("plants")


class TestInTheApp(Case):
    def make(self, text=PLANTS):
        path = self.write(text)
        app = QuillApp(_app, Settings.load(self.dir / "cfg"), CsvBridge(path), listener_factory=lambda *a: FakeListener(*a),
                       model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None)
        app.start()
        app.controller.handle_transcript("start listening")
        return app

    def test_connects_and_dictates_a_row(self):
        app = self.make()
        self.assertTrue(app.connected)
        app.controller.handle_transcript("fern large")
        app.controller.handle_transcript("next row")
        self.assertIn("Fern,Large", (self.dir / "plants.csv").read_text().splitlines()[-1])

    def test_a_search_is_reported_as_unavailable(self):
        app = self.make()
        app.controller.handle_transcript("search for fern")
        self.assertIn("can't be searched", app.window.log.toPlainText())

    def test_opening_a_csv_file_through_the_menu(self):
        app = self.make()
        other = self.write("Species,Colour\nFern,Green\n", "other.csv")
        self.assertTrue(app.open_workbook_file(other))
        self.assertIsInstance(app.controller.bridge, CsvBridge)
        self.assertEqual(app.controller.bridge.workbook_name, "other.csv")


if __name__ == "__main__":
    unittest.main()
