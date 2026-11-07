"""Quitting with windows open, instant spoken confirmations, remembered Settings page, and small control fixes."""
import pathlib
import tempfile
import time
import unittest

from PySide6.QtCore import QEvent
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp, QuillApplication
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.feedback import spoken_words
from quill.speaker.clips import SpokenClips
from quill.ui import theme
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.settings_widgets import GuardedSpinBox, SegmentedControl
from tests.fixtures import make_workbook
from tests.test_app import FakeListener, FakeSpeaker

_app = QApplication.instance() or QApplication([])


class StubQApp:
    """Stands in for the application object where a test must not really quit."""

    def __init__(self, real):
        self._real, self.quit_called, self.exit_called = real, False, False

    def topLevelWidgets(self):
        return self._real.topLevelWidgets()

    def quit(self):
        self.quit_called = True

    def exit(self, code=0):
        self.exit_called = True

    def __getattr__(self, name):
        return getattr(self._real, name)


class Case(unittest.TestCase):
    def build(self, clips=None, speaker=None, player=None, settings_edit=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = pathlib.Path(tmp.name)
        self.dir = d
        settings = Settings.load(d / "cfg")
        if settings_edit:
            settings_edit(settings)
        self.played, self.spoken = [], speaker or FakeSpeaker()
        app = QuillApp(_app, settings, XlsxBridge(make_workbook(d / "p.xlsx")), listener_factory=lambda *a: FakeListener(*a),
                       model_finder=lambda c: d, speaker=FakeSpeaker(), echo_speaker=self.spoken,
                       sound_player=player or self.played.append, clips=clips)
        app.quit_failsafe_ms = 0
        app.start()
        return app


class TestQuitting(Case):
    def test_the_applications_close_event_becomes_a_quit_request(self):
        class Stub:
            def __init__(self):
                self.requests = 0
                self.quit_requested = type("S", (), {"emit": lambda s: setattr(self, "requests", self.requests + 1)})()
        stub = Stub()
        self.assertTrue(QuillApplication.event(stub, QCloseEvent()))
        self.assertEqual(stub.requests, 1)

    def test_quitting_closes_an_open_settings_window_and_every_other_window(self):
        app = self.build()
        stub = app.qapp = StubQApp(_app)
        app.sorting.set_items([(None, "teal")])
        app.sorting.show()
        dialog = SettingsDialog(app.settings, app.window.widget)
        widget = dialog.build(lazy=True)
        widget.show()
        app._settings_dialog = dialog
        app.quit_app()
        self.assertFalse(widget.isVisible())
        self.assertFalse(app.sorting.widget.isVisible())
        self.assertFalse(app.window.widget.isVisible())
        self.assertTrue(stub.quit_called)
        self.assertFalse(app._quiet_timer.isActive())                    # the timers and the microphone are released too

    def test_asking_twice_quits_once(self):
        app = self.build()
        stub = app.qapp = StubQApp(_app)
        app.quit_app()
        stub.quit_called = False
        app.quit_app()
        self.assertFalse(stub.quit_called)

    def test_there_is_a_failsafe_that_ends_the_event_loop(self):
        app = self.build()
        self.assertEqual(QuillApp.quit_failsafe_ms, 1500)
        app.quit_failsafe_ms = 0                                          # (switched off for the other tests)
        self.assertFalse(app.quit_failsafe_ms)

    def test_opening_settings_twice_brings_the_open_one_forward(self):
        app = self.build()
        raised = []
        fake = type("D", (), {"bring_forward": lambda s: raised.append(1)})()
        app._settings_dialog = fake
        app.open_settings()
        self.assertEqual(raised, [1])


class TestInstantSpokenWords(Case):
    def test_a_word_with_a_clip_is_played_as_a_sound_not_spoken(self):
        import os
        os.environ.pop("QUILL_NO_SOUND", None)
        self.addCleanup(os.environ.__setitem__, "QUILL_NO_SOUND", "1")
        clips = SpokenClips(pathlib.Path(tempfile.mkdtemp()), render=lambda text, dest: dest.write_bytes(b"R" * 100) > 0)
        app = self.build(clips=clips)
        self.assertTrue(clips.make("Okay"))
        app._speak_word("Okay")
        self.assertEqual(self.played, [clips.path("Okay")])
        self.assertEqual(self.spoken.said, [])                          # no waiting for the system voice

    def test_a_word_without_a_clip_is_spoken_live_and_its_clip_is_made_for_next_time(self):
        import os
        os.environ.pop("QUILL_NO_SOUND", None)
        self.addCleanup(os.environ.__setitem__, "QUILL_NO_SOUND", "1")
        made = []
        clips = SpokenClips(pathlib.Path(tempfile.mkdtemp()),
                            render=lambda text, dest: (made.append(text), dest.write_bytes(b"R" * 100))[1] > 0)
        app = self.build(clips=clips)
        app._speak_word("Done")
        self.assertEqual(self.spoken.said, ["Done"])
        deadline = time.time() + 3
        while "Done" not in made and time.time() < deadline:
            time.sleep(0.02)
        self.assertIn("Done", made)

    def test_clips_are_written_aside_so_a_half_made_one_is_never_played(self):
        folder = pathlib.Path(tempfile.mkdtemp())
        clips = SpokenClips(folder, render=lambda text, dest: False)
        self.assertFalse(clips.make("Okay"))
        self.assertFalse(clips.ready("Okay"))
        self.assertEqual(list(folder.iterdir()), [])

    def test_every_word_quill_can_say_can_be_prepared_ahead(self):
        words = spoken_words()
        for expected in ("Okay", "Done", "Got It", "Ignored", "Undone", "Deleted", "Problem", "Please Sort"):
            self.assertIn(expected, words)

    def test_the_sounds_are_loaded_when_the_app_starts(self):
        loaded = []

        class Player:
            def __call__(self, path):
                pass

            def preload(self, paths):
                loaded.extend(paths)
        app = self.build(player=Player())
        app._warm_up_sounds()
        self.assertTrue(any(p.name == "success.wav" for p in loaded))
        self.assertGreaterEqual(len(loaded), 20)                          # every pack's every cue


class TestSettingsWindowDetails(Case):
    def test_it_reopens_on_the_page_it_was_closed_on_at_its_size(self):
        settings = Settings.load(pathlib.Path(tempfile.mkdtemp()))
        dialog = SettingsDialog(settings)
        dialog.build(lazy=True)
        dialog.nav.setCurrentRow(dialog._nav_row("Sounds"))
        dialog._dialog.resize(880, 600)
        dialog._remember_position()
        self.assertEqual(settings.preferences["settings_page"], "Sounds")
        again = SettingsDialog(settings)
        again.build(lazy=True)
        again._restore_position()
        self.assertEqual(again.nav.currentItem().data(0x100), "Sounds")
        self.assertEqual((again._dialog.width(), again._dialog.height()), (880, 600))

    def test_a_missing_or_unknown_page_opens_the_first(self):
        settings = Settings.load(pathlib.Path(tempfile.mkdtemp()))
        settings.preferences["settings_page"] = "Gone"
        dialog = SettingsDialog(settings)
        dialog.build(lazy=True)
        dialog._restore_position()
        self.assertEqual(dialog.nav.currentItem().data(0x100), "General")

    def test_the_theme_icons_are_redrawn_for_the_current_colour(self):
        theme.apply_theme(_app, "dark", "violet", "compact")
        control = SegmentedControl()
        control.addItem("sun", "Light", "light")
        first = control._buttons[0].icon().pixmap(18, 18).toImage()
        control.refresh_icons("#FFFFFF")
        light_ink = control._buttons[0].icon().pixmap(18, 18).toImage()
        control.refresh_icons("#000000")
        dark_ink = control._buttons[0].icon().pixmap(18, 18).toImage()
        self.assertNotEqual(light_ink, dark_ink)
        self.assertIsNotNone(first)

    def test_the_dialog_redraws_its_theme_icons_when_it_is_dressed(self):
        settings = Settings.load(pathlib.Path(tempfile.mkdtemp()))
        dialog = SettingsDialog(settings)
        dialog.build()
        called = []
        dialog.theme_combo.refresh_icons = lambda color=None: called.append(color)
        dialog._apply_dialog_look()
        self.assertEqual(len(called), 1)

    def test_number_boxes_keep_their_text_away_from_the_edges(self):
        spin = GuardedSpinBox()
        margins = spin.lineEdit().textMargins()
        self.assertGreater(margins.left(), 0)
        self.assertGreater(margins.right(), 0)


class TestDockToggleKeepsTheFocus(Case):
    def test_the_window_that_had_the_focus_is_raised_again(self):
        app = self.build()
        raised = []
        original = app.qapp
        app.qapp = type("Q", (), {"activeWindow": lambda s: type("W", (), {
            "raise_": lambda w: raised.append("raise"), "activateWindow": lambda w: raised.append("activate")})(),
            "__getattr__": lambda s, n: getattr(original, n)})()
        app._apply_dock()
        deadline = time.time() + 1
        while not raised and time.time() < deadline:
            _app.processEvents()
        self.assertEqual(raised, ["raise", "activate"])

    def test_the_application_is_activated_whether_the_icon_is_shown_or_hidden(self):
        from quill.platforms.macos import chrome

        class Kit:
            activated = 0

            class NSApplication:
                @staticmethod
                def sharedApplication():
                    return app_obj
        app_obj = type("A", (), {"setActivationPolicy_": lambda s, p: True,
                                 "activateIgnoringOtherApps_": lambda s, f: setattr(Kit, "activated", Kit.activated + 1)})()
        had = hasattr(chrome, "_native_platform")
        real = getattr(chrome, "_native_platform", None)
        chrome._native_platform = lambda platform=None: True
        try:
            chrome.set_dock_icon_visible(False, platform="darwin", appkit=Kit)
            chrome.set_dock_icon_visible(True, platform="darwin", appkit=Kit)
        finally:
            if had:
                chrome._native_platform = real
            else:
                del chrome._native_platform
        self.assertEqual(Kit.activated, 2)


if __name__ == "__main__":
    unittest.main()
