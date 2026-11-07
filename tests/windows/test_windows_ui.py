"""Windows-only behaviour of the menus, tray, voice, live bridge and Excel filters (all through quill.platforms.windows)."""
import sys
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon

from quill import platforms
from quill.bridge.base import BridgeError
from quill.bridge.factory import get_bridge
from quill.bridge.filters import ColumnFilter
from quill.bridge.grid import XlwingsGrid
from quill.platforms.windows import WinBridge
from quill.speaker.speaker import Speaker
from quill.ui.menus import QuillMenus
from quill.ui.main_window import MainWindow
from quill.ui.tray import TrayIcon

_app = QApplication.instance() or QApplication([])


class TestProvider(unittest.TestCase):
    def test_windows_has_a_provider_that_names_its_qt_plugin(self):
        self.assertEqual(platforms.offered("win32", "NATIVE_QPA"), "windows")
        self.assertIsNone(platforms.provider("darwin"))
        self.assertIsNone(platforms.provider("linux"))

    def test_the_quit_item_reads_exit(self):
        window = QMainWindow()
        windows = QuillMenus({}, platform="win32").install(window.menuBar())
        self.assertEqual(windows["quit"].text(), "Exit")

    def test_the_live_bridge_is_the_windows_one(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertIsInstance(get_bridge(), WinBridge)

    def test_other_systems_have_no_live_bridge(self):
        with mock.patch.object(sys, "platform", "linux"):
            with self.assertRaises(NotImplementedError):
                get_bridge()


class TestWindowsTray(unittest.TestCase):
    def setUp(self):
        self.started, self.stopped = [], []
        window = MainWindow()
        window.setup()
        self.tray = TrayIcon(_app, window, on_start=lambda: self.started.append(1),
                             on_stop=lambda: self.stopped.append(1))
        self.tray.setup()

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


class TestWinBridge(unittest.TestCase):
    def test_xlwings_missing(self):
        import sys
        saved = sys.modules.get("xlwings")
        sys.modules["xlwings"] = None  # forces ImportError
        try:
            with self.assertRaises(BridgeError):
                WinBridge().connect()
        finally:
            if saved is None:
                sys.modules.pop("xlwings", None)
            else:
                sys.modules["xlwings"] = saved


class TestSpeech(unittest.TestCase):
    def test_windows_uses_pyttsx3(self):
        engine = mock.Mock()
        fake = mock.Mock(init=mock.Mock(return_value=engine))
        with mock.patch.dict("sys.modules", {"pyttsx3": fake}):
            Speaker(platform="win32", run_in_thread=False).say("hello")
        engine.say.assert_called_once_with("hello")
        engine.runAndWait.assert_called_once()

    def test_windows_without_pyttsx3_does_not_raise(self):
        with mock.patch.dict("sys.modules", {"pyttsx3": None}):
            Speaker(platform="win32", run_in_thread=False).say("hello")


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
