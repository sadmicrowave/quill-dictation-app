"""Demo mode: a sample workbook and scenarios that fill the screens without speaking."""
import pathlib
import tempfile
import unittest

import openpyxl
from PySide6.QtWidgets import QApplication

from quill.bridge.xlsx_bridge import XlsxBridge
from quill.demo import Demo, demo_requested, make_demo_workbook
from tests.test_app import AppCase

_app = QApplication.instance() or QApplication([])


class TestDemoWorkbook(unittest.TestCase):
    def test_no_drop_down_rule_is_stored_with_a_leading_equals_sign(self):
        """Found on screen: Numbers showed "Unsupported formulas were replaced by the last calculated value" and a blue triangle in every
        cell with a drop-down, because the rules were stored as ``=Config!$A$2:$A$17``; Excel (and Numbers) store ``Config!$A$2:$A$17``."""
        import re
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            path = make_demo_workbook(pathlib.Path(tmp), blank_sheet=True)
            with zipfile.ZipFile(path) as package:
                sheets = [n for n in package.namelist() if n.startswith("xl/worksheets/sheet")]
                rules = [r for n in sheets for r in re.findall(r"<formula1>(.*?)</formula1>", package.read(n).decode())]
        self.assertGreaterEqual(len(rules), 7)
        self.assertFalse([r for r in rules if r.lstrip().startswith("=")], rules)
        self.assertIn("Config!$A$2:$A$17", rules)

    def test_the_lists_are_still_found_without_the_equals_sign(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = XlsxBridge(make_demo_workbook(pathlib.Path(tmp)))
            bridge.connect()
            lists = bridge.get_lists()
        self.assertEqual(lists["Category"], ["T-Shirt", "Jacket", "Sweater", "Hoodie", "Jeans", "Dress"])
        self.assertEqual(lists["Size"], ["XS", "S", "M", "L", "XL", "XXL"])

    def test_workbook_has_rows_and_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_demo_workbook(pathlib.Path(tmp))
            wb = openpyxl.load_workbook(path)
            self.assertEqual(wb.sheetnames, ["Inventory", "Config"])
            self.assertEqual(wb["Inventory"]["A4"].value, "Sweater")
            self.assertIsNone(wb["Inventory"]["A5"].value)
            self.assertEqual(wb["Config"]["A1"].value, "Category")

    def test_flag_and_environment(self):
        self.assertTrue(demo_requested(True))
        self.assertFalse(demo_requested(False))


class TestDemoScenarios(AppCase):
    def setUp(self):
        super().setUp()
        self.demo = Demo(self.quill, delay_ms=0)

    def run_scenario(self, action):
        action()
        for _ in range(20):
            _app.processEvents()
            import time
            time.sleep(0.01)

    def test_menu_lists_every_scenario(self):
        self.assertEqual([label for label, _ in self.demo.scenarios()],
                         ["A Row Being Dictated", "Terms To Sort", "A Saved Row", "Everything", "Promo Story (about 30 s)", "Clip: Dictate", "Clip: Term Helper", "Clip: It Learns", "Clip: Mini View", "Reset"])

    def test_every_scenario_runs(self):
        for _, action in self.demo.scenarios():
            self.run_scenario(action)

    def test_dictating_listens_and_fills_the_row(self):
        self.run_scenario(self.demo.dictating)
        self.assertTrue(self.quill.controller.session.listening)
        self.assertTrue(self.quill.controller.session.record)

    def test_reset_stops_listening(self):
        self.run_scenario(self.demo.dictating)
        self.demo.reset()
        self.assertFalse(self.quill.controller.session.listening)
        self.assertFalse(self.quill.controller.session.record)

    def test_demo_menu_added(self):
        self.quill.window.add_demo_menu(self.demo.scenarios())
        titles = [a.text() for a in self.quill.window.widget.menuBar().actions()]
        self.assertIn("Demo", titles)
