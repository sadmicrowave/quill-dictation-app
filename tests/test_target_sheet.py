"""Which sheet a finished row is written to, and what the window does when it cannot be saved."""
import pathlib
import tempfile
import unittest

import openpyxl
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from tests.test_app import FakeListener, FakeSpeaker

_app = QApplication.instance() or QApplication([])


def workbook(path, data_sheets=("Inventory",)):
    """A dashboard in front of one or more data sheets that share a header row."""
    wb = openpyxl.Workbook()
    dash = wb.active
    dash.title = "Dashboard"
    dash.append(["Measure", "Value"])
    for name in data_sheets:
        ws = wb.create_sheet(name)
        ws.append(["Species", "Pot Size"])
        ws.append(["Fern", "Small"])
    config = wb.create_sheet("Config")
    config.append(["Species", "Pot Size"])
    config.append(["Fern", "Small"])
    config.append(["Palm", "Large"])
    from openpyxl.worksheet.datavalidation import DataValidation
    for name in data_sheets:
        ws = wb[name]
        for col, ref in (("A", "Config!$A$2:$A$10"), ("B", "Config!$B$2:$B$10")):
            dv = DataValidation(type="list", formula1=f"={ref}")
            ws.add_data_validation(dv)
            dv.add(f"{col}2:{col}50")
    wb.active = 0
    wb.save(path)


class Case(unittest.TestCase):
    def build(self, data_sheets=("Inventory",)):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = pathlib.Path(tmp.name)
        path = d / "w.xlsx"
        workbook(path, data_sheets)
        self.path = path
        app = QuillApp(_app, Settings.load(d / "cfg"), XlsxBridge(path), listener_factory=lambda *a: FakeListener(*a),
                       model_finder=lambda c: d, speaker=FakeSpeaker(), sound_player=lambda p: None)
        app.start()
        app.controller.handle_transcript("start listening")
        return app

    def hear(self, app, text):
        app._on_phrase_heard(text)
        app.controller.handle_transcript(text)

    def rows(self, sheet):
        return [[c.value for c in row] for row in openpyxl.load_workbook(self.path)[sheet].iter_rows()]


class TestChoosingTheSheet(Case):
    def test_a_dashboard_in_front_does_not_stop_the_row_reaching_the_only_sheet_that_fits(self):
        app = self.build()
        self.hear(app, "fern large")
        self.hear(app, "next row")
        self.assertEqual(self.rows("Inventory")[-1], ["Fern", "Large"])
        self.assertEqual(app.window.row_table.rowCount(), 0)                 # the grid cleared
        self.assertTrue(app.window.last_label.full_text.startswith("Last Saved"))

    def test_with_several_sheets_that_fit_the_user_is_asked_to_open_one_and_nothing_is_lost(self):
        app = self.build(("2025", "2026"))
        self.hear(app, "fern large")
        self.hear(app, "next row")
        self.assertEqual(app.window.row_table.rowCount(), 2)                 # still there, not written anywhere
        self.assertIn("2025, 2026", app.window.footer.text())                # said where the user can see it
        self.assertIn("Open the sheet you are filling in", app.window.footer.text())
        self.assertNotIn("Last Saved", app.window.last_label.full_text)       # and not reported as saved
        self.assertEqual(app.controller.session.committed, 0 + app.controller.session.committed)
        self.assertEqual(self.rows("2025")[-1], ["Fern", "Small"])

    def test_after_the_user_opens_a_sheet_and_the_error_is_gone_the_next_row_works_and_the_footer_clears(self):
        app = self.build(("2025", "2026"))
        self.hear(app, "fern large")
        self.hear(app, "next row")
        wb = openpyxl.load_workbook(self.path)
        wb.active = wb.sheetnames.index("2026")
        wb.save(self.path)
        app.controller.bridge.connect()
        self.hear(app, "next row")
        self.assertEqual(self.rows("2026")[-1], ["Fern", "Large"])
        self.assertEqual(app.window.footer.text(), "")
        self.assertEqual(app.window.row_table.rowCount(), 0)

    def test_the_sheet_the_last_row_went_to_is_used_again_when_the_choice_is_otherwise_open(self):
        app = self.build(("2025", "2026"))
        app.controller._last_sheet = "2026"
        self.hear(app, "fern large")
        self.hear(app, "next row")
        self.assertEqual(self.rows("2026")[-1], ["Fern", "Large"])


class TestAFailedSaveIsNotReportedAsSaved(Case):
    def test_the_stream_keeps_its_words_and_the_event_is_an_error(self):
        app = self.build(("2025", "2026"))
        events = []
        original = app.controller._on_event
        app.controller._on_event = lambda e: (events.append(e.kind), original(e))[1]
        self.hear(app, "fern large")
        self.hear(app, "next row")
        self.assertIn("error", events)
        self.assertNotIn("committed", events)
        self.assertEqual(app.window.stream_text(), "fern large")              # not marked as a finished row


if __name__ == "__main__":
    unittest.main()


class TestSheetsThatAreNotPlacesToAddRows(Case):
    def test_list_sheets_and_formula_summaries_are_left_out(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name) / "w.xlsx"
        workbook(path)
        wb = openpyxl.load_workbook(path)
        summary = wb.create_sheet("Summary")
        summary.append(["Species", "Pot Size"])
        summary.append(["=Inventory!A2", "=Inventory!B2"])
        wb.save(path)
        bridge = XlsxBridge(path)
        bridge.connect()
        self.assertEqual(bridge.sheets_with_columns(["Species", "Pot Size"]), ["Inventory"])

    def test_a_sheet_the_user_has_open_is_always_a_choice(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name) / "w.xlsx"
        workbook(path)
        wb = openpyxl.load_workbook(path)
        wb.active = wb.sheetnames.index("Config")
        wb.save(path)
        bridge = XlsxBridge(path)
        bridge.connect()
        self.assertIn("Config", bridge.sheets_with_columns(["Species", "Pot Size"]))
