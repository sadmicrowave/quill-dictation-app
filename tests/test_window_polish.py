"""Connection chip, minimized Log at the bottom, title-bar Settings icon, Current Row sizing, alignment."""
import pathlib
import re
import tempfile
import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

import quill.ui.chrome as chrome
from quill.config.settings import Settings
from quill.ui import theme
from quill.ui.main_window import (
    CHIP_HEIGHT, LOG_BOTTOM_MARGIN, NOT_CONNECTED_HINT, NOT_CONNECTED_TEXT, ROW_EMPTY_HEIGHT, ROW_MAX_FULL, ROW_MAX_MINI,
    MainWindow,
)
from quill.ui.settings_widgets import SettingRow, ToggleSwitch
from tests.test_titlebar_and_refresh import FakeAppKit, FakeButton, FakeController, FakeTarget, native, restore

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
    def test_says_file_stream_not_connected(self):
        self.assertEqual(NOT_CONNECTED_TEXT, "File stream not connected")
        w = window()
        self.assertEqual(w.connection_chip.text(), "File stream not connected")

    def test_shown_in_place_of_the_empty_sheet_message(self):
        w = window()
        self.assertFalse(w.connection_chip.isVisibleTo(w.widget))         # until a failure is reported
        w.set_not_connected(True)
        _app.processEvents()
        self.assertTrue(w.connection_chip.isVisibleTo(w.widget))

    def test_hidden_again_once_connected(self):
        w = window()
        w.set_not_connected(True)
        w.set_not_connected(False)
        _app.processEvents()
        self.assertFalse(w.connection_chip.isVisibleTo(w.widget))

    def test_the_tooltip_explains_in_technical_third_person_terms(self):
        hint = NOT_CONNECTED_HINT
        self.assertFalse(FIRST_PERSON.search(hint), FIRST_PERSON.search(hint))
        self.assertIn("No spreadsheet is connected", hint)
        self.assertIn("spreadsheet program", hint)
        self.assertIn(".xlsx", hint)
        self.assertIn("File > Open Spreadsheet File", hint)
        tip = window().connection_chip.toolTip()
        self.assertFalse(FIRST_PERSON.search(tip), FIRST_PERSON.search(tip))
        for part in ("Not connected", "Spreadsheet program", ".xlsx", "File ▸ Open Spreadsheet File", "Start"):
            self.assertIn(part, tip)
        self.assertIn("<b>", tip)                                                  # bold, italics and spacing
        self.assertIn("<i>", tip)
        self.assertIn("line-height", tip)
        self.assertIn("letter-spacing", tip)

    def test_the_app_supplied_hint_has_no_first_person_either(self):
        from quill.controller import NO_WORKBOOK_HELP
        self.assertFalse(FIRST_PERSON.search(NO_WORKBOOK_HELP), NO_WORKBOOK_HELP)

    def test_a_custom_hint_replaces_the_tooltip(self):
        w = window()
        w.set_not_connected(True, "Custom hint")
        for chip in (w.connection_chip, w.mini_chip):
            self.assertIn("Custom hint", chip.toolTip())

    def test_still_shown_in_the_mini_view_where_the_sheet_name_is_not(self):
        w = window()
        w.set_not_connected(True)
        w.set_mini(True)
        _app.processEvents()
        self.assertTrue(w.mini_chip.isVisibleTo(w.widget))                 # the same chip, inside the Start button
        self.assertTrue(w.toggle_button.isAncestorOf(w.mini_chip))

    def test_the_chip_stays_a_fixed_height_pill_at_the_left_of_the_button(self):
        w = window()
        w.set_not_connected(True)
        w.widget.show()
        w.widget.resize(360, 900)
        _app.processEvents()
        chip = w.connection_chip
        self.assertTrue(chip.isVisibleTo(w.widget))
        self.assertEqual(chip.height(), CHIP_HEIGHT)
        self.assertTrue(w.toggle_button.isAncestorOf(chip))                # inside the Start button ...
        self.assertLess(chip.mapTo(w.toggle_button, chip.rect().topLeft()).x(), 20)   # ... at its left edge
        self.assertFalse(w.toggle_button.text_pill.isVisibleTo(w.widget))      # (the Start Listening pill steps aside)
        w.widget.resize(360, 400)
        _app.processEvents()
        self.assertEqual(chip.height(), CHIP_HEIGHT)
        self.assertEqual(w.mini_chip.height(), CHIP_HEIGHT)

    def test_nothing_about_the_connection_appears_at_the_bottom(self):
        w = window()
        w.set_not_connected(True)

    def test_chip_style_is_a_pill_in_the_theme_colour_in_both_themes(self):
        for dark in (False, True):
            sheet = theme.stylesheet_for(dark)
            start = sheet.index('QLabel[chip="warn"] {')
            rule = sheet[start: sheet.index("}", start)]
            warn = theme.WARNING_DARK if dark else theme.WARNING_LIGHT          # a warning colour, not the accent
            self.assertIn(theme.rgba(warn, 0.5), rule)
            self.assertIn("border-radius: 11px", rule)
            self.assertIn("rgba(", rule)

    def test_the_chip_is_a_pill_not_the_full_width(self):
        w = window()
        w.set_not_connected(True)
        _app.processEvents()
        self.assertLess(w.connection_chip.width(), w.widget.width() - 80)


class TestLogAtTheBottom(unittest.TestCase):
    def test_minimized_by_default_for_everyone(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(Settings.load(pathlib.Path(tmp)).preferences["log_collapsed"])
        w = window(log_collapsed=True)
        self.assertFalse(w.log.isVisibleTo(w.widget))

    def gap(self, w):
        return w.root.height() - w.log_toggle.geometry().bottom() - 1

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

    def test_opening_the_log_restores_the_normal_margin_and_closing_shrinks_it_again(self):
        w = window(log_collapsed=True)
        compact = w.root.layout().contentsMargins().bottom()
        self.assertEqual(compact, LOG_BOTTOM_MARGIN)
        w.log_toggle.click()
        _app.processEvents()
        opened = w.root.layout().contentsMargins().bottom()
        self.assertNotEqual(opened, LOG_BOTTOM_MARGIN)
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
        self.assertEqual((settings.frame[1], resize.frame[1]), ((30, 24), (30, 24)))     # every icon has the same box
        self.assertEqual(settings.image, f"image:{chrome.SYMBOL_SETTINGS}")
        self.assertEqual(settings.tip, "Settings")
        settings.performClick_(None)
        resize.performClick_(None)
        self.assertEqual((opened, resized), ([1], [1]))                  # each icon calls its own action
        self.assertEqual(kit.window.accessories[0].layout, 2)             # right side of the title bar
        self.assertIs(button._button, resize)                             # the resize icon stays the one that swaps

    def test_without_extras_there_is_no_stack(self):
        native()
        kit = FakeAppKit()
        chrome.add_titlebar_button(_fake_widget(), lambda: None, platform="darwin", appkit=kit)
        self.assertIsInstance(kit.window.accessories[0].view, FakeButton)

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
        self.assertEqual(w.connection_chip.height(), CHIP_HEIGHT)

    def test_the_log_heading_stays_with_its_box_when_open(self):
        w = window(log_collapsed=False)
        w.widget.resize(360, 1000)
        _app.processEvents()
        heading_bottom = w.log_toggle.mapTo(w.root, w.log_toggle.rect().bottomLeft()).y()
        log_top = w.log.mapTo(w.root, w.log.rect().topLeft()).y()
        self.assertLess(log_top - heading_bottom, 12)
        self.assertLess(w.root.height() - (w.log.mapTo(w.root, w.log.rect().bottomLeft()).y() + 1), 20)

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
