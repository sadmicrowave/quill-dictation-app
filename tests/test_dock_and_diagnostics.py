"""The Dock icon setting, reopening the window, and the log file a packaged app relies on."""
import logging
import pathlib
import sys
import tempfile
import threading
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

import quill.ui.chrome as chrome
from quill import diagnostics
from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.ui.main_window import MainWindow
from quill.ui.settings_dialog import SettingsDialog
from tests.test_app import FakeListener, FakeSpeaker
from tests.test_sorting import DemoCase

_app = QApplication.instance() or QApplication([])


class FakeNSApp:
    def __init__(self): self.policy, self.activated = None, False
    def setActivationPolicy_(self, policy): self.policy = policy; return True
    def activateIgnoringOtherApps_(self, flag): self.activated = flag


class FakeKit:
    def __init__(self): self.app = FakeNSApp()
    @property
    def NSApplication(self):
        app = self.app
        return type("A", (), {"sharedApplication": staticmethod(lambda: app)})


class TestSetDockIconVisible(unittest.TestCase):
    def tearDown(self):
        chrome.__dict__.pop("_native_platform", None)

    def test_headless_does_nothing(self):
        self.assertFalse(chrome.set_dock_icon_visible(False))

    def test_not_on_other_platforms(self):
        chrome._native_platform = lambda p: True
        self.assertFalse(chrome.set_dock_icon_visible(False, platform="win32"))

    def test_hiding_makes_it_an_accessory_app_and_showing_a_regular_one(self):
        chrome._native_platform = lambda p: True
        kit = FakeKit()
        self.assertTrue(chrome.set_dock_icon_visible(False, platform="darwin", appkit=kit))
        self.assertEqual(kit.app.policy, 1)                           # NSApplicationActivationPolicyAccessory
        self.assertTrue(chrome.set_dock_icon_visible(True, platform="darwin", appkit=kit))
        self.assertEqual(kit.app.policy, 0)                           # ...Regular
        self.assertTrue(kit.app.activated)

    def test_errors_are_swallowed(self):
        chrome._native_platform = lambda p: True
        class Boom:
            @property
            def NSApplication(self): raise RuntimeError("no")
        self.assertFalse(chrome.set_dock_icon_visible(True, platform="darwin", appkit=Boom()))


class DockCase(DemoCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        import quill.app as app_module
        self._original = app_module.set_dock_icon_visible
        app_module.set_dock_icon_visible = lambda visible: self.calls.append(visible) or True
        self.addCleanup(lambda: setattr(app_module, "set_dock_icon_visible", self._original))
        self.app = QuillApp(_app, self.settings, XlsxBridge(self.path), listener_factory=lambda *a: FakeListener(*a),
                            model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None)
        self.app.start()


class TestDockSetting(DockCase):
    def test_off_by_default_so_the_dock_icon_shows(self):
        self.assertFalse(Settings.load(self.dir / "cfg").preferences["hide_dock_icon"])
        self.assertEqual(self.calls[-1], True)                          # shown at launch

    def test_turning_it_on_hides_the_icon_live_and_off_shows_it_again(self):
        self.settings.preferences["hide_dock_icon"] = True
        self.app.apply_settings(quiet=True)
        self.assertEqual(self.calls[-1], False)
        self.settings.preferences["hide_dock_icon"] = False
        self.app.apply_settings(quiet=True)
        self.assertEqual(self.calls[-1], True)

    def test_a_remembered_choice_applies_at_launch(self):
        self.settings.preferences["hide_dock_icon"] = True
        self.settings.save()
        self.calls.clear()
        app = QuillApp(_app, Settings.load(self.dir / "cfg"), XlsxBridge(self.path),
                       listener_factory=lambda *a: FakeListener(*a), model_finder=lambda c: self.dir,
                       speaker=FakeSpeaker(), sound_player=lambda p: None)
        app.start()
        self.assertEqual(self.calls[0], False)

    def test_the_setting_is_in_the_settings_window_saved_and_live(self):
        d = SettingsDialog(self.settings, on_change=lambda: self.app.apply_settings(quiet=True))
        d.build()
        self.assertFalse(d.dock_check.isChecked())
        d.dock_check.setChecked(True)
        self.assertEqual(self.calls[-1], False)                        # applied as soon as it is ticked
        self.assertTrue(d.try_accept())
        self.assertTrue(Settings.load(self.dir / "cfg").preferences["hide_dock_icon"])

    def test_cancel_brings_the_dock_icon_back(self):
        d = SettingsDialog(self.settings, on_change=lambda: self.app.apply_settings(quiet=True))
        dlg = d.build()
        d.dock_check.setChecked(True)
        dlg.reject()
        self.assertEqual(self.calls[-1], True)
        self.assertFalse(self.settings.preferences["hide_dock_icon"])

    def test_the_settings_row_is_searchable(self):
        d = SettingsDialog(self.settings)
        d.build()
        self.assertEqual([r.title for r in d.rows if r.matches("dock")], ["Hide the Dock Icon"])


class TestReopening(DockCase):
    def test_activating_the_app_with_no_window_shows_it(self):
        self.app.window.widget.hide()
        self.app._app_state_changed(Qt.ApplicationState.ApplicationActive)
        self.assertTrue(self.app.window.widget.isVisible())

    def test_activating_with_the_window_already_up_changes_nothing(self):
        self.app.window.widget.show()
        self.app._app_state_changed(Qt.ApplicationState.ApplicationActive)
        self.assertTrue(self.app.window.widget.isVisible())

    def test_other_state_changes_do_not_pop_the_window_up(self):
        self.app.window.widget.hide()
        self.app._app_state_changed(Qt.ApplicationState.ApplicationInactive)
        self.assertFalse(self.app.window.widget.isVisible())

    def test_closing_the_window_leaves_the_app_running_in_the_menu_bar(self):
        self.assertIsNotNone(self.app.tray)
        self.assertIn("Open Quill", [a.text() for a in self.app.tray._menu.actions()])


class TestPackagingForClickableApps(unittest.TestCase):
    ROOT = pathlib.Path(__file__).resolve().parents[1]

    def test_the_mac_app_is_not_dock_hidden_by_default_and_can_talk_to_excel_and_the_mic(self):
        spec = (self.ROOT / "packaging" / "quill_mac.spec").read_text()
        self.assertNotIn('"LSUIElement":True', spec)
        self.assertIn("NSMicrophoneUsageDescription", spec)
        self.assertIn("NSAppleEventsUsageDescription", spec)


class TestLogFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self._hooks = (sys.excepthook, threading.excepthook)

    def tearDown(self):
        sys.excepthook, threading.excepthook = self._hooks
        logger = logging.getLogger("quill")
        for handler in list(logger.handlers):
            if getattr(handler, "_quill_file", False):
                logger.removeHandler(handler)
                handler.close()
        self._tmp.cleanup()

    def read(self):
        for handler in logging.getLogger("quill").handlers:
            handler.flush()
        return (self.dir / diagnostics.LOG_NAME).read_text(encoding="utf-8")

    def test_creates_the_log_and_says_it_started(self):
        path = diagnostics.setup_logging(self.dir)
        self.assertEqual(path, self.dir / "quill.log")
        self.assertIn("Quill started", self.read())

    def test_app_log_lines_go_to_the_file(self):
        diagnostics.setup_logging(self.dir)
        window = MainWindow()
        window.setup()
        window.append_log("Connected to plants.xlsx")
        self.assertIn("Connected to plants.xlsx", self.read())

    def test_an_uncaught_error_is_logged_with_its_traceback(self):
        diagnostics.setup_logging(self.dir)
        try:
            raise ValueError("boom in main")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        text = self.read()
        self.assertIn("Uncaught error", text)
        self.assertIn("ValueError: boom in main", text)

    def test_an_error_in_a_background_thread_is_logged_too(self):
        diagnostics.setup_logging(self.dir)

        def work():
            raise RuntimeError("boom in thread")

        thread = threading.Thread(target=work, name="test-worker")
        thread.start()
        thread.join()
        text = self.read()
        self.assertIn("test-worker", text)
        self.assertIn("RuntimeError: boom in thread", text)

    def test_calling_it_twice_does_not_duplicate_lines(self):
        diagnostics.setup_logging(self.dir)
        diagnostics.setup_logging(self.dir)
        logging.getLogger("quill").info("only once")
        self.assertEqual(self.read().count("only once"), 1)

    def test_the_log_folder_exists_and_is_per_user(self):
        folder = diagnostics.log_dir()
        self.assertTrue(folder.is_dir())
        self.assertIn("Quill", str(folder))

    def test_main_sets_logging_up(self):
        text = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text()
        self.assertIn("setup_logging()", text)

    def test_settings_can_open_the_log_folder(self):
        opened = []
        d = SettingsDialog(Settings.load(self.dir / "cfg"), on_open_logs=lambda: opened.append(1))
        dlg = d.build()
        button = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Open Log Folder")
        button.click()
        self.assertEqual(opened, [1])


if __name__ == "__main__":
    unittest.main()
