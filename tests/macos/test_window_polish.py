"""Connection chip, minimized Log at the bottom, title-bar Settings icon, Current Row sizing, alignment."""
import pathlib
import re
import tempfile
import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from quill.platforms.macos import chrome
from quill.config.settings import Settings
from quill.ui import theme
from quill.ui.main_window import (
    CHIP_HEIGHT, LOG_BOTTOM_MARGIN, NOT_CONNECTED_HINT, NOT_CONNECTED_TEXT, ROW_EMPTY_HEIGHT, ROW_MAX_FULL, ROW_MAX_MINI,
    MainWindow,
)
from quill.ui.settings_widgets import SettingRow, ToggleSwitch
from tests.macos.test_titlebar_and_refresh import FakeAppKit, FakeButton, FakeController, FakeTarget, native, restore

_app = QApplication.instance() or QApplication([])

FIRST_PERSON = re.compile(r"\b(I|I'm|I've|I'll|I'd|me|my|mine|we|our|us)\b")


def window(**kw):
    w = MainWindow(**kw)
    w.setup()
    w.widget.resize(360, 560)
    w.widget.show()
    _app.processEvents()
    return w


def left(widget, root):
    return widget.mapTo(root, widget.rect().topLeft()).x()


def right(widget, root):
    return widget.mapTo(root, widget.rect().topRight()).x()


class TestConnectionChip(unittest.TestCase):
    """"File not connected" is said by the Start button itself (the old separate pill is gone)."""

    def test_says_file_not_connected(self):
        self.assertEqual(NOT_CONNECTED_TEXT, "File not connected")
        w = window()
        w.set_not_connected(True)
        self.assertEqual(w.toggle_button.text_pill.text(), "File not connected")
        self.assertEqual(w.toggle_button.notice_text, "File not connected")

    def test_shown_in_place_of_start_listening_until_connected(self):
        w = window()
        self.assertFalse(w.toggle_button.notice)                              # until a failure is reported
        self.assertEqual(w.toggle_button.text_pill.text(), "Start Listening")
        w.set_not_connected(True)
        _app.processEvents()
        self.assertTrue(w.toggle_button.notice)
        self.assertEqual(w.toggle_button.text_pill.text(), "File not connected")

    def test_back_to_start_listening_once_connected(self):
        w = window()
        w.set_not_connected(True)
        w.set_not_connected(False)
        _app.processEvents()
        self.assertFalse(w.toggle_button.notice)
        self.assertEqual(w.toggle_button.text_pill.text(), "Start Listening")

    def test_the_tooltip_explains_in_technical_third_person_terms(self):
        hint = NOT_CONNECTED_HINT
        self.assertFalse(FIRST_PERSON.search(hint), FIRST_PERSON.search(hint))
        self.assertIn("No spreadsheet is connected", hint)
        self.assertIn("spreadsheet program", hint)
        self.assertIn(".xlsx", hint)
        self.assertIn("File > Open File", hint)
        w = window()
        w.set_not_connected(True)
        tip = w.toggle_button.toolTip()
        self.assertFalse(FIRST_PERSON.search(tip), FIRST_PERSON.search(tip))
        for part in ("Not connected", "read lists from", "write rows to"):
            self.assertIn(part, tip)
        self.assertNotIn("<", tip)                                                 # plain text, like every other tooltip
        self.assertTrue(tip.isascii())                                             # no emoji or symbols

    def test_the_app_supplied_hint_has_no_first_person_either(self):
        from quill.controller import NO_WORKBOOK_HELP
        self.assertFalse(FIRST_PERSON.search(NO_WORKBOOK_HELP), NO_WORKBOOK_HELP)

    def test_a_custom_hint_replaces_the_tooltip(self):
        w = window()
        w.set_not_connected(True, "Custom hint")
        self.assertIn("Custom hint", w.toggle_button.toolTip())

    def test_still_said_in_the_mini_view_where_the_sheet_name_is_not(self):
        w = window()
        w.set_not_connected(True)
        w.set_mini(True)
        _app.processEvents()
        self.assertTrue(w.toggle_button.notice)
        self.assertEqual(w.toggle_button.text_pill.text(), "File not connected")

    def test_the_words_sit_between_the_icon_disc_and_the_screen_and_the_button_keeps_its_height(self):
        w = window()
        w.set_not_connected(True)
        w.widget.show()
        w.widget.resize(360, 900)
        _app.processEvents()
        button = w.toggle_button
        height = button.height()
        self.assertEqual(height, button.HEIGHT)
        icon_x = button.icon_label.mapTo(button, button.icon_label.rect().topLeft()).x()
        text_x = button.text_pill.mapTo(button, button.text_pill.rect().topLeft()).x()
        screen_x = button.screen.mapTo(button, button.screen.rect().topLeft()).x()
        self.assertLess(icon_x, 12)                                                 # the disc is at the left edge
        self.assertLess(icon_x, text_x)
        self.assertLess(text_x, screen_x)
        w.widget.resize(360, 400)
        _app.processEvents()
        self.assertEqual(button.height(), height)                                   # (a taller or shorter window changes nothing)

    def test_nothing_about_the_connection_appears_at_the_bottom(self):
        w = window()
        w.set_not_connected(True)
        _app.processEvents()
        from PySide6.QtWidgets import QLabel
        self.assertNotIn("not connected", " ".join(label.text().lower() for label in w.footer.findChildren(QLabel)))


class TestLogAtTheBottom(unittest.TestCase):
    def test_minimized_by_default_for_everyone(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(Settings.load(pathlib.Path(tmp)).preferences["log_collapsed"])
        w = window(log_collapsed=True)
        self.assertFalse(w.log.isVisibleTo(w.widget))

    def gap(self, w):
        return w.root.height() - w.log_toggle.mapTo(w.root, w.log_toggle.rect().bottomLeft()).y() - 1

    def test_only_a_small_margin_below_log_when_minimized(self):
        for spacing in ("compact", "comfortable"):
            w = window(log_collapsed=True)
            w.apply_density(spacing)
            _app.processEvents()
            self.assertEqual(self.gap(w), LOG_BOTTOM_MARGIN, spacing)
            self.assertTrue(5 <= LOG_BOTTOM_MARGIN <= 10)

    def test_nothing_at_all_is_below_the_log_heading(self):
        w = window(log_collapsed=True)
        w.set_sorting_count(2)
        w.set_undo_count(1)
        _app.processEvents()
        lowest = max(child.mapTo(w.root, child.rect().bottomLeft()).y()
                     for child in w.root.children() if hasattr(child, "isVisibleTo") and child.isVisibleTo(w.root))
        self.assertEqual(lowest, w.log_toggle.mapTo(w.root, w.log_toggle.rect().bottomLeft()).y())

    def test_the_footer_keeps_the_same_small_margin_whether_the_log_is_open_or_not(self):
        w = window(log_collapsed=True)
        self.assertEqual(w.root.layout().contentsMargins().bottom(), LOG_BOTTOM_MARGIN)
        w.log_toggle.click()
        _app.processEvents()
        self.assertEqual(w.root.layout().contentsMargins().bottom(), LOG_BOTTOM_MARGIN)     # (the footer is last either way)
        w.log_toggle.click()
        _app.processEvents()
        self.assertEqual(w.root.layout().contentsMargins().bottom(), LOG_BOTTOM_MARGIN)

    def test_the_window_has_no_spare_space_under_the_log_heading(self):
        w = window(log_collapsed=True)
        MainWindow.animation_ms = 0
        w.log_toggle.click()
        w.log_toggle.click()
        _app.processEvents()
        self.assertLessEqual(self.gap(w), LOG_BOTTOM_MARGIN + 6)

    def test_the_mini_view_keeps_its_own_margins(self):
        w = window(log_collapsed=True)
        w.set_mini(True)
        self.assertEqual(w.root.layout().contentsMargins().bottom(), 8)


class TestTitlebarSettings(unittest.TestCase):
    def tearDown(self):
        restore()

    def test_settings_goes_left_of_the_resize_icon_in_one_accessory(self):
        native()
        kit = FakeAppKit()
        opened, resized = [], []
        button = chrome.add_titlebar_button(_fake_widget(), lambda: resized.append(1), platform="darwin", appkit=kit,
                                            extra=[(chrome.SYMBOL_SETTINGS, "Settings", lambda: opened.append(1))])
        stack = kit.window.accessories[0].view.subviews[0]            # the row sits in a plain holder view
        self.assertEqual(len(stack.subviews), 2)
        self.assertGreater(stack.frame[1][0], 40)                         # it has a width, or macOS would not show it
        settings, resize = stack.subviews
        self.assertEqual((settings.frame[1], resize.frame[1]), ((chrome._ICON_WIDTH, chrome._ICON_HEIGHT),) * 2)     # every icon has the same box
        self.assertEqual(settings.image, f"image:{chrome.SYMBOL_SETTINGS}")
        self.assertEqual(settings.tip, "Settings")
        settings.performClick_(None)
        resize.performClick_(None)
        self.assertEqual((opened, resized), ([1], [1]))                  # each icon calls its own action
        self.assertEqual(kit.window.accessories[0].layout, 2)             # right side of the title bar
        self.assertIs(button._button, resize)                             # the resize icon stays the one that swaps

    def test_a_lone_icon_sits_in_a_holder_with_a_margin_on_its_right_like_every_other_group(self):
        native()
        kit = FakeAppKit()
        button = chrome.add_titlebar_button(_fake_widget(), lambda: None, platform="darwin", appkit=kit)
        holder = kit.window.accessories[0].view
        self.assertNotIsInstance(holder, FakeButton)
        self.assertEqual(button._base_width, chrome._ICON_WIDTH + chrome._RIGHT_MARGIN)
        self.assertEqual(button._row_x, 0.0)

    def test_the_settings_icon_is_a_known_symbol(self):
        self.assertEqual(chrome.SYMBOL_SETTINGS, "slider.horizontal.3")


def _fake_widget():
    from PySide6.QtWidgets import QWidget
    return QWidget()


class TestStatusRowWithTheIconsInTheTitleBar(unittest.TestCase):
    def test_start_is_the_right_most_control_once_settings_and_resize_move_out(self):
        w = window()
        w.set_native_mini_button(True)
        w.set_native_settings_button(True)
        w.set_native_file_button(True)
        w.set_native_turn_button(True)
        w.set_native_undo_button(True)
        w.set_native_help_button(True)
        _app.processEvents()
        row = w._status_row
        visible = [row.itemAt(i).widget() for i in range(row.count())
                   if row.itemAt(i).widget() is not None and row.itemAt(i).widget().isVisibleTo(w.widget)]
        self.assertIs(visible[-1], w.toggle_button)
        self.assertFalse(w.settings_button.isVisibleTo(w.widget))
        self.assertFalse(w.mini_button.isVisibleTo(w.widget))

    def test_without_a_native_title_bar_the_window_keeps_its_own_icons(self):
        w = window()
        self.assertTrue(w.settings_button.isVisibleTo(w.widget))
        self.assertTrue(w.mini_button.isVisibleTo(w.widget))

    def test_start_reaches_the_right_margin(self):
        w = window()
        w.set_native_mini_button(True)
        w.set_native_settings_button(True)
        w.set_native_file_button(True)
        w.set_native_turn_button(True)
        w.set_native_undo_button(True)
        w.set_native_help_button(True)
        _app.processEvents()
        self.assertEqual(right(w.toggle_button, w.root), w.root.width() - w.root.layout().contentsMargins().right() - 1)

    def test_the_settings_icon_returns_in_the_window_for_the_full_view_only(self):
        w = window()
        w.set_mini(True)
        self.assertFalse(w.settings_button.isVisibleTo(w.widget))


class TestCurrentRowSizing(unittest.TestCase):
    def setUp(self):
        self.w = window()
        MainWindow.animation_ms = 0

    def fields(self, n):
        return {f"Column {i}": f"value {i}" for i in range(n)}

    def test_starts_small_with_a_hint(self):
        self.assertEqual(self.w.row_table.minimumHeight(), ROW_EMPTY_HEIGHT)
        self.assertTrue(self.w.row_placeholder.isVisibleTo(self.w.widget))
        self.assertLess(ROW_EMPTY_HEIGHT, 60)

    def test_grows_with_the_fields_then_stops_at_the_cap(self):
        heights = []
        for n in range(1, 12):
            self.w.update_current_row(self.fields(n))
            heights.append(self.w.row_table.minimumHeight())
        self.assertEqual(heights, sorted(heights))
        self.assertGreater(heights[3], heights[0])
        self.assertEqual(heights[-1], ROW_MAX_FULL)
        self.assertEqual(heights.count(ROW_MAX_FULL), len(heights) - heights.index(ROW_MAX_FULL))

    def test_past_the_cap_it_scrolls_inside_itself(self):
        self.w.update_current_row(self.fields(20))
        _app.processEvents()
        self.assertEqual(self.w.row_table.minimumHeight(), ROW_MAX_FULL)
        self.assertGreater(self.w.row_table.verticalScrollBar().maximum(), 0)

    def test_a_few_fields_do_not_scroll(self):
        self.w.update_current_row(self.fields(3))
        _app.processEvents()
        self.assertEqual(self.w.row_table.verticalScrollBar().maximum(), 0)

    def test_shrinks_back_and_shows_the_hint_after_the_row_is_saved(self):
        self.w.update_current_row(self.fields(6))
        self.w.update_current_row({})
        self.assertEqual(self.w.row_table.minimumHeight(), ROW_EMPTY_HEIGHT)
        self.assertTrue(self.w.row_placeholder.isVisibleTo(self.w.widget))

    def test_the_hint_goes_away_while_there_are_fields(self):
        self.w.update_current_row(self.fields(1))
        self.assertFalse(self.w.row_placeholder.isVisibleTo(self.w.widget))

    def test_a_tight_window_grows_to_fit_the_fields(self):
        self.w.widget.resize(360, self.w._fit_height())          # no spare room
        _app.processEvents()
        before = self.w.widget.height()
        self.w.update_current_row(self.fields(4))
        _app.processEvents()
        self.assertGreater(self.w.widget.height(), before)
        self.assertGreaterEqual(self.w.row_table.height(), self.w.row_table.minimumHeight())

    def test_a_roomy_window_does_not_grow(self):
        self.w.widget.resize(360, 900)
        _app.processEvents()
        before = self.w.widget.height()
        self.w.update_current_row(self.fields(4))
        self.assertEqual(self.w.widget.height(), before)

    def test_the_window_stops_growing_when_the_box_stops(self):
        self.w.update_current_row(self.fields(8))
        height = self.w.widget.height()
        self.w.update_current_row(self.fields(15))
        self.assertEqual(self.w.widget.height(), height)

    def test_the_mini_view_has_a_smaller_cap(self):
        self.w.set_mini(True)
        self.w.update_current_row(self.fields(10))
        self.assertEqual(self.w.row_table.minimumHeight(), ROW_MAX_MINI)
        self.assertLess(ROW_MAX_MINI, ROW_MAX_FULL)

    def test_the_mini_view_grows_with_its_rows_up_to_the_cap(self):
        self.w.set_mini(True)
        self.w.update_current_row(self.fields(1))
        one = self.w.widget.height()
        self.w.update_current_row(self.fields(3))
        self.assertGreaterEqual(self.w.widget.height(), one)

    def test_values_and_columns_are_shown(self):
        self.w.update_current_row({"Type": "Fern", "Price": 12.0})
        self.assertEqual(self.w.row_table.item(0, 0).text(), "Type")
        self.assertEqual(self.w.row_table.item(1, 1).text(), "12.0")


class TestAlignment(unittest.TestCase):
    def setUp(self):
        self.w = window()
        self.w.set_native_mini_button(True)
        self.w.set_native_settings_button(True)
        self.w.set_native_file_button(True)
        self.w.set_native_turn_button(True)
        self.w.set_native_undo_button(True)
        self.w.set_native_help_button(True)
        _app.processEvents()

    def test_the_current_row_box_lines_up_with_them_too(self):
        _app.processEvents()
        self.assertEqual(left(self.w.row_table, self.w.root), left(self.w.toggle_button, self.w.root))
        self.assertEqual(right(self.w.row_table, self.w.root), right(self.w.toggle_button, self.w.root))

    def test_settings_rows_keep_their_own_margins_too(self):
        row = SettingRow("T", "d", ToggleSwitch())
        theme.apply_spacing(row, "comfortable")
        m = row.layout().contentsMargins()
        self.assertEqual((m.left(), m.right()), (0, 0))

    def test_the_needs_sorting_button_keeps_its_inner_padding(self):
        self.w.apply_density("comfortable")
        m = self.w.sorting_button.layout().contentsMargins()
        self.assertEqual((m.left(), m.right()), (12, 12))

    def test_widgets_without_the_flag_still_get_the_spacing(self):
        from PySide6.QtWidgets import QVBoxLayout, QWidget
        plain = QWidget()
        QVBoxLayout(plain)
        theme.apply_spacing(plain, "comfortable")
        self.assertEqual(plain.layout().contentsMargins().left(), 20)


class TestWindowNeverSmallerThanItsContent(unittest.TestCase):
    def test_a_button_appearing_pushes_the_window_taller_instead_of_overlapping(self):
        w = window()
        w.widget.setMinimumSize(0, 0)
        w.widget.resize(360, w.widget.centralWidget().layout().minimumSize().height())
        _app.processEvents()
        before = w.widget.height()
        w.set_sorting_count(2)
        _app.processEvents()
        self.assertGreater(w.widget.height(), before)
        self.assertGreaterEqual(w.widget.height(), w.widget.centralWidget().layout().minimumSize().height())


class TestSectionHeadings(unittest.TestCase):
    def test_section_headings_are_not_bold(self):
        from quill.ui import theme
        sheet = theme.stylesheet_for(False)
        for selector in ('QLabel[staticHeading="true"]', 'QLabel[headingToggle="true"] {'):
            start = sheet.index(selector)
            self.assertIn("font-weight: 400", sheet[start: sheet.index("}", start)])


class TestResizingKeepsAlignment(unittest.TestCase):
    """Making the window taller gives the height to the Current Row box; nothing else gaps or stretches."""

    def top(self, w, name):
        widget = getattr(w, name)
        return widget.mapTo(w.root, widget.rect().topLeft()).y()

    def test_the_row_box_takes_the_height_and_log_stays_at_the_bottom(self):
        w = window(log_collapsed=True)
        w.set_not_connected(True)
        _app.processEvents()
        small = w.row_table.height()
        w.widget.resize(360, 1000)
        _app.processEvents()
        self.assertGreater(w.row_table.height(), small + 200)                 # the watched box grows
        bottom = w.log_toggle.mapTo(w.root, w.log_toggle.rect().bottomLeft()).y()
        self.assertEqual(w.root.height() - bottom - 1, LOG_BOTTOM_MARGIN)       # Log hugs the bottom edge
        self.assertEqual(w.toggle_button.height(), w.toggle_button.HEIGHT)

    def test_the_log_heading_stays_with_its_box_when_open(self):
        w = window(log_collapsed=False)
        w.widget.resize(360, 1000)
        _app.processEvents()
        log_bottom = w.log.mapTo(w.root, w.log.rect().bottomLeft()).y()
        footer_top = w.footer.mapTo(w.root, w.footer.rect().topLeft()).y()
        self.assertLess(footer_top - log_bottom, 12)                              # the footer sits right under the log
        self.assertLess(w.root.height() - (w.footer.mapTo(w.root, w.footer.rect().bottomLeft()).y() + 1), 20)

    def test_the_sections_above_stay_put_when_the_window_grows(self):
        w = window(log_collapsed=False)
        before = [self.top(w, n) for n in ("toggle_button", "stream")]
        w.widget.resize(360, 1000)
        _app.processEvents()
        self.assertEqual(before, [self.top(w, n) for n in ("toggle_button", "stream")])


if __name__ == "__main__":
    unittest.main()


class TestLastSavedSitsAtTheRight(unittest.TestCase):
    def test_it_shares_the_log_heading_line_right_aligned_and_has_no_generic_prefix(self):
        w = window(log_collapsed=True)
        w.set_last_saved("Row saved", {"Type": "Fern"})
        w.set_native_mini_button(True)
        _app.processEvents()
        self.assertTrue(w.last_label.isVisibleTo(w.root))
        self.assertTrue(bool(w.last_label.alignment() & Qt.AlignmentFlag.AlignRight))
        top = lambda widget: widget.mapTo(w.root, widget.rect().topLeft()).y()        # noqa: E731
        self.assertAlmostEqual(top(w.last_label) + w.last_label.height() / 2,
                               top(w.log_toggle) + w.log_toggle.height() / 2, delta=3)   # the same line
        self.assertGreater(w.last_label.x(), w.log_toggle.x() + w.log_toggle.width() - 1)
        self.assertEqual(w.last_label.full_text, "Last Saved: 1 field · Type: Fern")
