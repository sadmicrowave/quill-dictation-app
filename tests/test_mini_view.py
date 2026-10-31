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

HIDDEN_IN_MINI = ("settings_button", "workbook_row", "sheet_label", "row_heading",
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
        self.w.set_last_saved("Row 4", {"Type": "Fern"})
        _app.processEvents()

    def test_last_saved_stays_hidden_until_something_was_saved(self):
        fresh = MainWindow()
        fresh.setup()
        fresh.widget.show()
        _app.processEvents()
        self.assertFalse(shown(fresh, "last_label"))
        fresh.set_last_saved("Row 2")
        _app.processEvents()
        self.assertTrue(shown(fresh, "last_label"))

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
        for name in ("dot", "state_label", "toggle_button", "row_table", "sorting_button", "mini_button"):
            self.assertTrue(shown(self.w, name), name)

    def test_the_state_text_is_still_there_in_the_mini_view(self):
        self.w.set_mini(True)
        _app.processEvents()
        self.assertEqual(self.w.state_label.text(), "Not Listening")
        self.w.set_listening_indicator(True)
        self.assertEqual(self.w.state_label.text(), "Listening")
        self.assertTrue(shown(self.w, "state_label"))

    def test_the_buttons_shrink_to_icons(self):
        self.w.set_mini(True)
        self.assertEqual(self.w.toggle_button.text(), "")
        self.assertFalse(self.w.toggle_icon.pixmap().isNull())
        self.assertEqual(self.w.toggle_button.toolTip(), "Start Listening")
        self.assertFalse(self.w.sorting_title.isVisibleTo(self.w.widget))
        self.assertEqual(self.w.badge_label.text(), "3")                  # just the count pill
        self.w.set_listening_indicator(True)
        self.assertEqual((self.w.toggle_button.text(), self.w.toggle_button.toolTip()), ("", "Stop Listening"))

    def test_the_window_becomes_small_and_comes_back_to_its_size(self):
        full = self.w.widget.size()
        self.w.set_mini(True)
        _app.processEvents()
        small = self.w.widget.size()
        self.assertEqual(small.width(), MainWindow.MINI_WIDTH)
        self.assertLess(small.height(), 130)                  # shorter than the first version (164)
        self.assertLess(small.height() * 2, full.height())
        self.w.set_mini(False)
        _app.processEvents()
        self.assertEqual(self.w.widget.size(), full)
        self.assertEqual(self.w.state_label.text(), "Not Listening")

    def test_the_needs_sorting_count_moves_into_the_status_row(self):
        row = self.w._status_row
        self.assertEqual(row.indexOf(self.w.sorting_button), -1)
        self.w.set_mini(True)
        self.assertGreaterEqual(row.indexOf(self.w.sorting_button), 0)
        self.assertGreater(row.indexOf(self.w.sorting_button), row.indexOf(self.w.toggle_button))
        self.w.set_mini(False)
        self.assertEqual(row.indexOf(self.w.sorting_button), -1)
        self.assertEqual(self.w._layout.indexOf(self.w.sorting_button), self.w._sorting_index)

    def test_the_mini_view_has_tight_margins_and_the_full_view_gets_its_own_back(self):
        full = self.w._layout.contentsMargins().left()
        self.w.set_mini(True)
        self.assertEqual(self.w._layout.contentsMargins().left(), 10)
        self.w.set_mini(False)
        self.assertEqual(self.w._layout.contentsMargins().left(), full)

    def test_density_changes_keep_the_mini_margins(self):
        self.w.set_mini(True)
        self.w.apply_density("comfortable")
        self.assertEqual(self.w._layout.contentsMargins().left(), 10)

    def test_the_resize_button_is_just_an_icon_without_a_box(self):
        from PySide6.QtWidgets import QToolButton
        self.assertIsInstance(self.w.mini_button, QToolButton)
        self.assertTrue(self.w.mini_button.autoRaise())
        self.assertTrue(self.w.mini_button.property("flatIcon"))
        from quill.ui import theme
        sheet = theme.stylesheet_for(False)
        start = sheet.index('QToolButton[flatIcon="true"] {')
        rule = sheet[start: sheet.index("}", start)]
        self.assertIn("border: none", rule)
        self.assertIn("background: transparent", rule)

    def test_the_row_box_is_small_but_always_there(self):
        self.w.set_mini(True)
        _app.processEvents()
        self.assertTrue(shown(self.w, "row_table"))
        self.assertLessEqual(self.w.row_table.minimumHeight(), 70)
        self.w.set_mini(False)
        _app.processEvents()
        self.assertTrue(shown(self.w, "row_table"))                         # and never hidden in the full view

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
        self.assertEqual(self.w.mini_button.toolTip(), "Mini View")
        self.w.set_mini(True)
        self.assertEqual(self.w.mini_button.toolTip(), "Back to the Full Window")
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


class TestResizeAnimation(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.resize(360, 620)
        self.w.widget.show()
        MainWindow.animation_ms = 120
        _app.processEvents()

    def tearDown(self):
        MainWindow.animation_ms = 0

    def wait(self):
        from PySide6.QtTest import QTest
        QTest.qWait(260)

    def test_entering_the_mini_view_eases_instead_of_jumping(self):
        self.w.set_mini(True)
        self.assertGreater(self.w.widget.height(), 400, "it must not jump straight to the small size")
        self.assertEqual(self.w._animation.endValue().width(), MainWindow.MINI_WIDTH)
        self.wait()
        self.assertEqual(self.w.widget.width(), MainWindow.MINI_WIDTH)
        self.assertLess(self.w.widget.height(), 150)

    def test_leaving_eases_back_to_the_old_size(self):
        self.w.set_mini(True)
        self.wait()
        self.w.set_mini(False)
        self.assertLess(self.w.widget.height(), 200, "starts from the small size")
        self.wait()
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (360, 620))

    def test_toggling_quickly_ends_in_the_right_place(self):
        for mini in (True, False, True):
            self.w.set_mini(mini)
        self.wait()
        self.assertEqual(self.w.widget.width(), MainWindow.MINI_WIDTH)

    def test_quick_toggle_there_and_back_restores_the_full_size(self):
        self.w.set_mini(True)
        self.w.set_mini(False)                       # before the first animation finished
        self.wait()
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (360, 620))

    def test_collapsing_the_log_eases_too_and_reopening_restores_exactly(self):
        full = self.w.widget.height()
        self.w.set_log_collapsed(True)
        self.assertGreater(self.w.widget.height(), full - 50)
        self.wait()
        self.assertLess(self.w.widget.height(), full - 100)
        self.w.set_log_collapsed(False)
        self.wait()
        self.assertEqual(self.w.widget.height(), full)

    def test_a_hidden_window_resizes_at_once(self):
        w = MainWindow()
        w.setup()
        w.set_mini(True)
        self.assertEqual(w.widget.width(), MainWindow.MINI_WIDTH)

    def test_animation_can_be_switched_off(self):
        MainWindow.animation_ms = 0
        self.w.set_mini(True)
        self.assertEqual(self.w.widget.width(), MainWindow.MINI_WIDTH)


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

    def test_the_menu_bar_menu_has_no_mini_view_item(self):
        titles = [action.text() for action in self.app.tray._menu.actions()]
        self.assertNotIn("Mini View", titles)
        self.assertFalse(hasattr(self.app.tray, "mini_action"))

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
