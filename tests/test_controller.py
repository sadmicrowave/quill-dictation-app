"""End-to-end dictation against a real workbook file (S4): speech in, cells out."""
import datetime as dt
import pathlib
import tempfile
import unittest

import openpyxl

from quill.bridge.base import BridgeError
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import Controller
from tests.fixtures import make_workbook


class FakeSpeaker:
    def __init__(self):
        self.said = []

    def say(self, text, on_done=None):
        self.said.append(text)
        if on_done:
            on_done()


class ControllerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.path = make_workbook(self.dir / "plants.xlsx")
        self.events = []
        self.speaker = FakeSpeaker()
        self.ctl = Controller(
            XlsxBridge(self.path), Settings.load(self.dir / "cfg"), self.speaker,
            on_event=self.events.append, today=lambda: dt.date(2026, 10, 30),
        )
        self.ctl.connect()

    def tearDown(self):
        self._tmp.cleanup()

    def say(self, *phrases):
        for phrase in phrases:
            self.ctl.handle_transcript(phrase)

    def sheet(self, name="Inventory"):
        return openpyxl.load_workbook(self.path)[name]

    def kinds(self):
        return [e.kind for e in self.events]


class TestDictation(ControllerCase):
    def test_vocabulary_learned_from_workbook(self):
        self.assertIn("Fern", self.ctl.vocab.values_for("Species"))
        self.assertEqual(self.ctl.vocab.field_at(["pot", "size"], 0), ("Pot Size", 2))

    def test_spoken_row_lands_in_cells(self):
        self.say("start listening",
                 "fern small bright price twelve dollars acquired today notes needs water",
                 "next row")
        ws = self.sheet()
        self.assertEqual(
            [ws.cell(4, c).value for c in (1, 2, 3, 5, 7)],
            ["Fern", "Small", "Bright", 12.0, "needs water"],
        )
        self.assertEqual(ws["F4"].value.date(), dt.date(2026, 10, 30))
        committed = [e for e in self.events if e.kind == "committed"][0]
        self.assertEqual(committed.detail, "Row 4")

    def test_two_rows_stack(self):
        self.say("start listening", "fern next row", "cactus next row")
        ws = self.sheet()
        self.assertEqual((ws["A4"].value, ws["A5"].value), ("Fern", "Cactus"))

    def test_nothing_written_while_stopped(self):
        self.say("fern next row")
        self.assertIsNone(self.sheet()["A4"].value)


class TestUnknownValueFlow(ControllerCase):
    def test_yes_writes_value_into_workbook_list(self):
        self.say("start listening", "species snake plant", "next row")
        self.assertIn("confirm", self.kinds())
        self.assertIn("Snake Plant isn't in the Species list", self.speaker.said[0])
        self.say("yes")
        self.assertEqual(self.sheet("Config")["A6"].value, "Snake Plant")
        self.assertIn("Snake Plant", self.ctl.bridge.get_lists()["Species"])

    def test_added_value_is_then_recognised(self):
        self.say("start listening", "species snake plant", "next row", "yes")
        self.say("snake plant", "next row")
        self.assertEqual(self.sheet()["A4"].value, "Snake Plant")

    def test_no_leaves_workbook_untouched(self):
        self.say("start listening", "species snake plant", "next row", "no")
        self.assertIsNone(self.sheet("Config")["A6"].value)

    def test_full_list_reports_error_event(self):
        self.say("start listening", "light dim", "next row", "yes")
        errors = [e for e in self.events if e.kind == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("full", errors[0].detail)

    def test_silent_when_no_speaker(self):
        ctl = Controller(XlsxBridge(self.path), Settings.defaults(), None)
        ctl.connect()
        ctl.handle_transcript("start listening")
        ctl.handle_transcript("species snake plant")
        ctl.handle_transcript("next row")   # must not raise without a speaker

    def test_expire_prompt_forwards_event(self):
        self.say("start listening", "species snake plant", "next row")
        self.ctl.expire_prompt()
        self.assertEqual(self.kinds()[-1], "expired")


class TestGateAndSpeechHooks(ControllerCase):
    def test_set_listening_opens_and_closes_gate(self):
        self.ctl.set_listening(True)
        self.assertTrue(self.ctl.session.listening)
        self.assertEqual(self.kinds(), ["started"])
        self.ctl.set_listening(False)
        self.assertFalse(self.ctl.session.listening)
        self.assertEqual(self.kinds(), ["started", "stopped"])

    def test_speech_hook_brackets_the_question(self):
        calls = []
        ctl = Controller(XlsxBridge(self.path), Settings.defaults(), self.speaker,
                         on_speech=calls.append)
        ctl.connect()
        for phrase in ("start listening", "species snake plant", "next row"):
            ctl.handle_transcript(phrase)
        self.assertEqual(calls, [True, False])


class TestFailureHandling(ControllerCase):
    def test_failed_write_keeps_the_row(self):
        self.say("start listening", "fern")
        # Break the destination: a column the sheet doesn't have.
        self.ctl.session.record["Bogus"] = "x"
        self.say("next row")
        self.assertIn("error", self.kinds())
        self.assertEqual(self.ctl.session.record["Species"], "Fern")
        self.assertEqual(self.ctl.session.committed, 0)

    def test_refresh_picks_up_workbook_changes(self):
        wb = openpyxl.load_workbook(self.path)
        wb["Config"]["A6"] = "Palm"
        wb.save(self.path)
        self.ctl.refresh()
        self.assertIn("Palm", self.ctl.vocab.values_for("Species"))

    def test_connect_failure_propagates(self):
        ctl = Controller(XlsxBridge(self.dir / "missing.xlsx"), Settings.defaults())
        with self.assertRaises(BridgeError):
            ctl.connect()


class TestSettingsAndSheets(ControllerCase):
    def test_custom_keyword_after_apply_settings(self):
        self.ctl.settings.set_keywords([("go", self.ctl.settings.keywords["start listening"]),
                                        ("halt", self.ctl.settings.keywords["stop listening"]),
                                        ("commit", self.ctl.settings.keywords["next row"])])
        self.ctl.apply_settings()
        self.say("go", "fern", "commit")
        self.assertEqual(self.sheet()["A4"].value, "Fern")

    def test_sheet_change_reloads_field_words(self):
        self.say("start listening")
        wb = openpyxl.load_workbook(self.path)
        wb.active = wb.sheetnames.index("Config")
        wb.save(self.path)
        self.ctl.refresh()          # picks up the new active sheet
        self.assertIn("Season_list", self.ctl.bridge.get_headers())
        self.assertEqual(self.ctl.bridge.active_sheet_name(), "Config")

    def test_follow_active_sheet_notifies(self):
        self.ctl._sheet = "Elsewhere"   # as if the user had been on another sheet
        self.say("start listening")
        self.assertTrue(any("Now on sheet" in e.detail for e in self.events))


if __name__ == "__main__":
    unittest.main()
