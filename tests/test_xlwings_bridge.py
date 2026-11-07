"""Tests for the live-Excel bridge using a fake xlwings (no Excel required)."""
import pathlib
import tempfile
import unittest

import openpyxl

from quill.bridge.base import BridgeError
from quill.bridge.factory import get_bridge
from quill.bridge.mac_bridge import MacBridge
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.bridge.xlwings_bridge import XlwingsBridge
from tests.fixtures import (FakeApp, FakeBook, FakeSheet, FakeXlwings, SPECIES, make_workbook)


def fake_book_from(path: pathlib.Path, name: str | None = None) -> FakeBook:
    """Mirror a workbook file's cells into a FakeBook (as Excel would hold them)."""
    wb = openpyxl.load_workbook(path)
    sheets = []
    for ws in wb.worksheets:
        fs = FakeSheet(ws.title)
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None:
                    fs.cells[(cell.row, cell.column)] = cell.value
        sheets.append(fs)
    return FakeBook(name or path.name, str(path), sheets)


class TestXlwingsBridge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = make_workbook(pathlib.Path(self._tmp.name) / "plants.xlsx")
        self.book = fake_book_from(self.path)
        self.xw = FakeXlwings([FakeApp([self.book])])
        self.bridge = XlwingsBridge(self.xw)

    def tearDown(self):
        self._tmp.cleanup()

    def test_connect_active_workbook(self):
        self.bridge.connect()
        self.assertEqual(self.bridge.workbook_name, "plants.xlsx")
        self.assertEqual(self.bridge.active_sheet_name(), "Inventory")

    def test_lists_read_from_live_cells(self):
        self.bridge.connect()
        self.book.sheets["Config"].cells[(6, 1)] = "Palm"  # edited in Excel, unsaved
        self.assertIn("Palm", self.bridge.get_lists()["Species"])
        self.assertEqual(self.bridge.get_lists()["Pot Size"], ["Small", "Medium", "Large"])

    def test_headers(self):
        self.bridge.connect()
        self.assertIn("Price", self.bridge.get_headers())

    def test_append_row_writes_live_cells(self):
        self.bridge.connect()
        row = self.bridge.append_row("Inventory", {"Species": "Fern", "Price": 3.0})
        self.assertEqual(row, 4)
        cells = self.book.sheets["Inventory"].cells
        self.assertEqual((cells[(4, 1)], cells[(4, 5)]), ("Fern", 3.0))

    def test_add_to_list_writes_live_cell(self):
        self.bridge.connect()
        self.bridge.add_to_list("Species", "Palm")
        self.assertEqual(self.book.sheets["Config"].cells[(6, 1)], "Palm")

    def test_inline_list_cannot_be_extended_live(self):
        self.bridge.connect()
        with self.assertRaises(BridgeError):
            self.bridge.add_to_list("Pot Size", "Huge")

    def test_open_workbooks_and_pick_by_name(self):
        other = fake_book_from(self.path, name="other.xlsx")
        self.xw.apps.append(FakeApp([other]))
        self.bridge.connect("other.xlsx")
        self.assertEqual(self.bridge.workbook_name, "other.xlsx")
        self.assertEqual(sorted(self.bridge.open_workbooks()), ["other.xlsx", "plants.xlsx"])

    def test_unknown_workbook_name(self):
        with self.assertRaises(BridgeError):
            self.bridge.connect("ghost.xlsx")

    def test_nothing_open(self):
        with self.assertRaises(BridgeError):
            XlwingsBridge(FakeXlwings([FakeApp([])])).connect()

    def test_unsaved_workbook_warns_and_has_no_lists(self):
        self.book.fullname = "Book1"
        self.bridge.connect()
        self.assertIsNotNone(self.bridge.discovery_warning)
        self.assertEqual(self.bridge.get_lists(), {})

    def test_refresh_rereads_structure(self):
        self.bridge.connect()
        wb = openpyxl.load_workbook(self.path)
        wb["Config"]["D1"] = "Pest_list"
        wb.save(self.path)
        self.bridge.refresh()
        self.assertIn("Pest", self.bridge.get_lists())

    def test_excel_unreachable_gives_hint(self):
        class Broken:
            @property
            def apps(self):
                raise RuntimeError("boom")
        bridge = MacBridge(Broken())
        with self.assertRaises(BridgeError) as ctx:
            bridge.connect()
        self.assertIn("Automation", str(ctx.exception))



class TestFactory(unittest.TestCase):
    def test_xlsx_path_gives_file_bridge(self):
        self.assertIsInstance(get_bridge("x.xlsx"), XlsxBridge)

    def test_platform_dispatch(self):
        import sys
        from unittest import mock
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertIsInstance(get_bridge(), MacBridge)
        with mock.patch.object(sys, "platform", "linux"):
            with self.assertRaises(NotImplementedError):
                get_bridge()


if __name__ == "__main__":
    unittest.main()
