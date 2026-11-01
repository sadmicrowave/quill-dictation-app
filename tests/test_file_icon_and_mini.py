"""The folder icon that replaces the file picker, Start asking for a file, the mini view's red "!", no drift leaving mini."""
import pathlib
import tempfile
import unittest

import openpyxl
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.ui import chrome
from quill.ui.main_window import MainWindow
from quill.ui.widgets import WaveMeter
from tests.test_app import FakeListener, FakeSpeaker

_app = QApplication.instance() or QApplication([])


class TestFolderIconInTheWindow(unittest.TestCase):
    def setUp(self):
        self.seen = []
        self.w = MainWindow(on_file_state=lambda has, name: self.seen.append((has, name)))
        self.w.setup()
        self.w.widget.show()
        _app.processEvents()

    def test_there_is_no_file_name_box_or_picker_in_the_window(self):
        for name in ("workbook_combo", "workbook_row", "picker_row"):
            self.assertFalse(hasattr(self.w, name), name)

    def test_the_folder_is_muted_with_no_file_and_solid_with_one(self):
        empty = self.w.open_file_button.icon().pixmap(18, 18).toImage()
        self.w.update_workbook("plants.xlsx")
        filled = self.w.open_file_button.icon().pixmap(18, 18).toImage()
        self.assertNotEqual(empty, filled)
        self.assertEqual(self.seen[-1], (True, "plants.xlsx"))
        self.assertIn("plants.xlsx", self.w.open_file_button.toolTip())
        self.w.update_workbooks([], "")
        self.assertEqual(self.seen[-1], (False, ""))
        self.assertEqual(self.w.open_file_button.toolTip().splitlines()[0], "Open Spreadsheet File")

    def test_the_folder_sits_left_of_the_settings_icon(self):
        row = self.w._status_row
        order = [row.itemAt(i).widget() for i in range(row.count())]
        self.assertEqual(order.index(self.w.open_file_button) + 1, order.index(self.w.settings_button))

    def test_the_window_icon_hides_once_the_title_bar_has_its_own(self):
        self.w.set_native_file_button(True)
        self.assertFalse(self.w.open_file_button.isVisibleTo(self.w.widget))


class TestFolderIconInTheTitleBar(unittest.TestCase):
    def test_it_is_the_first_extra_icon_left_of_settings(self):
        from tests.test_window_polish import FakeAppKit, native, restore
        native()
        self.addCleanup(restore)
        kit = FakeAppKit()
        kit.NSStackView = type("S", (), {"stackViewWithViews_": staticmethod(lambda views: type(
            "Stack", (), {"views": views, "setSpacing_": lambda s, v: None, "setFrame_": lambda s, f: None})())})
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QRegion
        from PySide6.QtWidgets import QWidget
        chrome.add_titlebar_button(QWidget(), lambda: None, platform="darwin", appkit=kit,
                                   extra=[(chrome.SYMBOL_FOLDER, "Open Spreadsheet File", lambda: None),
                                          (chrome.SYMBOL_SETTINGS, "Settings", lambda: None)])
        views = kit.window.accessories[0].view.views
        self.assertEqual(views[0].image, f"image:{chrome.SYMBOL_FOLDER}")
        self.assertEqual(views[1].image, f"image:{chrome.SYMBOL_SETTINGS}")


class TestStartAsksForAFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        wb = openpyxl.Workbook()
        wb.active.append(["Species"])
        wb.active.append(["Fern"])
        self.plants = self.dir / "plants.xlsx"
        wb.save(self.plants)
        self.asked = []

    def make(self, answer):
        def chooser():
            self.asked.append(1)
            return answer
        class Dead(XlsxBridge):
            def connect(self, workbook=None):
                from quill.bridge.base import BridgeError
                raise BridgeError("nothing open")
        app = QuillApp(_app, Settings.load(self.dir / "cfg"), Dead(), listener_factory=lambda *a: FakeListener(*a),
                       model_finder=lambda c: self.dir, speaker=FakeSpeaker(), file_chooser=chooser,
                       live_bridge_factory=lambda: Dead())
        app.start()
        return app

    def test_start_with_no_file_opens_the_file_window_and_then_listens(self):
        app = self.make(str(self.plants))
        self.assertFalse(app.connected)
        app.toggle_listening(True)
        self.assertEqual(self.asked, [1])
        self.assertTrue(app.connected)
        self.assertTrue(app.controller.session.listening)

    def test_cancelling_the_file_window_does_not_start_listening(self):
        app = self.make(None)
        app.toggle_listening(True)
        self.assertEqual(self.asked, [1])
        self.assertFalse(app.controller.session.listening)

    def test_with_a_file_open_start_just_starts(self):
        app = self.make(str(self.plants))
        app.open_workbook_file(self.plants)
        self.asked.clear()
        app.toggle_listening(True)
        self.assertEqual(self.asked, [])


class TestMiniErrorMark(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.resize(460, 500)
        self.w.widget.show()
        self.w.set_mini(True)
        _app.processEvents()

    def test_hidden_until_an_error_then_shown_with_the_message(self):
        self.assertFalse(self.w.error_button.isVisibleTo(self.w.widget))
        self.w.append_log("All fine")
        self.assertFalse(self.w.error_button.isVisibleTo(self.w.widget))
        self.w.append_log("Could not save the row: x", "error")
        self.assertTrue(self.w.error_button.isVisibleTo(self.w.widget))
        self.assertIn("Could not save the row: x", self.w.error_button.toolTip())

    def test_not_shown_in_the_full_window(self):
        self.w.set_mini(False)
        self.w.append_log("bad", "error")
        _app.processEvents()
        self.assertFalse(self.w.error_button.isVisibleTo(self.w.widget))

    def test_clicking_it_goes_back_to_the_full_window_with_the_log_open(self):
        self.w.append_log("bad", "error")
        self.w.error_button.click()
        _app.processEvents()
        self.assertFalse(self.w.mini)
        self.assertTrue(self.w.log.isVisibleTo(self.w.widget))
        self.assertFalse(self.w.error_button.isVisibleTo(self.w.widget))

    def test_a_saved_row_clears_it(self):
        self.w.append_log("bad", "error")
        self.w.clear_mini_error()
        self.assertFalse(self.w.error_button.isVisibleTo(self.w.widget))


class TestLeavingMiniDoesNotDrift(unittest.TestCase):
    def test_the_start_button_stays_put_while_the_window_grows_back(self):
        w = MainWindow()
        w.setup()
        w.widget.resize(460, 500)
        w.widget.show()
        w.animation_ms = 200
        w.set_mini(True)
        _app.processEvents()
        w.set_mini(False)
        tops = []
        timer = QTimer()
        timer.timeout.connect(lambda: tops.append(w.toggle_button.geometry().y()))
        timer.start(20)
        end = QTimer()
        end.setSingleShot(True)
        end.timeout.connect(_app.quit)
        end.start(450)
        _app.exec()
        timer.stop()
        self.assertGreater(len(tops), 5)
        self.assertLessEqual(max(tops) - min(tops), 2)           # it used to slide 150 px down and jump back up


class TestWaveIsThinner(unittest.TestCase):
    def test_the_lines_are_two_pixels_wide(self):
        wave = WaveMeter()
        from PySide6.QtGui import QImage
        image = QImage(wave.size(), QImage.Format.Format_ARGB32)
        image.fill(0)
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QRegion
        from PySide6.QtWidgets import QWidget
        wave.render(image, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
        row = image.height() // 2
        run = best = 0
        for x in range(image.width()):
            if image.pixelColor(x, row).alpha() > 128:
                run += 1
                best = max(best, run)
            else:
                run = 0
        self.assertLessEqual(best, 2)


if __name__ == "__main__":
    unittest.main()
