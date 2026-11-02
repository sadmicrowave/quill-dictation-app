"""Graceful handling when no spreadsheet is open, auto-attach, and the tray's workbook line."""
import pathlib
import tempfile
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.base import BridgeError
from quill.bridge.grid import XlwingsGrid
from quill.bridge.filters import ColumnFilter
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import NO_WORKBOOK_HELP, Controller
from quill.ui.main_window import MainWindow
from quill.ui.tray import TrayIcon, elide_end, elide_middle, folder_for_display
from tests.fixtures import make_workbook

_app = QApplication.instance() or QApplication([])


class FakeSpeaker:
    enabled = True

    def __init__(self):
        self.said = []

    def say(self, text, on_done=None, lead_in=0.0):
        self.said.append(text)
        if on_done:
            on_done()


class PresenceCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.path = self.dir / "plants.xlsx"          # does not exist yet
        self.events, self.speaker = [], FakeSpeaker()
        self.ctl = Controller(XlsxBridge(self.path), Settings.defaults(), self.speaker,
                              on_event=self.events.append)

    def tearDown(self):
        self._tmp.cleanup()

    def kinds(self):
        return [e.kind for e in self.events]


class TestControllerWithoutWorkbook(PresenceCase):
    def test_voice_start_is_refused_with_guidance(self):
        self.ctl.handle_transcript("start listening")
        self.assertFalse(self.ctl.session.listening)
        self.assertEqual(self.kinds(), ["error"])
        self.assertEqual(self.events[0].detail, NO_WORKBOOK_HELP)
        self.assertEqual(self.speaker.said, [])                    # guidance is shown, never spoken

    def test_button_start_is_refused_with_guidance(self):
        self.ctl.set_listening(True)
        self.assertFalse(self.ctl.session.listening)
        self.assertEqual(self.events[0].detail, NO_WORKBOOK_HELP)
        self.assertEqual(self.speaker.said, [])

    def test_help_text_says_how_to_proceed(self):
        self.assertIn("Open a spreadsheet and Quill connects to it automatically", NO_WORKBOOK_HELP)
        self.assertIn("Open File", NO_WORKBOOK_HELP)

    def test_workbook_opened_later_is_picked_up_by_next_phrase(self):
        make_workbook(self.path)
        self.ctl.handle_transcript("start listening")
        self.assertTrue(self.ctl.connected)
        self.assertTrue(self.ctl.session.listening)
        self.assertEqual(self.kinds(), ["started"])

    def test_workbook_opened_later_is_picked_up_by_button(self):
        make_workbook(self.path)
        self.ctl.set_listening(True)
        self.assertTrue(self.ctl.session.listening)

    def test_stopping_without_workbook_is_harmless(self):
        self.ctl.set_listening(False)
        self.assertNotIn("error", self.kinds())
        self.assertFalse(self.ctl.session.listening)

    def test_detach_closes_gate(self):
        make_workbook(self.path)
        self.ctl.connect()
        self.ctl.set_listening(True)
        self.events.clear()
        self.ctl.detach()
        self.assertFalse(self.ctl.connected)
        self.assertFalse(self.ctl.session.listening)
        self.assertEqual(self.kinds(), ["stopped"])


class AppPresenceCase(PresenceCase):
    def make_app(self):
        quill = QuillApp(_app, Settings.load(self.dir / "cfg"), XlsxBridge(self.path),
                         listener_factory=lambda m, t, e: mock.Mock(),
                         model_finder=lambda c: self.dir, speaker=self.speaker)
        quill.tray.notify = mock.Mock()
        quill.start()
        return quill


class TestStartingWithNoWorkbook(AppPresenceCase):
    def test_window_explains_what_to_do(self):
        quill = self.make_app()
        self.assertFalse(quill.connected)
        self.assertTrue(quill.window.connection_chip.isVisibleTo(quill.window.widget))
        self.assertIn("Not connected", quill.window.connection_chip.toolTip())

    def test_start_button_informs_user_everywhere(self):
        quill = self.make_app()
        quill.window.toggle_button.click()
        self.assertFalse(quill.controller.session.listening)
        self.assertFalse(quill.window.listening)
        self.assertTrue(quill.window.connection_chip.isVisibleTo(quill.window.widget))
        quill.tray.notify.assert_called_with(NO_WORKBOOK_HELP)
        self.assertEqual(self.speaker.said, [])                    # the popup shows it; nothing is spoken


class TestWatcher(AppPresenceCase):
    def test_attaches_when_workbook_appears(self):
        quill = self.make_app()
        make_workbook(self.path)
        quill.poll_workbooks()
        self.assertTrue(quill.connected)
        self.assertIn("Attached to plants.xlsx automatically", quill.window.log.toPlainText())

    def test_attach_does_not_open_the_gate(self):
        quill = self.make_app()
        make_workbook(self.path)
        quill.poll_workbooks()
        self.assertFalse(quill.controller.session.listening)

    def test_voice_works_right_after_auto_attach(self):
        quill = self.make_app()
        make_workbook(self.path)
        quill.poll_workbooks()
        quill.relay.transcript.emit("start listening")
        self.assertTrue(quill.window.listening)

    def test_detects_closed_workbook_and_stops_listening(self):
        make_workbook(self.path)
        quill = self.make_app()
        quill.toggle_listening(True)
        self.assertTrue(quill.window.listening)
        self.path.unlink()                       # "closed"
        quill.poll_workbooks()
        self.assertFalse(quill.connected)
        self.assertFalse(quill.window.listening)
        self.assertFalse(quill.tray.listening)
        self.assertIn("was closed", quill.window.log.toPlainText())
        self.assertTrue(quill.window.connection_chip.isVisibleTo(quill.window.widget))

    def test_reattaches_when_it_returns(self):
        make_workbook(self.path)
        quill = self.make_app()
        self.path.unlink()
        quill.poll_workbooks()
        make_workbook(self.path)
        quill.poll_workbooks()
        self.assertTrue(quill.connected)

    def test_poll_is_quiet_when_nothing_changes(self):
        quill = self.make_app()
        before = quill.window.log.toPlainText()
        quill.poll_workbooks()
        self.assertEqual(quill.window.log.toPlainText(), before)

    def test_excel_not_running_counts_as_no_workbooks(self):
        quill = self.make_app()
        quill.controller.bridge.open_workbooks = mock.Mock(side_effect=BridgeError("no excel"))
        quill.poll_workbooks()     # must not raise
        self.assertFalse(quill.connected)

    def test_timer_started_with_app(self):
        quill = self.make_app()
        self.assertTrue(quill._watcher.isActive())


class TestTrayWorkbookLine(unittest.TestCase):
    def make(self):
        calls = []
        tray = TrayIcon(_app, MainWindow(), lambda: None, lambda: None,
                        on_open_workbook=lambda: calls.append("open"))
        tray.setup()          # builds the menu even on platforms with no tray
        return tray, calls

    def test_hidden_until_listening(self):
        tray, _ = self.make()
        tray.set_workbook("plants.xlsx", "/Users/me/Documents/plants.xlsx")
        title, folder = tray.workbook_items
        self.assertTrue(title.isVisible() is False and folder.isVisible() is False)
        tray.set_listening(True)
        self.assertTrue(title.isVisible() and folder.isVisible())
        tray.set_listening(False)
        self.assertFalse(title.isVisible())

    def test_text_shows_name_and_folder(self):
        tray, _ = self.make()
        tray.set_workbook("plants.xlsx", "/data/Inventory/plants.xlsx")
        tray.set_listening(True)
        title, folder = tray.workbook_items
        self.assertEqual(title.text(), "Editing: plants.xlsx")
        self.assertEqual(folder.text(), "/data/Inventory")
        self.assertEqual(title.toolTip(), "/data/Inventory/plants.xlsx")

    def test_long_names_are_elided(self):
        tray, _ = self.make()
        name = "A very long workbook title " * 5 + ".xlsx"
        tray.set_workbook(name, "/a/" + "b" * 100 + "/c/" + name)
        tray.set_listening(True)
        title, folder = tray.workbook_items
        self.assertLessEqual(len(title.text()), len("Editing: ") + 44)
        self.assertTrue(title.text().endswith("…"))
        self.assertLessEqual(len(folder.text()), 52)
        self.assertIn("…", folder.text())

    def test_no_name_means_no_lines(self):
        tray, _ = self.make()
        tray.set_workbook("", "")
        tray.set_listening(True)
        self.assertFalse(tray.workbook_items[0].isVisible())

    def test_unknown_path_hides_only_the_folder_line(self):
        tray, _ = self.make()
        tray.set_workbook("Book1", "")
        tray.set_listening(True)
        title, folder = tray.workbook_items
        self.assertTrue(title.isVisible())
        self.assertFalse(folder.isVisible())

    def test_clicking_either_line_opens_workbook(self):
        tray, calls = self.make()
        tray.set_workbook("a.xlsx", "/x/a.xlsx")
        tray.set_listening(True)
        for action in tray.workbook_items:
            action.trigger()
        self.assertEqual(calls, ["open", "open"])

    def test_notify_without_tray_is_safe(self):
        tray = TrayIcon(_app, MainWindow(), lambda: None, lambda: None)
        tray.notify("hello")


class TestElide(unittest.TestCase):
    def test_end(self):
        self.assertEqual(elide_end("short", 10), "short")
        self.assertEqual(elide_end("abcdefghij", 5), "abcd…")

    def test_middle_keeps_both_ends(self):
        out = elide_middle("/Users/me/Documents/Vaults/Plants/2026/Inventory", 30)
        self.assertEqual(len(out), 30)
        self.assertTrue(out.startswith("/Users") and out.endswith("Inventory"))
        self.assertIn("…", out)

    def test_folder_uses_tilde_for_home(self):
        home = str(pathlib.Path.home())
        self.assertEqual(folder_for_display(f"{home}/Docs/a.xlsx"), "~/Docs")


class TestShowWorkbook(AppPresenceCase):
    def test_tray_click_activates_bridge(self):
        make_workbook(self.path)
        quill = self.make_app()
        quill.controller.bridge.activate = mock.Mock()
        quill.show_workbook()
        quill.controller.bridge.activate.assert_called_once()

    def test_activate_failure_is_logged(self):
        make_workbook(self.path)
        quill = self.make_app()
        quill.controller.bridge.activate = mock.Mock(side_effect=BridgeError("nope"))
        quill.show_workbook()
        self.assertIn("nope", quill.window.log.toPlainText())

    def test_tray_shows_workbook_after_start(self):
        make_workbook(self.path)
        quill = self.make_app()
        quill.toggle_listening(True)
        title, _ = quill.tray.workbook_items
        self.assertEqual(title.text(), "Editing: plants.xlsx")
        self.assertTrue(title.isVisible())
        quill.toggle_listening(False)
        self.assertFalse(title.isVisible())


class TestFileBridgePathAndActivate(unittest.TestCase):
    def test_path_and_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_workbook(pathlib.Path(tmp) / "p.xlsx")
            bridge = XlsxBridge(path)
            bridge.connect()
            self.assertEqual(pathlib.Path(bridge.workbook_path).name, "p.xlsx")
            with mock.patch("subprocess.run") as run, mock.patch("sys.platform", "darwin"):
                bridge.activate()
            self.assertEqual(run.call_args[0][0][0], "open")


class TestXlwingsGridFilters(unittest.TestCase):
    """The native Excel calls, checked against recording doubles (not real Excel)."""

    def make(self, platform="win32"):
        sheet = mock.MagicMock()
        book = mock.MagicMock()
        book.sheets.__getitem__.return_value = sheet
        table = sheet.range.return_value
        return XlwingsGrid(book, platform=platform), sheet, table.api

    def test_windows_single_value(self):
        grid, sheet, api = self.make()
        sheet.api.AutoFilterMode = True
        grid.set_autofilter("S", 3, 1, 5, 20, {2: ColumnFilter("Color", values=["Black"])})
        sheet.range.assert_called_with((3, 1), (20, 5))
        api.AutoFilter.assert_called_once_with(Field=2, Criteria1="=Black")
        self.assertIs(sheet.api.AutoFilterMode, False)      # reset before applying

    def test_windows_value_list_uses_filter_values_operator(self):
        grid, _, api = self.make()
        grid.set_autofilter("S", 1, 1, 3, 9, {1: ColumnFilter("C", values=["A", "B"])})
        api.AutoFilter.assert_called_once_with(Field=1, Criteria1=["A", "B"], Operator=7)

    def test_windows_numeric_comparisons(self):
        grid, _, api = self.make()
        grid.set_autofilter("S", 1, 2, 5, 9, {
            4: ColumnFilter("P", comparisons=[("<", 50.0)]),
            5: ColumnFilter("Q", comparisons=[(">", 20.0), ("<=", 30.0)]),
        })
        calls = api.AutoFilter.call_args_list
        self.assertEqual(calls[0].kwargs, {"Field": 3, "Criteria1": "<50"})      # relative to col 2
        self.assertEqual(calls[1].kwargs,
                         {"Field": 4, "Criteria1": ">20", "Operator": 1, "Criteria2": "<=30"})

    def test_windows_clear_shows_all_data(self):
        grid, sheet, _ = self.make()
        sheet.api.FilterMode = True
        grid.clear_autofilter("S")
        sheet.api.ShowAllData.assert_called_once()

    def test_excel_errors_become_bridge_errors(self):
        grid, _, api = self.make()
        api.AutoFilter.side_effect = RuntimeError("COM exploded")
        with self.assertRaises(BridgeError) as ctx:
            grid.set_autofilter("S", 1, 1, 3, 9, {1: ColumnFilter("C", values=["A"])})
        self.assertIn("COM exploded", str(ctx.exception))

    def test_cursor_roundtrip_and_failure_is_silent(self):
        grid, sheet, _ = self.make()
        grid._book.app.selection.row, grid._book.app.selection.column = 7, 3
        self.assertEqual(grid.get_cursor("S"), (7, 3))
        grid.set_cursor("S", 7, 3)
        sheet.activate.assert_called_once()
        sheet.range.return_value.select.assert_called_once()
        sheet.activate.side_effect = RuntimeError("x")
        grid.set_cursor("S", 1, 1)       # must not raise

    def test_path(self):
        grid, _, _ = self.make()
        grid._book.fullname = "/Users/me/a.xlsx"
        self.assertEqual(grid.path(), "/Users/me/a.xlsx")
        grid._book.fullname = "Book1"
        self.assertEqual(grid.path(), "")


if __name__ == "__main__":
    unittest.main()
