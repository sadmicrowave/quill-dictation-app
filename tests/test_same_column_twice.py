"""Two values for one column go in the same cell, one per line; Start ends voice sorting."""
import datetime as dt
import unittest

from quill.parser.phrase_parser import parse
from quill.parser.vocab import Vocabulary


class TestSameColumnTwice(unittest.TestCase):
    def setUp(self):
        self.vocab = Vocabulary()
        self.vocab.load({"Category": ["Jeans", "Other"], "Color": ["Black"]}, ["Category", "Color"])

    def test_the_second_value_goes_under_the_first_in_the_same_cell(self):
        result = parse("jeans and other stuff", self.vocab, dt.date(2026, 1, 1))
        self.assertEqual(result.updates["Category"], "Jeans\nOther")

    def test_the_same_value_twice_is_one_value(self):
        self.assertEqual(parse("jeans jeans", self.vocab, dt.date(2026, 1, 1)).updates["Category"], "Jeans")

    def test_different_columns_are_unaffected(self):
        result = parse("jeans black", self.vocab, dt.date(2026, 1, 1))
        self.assertEqual(result.updates, {"Category": "Jeans", "Color": "Black"})

    def test_naming_the_column_replaces_the_value(self):
        result = parse("category other", self.vocab, dt.date(2026, 1, 1))
        self.assertEqual(result.updates["Category"], "Other")


from tests.test_sorting import SENTENCE, DemoCase  # noqa: E402


class TestStartListeningEndsVoiceSorting(DemoCase):
    def test_words_after_pressing_start_go_to_the_row_not_the_term_helper(self):
        self.say("start listening", SENTENCE, "next row")
        self.assertTrue(self.ctl.start_voice_sort())               # the Term Helper is answering by voice
        self.say("stop listening")
        self.ctl.set_listening(True)                               # the Start button
        self.assertIsNone(self.ctl.voice_sorter)
        self.say("black jeans")
        self.assertIn("Color", self.ctl.session.record)

    def test_values_heard_in_different_phrases_are_added_too(self):
        self.say("start listening", "jeans", "hoodie")
        self.assertEqual(self.ctl.session.record["Type"], "Jeans\nHoodie")


class TestMultipleValuesInOneCell(unittest.TestCase):
    def test_the_cell_is_written_with_one_value_per_line_and_wrapped(self):
        import pathlib
        import tempfile

        import openpyxl

        from quill.bridge.xlsx_bridge import XlsxBridge
        from tests.test_app import make_workbook
        with tempfile.TemporaryDirectory() as tmp:
            path = make_workbook(pathlib.Path(tmp) / "w.xlsx")
            bridge = XlsxBridge(path)
            bridge.connect()
            row = bridge.append_row(bridge.active_sheet_name(), {"Species": "Fern\nCactus"})
            ws = openpyxl.load_workbook(path)[bridge.active_sheet_name()]
            cell = [c for c in ws[row] if c.value == "Fern\nCactus"][0]
            self.assertTrue(cell.alignment.wrap_text)

    def test_the_grid_shows_a_line_per_value(self):
        from PySide6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])
        from quill.ui.main_window import MainWindow
        w = MainWindow()
        w.setup()
        w.update_current_row({"Category": "Jeans", "Brand": "Nike"})
        single = w.row_table.rowHeight(0)
        w.update_current_row({"Category": "Jeans\nOther", "Brand": "Nike"})
        self.assertGreater(w.row_table.rowHeight(0), single)
        self.assertEqual(w.row_table.rowHeight(1), single)
        self.assertEqual(w.row_table.item(0, 1).text(), "Jeans\nOther")
