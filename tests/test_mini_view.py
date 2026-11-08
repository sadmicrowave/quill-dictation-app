"""The mini view: a small always-handy overlay with only the row, start / stop and Needs sorting."""
import pathlib
import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.ui.main_window import LOG_OPEN_HEIGHT, MainWindow
from quill.ui.settings_dialog import SettingsDialog
from tests.test_app import FakeListener, FakeSpeaker
from tests.test_sorting import SENTENCE, DemoCase

_app = QApplication.instance() or QApplication([])

HIDDEN_IN_MINI = ("settings_button", "open_file_button",
                  "last_label", "log_toggle", "log", "undo_button")


def shown(window, name):
    return getattr(window, name).isVisibleTo(window.widget)


class TestMiniWindow(unittest.TestCase):
    def setUp(self):
        self.toggled = []
        self.w = MainWindow(on_mini_toggled=self.toggled.append)
        self.w.setup()
        self.w.widget.resize(460, 620)
        self.w.widget.show()
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

    def test_the_mini_view_keeps_the_buttons_and_the_way_back(self):
        self.w.set_mini(True)
        _app.processEvents()
        for name in ("wave", "toggle_button", "sorting_button", "mini_button"):
            self.assertTrue(shown(self.w, name), name)

    def test_the_default_mini_size_has_no_stream_or_row_but_a_taller_one_does(self):
        self.w.set_mini(True)
        _app.processEvents()
        self.assertFalse(shown(self.w, "row_table"))
        self.assertFalse(shown(self.w, "stream"))
        self.w.widget.resize(MainWindow.MINI_WIDTH, 260)
        _app.processEvents()
        self.assertTrue(shown(self.w, "row_table"))
        self.assertTrue(shown(self.w, "stream"))
        self.w.widget.resize(MainWindow.MINI_WIDTH, self.w._mini_base)
        _app.processEvents()
        self.assertFalse(shown(self.w, "row_table"))

    def test_the_mini_view_comes_back_at_the_size_the_user_left_it(self):
        self.w.set_mini(True)
        _app.processEvents()
        self.w.widget.resize(400, 300)
        _app.processEvents()
        self.w.report_size()
        self.w.set_mini(False)
        _app.processEvents()
        self.w.set_mini(True)
        _app.processEvents()
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (400, 300))
        self.assertTrue(shown(self.w, "row_table"))

    def test_the_mini_size_is_reported_on_its_own(self):
        reported = []
        w = MainWindow(on_mini_resized=lambda a, b: reported.append((a, b)))
        w.setup()
        w.widget.show()
        w.set_mini(True)
        _app.processEvents()
        w.widget.resize(380, 280)
        _app.processEvents()
        w.report_size()
        self.assertEqual(reported[-1], (380, 280))

    def test_a_remembered_mini_size_is_used(self):
        self.w.restore_mini_size(390, 310)
        self.w.set_mini(True)
        _app.processEvents()
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (390, 310))

    def test_the_wave_is_still_there_in_the_mini_view(self):
        self.w.set_mini(True)
        _app.processEvents()
        self.assertFalse(self.w.wave.active)
        self.w.set_listening_indicator(True)
        self.assertTrue(self.w.wave.active)
        self.assertTrue(shown(self.w, "wave"))

    def test_next_row_is_as_tall_as_the_start_button_in_both_views(self):
        self.w.set_listening_indicator(True)
        for mini in (False, True, False):
            self.w.set_mini(mini)
            _app.processEvents()
            self.assertEqual(self.w.next_button.height(), self.w.toggle_button.sizeHint().height())

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
        self.assertFalse(self.w.wave.active)

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

    def test_the_row_box_is_small_in_the_mini_view_and_always_there_in_the_full_one(self):
        self.w.set_mini(True)
        _app.processEvents()
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

    def test_undo_comes_back(self):
        self.w.set_mini(True)
        self.w.set_mini(False)
        _app.processEvents()
        for name in ("undo_button",):
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
        self.w.widget.resize(460, 620)
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
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (460, 620))

    def test_toggling_quickly_ends_in_the_right_place(self):
        for mini in (True, False, True):
            self.w.set_mini(mini)
        self.wait()
        self.assertEqual(self.w.widget.width(), MainWindow.MINI_WIDTH)

    def test_quick_toggle_there_and_back_restores_the_full_size(self):
        self.w.set_mini(True)
        self.w.set_mini(False)                       # before the first animation finished
        self.wait()
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (460, 620))

    def test_opening_the_log_slides_it_up_without_moving_the_window(self):
        self.w.set_log_collapsed(True)
        self.wait()
        full, table = self.w.widget.height(), self.w.row_table.height()
        self.w.set_log_collapsed(False)
        self.wait()
        self.assertEqual(self.w.widget.height(), full)               # the Current Row box gave the room
        self.assertLess(self.w.row_table.height(), table)
        self.assertEqual(self.w.log.height(), LOG_OPEN_HEIGHT)
        self.w.set_log_collapsed(True)
        self.wait()
        self.assertEqual((self.w.widget.height(), self.w.row_table.height()), (full, table))

    def test_the_log_grows_a_little_at_a_time(self):
        self.w.set_log_collapsed(True)
        self.wait()
        self.w.set_log_collapsed(False)
        self.assertLess(self.w.log.height(), LOG_OPEN_HEIGHT)        # not there at once
        self.wait()
        self.assertEqual(self.w.log.height(), LOG_OPEN_HEIGHT)

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
        self.assertGreater(self.app.window.row_table.rowCount(), 0)             # still filled, shown once the mini view is tall
        self.app.window.widget.resize(MainWindow.MINI_WIDTH, 300)
        _app.processEvents()
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


class TestRememberedSize(unittest.TestCase):
    def setUp(self):
        self.sizes = []
        self.w = MainWindow(on_resized=lambda w, h: self.sizes.append((w, h)))
        self.w.setup()
        self.w.widget.show()
        _app.processEvents()

    def test_the_settled_size_is_reported(self):
        from PySide6.QtTest import QTest
        self.w.widget.resize(430, 640)
        QTest.qWait(600)
        self.assertEqual(self.sizes[-1], (430, 640))

    def test_a_remembered_size_is_used_and_is_where_the_mini_view_returns_to(self):
        self.assertTrue(self.w.restore_size(500, 600))
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (500, 600))
        self.w.set_mini(True)
        self.w.set_mini(False)
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (500, 600))

    def test_nothing_saved_or_a_tiny_size_changes_nothing(self):
        before = self.w.widget.size()
        self.assertFalse(self.w.restore_size(0, 0))
        self.assertFalse(self.w.restore_size(100, 100))
        self.assertEqual(self.w.widget.size(), before)

    def test_the_mini_views_size_is_never_reported(self):
        self.w.set_mini(True)
        self.sizes.clear()
        self.w.report_size()
        self.assertEqual(self.sizes, [])

    def test_a_size_bigger_than_the_screen_is_trimmed(self):
        self.w.restore_size(90000, 90000)
        room = self.w.widget.screen().availableGeometry()
        self.assertLessEqual(self.w.widget.width(), room.width())


class TestVoiceStream(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.resize(460, 620)
        self.w.widget.show()
        from quill.stream import WordMatch
        self.w.set_stream_classifier(
            lambda words: [WordMatch(word in ("black", "large"), "Color" if word == "black" else None) for word in words])
        _app.processEvents()

    def test_the_box_is_there_with_no_title_above_it(self):
        self.assertFalse(hasattr(self.w, "row_heading"))
        self.assertEqual(self.w.stream.hint.text(), "Words you say appear here as they are heard.")
        self.assertTrue(self.w.stream.isReadOnly())
        self.assertTrue(self.w.stream.font().italic())

    def test_heard_words_appear_with_known_ones_as_pills(self):
        self.w.add_stream_text("a black shirt")
        self.assertEqual(self.w.stream_text(), "a black shirt")
        html = self.w.stream.toHtml()
        self.assertIn(self.w._accent.lower(), html.lower())          # the pill's colour
        self.assertIn("italic", html)

    def test_the_unfinished_phrase_is_shown_then_replaced_by_the_final_one(self):
        self.w.set_stream_partial("black")
        self.assertEqual(self.w.stream_text(), "black")
        self.w.add_stream_text("black large")
        self.assertEqual(self.w.stream_text(), "black large")

    def test_the_box_grows_with_the_text_up_to_a_limit(self):
        one = self.w.stream.height()
        self.w.add_stream_text(" ".join(["word"] * 60))
        _app.processEvents()
        self.assertGreater(self.w.stream.height(), one)
        self.w.add_stream_text(" ".join(["word"] * 600))
        _app.processEvents()
        line = self.w.stream.fontMetrics().lineSpacing()
        self.assertLessEqual(self.w.stream.height(), 5 * line + 30)
        self.assertTrue(self.w.stream.verticalScrollBar().maximum() > 0)

    def test_spoken_commands_are_left_out_of_the_stream(self):
        from quill.stream import WordMatch
        self.w.set_stream_classifier(lambda words: [
            WordMatch(True, command=word in ("next", "item")) for word in words])
        self.w.add_stream_text("black shirt next item")
        self.assertEqual(self.w.stream_text(), "black shirt")
        self.w.end_stream()
        self.w.add_stream_text("next item")                    # only a command: the finished row stays as it was
        self.assertEqual(self.w.stream_text(), "black shirt")

    def test_a_finished_row_stays_until_the_next_words_arrive(self):
        self.w.add_stream_text("black large")
        self.w.end_stream()
        self.assertEqual(self.w.stream_text(), "black large")
        self.w.add_stream_text("navy")
        self.assertEqual(self.w.stream_text(), "navy")

    def test_the_text_cannot_be_selected(self):
        self.assertEqual(self.w.stream.textInteractionFlags(), Qt.TextInteractionFlag.NoTextInteraction)


class TestSortingButtonSlidesIn(unittest.TestCase):
    def test_in_the_mini_view_start_makes_room_while_the_button_grows(self):
        from PySide6.QtTest import QTest
        MainWindow.animation_ms = 240
        w = MainWindow()
        w.setup()
        w.widget.show()
        w.set_mini(True)
        QTest.qWait(300)
        start = w.toggle_button.width()
        w.set_sorting_count(2)
        QTest.qWait(60)
        mid = w.sorting_button.width()
        self.assertLess(mid, w.sorting_button.sizeHint().width() + 1)
        QTest.qWait(400)
        end = w.sorting_button.width()
        self.assertGreater(end, mid - 1)
        self.assertLess(w.toggle_button.width(), start)                       # Start eased narrower
        self.assertIsNone(w.sorting_button.graphicsEffect())


class TestStreamWordColours(unittest.TestCase):
    def setUp(self):
        from quill.stream import WordMatch
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.show()
        self.w.refresh_icons("#EDEDED", "#FFFFFF", "#7A55C2")
        self.w.set_stream_classifier(
            lambda words: [WordMatch(word == "black", "Color" if word == "black" else None) for word in words])

    def colours(self):
        import re
        found = re.findall(r'<span style="([^"]*)"[^>]*>([^<]*)', self.w.stream.toHtml())
        return [(style, text.replace("&nbsp;", "").replace("\u00a0", "").strip()) for style, text in found]

    def test_words_still_being_spoken_start_in_the_normal_colour(self):
        self.w.set_stream_partial("hello")
        (style, word), = [c for c in self.colours() if c[1] == "hello"]
        self.assertIn("#ededed", style.lower())

    def test_once_final_a_word_that_was_not_understood_is_muted(self):
        self.w.set_stream_partial("hello")
        self.w.add_stream_text("hello black")
        styles = {word: style.lower() for style, word in self.colours()}
        self.assertNotIn("#ededed", styles["hello"])                         # muted now
        self.assertIn("background-color:#7a55c2", styles["black"])           # the pill

    def test_removing_a_column_takes_the_pill_off_its_words(self):
        self.w.add_stream_text("hello black")
        self.w.unmatch_stream_column("Color")
        self.assertNotIn("background-color:#7a55c2", self.w.stream.toHtml().lower())


class TestDeletableRows(unittest.TestCase):
    def setUp(self):
        self.removed = []
        self.w = MainWindow(on_field_removed=self.removed.append)
        self.w.setup()
        self.w.widget.resize(380, 560)
        self.w.widget.show()
        self.w.update_current_row({"Type": "Fern", "Size": "L"})
        _app.processEvents()
        self.table = self.w.row_table

    def hover(self, row):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        point = QPoint(self.table.viewport().width() - 40, self.table.rowViewportPosition(row) + 10)
        QTest.mouseMove(self.table.viewport(), point)
        _app.processEvents()

    def click_button(self, row):
        from PySide6.QtTest import QTest
        QTest.mouseClick(self.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         self.table.delete_button_rect(row).center())

    def test_hovering_a_line_shows_its_delete_button_and_clicking_it_removes_the_line(self):
        self.hover(1)
        self.assertEqual(self.table._hovered_row, 1)
        self.click_button(1)
        self.assertEqual(self.removed, ["Size"])
        self.assertEqual(self.table.rowCount(), 1)
        self.assertEqual(self.table.item(0, 0).text(), "Type")

    def test_clicking_elsewhere_in_the_line_does_nothing(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        self.hover(0)
        QTest.mouseClick(self.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 10))
        self.assertEqual(self.removed, [])
        self.assertEqual(self.table.rowCount(), 2)

    def test_the_cells_cannot_be_selected_or_edited(self):
        self.assertEqual(self.table.selectionMode(), self.table.SelectionMode.NoSelection)
        self.assertEqual(self.table.editTriggers(), self.table.EditTrigger.NoEditTriggers)
        self.assertEqual(self.table.focusPolicy(), Qt.FocusPolicy.NoFocus)


class TestPlaceholdersMatchToThePixel(unittest.TestCase):
    """The two empty boxes under the file picker must show their hints identically placed and styled."""

    def inked_box(self, window, widget, image):
        from PySide6.QtCore import QPoint
        top_left = widget.mapTo(window.widget, QPoint(0, 0))
        x0, y0, width, height = top_left.x(), top_left.y(), widget.width(), widget.height()
        background = image.pixelColor(x0 + width // 2, y0 + height - 4)
        xs, ys = [], []
        for y in range(y0 + 6, y0 + height - 6):                  # inside the border and the rounded corners
            for x in range(x0 + 6, x0 + width - 6):
                pixel = image.pixelColor(x, y)
                if (abs(pixel.red() - background.red()) + abs(pixel.green() - background.green())
                        + abs(pixel.blue() - background.blue())) > 60:
                    xs.append(x - x0)
                    ys.append(y - y0)
        return min(xs), max(xs), min(ys), max(ys)

    def windows(self):
        from PySide6.QtTest import QTest
        from quill.ui.theme import apply_spacing, apply_theme
        for spacing in ("compact", "comfortable"):
            apply_theme(_app, "dark", "violet", spacing)                # the same look whatever ran before
            window = MainWindow()
            window.setup()
            window.refresh_icons("#EDEDED", "#FFFFFF", "#7A55C2")
            apply_spacing(window.widget, spacing)
            window.widget.resize(380, 420)
            window.widget.show()
            QTest.qWait(80)                                             # let the layout and the hints settle
            yield spacing, window

    def test_the_hints_use_the_same_font_colour_and_position_in_their_boxes(self):
        from PySide6.QtCore import QPoint
        for spacing, window in self.windows():
            stream_hint, grid_hint = window.stream.hint, window.row_placeholder
            self.assertEqual(stream_hint.font(), grid_hint.font(), spacing)
            self.assertEqual(stream_hint.palette().windowText().color(), grid_hint.palette().windowText().color(), spacing)
            self.assertEqual(stream_hint.mapTo(window.stream, QPoint(0, 0)),
                             grid_hint.mapTo(window.row_table, QPoint(0, 0)), spacing)

    def test_the_same_words_are_drawn_to_the_same_pixels_in_both_boxes(self):
        for spacing, window in self.windows():
            text = "Hamburgefonstiv sample hint"
            window.stream.hint.setText(text)
            window.row_placeholder.setText(text)
            from PySide6.QtTest import QTest
            QTest.qWait(40)
            window.row_grip.allowed = False                      # (its drag dots are not part of the placeholder)
            window.row_grip.hide()
            image = window.widget.grab().toImage()
            self.assertEqual(self.inked_box(window, window.stream, image),
                             self.inked_box(window, window.row_table, image), spacing)


class TestOldMiniSizeIsWidened(unittest.TestCase):
    def test_a_remembered_width_below_the_current_minimum_is_raised(self):
        w = MainWindow()
        w.setup()
        w.restore_mini_size(300, 200)
        self.assertEqual(w._mini_size.width(), MainWindow.MINI_WIDTH)
        w.restore_mini_size(520, 200)
        self.assertEqual(w._mini_size.width(), 520)


class TestSizeAfterCloseAndReopen(unittest.TestCase):
    """macOS gives a reopened window a different title bar, so it came back taller each time; it must come back as it was."""

    def wait(self, ms):
        import time
        end = time.time() + ms / 1000
        while time.time() < end:
            _app.processEvents()
            time.sleep(0.005)

    def test_a_window_that_comes_back_bigger_is_put_back_and_the_bigger_size_is_never_saved(self):
        w = MainWindow()
        w.setup()
        reported = []
        w._on_resized = lambda width, height: reported.append((width, height))
        w.widget.show()
        w.widget.resize(560, 700)
        self.wait(100)
        w.widget.hide()
        self.assertEqual((w._reshow_size.width(), w._reshow_size.height()), (560, 700))
        w.widget.move(120, 140)
        w.widget.hide()
        spot = w._reshow_pos
        w.widget.show()
        w.widget.resize(560, 728)                                  # what the system did: 28 more ...
        w.widget.move(spot.x(), spot.y() + 24)                     # ... and 24 lower
        self.wait(1300)
        self.assertEqual((w.widget.width(), w.widget.height()), (560, 700))
        self.assertEqual((w.widget.pos().x(), w.widget.pos().y()), (spot.x(), spot.y()))
        self.assertNotIn((560, 728), reported)
        self.assertFalse(w._reshowing)
        w.widget.hide()
        w.widget.show()
        w.widget.resize(560, 720)
        self.wait(1300)
        self.assertEqual(w.widget.height(), 700)                    # every time

    def test_a_window_shown_for_the_first_time_is_left_alone(self):
        w = MainWindow()
        w.setup()
        w.widget.resize(520, 600)
        w.widget.show()
        self.wait(1100)
        self.assertEqual((w.widget.width(), w.widget.height()), (520, 600))

    def test_the_mini_view_gets_its_own_size_back_not_the_full_windows(self):
        w = MainWindow()
        w.setup()
        w.widget.show()
        w.set_mini(True)
        self.wait(200)
        mini = (w.widget.width(), w.widget.height())
        w.widget.hide()
        self.assertEqual((w._reshow_size.width(), w._reshow_size.height()), mini)
        w.widget.show()
        w.widget.resize(mini[0], mini[1] + 28)
        self.wait(1300)
        self.assertEqual((w.widget.width(), w.widget.height()), mini)
