"""A finished row is written to the open sheet only, and a failed save is reported as an error."""
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


class TestAlwaysTheOpenSheet(Case):
    def test_a_row_goes_to_the_sheet_that_is_open_and_never_to_another(self):
        app = self.build()                                                    # the Dashboard is in front
        self.hear(app, "fern large")
        self.hear(app, "next row")
        self.assertEqual(self.rows("Inventory")[-1], ["Fern", "Small"])      # untouched: Quill did not choose it
        self.assertEqual(len(app.window.heard_lines()), 2)                 # the row is kept, nothing lost
        self.assertIn("Could not save the row", app.window.log.toPlainText())

    def test_after_the_user_opens_the_sheet_the_next_row_works(self):
        app = self.build(("2025", "2026"))
        self.hear(app, "fern large")
        self.hear(app, "next row")
        wb = openpyxl.load_workbook(self.path)
        wb.active = wb.sheetnames.index("2026")
        wb.save(self.path)
        app.controller.bridge.connect()
        self.hear(app, "next row")
        self.assertEqual(self.rows("2026")[-1], ["Fern", "Large"])
        self.assertEqual(self.rows("2025")[-1], ["Fern", "Small"])
        self.assertEqual(len(app.window.heard_lines()), 0)

    def test_the_error_says_what_to_do(self):
        app = self.build()
        self.hear(app, "fern large")
        self.hear(app, "next row")
        self.assertIn("Open the sheet you are filling in", app.window.log.toPlainText())


class TestAFailedSaveIsNotReportedAsSaved(Case):
    def test_the_stream_keeps_its_words_and_the_event_is_an_error(self):
        app = self.build()
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
