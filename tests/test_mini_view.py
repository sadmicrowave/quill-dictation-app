"""The mini view: a small always-handy overlay with only the row, start / stop and Needs sorting."""
import pathlib
import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.ui.main_window import MainWindow
from quill.ui.settings_dialog import SettingsDialog
from tests.test_app import FakeListener, FakeSpeaker
from tests.test_sorting import SENTENCE, DemoCase

_app = QApplication.instance() or QApplication([])

HIDDEN_IN_MINI = ("state_label", "settings_button", "workbook_row", "sheet_label", "row_toggle",
                  "last_label", "log_toggle", "log", "footer", "download_button", "undo_button")


def shown(window, name):
    return getattr(window, name).isVisibleTo(window.widget)


class TestMiniWindow(unittest.TestCase):
    def setUp(self):
        self.toggled = []
        self.w = MainWindow(on_mini_toggled=self.toggled.append)
        self.w.setup()
        self.w.widget.resize(360, 620)
        self.w.widget.show()
        self.w.set_footer("Some status", offer_download=True)
        self.w.set_undo_count(2)
        self.w.set_sorting_count(3)
        _app.processEvents()

    def test_the_full_view_shows_everything(self):
        for name in HIDDEN_IN_MINI:
            self.assertTrue(shown(self.w, name), name)

    def test_the_mini_view_hides_the_log_saved_line_and_workbook_details(self):
        self.w.set_mini(True)
        _app.processEvents()
        for name in HIDDEN_IN_MINI:
            self.assertFalse(shown(self.w, name), name)

    def test_the_mini_view_keeps_the_row_the_buttons_and_the_way_back(self):
        self.w.set_mini(True)
        _app.processEvents()
        for name in ("dot", "toggle_button", "row_table", "sorting_button", "mini_button"):
            self.assertTrue(shown(self.w, name), name)

    def test_the_buttons_shrink_to_icons(self):
        self.w.set_mini(True)
        self.assertEqual(self.w.toggle_button.text(), "")
        self.assertFalse(self.w.toggle_button.icon().isNull())
        self.assertEqual(self.w.toggle_button.toolTip(), "Start listening")
        self.assertFalse(self.w.sorting_title.isVisibleTo(self.w.widget))
        self.assertEqual(self.w.badge_label.text(), "3")                  # just the count pill
        self.w.set_listening_indicator(True)
        self.assertEqual((self.w.toggle_button.text(), self.w.toggle_button.toolTip()), ("", "Stop listening"))

    def test_the_window_becomes_small_and_comes_back_to_its_size(self):
        full = self.w.widget.size()
        self.w.set_mini(True)
        _app.processEvents()
        small = self.w.widget.size()
        self.assertEqual(small.width(), MainWindow.MINI_WIDTH)
        self.assertLess(small.height(), 260)
        self.assertLess(small.height() * 2, full.height())
        self.w.set_mini(False)
        _app.processEvents()
        self.assertEqual(self.w.widget.size(), full)
        self.assertEqual(self.w.toggle_button.text(), "Start")

    def test_the_row_box_is_small_but_always_there(self):
        self.w.set_row_collapsed(True)
        self.w.set_mini(True)
        _app.processEvents()
        self.assertTrue(shown(self.w, "row_table"))                         # shown even if collapsed in the full view
        self.assertLessEqual(self.w.row_table.maximumHeight(), 110)
        self.w.set_mini(False)
        _app.processEvents()
        self.assertFalse(shown(self.w, "row_table"))                        # the full view remembers it was collapsed

    def test_sections_keep_their_state_through_a_round_trip(self):
        self.w.set_log_collapsed(True)
        self.w.set_mini(True)
        self.w.set_mini(False)
        _app.processEvents()
        self.assertFalse(shown(self.w, "log"))
        self.assertTrue(shown(self.w, "log_toggle"))

    def test_footer_download_and_undo_come_back(self):
        self.w.set_mini(True)
        self.w.set_mini(False)
        _app.processEvents()
        for name in ("footer", "download_button", "undo_button"):
            self.assertTrue(shown(self.w, name), name)

    def test_button_in_the_status_row_toggles_and_reports(self):
        self.w.mini_button.click()
        self.assertTrue(self.w.mini)
        self.w.mini_button.click()
        self.assertFalse(self.w.mini)
        self.assertEqual(self.toggled, [True, False])
        self.w.set_mini(True)
        self.assertEqual(self.toggled, [True, False])                       # programmatic changes don't notify

    def test_the_button_tooltip_and_icon_follow_the_view(self):
        self.assertEqual(self.w.mini_button.toolTip(), "Mini view")
        self.w.set_mini(True)
        self.assertEqual(self.w.mini_button.toolTip(), "Back to the full window")
        self.assertFalse(self.w.mini_button.icon().isNull())

    def test_the_needs_sorting_button_hides_with_no_terms_in_either_view(self):
        self.w.set_sorting_count(0)
        self.w.set_mini(True)
        self.assertFalse(shown(self.w, "sorting_button"))

    def test_floats_on_top_only_in_the_mini_view(self):
        flag = Qt.WindowType.WindowStaysOnTopHint
        self.assertFalse(self.w.widget.windowFlags() & flag)
        self.w.set_mini(True)
        self.assertTrue(self.w.widget.windowFlags() & flag)
        self.w.set_mini(False)
        self.assertFalse(self.w.widget.windowFlags() & flag)

    def test_staying_on_top_can_be_turned_off(self):
        flag = Qt.WindowType.WindowStaysOnTopHint
        self.w.set_mini_on_top(False)
        self.w.set_mini(True)
        self.assertFalse(self.w.widget.windowFlags() & flag)
        self.w.set_mini_on_top(True)
        self.assertTrue(self.w.widget.windowFlags() & flag)

    def test_starting_in_the_mini_view(self):
        w = MainWindow(mini=True)
        w.setup()
        w.widget.show()
        _app.processEvents()
        self.assertTrue(w.mini)
        self.assertFalse(shown(w, "log"))
        self.assertEqual(w.widget.width(), MainWindow.MINI_WIDTH)

    def test_collapsing_a_section_while_mini_does_not_disturb_the_size(self):
        self.w.set_mini(True)
        _app.processEvents()
        size = self.w.widget.size()
        self.w.set_log_collapsed(True)
        self.assertEqual(self.w.widget.size(), size)


class TestMiniInTheApp(DemoCase):
    def setUp(self):
        super().setUp()
        self.listeners = []
        self.app = QuillApp(_app, self.settings, XlsxBridge(self.path),
                            listener_factory=lambda *a: self.listeners.append(FakeListener(*a)) or self.listeners[-1],
                            model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None)
        self.app.start()

    def test_the_choice_is_remembered(self):
        self.app.window.mini_button.click()
        self.assertTrue(Settings.load(self.dir / "cfg").preferences["mini_mode"])
        self.app.window.mini_button.click()
        self.assertFalse(Settings.load(self.dir / "cfg").preferences["mini_mode"])

    def test_it_starts_mini_when_it_was_left_mini(self):
        self.settings.preferences["mini_mode"] = True
        app = QuillApp(_app, self.settings, XlsxBridge(self.path), listener_factory=lambda *a: FakeListener(*a),
                       model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None)
        app.start()
        self.assertTrue(app.window.mini)
        self.assertTrue(app.tray.mini_action.isChecked())

    def test_the_tray_menu_toggles_it_and_stays_in_step(self):
        self.assertIsNotNone(self.app.tray.mini_action)
        self.assertTrue(self.app.tray.mini_action.isCheckable())
        self.app.tray.mini_action.setChecked(True)
        self.assertTrue(self.app.window.mini)
        self.app.window.mini_button.click()                                 # leave via the window
        self.assertFalse(self.app.tray.mini_action.isChecked())

    def test_dictation_still_shows_in_the_mini_row(self):
        self.app.window.set_mini(True)
        self.app.controller.handle_transcript("start listening")
        self.app.controller.handle_transcript("t-shirt thirty five dollars")
        _app.processEvents()
        self.assertGreater(self.app.window.row_table.rowCount(), 0)
        self.assertTrue(self.app.window.row_table.isVisibleTo(self.app.window.widget))

    def test_needs_sorting_count_shows_in_the_mini_view(self):
        self.app.window.set_mini(True)
        self.app.controller.handle_transcript("start listening")
        self.app.controller.handle_transcript(SENTENCE)
        self.app.controller.handle_transcript("next row")
        _app.processEvents()
        self.assertEqual(self.app.window.badge_label.text(), "3")
        self.assertTrue(self.app.window.sorting_button.isVisibleTo(self.app.window.widget))

    def test_the_sorting_button_still_opens_the_list_from_the_mini_view(self):
        opened = []
        w = MainWindow(on_sorting=lambda: opened.append(1), mini=True)
        w.setup()
        w.widget.show()
        w.set_sorting_count(2)
        w.sorting_button.click()
        self.assertEqual(opened, [1])

    def test_the_mic_button_works_from_the_mini_view(self):
        self.app.window.set_mini(True)
        self.app.window.toggle_button.click()
        self.assertTrue(self.app.controller.session.listening)
        self.assertTrue(self.listeners[0].started)

    def test_the_setting_to_keep_it_on_top_applies_live(self):
        flag = Qt.WindowType.WindowStaysOnTopHint
        self.app.window.set_mini(True)
        self.assertTrue(self.app.window.widget.windowFlags() & flag)
        self.settings.preferences["mini_on_top"] = False
        self.app.apply_settings(quiet=True)
        self.assertFalse(self.app.window.widget.windowFlags() & flag)

    def test_settings_has_the_on_top_switch(self):
        d = SettingsDialog(self.settings)
        d.build()
        self.assertTrue(d.mini_top_check.isChecked())
        d.mini_top_check.setChecked(False)
        self.assertTrue(d.try_accept())
        self.assertFalse(Settings.load(self.dir / "cfg").preferences["mini_on_top"])

    def test_the_title_bar_styling_is_reapplied_after_the_window_is_recreated(self):
        calls = []
        self.app._apply_look = lambda: calls.append(1)
        self.app.window.mini_button.click()
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
