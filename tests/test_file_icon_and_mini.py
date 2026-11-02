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
        self.w = MainWindow(on_file_state=lambda has, name, sheet: self.seen.append((has, name, sheet)))
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
        self.assertEqual(self.seen[-1], (True, "plants.xlsx", ""))
        self.w.set_active_sheet("Inventory")
        self.assertIn("Sheet: Inventory", self.w.open_file_button.toolTip())
        self.assertEqual(self.seen[-1], (True, "plants.xlsx", "Inventory"))
        self.assertIn("plants.xlsx", self.w.open_file_button.toolTip())
        self.w.update_workbooks([], "")
        self.assertEqual(self.seen[-1], (False, "", ""))
        self.assertEqual(self.w.open_file_button.toolTip().splitlines()[0], "Open Spreadsheet File")

    def test_the_folder_sits_left_of_the_settings_icon(self):
        row = self.w._status_row
        order = [row.itemAt(i).widget() for i in range(row.count())]
        self.assertEqual(order.index(self.w.open_file_button) + 2, order.index(self.w.settings_button))      # the turn icon sits between

    def test_the_window_icon_hides_once_the_title_bar_has_its_own(self):
        self.w.set_native_file_button(True)
        self.assertFalse(self.w.open_file_button.isVisibleTo(self.w.widget))


class TestFolderIconInTheTitleBar(unittest.TestCase):
    def test_it_is_the_first_extra_icon_left_of_settings(self):
        from tests.test_window_polish import FakeAppKit, native, restore
        native()
        self.addCleanup(restore)
        kit = FakeAppKit()
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QRegion
        from PySide6.QtWidgets import QWidget
        chrome.add_titlebar_button(QWidget(), lambda: None, platform="darwin", appkit=kit,
                                   extra=[(chrome.SYMBOL_FOLDER, "Open Spreadsheet File", lambda: None),
                                          (chrome.SYMBOL_SETTINGS, "Settings", lambda: None)])
        views = kit.window.accessories[0].view.subviews[0].subviews           # the row inside the holder
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

    def test_start_with_no_file_opens_the_files_panel_not_the_file_window(self):
        app = self.make(str(self.plants))
        self.assertFalse(app.connected)
        app.toggle_listening(True)
        self.assertEqual(self.asked, [])                              # the system file window is not shown
        self.assertEqual(app.window.panel_page, "file")               # the Files panel is
        self.assertFalse(app.controller.session.listening)            # and nothing listens until a file is chosen

    def test_a_file_picked_in_the_panel_then_lets_start_listen(self):
        app = self.make(str(self.plants))
        app.toggle_listening(True)
        app.window.panel.file_button.click()                           # the panel's button asks for the file
        self.assertEqual(self.asked, [1])
        self.assertTrue(app.connected)
        app.toggle_listening(True)
        self.assertTrue(app.controller.session.listening)

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


class TestTermHelperClosing(unittest.TestCase):
    def setUp(self):
        from quill.parser.vocab import Vocabulary
        from quill.ui.sorting_window import SortingWindow
        vocab = Vocabulary()
        vocab.load({"Era": ["1980s"], "Color": ["Black"]})
        self.done = []
        self.win = SortingWindow(vocab, lambda *a: None)
        self.win.setup()
        self.win.on_done = lambda: self.done.append(1)

    def test_on_done_is_called_once_when_the_last_row_has_gone(self):
        self.win.set_items([("Era", "90s"), ("Color", "teal")])
        self.win.widget.show()
        self.win.set_items([])
        self.assertEqual(self.done, [1])

    def test_it_is_not_called_for_an_empty_list_while_the_window_was_never_open(self):
        self.win.set_items([])
        self.assertEqual(self.done, [])

    def test_the_main_window_comes_back_and_a_finished_row_is_cleared(self):
        w = MainWindow()
        w.setup()
        w.set_stream_partial("black shirt")
        w.end_stream()
        w.sorting_finished()
        self.assertEqual(w.stream_text(), "")

    def test_a_row_still_being_built_keeps_its_heard_words(self):
        w = MainWindow()
        w.setup()
        w.set_stream_partial("black shirt")
        w.sorting_finished()
        self.assertEqual(w.stream_text(), "black shirt")


class TestNextRowButton(unittest.TestCase):
    def test_visible_only_while_listening_and_it_calls_back(self):
        calls = []
        w = MainWindow(on_next_row=lambda: calls.append(1))
        w.setup()
        w.widget.resize(460, 500)
        w.widget.show()
        _app.processEvents()
        self.assertFalse(w.next_button.isVisibleTo(w.widget))
        w.set_listening_indicator(True)
        self.assertTrue(w.next_button.isVisibleTo(w.widget))
        w.next_button.click()
        self.assertEqual(calls, [1])
        w.set_listening_indicator(False)
        self.assertFalse(w.next_button.isVisibleTo(w.widget))


class TestNextRowInTheApp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = pathlib.Path(self._tmp.name)
        from quill.demo import make_demo_workbook
        self.app = QuillApp(_app, Settings.load(d / "cfg"), XlsxBridge(make_demo_workbook(d)),
                            listener_factory=lambda *a: FakeListener(*a), model_finder=lambda c: d,
                            speaker=FakeSpeaker(), sound_player=lambda p: None)
        self.app.start()
        self.app.toggle_listening(True)

    def test_the_arrow_saves_the_row_clears_the_words_and_the_grid(self):
        self.app._on_phrase_heard("black jeans medium")
        self.app.controller.handle_transcript("black jeans medium")
        self.assertTrue(self.app.controller.session.record)
        before = self.app.controller.session.committed
        self.app.next_row()
        self.assertEqual(self.app.controller.session.committed, before + 1)
        self.assertEqual(self.app.window.stream_text(), "")
        self.assertEqual(self.app.window.row_table.rowCount(), 0)
        self.assertTrue(self.app.controller.session.listening)               # ready for the next row

    def test_with_nothing_heard_it_only_clears_the_words(self):
        self.app.window.set_stream_partial("mumble")
        self.app.next_row()
        self.assertEqual(self.app.window.stream_text(), "")
        self.assertEqual(self.app.controller.session.committed, 0)


class TestOpenTermHelperByVoice(unittest.TestCase):
    def test_the_keywords_exist_and_say_it_opens_the_window(self):
        from quill.parser.commands import Action
        settings = Settings.defaults()
        self.assertEqual(settings.keywords["open term helper"], Action.OPEN_TERM_HELPER)
        self.assertEqual(settings.keywords["term helper"], Action.OPEN_TERM_HELPER)

    def test_the_command_becomes_an_event(self):
        from quill.session import Session
        from quill.parser.vocab import Vocabulary
        from quill.parser.commands import CommandMatcher
        settings = Settings.defaults()
        session = Session(Vocabulary(), CommandMatcher(settings.keywords))
        session.listening = True
        kinds = [e.kind for e in session.feed("open term helper")]
        self.assertIn("open_term_helper", kinds)


class TestMiniCollapseWithContent(unittest.TestCase):
    def test_a_long_stream_and_a_full_grid_do_not_stop_the_window_shrinking(self):
        w = MainWindow()
        w.setup()
        w.widget.resize(460, 420)
        w.widget.show()
        w.animation_ms = 120
        w.set_stream_partial("give me some things to say i don't have anything you talk a little bit you really good "
                             "you feel this whole prompt up for stuff the red cat ugly matt add to the hat")
        w.update_current_row({"Category": "Other", "Brand": "Things", "Condition": "Good", "Color": "Red"})
        w.set_sorting_count(7)
        _app.processEvents()
        w.set_mini(True, notify=True)
        end = QTimer()
        end.setSingleShot(True)
        end.timeout.connect(_app.quit)
        end.start(700)
        _app.exec()
        self.assertTrue(w._view_mini)                                  # the switch finished (it used to be cut short)
        self.assertLess(w.widget.height(), 200)


class TestOneClickWithADropDownOpen(unittest.TestCase):
    def test_a_click_on_the_listen_button_closes_the_popup_and_presses_it(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget
        from quill.ui.widgets import ListenButton, PopupClickThrough
        host = QWidget()
        layout = QVBoxLayout(host)
        combo = QComboBox()
        combo.addItems(["a", "b"])
        button = ListenButton()
        pressed = []
        button.clicked.connect(lambda: pressed.append(1))
        layout.addWidget(combo)
        layout.addWidget(button)
        host.resize(300, 300)
        host.show()
        filt = PopupClickThrough(_app)
        _app.installEventFilter(filt)
        try:
            combo.showPopup()
            QTest.qWait(100)
            if _app.activePopupWidget() is None:
                self.skipTest("this platform does not open real popups")
            global_pos = button.mapToGlobal(button.rect().center())
            event = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(button.rect().center()), QPointF(global_pos),
                                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            self.assertTrue(filt.eventFilter(button, event))
            QTest.qWait(100)
            self.assertIsNone(_app.activePopupWidget())
            self.assertEqual(pressed, [1])
        finally:
            _app.removeEventFilter(filt)
            host.close()
