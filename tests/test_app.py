"""Wiring tests for QuillApp using a file bridge and a fake listener (headless)."""
import pathlib
import tempfile
import unittest

import openpyxl
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from tests.fixtures import make_workbook

_app = QApplication.instance() or QApplication([])


class FakeListener:
    def __init__(self, model, on_transcript, on_error):
        self.on_transcript, self.on_error = on_transcript, on_error
        self.started = False
        self.preloaded = False
        self.starts, self.stops = 0, 0
        self.muted = []

    def preload(self):
        self.preloaded = True

    def start(self):
        self.started = True
        self.starts += 1

    def stop(self):
        self.started = False
        self.stops += 1

    def mute(self):
        self.muted.append(True)

    def unmute(self):
        self.muted.append(False)


class FakeSpeaker:
    enabled = True

    def __init__(self):
        self.said = []

    def say(self, text, on_done=None, lead_in=0.0):
        self.said.append(text)
        if on_done:
            on_done()


class AppCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.path = make_workbook(self.dir / "plants.xlsx")
        self.settings = Settings.load(self.dir / "cfg")
        self.speaker = FakeSpeaker()
        self.listeners = []

        def factory(model, on_transcript, on_error):
            listener = FakeListener(model, on_transcript, on_error)
            self.listeners.append(listener)
            return listener

        self.model = self.dir / "model"
        self.quill = QuillApp(
            _app, self.settings, XlsxBridge(self.path), listener_factory=factory,
            model_finder=lambda configured: self.model, speaker=self.speaker,
        )
        self.quill.start()

    def tearDown(self):
        self._tmp.cleanup()

    def hear(self, *phrases):
        for phrase in phrases:
            self.quill.relay.transcript.emit(phrase)   # same path the listener thread uses

    def log(self):
        return self.quill.window.log.toPlainText()

    def sheet(self, name="Inventory"):
        return openpyxl.load_workbook(self.path)[name]


class TestStartup(AppCase):
    def test_connects_and_reports_lists(self):
        self.assertTrue(self.quill.connected)
        self.assertIn("Connected to plants.xlsx", self.log())
        self.assertEqual(self.quill.window.sheet_label.text(), "Sheet: Inventory")
        self.assertEqual(self.quill.window.workbook_combo.currentText(), "plants.xlsx")

    def test_last_workbook_remembered(self):
        self.assertEqual(Settings.load(self.dir / "cfg").preferences["last_workbook"], "plants.xlsx")

    def test_model_is_loaded_but_the_microphone_stays_off_at_launch(self):
        self.assertTrue(self.listeners[0].preloaded)
        self.assertFalse(self.listeners[0].started)
        self.assertEqual(self.listeners[0].starts, 0)


class TestDictationThroughUi(AppCase):
    def test_voice_start_lights_up_and_row_is_saved(self):
        self.hear("start listening")
        self.assertTrue(self.quill.window.listening)
        self.assertTrue(self.quill.tray.listening)
        self.hear("fern bright")
        self.assertEqual(self.quill.window.row_table.rowCount(), 2)
        self.hear("next row")
        self.assertEqual(self.sheet()["A4"].value, "Fern")
        self.assertEqual(self.quill.window.row_table.rowCount(), 0)
        self.assertIn("Row 4", self.quill.window.last_label.text())

    def test_stop_turns_light_off(self):
        self.hear("start listening", "stop listening")
        self.assertFalse(self.quill.window.listening)
        self.assertFalse(self.quill.tray.listening)

    def test_button_toggle_opens_gate(self):
        self.quill.window.toggle_button.click()
        self.assertTrue(self.quill.controller.session.listening)
        self.assertTrue(self.quill.window.listening)

    def test_tray_toggle_closes_gate(self):
        self.quill.toggle_listening(True)
        self.quill.tray.toggle()
        self.assertFalse(self.quill.controller.session.listening)

    def test_question_is_spoken_mutes_mic_and_arms_timeout(self):
        self.hear("start listening", "species snake plant", "next row")
        self.assertIn("Snake Plant", self.speaker.said[0])
        self.assertEqual(self.listeners[0].muted, [True, False])
        self.assertTrue(self.quill._expiry.isActive())
        self.hear("yes")
        self.assertEqual(self.sheet("Config")["A6"].value, "Snake Plant")
        self.assertIn("Added Snake Plant to Species", self.log())

    def test_error_event_is_logged(self):
        self.hear("start listening", "light dim", "next row", "yes")
        self.assertIn("Could not add", self.log())


class TestWorkbookActions(AppCase):
    def test_refresh_rereads(self):
        wb = openpyxl.load_workbook(self.path)
        wb["Config"]["A6"] = "Palm"
        wb.save(self.path)
        self.quill.refresh()
        self.assertIn("Palm", self.quill.controller.vocab.values_for("Species"))
        self.assertIn("Workbook re-read", self.log())

    def test_missing_workbook_is_reported_not_raised(self):
        quill = QuillApp(_app, Settings.defaults(), XlsxBridge(self.dir / "nope.xlsx"),
                         model_finder=lambda c: None, speaker=self.speaker)
        quill.start()
        self.assertFalse(quill.connected)
        self.assertIn("Not connected", quill.window.log.toPlainText())

    def test_toggle_when_not_connected_does_not_open_gate(self):
        quill = QuillApp(_app, Settings.defaults(), XlsxBridge(self.dir / "nope.xlsx"),
                         model_finder=lambda c: None, speaker=self.speaker)
        quill.start()
        quill.toggle_listening(True)
        self.assertFalse(quill.controller.session.listening)


class TestModelHandling(AppCase):
    def make(self, finder, downloader):
        quill = QuillApp(_app, Settings.defaults(), XlsxBridge(self.path),
                         listener_factory=lambda m, t, e: FakeListener(m, t, e),
                         model_finder=finder, model_downloader=downloader, speaker=self.speaker)
        quill.start()
        return quill

    def test_missing_model_offers_download(self):
        quill = self.make(lambda c: None, None)
        self.assertIsNone(quill.listener)
        self.assertFalse(quill.window.download_button.isHidden())

    def test_download_success_starts_listener(self):
        found = {"model": None}
        quill = self.make(lambda c: found["model"], lambda dest, progress: self.model)
        found["model"] = self.model
        quill._on_progress(50, 100)
        self.assertIn("50%", quill.window.footer.text())
        quill._on_model_ready(self.model)
        self.assertIsNotNone(quill.listener)
        self.assertTrue(quill.listener.preloaded)
        self.assertFalse(quill.listener.started)          # the microphone waits for Start
        self.assertEqual(quill.window.footer.text(), "")

    def test_download_failure_offers_retry(self):
        quill = self.make(lambda c: None, None)
        quill._on_model_ready(None)
        self.assertFalse(quill.window.download_button.isHidden())
        self.assertIn("failed", quill.window.footer.text())

    def test_download_runs_off_thread_and_reports(self):
        import threading
        done = threading.Event()

        def downloader(dest, progress):
            progress(1, 2)
            done.set()
            return self.model

        quill = self.make(lambda c: None, downloader)
        quill.download_model()
        self.assertTrue(done.wait(2))

    def test_listener_error_shown_in_footer(self):
        self.quill._on_error("Listening stopped: no microphone")
        self.assertIn("no microphone", self.quill.window.footer.text())


class TestSettingsApplied(AppCase):
    def test_apply_settings_updates_speaker_and_keywords(self):
        from quill.parser.commands import Action
        self.settings.preferences["speak_prompts"] = False
        self.settings.set_keywords([("go", Action.START_LISTENING), ("halt", Action.STOP_LISTENING),
                                    ("commit", Action.NEXT_ROW)])
        self.quill.apply_settings()
        self.assertFalse(self.speaker.enabled)
        self.hear("go")
        self.assertTrue(self.quill.controller.session.listening)


if __name__ == "__main__":
    unittest.main()


class TestVoiceStreamInTheApp(unittest.TestCase):
    def setUp(self):
        import pathlib, tempfile
        from quill.bridge.xlsx_bridge import XlsxBridge
        from quill.config.settings import Settings
        from tests.fixtures import make_workbook
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = pathlib.Path(self._tmp.name)
        path = make_workbook(d / "p.xlsx")
        self.app = QuillApp(_app, Settings.load(d / "cfg"), XlsxBridge(path),
                            listener_factory=lambda *a: FakeListener(*a), model_finder=lambda c: d,
                            speaker=FakeSpeaker(), sound_player=lambda p: None)
        self.app.start()

    def test_words_are_shown_while_listening_and_known_ones_are_flagged(self):
        self.app.controller.handle_transcript("start listening")
        self.app._heard("hello there")
        self.assertEqual(self.app.window.stream_text(), "hello there")
        known = self.app._known_words(["next", "row", "zzzz"])
        self.assertEqual(known, [True, True, False])

    def test_nothing_is_shown_while_not_listening(self):
        self.app._heard("hello there")
        self.app._hearing("hello")
        self.assertEqual(self.app.window.stream_text(), "")

    def test_the_stream_restarts_after_listening_stops_and_starts_again(self):
        self.app.controller.handle_transcript("start listening")
        self.app._heard("black")
        self.app.controller.handle_transcript("stop listening")
        self.app.controller.handle_transcript("start listening")
        self.app._heard("navy")
        self.assertEqual(self.app.window.stream_text(), "navy")
