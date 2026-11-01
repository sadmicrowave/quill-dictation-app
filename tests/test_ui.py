"""UI tests, run headless (QT_QPA_PLATFORM=offscreen, set in conftest.py).

Widgets are exercised through their public methods and signals; no pixel
checks. System-tray behaviour that needs a real desktop is covered manually
(see the To Do checklist for S3).
"""
import datetime as dt
import pathlib
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QDialog

from quill.config.settings import Settings
from quill.parser.commands import Action
from quill.ui.main_window import MainWindow
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.theme import apply_theme
from quill.ui.tray import TrayIcon, make_icon

_app = QApplication.instance() or QApplication([])


class TestMainWindow(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.w = MainWindow(
            on_toggle=lambda a: self.calls.append(("toggle", a)),
            on_settings=lambda: self.calls.append(("settings",)),
        )
        self.w.setup()

    def test_starts_not_listening(self):
        self.assertFalse(self.w.wave.active)
        self.assertEqual(self.w.toggle_button.toolTip(), "Start Listening")
        self.assertFalse(self.w.toggle_button.property("accent"))

    def test_listening_indicator(self):
        self.w.set_listening_indicator(True)
        self.assertEqual((self.w.wave.active, self.w.toggle_button.toolTip()), (True, "Stop Listening"))
        self.assertTrue(self.w.toggle_button.property("accent"))
        self.assertTrue(self.w.listening)

    def test_toggle_button_requests_opposite_state(self):
        self.w.toggle_button.click()
        self.w.set_listening_indicator(True)
        self.w.toggle_button.click()
        self.assertEqual(self.calls, [("toggle", True), ("toggle", False)])

    def test_current_row_shows_fields_and_dates(self):
        self.w.update_current_row({"Species": "Fern", "Acquired": dt.date(2026, 10, 30)})
        t = self.w.row_table
        self.assertEqual(t.rowCount(), 2)
        self.assertEqual((t.item(0, 0).text(), t.item(0, 1).text()), ("Species", "Fern"))
        self.assertEqual(t.item(1, 1).text(), "2026-10-30")
        self.w.update_current_row({})
        self.assertEqual(t.rowCount(), 0)

    def test_log_is_timestamped_and_bounded(self):
        self.w.append_log("hello")
        self.assertRegex(self.w.log.toPlainText(), r"^\d\d:\d\d:\d\d\thello$")
        for i in range(600):
            self.w.append_log(f"line {i}")
        self.assertEqual(self.w.log.document().blockCount(), 500)
        self.assertTrue(self.w.log.toPlainText().endswith("line 599"))
        self.assertNotIn("line 99\n", self.w.log.toPlainText())

    def test_workbook_picker(self):
        self.w.update_workbooks(["a.xlsx", "b.xlsx"], "b.xlsx")
        self.assertEqual(self.w.workbook_name, "b.xlsx")
        self.w.update_workbook("c.xlsx")
        self.assertEqual(self.w.workbook_name, "c.xlsx")
        self.assertIn("c.xlsx", self.w.open_file_button.toolTip())          # the folder icon names the file

    def test_last_saved(self):
        self.w.set_last_saved("Row 4")
        self.assertEqual(self.w.last_label.text(), "Last Saved: Row 4")

    def test_show_before_setup_is_harmless(self):
        MainWindow().show()


class TestTray(unittest.TestCase):
    def test_icons_differ_by_state(self):
        on, off = make_icon(True).pixmap(64, 64).toImage(), make_icon(False).pixmap(64, 64).toImage()
        self.assertNotEqual(on, off)
        self.assertEqual(on.pixelColor(32, 32).alpha(), 0)       # listening: solid, the lines cut out
        self.assertGreater(on.pixelColor(14, 14).alpha(), 200)
        self.assertEqual(off.pixelColor(18, 18).alpha(), 0)      # idle: an outline is hollow
        self.assertGreater(off.pixelColor(32, 32).alpha(), 200)

    def test_toggle_asks_app_for_opposite_state(self):
        calls = []
        tray = TrayIcon(_app, MainWindow(), lambda: calls.append("start"), lambda: calls.append("stop"))
        tray.toggle()
        tray.set_listening(True)
        tray.toggle()
        self.assertEqual(calls, ["start", "stop"])

    def test_set_listening_without_setup_is_safe(self):
        tray = TrayIcon(_app, MainWindow(), lambda: None, lambda: None)
        tray.set_listening(True)
        self.assertTrue(tray.listening)

    def test_menu_label_flips_when_tray_available(self):
        tray = TrayIcon(_app, MainWindow(), lambda: None, lambda: None)
        if not tray.setup():
            self.skipTest("no system tray on this platform/display")
        self.assertEqual(tray.toggle_action.text(), "Start Listening")
        tray.set_listening(True)
        self.assertEqual(tray.toggle_action.text(), "Stop Listening")


class TestSettingsDialog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = Settings.load(pathlib.Path(self._tmp.name))
        self.dlg = SettingsDialog(self.settings)
        self.dlg.build()
        self.errors = []
        self.dlg.show_errors = self.errors.extend   # no modal box in tests

    def tearDown(self):
        self._tmp.cleanup()

    def test_table_lists_current_keywords(self):
        rows = dict(self.dlg.collect_rows())
        self.assertEqual(rows, self.settings.keywords)

    def test_edit_persists(self):
        self.dlg.table.item(0, 0).setText("zzz go")
        self.dlg.table.cellWidget(0, 1).setCurrentIndex(0)   # START_LISTENING first
        # keep Start/Stop present after the edit
        self.assertTrue(self.dlg.try_accept())
        reloaded = Settings.load(pathlib.Path(self._tmp.name))
        self.assertIn("zzz go", reloaded.keywords)

    def test_add_and_remove_rows(self):
        before = self.dlg.table.rowCount()
        self.dlg.add_row("brand new", Action.DELETE_ROW)
        self.assertEqual(self.dlg.table.rowCount(), before + 1)
        self.dlg.table.selectRow(before)
        self.dlg.remove_selected()
        self.assertEqual(self.dlg.table.rowCount(), before)

    def test_duplicate_rejected_and_dialog_stays_open(self):
        self.dlg.add_row("next row", Action.DELETE_ROW)
        self.assertFalse(self.dlg.try_accept())
        self.assertTrue(any("Duplicate" in e for e in self.errors))
        self.assertIn("next row", self.settings.keywords)   # unchanged in memory
        self.assertFalse((pathlib.Path(self._tmp.name) / Settings.KEYWORDS_FILE).exists())

    def test_reserved_word_rejected(self):
        self.dlg.add_row("yes", Action.NEXT_ROW)
        self.assertFalse(self.dlg.try_accept())

    def test_restore_defaults(self):
        self.dlg.table.setRowCount(0)
        self.dlg.restore_defaults()
        self.assertEqual(dict(self.dlg.collect_rows()), Settings.defaults().keywords)

    def test_preferences_saved(self):
        self.dlg.theme_combo.setCurrentIndex(2)
        self.dlg.speak_check.setChecked(True)
        self.assertTrue(self.dlg.try_accept())
        reloaded = Settings.load(pathlib.Path(self._tmp.name))
        self.assertEqual(reloaded.preferences["theme"], "dark")
        self.assertIs(reloaded.preferences["speak_sort_prompts"], True)

    def test_blank_row_rejected(self):
        self.dlg.add_row("  ", Action.NEXT_ROW)
        self.assertFalse(self.dlg.try_accept())

    def test_accept_closes_dialog(self):
        self.assertTrue(self.dlg.try_accept())
        self.assertEqual(self.dlg._dialog.result(), QDialog.DialogCode.Accepted)


class TestTheme(unittest.TestCase):
    def test_modes_apply(self):
        from PySide6.QtCore import Qt
        apply_theme(_app, "dark")
        if _app.styleHints().colorScheme() == Qt.ColorScheme.Unknown:
            self.skipTest(f"platform '{_app.platformName()}' does not implement colour schemes")
        self.assertEqual(_app.styleHints().colorScheme(), Qt.ColorScheme.Dark)
        apply_theme(_app, "light")
        self.assertEqual(_app.styleHints().colorScheme(), Qt.ColorScheme.Light)

    def test_unknown_and_auto_modes_do_not_raise(self):
        apply_theme(_app, "bogus")
        apply_theme(_app, "auto")


if __name__ == "__main__":
    unittest.main()
