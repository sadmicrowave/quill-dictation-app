"""The microphone is open only while Quill is listening (or has been told to stay on)."""
import pathlib
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.listener.listener import Listener
from tests.fixtures import make_workbook
from tests.test_app import FakeListener, FakeSpeaker

_app = QApplication.instance() or QApplication([])


class MicCase(unittest.TestCase):
    always_on = False

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.path = make_workbook(self.dir / "plants.xlsx")
        self.settings = Settings.load(self.dir / "cfg")
        self.settings.preferences["mic_always_on"] = self.always_on
        self.listeners = []

        def factory(model, on_transcript, on_error):
            self.listeners.append(FakeListener(model, on_transcript, on_error))
            return self.listeners[-1]

        self.quill = QuillApp(_app, self.settings, XlsxBridge(self.path), listener_factory=factory,
                              model_finder=lambda c: self.dir, speaker=FakeSpeaker(),
                              sound_player=lambda p: None)
        self.quill.start()
        self.mic = self.listeners[0]

    def tearDown(self):
        self._tmp.cleanup()

    def hear(self, *phrases):
        for phrase in phrases:
            self.quill.controller.handle_transcript(phrase)


class TestMicOffByDefault(MicCase):
    def test_closed_at_launch(self):
        self.assertEqual((self.mic.starts, self.mic.started), (0, False))
        self.assertIn("Speech model ready", self.quill.window.log.toPlainText())
        self.assertNotIn("Microphone on", self.quill.window.log.toPlainText())

    def test_opens_when_listening_starts_and_closes_when_it_stops(self):
        self.quill.window.toggle_button.click()
        self.assertTrue(self.mic.started)
        self.assertIn("Microphone on", self.quill.window.log.toPlainText())
        self.quill.window.toggle_button.click()
        self.assertFalse(self.mic.started)
        self.assertEqual((self.mic.starts, self.mic.stops), (1, 1))
        self.assertIn("Microphone off", self.quill.window.log.toPlainText())

    def test_the_tray_menu_opens_and_closes_it_too(self):
        self.quill.tray.toggle()
        self.assertTrue(self.mic.started)
        self.quill.tray.toggle()
        self.assertFalse(self.mic.started)

    def test_it_is_not_reopened_for_every_event_while_listening(self):
        self.quill.window.toggle_button.click()
        self.hear("fern bright", "next row", "cactus", "next row")
        self.assertEqual(self.mic.starts, 1)

    def test_stays_open_while_a_spoken_answer_is_expected_then_closes(self):
        self.quill.window.toggle_button.click()
        self.hear("species snake plant", "next row")             # asks "add it? yes or no"
        self.assertTrue(self.quill.controller.session.awaiting_answer)
        self.quill.window.toggle_button.click()                  # stop listening
        self.assertTrue(self.mic.started, "a pending yes / no needs the mic")
        self.hear("yes")
        self.quill._sync_mic()
        self.assertFalse(self.mic.started)

    def test_an_unanswered_question_closes_the_mic_when_it_expires(self):
        self.quill.window.toggle_button.click()
        self.hear("species snake plant", "next row")
        self.quill.window.toggle_button.click()
        self.assertTrue(self.mic.started)
        self.quill.controller.expire_prompt()
        self.assertFalse(self.mic.started)

    def test_voice_sorting_keeps_it_open_until_done(self):
        self.quill.window.toggle_button.click()
        self.hear("species snake plant", "next row")
        self.quill.window.toggle_button.click()
        self.quill.controller.expire_prompt()
        self.assertFalse(self.mic.started)
        self.assertTrue(self.quill.controller.start_voice_sort())
        self.quill._sync_mic()
        self.assertTrue(self.mic.started)
        self.quill.controller.stop_voice_sort()
        self.quill._sync_mic()
        self.assertFalse(self.mic.started)

    def test_no_workbook_means_it_never_opens(self):
        quill = QuillApp(_app, Settings.load(self.dir / "cfg2"), XlsxBridge(self.dir / "none.xlsx"),
                         listener_factory=lambda *a: self.listeners.append(FakeListener(*a)) or self.listeners[-1],
                         model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None)
        quill.start()
        quill.window.toggle_button.click()
        self.assertFalse(quill.controller.session.listening)
        self.assertFalse(self.listeners[-1].started)


class TestAlwaysOn(MicCase):
    always_on = True

    def test_open_from_launch_so_start_listening_can_be_spoken(self):
        self.assertTrue(self.mic.started)
        self.hear("start listening")
        self.assertTrue(self.quill.controller.session.listening)

    def test_stays_open_after_listening_stops(self):
        self.quill.window.toggle_button.click()
        self.quill.window.toggle_button.click()
        self.assertTrue(self.mic.started)

    def test_turning_the_setting_off_live_closes_it(self):
        self.settings.preferences["mic_always_on"] = False
        self.quill.apply_settings(quiet=True)
        self.assertFalse(self.mic.started)

    def test_turning_it_on_live_opens_it(self):
        self.settings.preferences["mic_always_on"] = False
        self.quill.apply_settings(quiet=True)
        self.settings.preferences["mic_always_on"] = True
        self.quill.apply_settings(quiet=True)
        self.assertTrue(self.mic.started)


class TestRealListenerOnlyOpensWhenStarted(unittest.TestCase):
    """The real Listener must not touch the microphone for preload or construction."""

    def test_preload_loads_the_model_without_opening_a_stream(self):
        import threading
        opened = []
        loaded = threading.Event()

        def stream_factory(rate, push):
            opened.append(1)
            raise AssertionError("the microphone must not be opened by preload")

        def loader(path):
            loaded.set()
            return object()

        listener = Listener(pathlib.Path("."), lambda t: None, model_loader=loader, stream_factory=stream_factory)
        listener.preload()
        self.assertTrue(loaded.wait(2))
        self.assertEqual(opened, [])
        self.assertFalse(listener.running)

    def test_stop_closes_the_stream_and_start_reopens_it_without_reloading_the_model(self):
        import contextlib
        import queue
        import time
        events, loads = [], []

        @contextlib.contextmanager
        def stream_factory(rate, push):
            events.append("open")
            try:
                yield
            finally:
                events.append("close")

        class Rec:
            def AcceptWaveform(self, chunk): return False
            def Result(self): return "{}"

        def loader(path):
            loads.append(1)
            return object()

        listener = Listener(pathlib.Path("."), lambda t: None, model_loader=loader,
                            recognizer_factory=lambda m, r: Rec(), stream_factory=stream_factory)
        listener.start()
        for _ in range(40):
            if events:
                break
            time.sleep(0.05)
        listener.stop()
        listener.start()
        for _ in range(40):
            if events.count("open") == 2:
                break
            time.sleep(0.05)
        listener.stop()
        self.assertEqual(events, ["open", "close", "open", "close"])
        self.assertEqual(loads, [1])

    def test_preloading_twice_loads_once(self):
        import time
        loads = []
        listener = Listener(pathlib.Path("."), lambda t: None,
                            model_loader=lambda p: loads.append(1) or object())
        listener.preload()
        listener.preload()
        time.sleep(0.3)
        listener.preload()
        time.sleep(0.2)
        self.assertEqual(loads, [1])


if __name__ == "__main__":
    unittest.main()
