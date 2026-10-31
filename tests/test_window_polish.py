"""Connection chip, minimized Log at the bottom, title-bar Settings icon, Current Row sizing, alignment."""
import pathlib
import re
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

import quill.ui.chrome as chrome
from quill.config.settings import Settings
from quill.ui import theme
from quill.ui.main_window import (
    LOG_BOTTOM_MARGIN, NOT_CONNECTED_HINT, NOT_CONNECTED_TEXT, ROW_EMPTY_HEIGHT, ROW_MAX_FULL, ROW_MAX_MINI,
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
        self.assertEqual(NOT_CONNECTED_TEXT, "File stream not connected.")
        w = window()
        self.assertEqual(w.connection_chip.text(), "File stream not connected.")

    def test_shown_in_place_of_the_empty_sheet_message(self):
        w = window()
        self.assertFalse(w.connection_chip.isVisibleTo(w.widget))         # until a failure is reported
        w.set_not_connected(True)
        _app.processEvents()
        self.assertTrue(w.connection_chip.isVisibleTo(w.widget))
        self.assertFalse(w.sheet_label.isVisibleTo(w.widget))             # no "Sheet: –" next to it

    def test_hidden_again_and_the_sheet_name_returns_once_connected(self):
        w = window()
        w.set_not_connected(True)
        w.set_not_connected(False)
        w.update_sheet("Inventory")
        _app.processEvents()
        self.assertFalse(w.connection_chip.isVisibleTo(w.widget))
        self.assertTrue(w.sheet_label.isVisibleTo(w.widget))
        self.assertEqual(w.sheet_label.text(), "Sheet: Inventory")

    def test_the_tooltip_explains_in_technical_third_person_terms(self):
        hint = NOT_CONNECTED_HINT
        self.assertFalse(FIRST_PERSON.search(hint), FIRST_PERSON.search(hint))
        self.assertIn("No spreadsheet is connected", hint)
        self.assertIn("Excel", hint)
        self.assertIn(".xlsx", hint)
        self.assertIn("File > Open Spreadsheet File", hint)
        self.assertEqual(window().connection_chip.toolTip(), hint)

    def test_the_app_supplied_hint_has_no_first_person_either(self):
        from quill.controller import NO_WORKBOOK_HELP
        self.assertFalse(FIRST_PERSON.search(NO_WORKBOOK_HELP), NO_WORKBOOK_HELP)

    def test_a_custom_hint_replaces_the_tooltip(self):
        w = window()
        w.set_not_connected(True, "Custom hint")
        self.assertEqual(w.connection_chip.toolTip(), "Custom hint")

    def test_still_shown_in_the_mini_view_where_the_sheet_name_is_not(self):
        w = window()
        w.set_not_connected(True)
        w.set_mini(True)
        _app.processEvents()
        self.assertTrue(w.connection_chip.isVisibleTo(w.widget))

    def test_nothing_about_the_connection_appears_at_the_bottom(self):
        w = window()
        w.set_not_connected(True)
        self.assertEqual(w.footer.text(), "")
        self.assertFalse(w.footer.isVisibleTo(w.widget))

    def test_chip_style_is_an_amber_pill_in_both_themes(self):
        for dark in (False, True):
            sheet = theme.stylesheet_for(dark)
            start = sheet.index('QLabel[chip="warn"] {')
            rule = sheet[start: sheet.index("}", start)]
            warn = theme.colors_for(dark)["warn"]
            self.assertIn(warn, rule)
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
            self.assertTrue(10 <= LOG_BOTTOM_MARGIN <= 15)

    def test_nothing_at_all_is_below_the_log_heading(self):
        w = window(log_collapsed=True)
        w.set_footer("Downloading speech model…", offer_download=True)
        w.set_sorting_count(2)
        w.set_undo_count(1)
        _app.processEvents()
        lowest = max(child.mapTo(w.root, child.rect().bottomLeft()).y()
                     for child in w.root.children() if hasattr(child, "isVisibleTo") and child.isVisibleTo(w.root))
        self.assertEqual(lowest, w.log_toggle.mapTo(w.root, w.log_toggle.rect().bottomLeft()).y())

    def test_status_messages_sit_above_the_log(self):
        w = window()
        layout = w.root.layout()
        self.assertLess(layout.indexOf(w.footer), layout.indexOf(w.log_toggle))
        self.assertLess(layout.indexOf(w.download_button), layout.indexOf(w.log_toggle))
        self.assertEqual(layout.indexOf(w.log), layout.count() - 1)

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
        kit.NSStackView = type("S", (), {"stackViewWithViews_": staticmethod(lambda views: type(
            "Stack", (), {"views": views, "setSpacing_": lambda s, v: None,
                          "setFrame_": lambda s, f: setattr(s, "frame", f)})())})
        opened, resized = [], []
        button = chrome.add_titlebar_button(_fake_widget(), lambda: resized.append(1), platform="darwin", appkit=kit,
                                            extra=[(chrome.SYMBOL_SETTINGS, "Settings", lambda: opened.append(1))])
        stack = kit.window.accessories[0].view
        self.assertEqual(len(stack.views), 2)
        self.assertGreater(stack.frame[1][0], 40)                         # it has a width, or macOS would not show it
        settings, resize = stack.views
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
        self.assertEqual(self.w.row_table.height(), ROW_EMPTY_HEIGHT)
        self.assertTrue(self.w.row_placeholder.isVisibleTo(self.w.widget))
        self.assertLess(ROW_EMPTY_HEIGHT, 60)

    def test_grows_with_the_fields_then_stops_at_the_cap(self):
        heights = []
        for n in range(1, 12):
            self.w.update_current_row(self.fields(n))
            heights.append(self.w.row_table.height())
        self.assertEqual(heights, sorted(heights))
        self.assertGreater(heights[3], heights[0])
        self.assertEqual(heights[-1], ROW_MAX_FULL)
        self.assertEqual(heights.count(ROW_MAX_FULL), len(heights) - heights.index(ROW_MAX_FULL))

    def test_past_the_cap_it_scrolls_inside_itself(self):
        self.w.update_current_row(self.fields(20))
        _app.processEvents()
        self.assertEqual(self.w.row_table.height(), ROW_MAX_FULL)
        self.assertGreater(self.w.row_table.verticalScrollBar().maximum(), 0)

    def test_a_few_fields_do_not_scroll(self):
        self.w.update_current_row(self.fields(3))
        _app.processEvents()
        self.assertEqual(self.w.row_table.verticalScrollBar().maximum(), 0)

    def test_shrinks_back_and_shows_the_hint_after_the_row_is_saved(self):
        self.w.update_current_row(self.fields(6))
        self.w.update_current_row({})
        self.assertEqual(self.w.row_table.height(), ROW_EMPTY_HEIGHT)
        self.assertTrue(self.w.row_placeholder.isVisibleTo(self.w.widget))

    def test_the_hint_goes_away_while_there_are_fields(self):
        self.w.update_current_row(self.fields(1))
        self.assertFalse(self.w.row_placeholder.isVisibleTo(self.w.widget))

    def test_the_window_follows_by_the_same_amount(self):
        before = self.w.widget.height()
        self.w.update_current_row(self.fields(4))
        grown = self.w.widget.height() - before
        self.assertEqual(grown, self.w.row_table.height() - ROW_EMPTY_HEIGHT)
        self.w.update_current_row({})
        self.assertEqual(self.w.widget.height(), before)

    def test_the_window_stops_growing_when_the_box_stops(self):
        self.w.update_current_row(self.fields(8))
        height = self.w.widget.height()
        self.w.update_current_row(self.fields(15))
        self.assertEqual(self.w.widget.height(), height)

    def test_a_collapsed_current_row_does_not_move_the_window(self):
        self.w.set_row_collapsed(True)
        _app.processEvents()
        height = self.w.widget.height()
        self.w.update_current_row(self.fields(5))
        self.assertEqual(self.w.widget.height(), height)

    def test_the_mini_view_has_a_smaller_cap(self):
        self.w.set_mini(True)
        self.w.update_current_row(self.fields(10))
        self.assertEqual(self.w.row_table.height(), ROW_MAX_MINI)
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
        _app.processEvents()

    def test_the_file_row_has_no_inner_margin(self):
        for spacing in ("compact", "comfortable"):
            self.w.apply_density(spacing)
            margins = self.w.workbook_row.layout().contentsMargins()
            self.assertEqual((margins.left(), margins.right(), margins.top(), margins.bottom()), (0, 0, 0, 0), spacing)

    def test_the_picker_starts_where_the_text_below_it_starts(self):
        for spacing in ("compact", "comfortable"):
            self.w.apply_density(spacing)
            _app.processEvents()
            self.assertEqual(left(self.w.workbook_combo, self.w.root), left(self.w.sheet_label, self.w.root), spacing)
            self.assertEqual(left(self.w.workbook_combo, self.w.root), left(self.w.dot, self.w.root), spacing)

    def test_open_file_ends_where_start_ends(self):
        for spacing in ("compact", "comfortable"):
            self.w.apply_density(spacing)
            _app.processEvents()
            self.assertEqual(right(self.w.open_file_button, self.w.root), right(self.w.toggle_button, self.w.root), spacing)

    def test_the_current_row_box_lines_up_with_them_too(self):
        _app.processEvents()
        self.assertEqual(left(self.w.row_table, self.w.root), left(self.w.workbook_combo, self.w.root))
        self.assertEqual(right(self.w.row_table, self.w.root), right(self.w.open_file_button, self.w.root))

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


if __name__ == "__main__":
    unittest.main()
