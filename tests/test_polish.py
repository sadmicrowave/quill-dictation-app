"""Hover contrast, modern checkboxes, unbold headings, tray clicks, log-collapse resize, sample playback."""
import pathlib
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from quill.config.settings import Settings
from quill.ui import theme
from quill.ui.main_window import LOG_OPEN_HEIGHT, MainWindow
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.settings_widgets import ToggleSwitch
from quill.ui.tray import TrayIcon

_app = QApplication.instance() or QApplication([])


def rule(sheet: str, selector: str) -> str:
    """The declarations of the first rule that starts with *selector*."""
    start = sheet.index(selector + " {")
    return sheet[start: sheet.index("}", start)]


def luminance(color: str) -> float:
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestHoverContrast(unittest.TestCase):
    def test_hovered_and_selected_list_items_keep_the_normal_text_colour(self):
        for dark in (False, True):
            sheet = theme.stylesheet_for(dark)
            t = theme.colors_for(dark)
            hover = rule(sheet, "QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected")
            self.assertIn(f"color: {t['text']}", hover)
            self.assertNotIn(t["on_accent"], hover)           # never the white-on-light combination

    def test_menu_hover_is_a_tint_with_normal_text(self):
        for dark in (False, True):
            sheet = theme.stylesheet_for(dark)
            t = theme.colors_for(dark)
            selected = rule(sheet, "QMenu::item:selected")
            self.assertIn(f"color: {t['text']}", selected)
            self.assertIn("rgba(", selected)

    def test_hover_tint_is_light_enough_for_the_text_to_stay_readable(self):
        # The tint is 20% accent over the surface; check the blend against the text colour.
        for dark in (False, True):
            t = theme.colors_for(dark)
            for key in theme.ACCENTS:
                a = theme.colors_for(dark, key)["accent"]
                blend = "#" + "".join(
                    f"{round(int(t['surface'][i:i + 2], 16) * 0.8 + int(a[i:i + 2], 16) * 0.2):02X}"
                    for i in (1, 3, 5))
                self.assertGreaterEqual(contrast(blend, t["text"]), 7, (dark, key))

    def test_buttons_hover_keeps_text_readable(self):
        for dark in (False, True):
            t = theme.colors_for(dark)
            self.assertGreaterEqual(contrast(t["hover"], t["text"]), 7)


class TestCheckboxAndHeadings(unittest.TestCase):
    def test_checkbox_has_a_rounded_box_and_a_check_image(self):
        sheet = theme.stylesheet_for(False)
        self.assertIn("QCheckBox::indicator {", sheet)
        self.assertIn("border-radius: 5px", rule(sheet, "QCheckBox::indicator"))
        checked = rule(sheet, "QCheckBox::indicator:checked")
        self.assertIn(theme.colors_for(False)["accent"], checked)
        path = checked.split("url(")[1].split(")")[0]
        svg = pathlib.Path(path).read_text()
        self.assertIn("<polyline", svg)
        self.assertIn(theme.colors_for(False)["on_accent"], svg)        # white tick on light, dark on dark

    def test_checkbox_follows_the_accent(self):
        self.assertIn(theme.colors_for(False, "forest")["accent"],
                      rule(theme.stylesheet_for(False, "forest"), "QCheckBox::indicator:checked"))

    def test_no_heading_is_bold(self):
        sheet = theme.stylesheet_for(False)
        for selector in ('QLabel[heading="true"]', 'QToolButton[heading="true"]'):
            self.assertNotIn("font-weight", rule(sheet, selector))
        self.assertNotIn("font-weight: 700", sheet)

    def test_dialog_checkboxes_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlg = SettingsDialog(Settings.load(pathlib.Path(tmp)))
            dlg.build()
            self.assertTrue(dlg.speak_check.isCheckable() and dlg.auto_sort_check.isCheckable())
            self.assertIsInstance(dlg.speak_check, ToggleSwitch)


class TestTrayClick(unittest.TestCase):
    def setUp(self):
        self.started, self.stopped = [], []
        window = MainWindow()
        window.setup()
        self.tray = TrayIcon(_app, window, on_start=lambda: self.started.append(1),
                             on_stop=lambda: self.stopped.append(1))
        self.tray.setup()

    def test_clicking_the_icon_never_starts_or_stops_listening(self):
        for reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick,
                       QSystemTrayIcon.ActivationReason.MiddleClick):
            self.tray._on_activated(reason)
        self.tray.set_listening(True)
        self.tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
        self.assertEqual((self.started, self.stopped), ([], []))

    def test_on_windows_a_left_click_pops_up_the_menu(self):
        import quill.ui.tray as tray_module
        shown = []
        self.tray._menu.popup = lambda pos: shown.append(pos)
        original = tray_module.sys.platform
        tray_module.sys.platform = "win32"
        try:
            self.tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
        finally:
            tray_module.sys.platform = original
        self.assertEqual(len(shown), 1)
        self.assertEqual((self.started, self.stopped), ([], []))

    def test_the_menu_item_still_toggles(self):
        self.tray.toggle_action.trigger()
        self.assertEqual(self.started, [1])


class TestLogCollapseResizes(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.resize(360, 620)
        self.w.widget.show()
        _app.processEvents()

    def test_a_roomy_window_keeps_its_size_and_the_row_box_gives_the_room(self):
        full, table = self.w.widget.height(), self.w.row_table.height()
        self.w.log_toggle.click()
        _app.processEvents()
        self.assertEqual(self.w.widget.height(), full)
        self.assertGreater(self.w.row_table.height(), table)         # the box takes the log's room
        self.w.log_toggle.click()
        _app.processEvents()
        self.assertEqual((self.w.widget.height(), self.w.row_table.height()), (full, table))

    def test_a_snug_window_grows_by_the_shortfall_and_shrinks_back(self):
        w = MainWindow(log_collapsed=True)
        w.setup()
        w.widget.show()
        _app.processEvents()
        snug = w.widget.height()
        w.log_toggle.click()
        _app.processEvents()
        grown = w.widget.height()
        self.assertGreater(grown, snug)
        self.assertLessEqual(grown - snug, LOG_OPEN_HEIGHT + 20)
        self.assertEqual(w.log.height(), LOG_OPEN_HEIGHT)
        w.log_toggle.click()
        _app.processEvents()
        self.assertAlmostEqual(w.widget.height(), snug, delta=3)       # (the content's own minimum may be a pixel or two more)

    def test_no_empty_gap_below_the_last_control(self):
        self.w.log_toggle.click()
        _app.processEvents()
        window = self.w.widget
        bottom = max(child.geometry().bottom() for child in window.centralWidget().findChildren(
            type(self.w.footer)) if child.isVisible())
        self.assertLessEqual(window.height() - bottom, 80)

    def test_starting_collapsed_gives_a_compact_window(self):
        w = MainWindow(log_collapsed=True)
        w.setup()
        w.widget.show()
        _app.processEvents()
        self.assertLess(w.widget.height(), 520 - 100)


class TestSamplePlayback(unittest.TestCase):
    def test_play_sample_sends_exactly_one_request_with_the_selected_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            dlg = SettingsDialog(Settings.load(pathlib.Path(tmp)), on_preview=lambda *a: calls.append(a))
            dlg.build()
            dlg.pack_combo.setCurrentIndex(dlg.pack_combo.findData("marimba"))
            dlg.play_sample()
            self.assertEqual(calls, [("sounds", "marimba", "okay")])

    def test_choosing_a_sound_set_plays_it_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            dlg = SettingsDialog(Settings.load(pathlib.Path(tmp)), on_preview=lambda *a: calls.append(a))
            dlg.build()
            dlg.pack_combo.activated.emit(3)               # what the user's pick emits
            self.assertEqual(len(calls), 1)

    def test_programmatic_changes_do_not_play(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            dlg = SettingsDialog(Settings.load(pathlib.Path(tmp)), on_preview=lambda *a: calls.append(a))
            dlg.build()
            dlg.pack_combo.setCurrentIndex(2)
            dlg.echo_combo.setCurrentIndex(1)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
