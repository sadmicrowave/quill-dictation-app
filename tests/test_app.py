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
        self.assertEqual(self.quill.window.workbook_name, "plants.xlsx")

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
        self.assertIn("No speech model found", quill.window.log.toPlainText())        # the download itself is in Settings

    def test_download_success_starts_listener(self):
        found = {"model": None}
        quill = self.make(lambda c: found["model"], lambda dest, progress: self.model)
        found["model"] = self.model
        quill._on_progress(50, 100)
        self.assertEqual(quill._model_note, "Downloading… 50%")
        quill._on_model_ready(self.model)
        self.assertIsNotNone(quill.listener)
        self.assertTrue(quill.listener.preloaded)
        self.assertFalse(quill.listener.started)          # the microphone waits for Start
        self.assertEqual(quill._model_note, "")

    def test_download_failure_offers_retry(self):
        quill = self.make(lambda c: None, None)
        quill._on_model_ready(None)
        self.assertFalse(quill._model_busy)
        self.assertIn("failed", quill.window.log.toPlainText())          # the error is in the log
        self.assertIn("Error", quill.window.log.toPlainText().splitlines()[-1])

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

    def test_listener_error_goes_to_the_log(self):
        self.quill._on_error("Listening stopped: no microphone")
        self.assertIn("no microphone", self.quill.window.log.toPlainText())


class TestSettingsApplied(AppCase):
    def test_apply_settings_updates_speaker_and_keywords(self):
        from quill.parser.commands import Action
        self.settings.preferences["speak_sort_prompts"] = True
        self.settings.set_keywords([("go", Action.START_LISTENING), ("halt", Action.STOP_LISTENING),
                                    ("commit", Action.NEXT_ROW)])
        self.quill.apply_settings()
        self.assertTrue(self.speaker.enabled)
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
        self.app._on_phrase_heard("hello there")
        self.assertEqual(self.app.window.stream_text(), "hello there")
        known = [m.known for m in self.app._match_heard_words(["next", "row", "zzzz"])]
        self.assertEqual(known, [True, True, False])

    def test_nothing_is_shown_while_not_listening(self):
        self.app._on_phrase_heard("hello there")
        self.app._on_partial_heard("hello")
        self.assertEqual(self.app.window.stream_text(), "")

    def test_the_stream_restarts_after_listening_stops_and_starts_again(self):
        self.app.controller.handle_transcript("start listening")
        self.app._on_phrase_heard("black")
        self.app.controller.handle_transcript("stop listening")
        self.app.controller.handle_transcript("start listening")
        self.app._on_phrase_heard("navy")
        self.assertEqual(self.app.window.stream_text(), "navy")


    def test_deleting_a_grid_row_removes_it_from_the_record_and_unmarks_its_words(self):
        self.app.controller.handle_transcript("start listening")
        self.app.controller.session.record.update({"Type": "Fern"})
        self.app.window.update_current_row({"Type": "Fern"})
        self.app.window.set_stream_classifier(
            lambda words: [__import__("quill.stream", fromlist=["WordMatch"]).WordMatch(w == "fern", "Type" if w == "fern" else None)
                           for w in words])
        self.app._on_phrase_heard("a fern")
        self.app.window._remove_row_requested("Type")
        self.assertNotIn("Type", self.app.controller.session.record)
        self.assertEqual(self.app.window.row_table.rowCount(), 0)
        self.assertNotIn("fern", self.app.window.stream.toHtml().split("background-color")[-1:][0][:5])   # no pill left
        self.assertIn("Removed Type", self.app.window.log.toPlainText())


class TestAutoStopWhenQuiet(unittest.TestCase):
    def setUp(self):
        import pathlib, tempfile
        from quill.bridge.xlsx_bridge import XlsxBridge
        from quill.config.settings import Settings
        from tests.fixtures import make_workbook
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = pathlib.Path(self._tmp.name)
        self.settings = Settings.load(d / "cfg")
        self.app = QuillApp(_app, self.settings, XlsxBridge(make_workbook(d / "p.xlsx")),
                            listener_factory=lambda *a: FakeListener(*a), model_finder=lambda c: d,
                            speaker=FakeSpeaker(), sound_player=lambda p: None)
        self.app.start()

    def test_it_is_on_by_default_with_ten_seconds(self):
        self.assertTrue(self.settings.preferences["auto_stop"])
        self.assertEqual(self.settings.preferences["auto_stop_seconds"], 10)

    def test_the_countdown_runs_only_while_listening(self):
        self.assertFalse(self.app._quiet_timer.isActive())
        self.app.controller.handle_transcript("start listening")
        self.assertTrue(self.app._quiet_timer.isActive())
        self.assertEqual(self.app._quiet_timer.interval(), 10_000)
        self.app.controller.handle_transcript("stop listening")
        self.assertFalse(self.app._quiet_timer.isActive())

    def test_after_the_quiet_time_listening_stops_and_says_why(self):
        self.app.controller.handle_transcript("start listening")
        self.app._quiet_for_too_long()
        self.assertFalse(self.app.controller.session.listening)
        self.assertFalse(self.app.window.listening)
        self.assertIn("nothing was said for 10 seconds", self.app.window.log.toPlainText())

    def test_hearing_something_restarts_the_countdown(self):
        self.settings.preferences["auto_stop_seconds"] = 30
        self.app.controller.handle_transcript("start listening")
        self.app._on_partial_heard("black")
        self.assertEqual(self.app._quiet_timer.interval(), 30_000)
        self.assertTrue(self.app._quiet_timer.isActive())

    def test_the_setting_can_turn_it_off_entirely(self):
        self.settings.preferences["auto_stop"] = False
        self.app.controller.handle_transcript("start listening")
        self.assertFalse(self.app._quiet_timer.isActive())
        self.app._on_phrase_heard("black")
        self.assertFalse(self.app._quiet_timer.isActive())

    def test_it_also_ends_a_wait_for_a_spoken_answer_and_voice_sorting(self):
        self.app.controller.handle_transcript("start listening")
        self.app.controller.session.pending = [("Color", "teal")]
        self.app.controller.session._voice_open = True
        self.app.controller.start_voice_sort()
        self.app._sync_mic()
        self.assertTrue(self.app._quiet_timer.isActive())
        self.app._quiet_for_too_long()
        self.assertIsNone(self.app.controller.voice_sorter)               # voice sorting ended
        self.assertFalse(self.app.controller.session.awaiting_answer)     # the wait for an answer ended
        self.assertFalse(self.app.controller.session.listening)           # and listening itself
        self.assertEqual(self.app.controller.pending_terms(), [("Color", "teal")])   # the question stays for later
        self.assertFalse(self.app._quiet_timer.isActive())

    def test_unrelated_events_do_not_keep_postponing_the_countdown(self):
        self.app.controller.handle_transcript("start listening")
        self.app._quiet_timer.start(7000)
        remaining = self.app._quiet_timer.remainingTime()
        self.app._sync_mic()
        self.assertLessEqual(self.app._quiet_timer.remainingTime(), remaining)


class TestNextItemAsTheLastWords(unittest.TestCase):
    def test_next_item_is_heard_as_part_of_the_turn_then_removed_as_a_command(self):
        import pathlib, tempfile
        from quill.bridge.xlsx_bridge import XlsxBridge
        from quill.config.settings import Settings
        from tests.fixtures import make_workbook
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            app = QuillApp(_app, Settings.load(d / "cfg"), XlsxBridge(make_workbook(d / "p.xlsx")),
                           listener_factory=lambda *a: FakeListener(*a), model_finder=lambda c: d,
                           speaker=FakeSpeaker(), sound_player=lambda p: None)
            app.start()
            app.controller.handle_transcript("start listening")
            app._on_phrase_heard("fern small next item")
            app.controller.handle_transcript("fern small next item")
            self.assertEqual(app.window.stream_text(), "fern small")
            self.assertEqual(app.controller.session.committed, 1)


class TestQuietCountdownLabel(unittest.TestCase):
    def setUp(self):
        import pathlib, tempfile
        from quill.bridge.xlsx_bridge import XlsxBridge
        from quill.config.settings import Settings
        from tests.fixtures import make_workbook
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = pathlib.Path(self._tmp.name)
        self.settings = Settings.load(d / "cfg")
        self.app = QuillApp(_app, self.settings, XlsxBridge(make_workbook(d / "p.xlsx")),
                            listener_factory=lambda *a: FakeListener(*a), model_finder=lambda c: d,
                            speaker=FakeSpeaker(), sound_player=lambda p: None)
        self.app.start()
        self.label = self.app.window.countdown_label

    def test_hidden_until_listening_then_it_counts_from_the_setting(self):
        self.assertFalse(self.label.isVisibleTo(self.app.window.widget))
        self.app.controller.handle_transcript("start listening")
        self.assertTrue(self.label.isVisibleTo(self.app.window.widget))
        self.assertEqual(self.label.text(), "Stops in 10s")

    def test_it_follows_the_timer_and_restarts_when_something_is_heard(self):
        self.app.controller.handle_transcript("start listening")
        self.app._quiet_timer.start(4200)
        self.app._show_countdown()
        self.assertEqual(self.label.text(), "Stops in 5s")                  # rounded up
        self.app._on_partial_heard("black")
        self.assertEqual(self.label.text(), "Stops in 10s")                 # back to the full setting

    def test_it_uses_the_users_seconds_with_the_word_in_both_views(self):
        self.settings.preferences["auto_stop_seconds"] = 25
        self.app.controller.handle_transcript("start listening")
        self.assertEqual(self.label.text(), "Stops in 25s")
        self.app.window.set_mini(True)
        self.assertEqual(self.label.text(), "Stops in 25s")

    def test_it_disappears_when_listening_stops_or_the_setting_is_off(self):
        self.app.controller.handle_transcript("start listening")
        self.app.controller.handle_transcript("stop listening")
        self.assertFalse(self.label.isVisibleTo(self.app.window.widget))
        self.settings.preferences["auto_stop"] = False
        self.app.controller.handle_transcript("start listening")
        self.assertFalse(self.label.isVisibleTo(self.app.window.widget))

    def test_it_is_muted_and_italic(self):
        from quill.ui.theme import stylesheet_for
        sheet = stylesheet_for(True)
        rule = sheet[sheet.index('QLabel[countdown="true"]'):].split("}")[0]
        self.assertIn("font-style: italic", rule)
        self.assertNotIn("font-size", rule)           # the same size as every other text
        self.assertIn("color:", rule)


class TestSystemSpeechOnlyForSortPrompts(unittest.TestCase):
    """Quill speaks nowhere except the Term Helper prompts, and only when the user turned that on."""

    def build(self, speak):
        import pathlib, tempfile
        from quill.bridge.xlsx_bridge import XlsxBridge
        from quill.config.settings import Settings
        from tests.fixtures import make_workbook
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = pathlib.Path(tmp.name)
        settings = Settings.load(d / "cfg")
        settings.preferences["speak_sort_prompts"] = speak
        self.speaker = FakeSpeaker()
        app = QuillApp(_app, settings, XlsxBridge(make_workbook(d / "p.xlsx")),
                       listener_factory=lambda *a: FakeListener(*a), model_finder=lambda c: d,
                       speaker=self.speaker, sound_player=lambda p: None)
        app.start()
        app.apply_settings(quiet=True)                 # the speaker follows the setting
        return app

    def test_it_is_off_by_default(self):
        from quill.config.settings import DEFAULT_PREFERENCES
        self.assertFalse(DEFAULT_PREFERENCES["speak_sort_prompts"])

    def test_starting_with_no_spreadsheet_is_never_spoken(self):
        from quill.bridge.base import BridgeError
        for speak in (False, True):
            app = self.build(speak)
            self.speaker.said.clear()
            app.controller.bridge.disconnect()
            app.controller.connected = False
            app.controller.bridge.connect = lambda *a, **k: (_ for _ in ()).throw(BridgeError("none"))
            app.controller.set_listening(True)
            self.assertEqual(self.speaker.said, [], speak)

    def test_with_the_setting_off_nothing_is_spoken_even_for_sort_rows(self):
        app = self.build(False)
        app.controller.handle_transcript("start listening")
        app.controller.handle_transcript("teal t-shirt")
        app.controller.handle_transcript("next row")
        app.controller.start_voice_sort()
        self.assertEqual(self.speaker.said, [])

    def test_each_sort_row_is_spoken_once_when_it_becomes_the_active_one_and_the_setting_is_on(self):
        app = self.build(True)
        app.controller.handle_transcript("start listening")
        app.controller.handle_transcript("teal t-shirt")
        app.controller.handle_transcript("next row")
        self.speaker.said.clear()
        app.controller.start_voice_sort()
        spoken = [text for text in self.speaker.said if "Say" in text]
        self.assertTrue(any(text.startswith("Teal") for text in spoken), spoken)
        count = len(self.speaker.said)
        app.refresh_sorting()                                            # the same row again: not repeated
        self.assertEqual(len(self.speaker.said), count)
