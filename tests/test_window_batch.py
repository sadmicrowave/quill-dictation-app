"""Log columns, the grid's last row, the Start button colours, minimum size, the speech model setting and Cancel."""
import pathlib
import tempfile
import unittest

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from quill.config.settings import Settings
from quill.ui.main_widgets import RowTable
from quill.ui.main_window import MIN_WINDOW, MainWindow
from quill.ui.settings_dialog import SettingsDialog

_app = QApplication.instance() or QApplication([])


class TestLogColumns(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.show()

    def block(self, index):
        block = self.w.log.document().begin()
        for _ in range(index):
            block = block.next()
        return block.blockFormat()

    def test_a_wrapped_line_returns_to_where_the_message_starts_not_under_the_time(self):
        self.w.append_log("a very long message " * 20, "error")
        fmt = self.block(0)
        self.assertGreater(fmt.leftMargin(), 30)
        self.assertEqual(fmt.textIndent(), -fmt.leftMargin())           # the first line starts at the edge, the rest at the margin
        self.assertEqual(fmt.tabPositions()[0].position, fmt.leftMargin())

    def test_every_line_has_the_same_columns(self):
        self.w.append_log("one")
        self.w.append_log("two", "warning")
        self.assertEqual(self.block(0).leftMargin(), self.block(1).leftMargin())

    def test_the_message_text_is_after_a_tab(self):
        self.w.append_log("hello")
        self.assertRegex(self.w.log.toPlainText(), r"^\d\d:\d\d:\d\d\thello$")


class TestStartButton(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.refresh_icons("#222222", "#FFFFFF", "#7A55C2")

    def icon_colour(self):
        image = self.w.toggle_icon.pixmap().toImage()
        for x in range(image.width()):
            for y in range(image.height()):
                if image.pixelColor(x, y).alpha() > 200:
                    return image.pixelColor(x, y).name().upper()

    def test_the_play_icon_follows_the_theme_colour(self):
        self.assertEqual(self.icon_colour(), "#7A55C2")

    def test_the_wave_is_muted_and_still_until_listening_then_green_and_moving(self):
        from quill.ui.main_window import COLOR_ACTIVE
        wave = self.w.wave
        self.assertFalse(wave.active)
        self.assertFalse(wave._timer.isActive())
        idle = wave.bar_heights()
        self.w.set_listening_indicator(True)
        self.assertTrue(wave.active and wave._timer.isActive())
        self.assertEqual(wave._live.name().lower(), COLOR_ACTIVE)
        wave._tick()
        self.assertNotEqual(idle, wave.bar_heights())               # it moves
        self.w.set_listening_indicator(False)
        self.assertFalse(wave._timer.isActive())
        self.assertEqual(idle, wave.bar_heights())                  # and is back to rest
        self.assertLess(wave._idle.alpha(), 255)                    # muted

    def test_there_is_no_listening_text_any_more(self):
        self.assertFalse(hasattr(self.w, "state_label"))
        self.w.set_listening_indicator(True)
        self.assertEqual(self.w.toggle_button.toolTip(), "Stop Listening")

class TestRowTable(unittest.TestCase):
    def test_no_line_under_the_last_row(self):
        table = RowTable(0, 2)
        table.setRowCount(2)
        from PySide6.QtWidgets import QTableWidgetItem
        for r in range(2):
            for c in range(2):
                table.setItem(r, c, QTableWidgetItem("x"))
        table.setStyleSheet("QTableWidget { gridline-color: #FF0000; }")
        table.resize(300, 120)
        table.show()
        _app.processEvents()
        image = QImage(table.viewport().size(), QImage.Format.Format_ARGB32)
        table.viewport().render(image)
        first_line = table.rowViewportPosition(0) + table.rowHeight(0) - 1
        last_line = table.rowViewportPosition(1) + table.rowHeight(1) - 1
        probe = 5       # inside the first column, away from the divider
        self.assertNotEqual(image.pixelColor(probe, first_line), image.pixelColor(probe, last_line))      # a line, then none
        self.assertEqual(image.pixelColor(probe, last_line), image.pixelColor(probe, last_line - 3))

    def test_the_tip_no_longer_mentions_grey_words(self):
        self.assertNotIn("grey", RowTable.DELETE_TIP)


class TestWindowSize(unittest.TestCase):
    def test_the_first_launch_opens_at_the_minimum(self):
        w = MainWindow()
        w.setup()
        w.widget.show()
        _app.processEvents()
        self.assertEqual((w.widget.width(), w.widget.height()), MIN_WINDOW)

    def test_the_window_cannot_be_dragged_smaller(self):
        w = MainWindow()
        w.setup()
        w.show()
        _app.processEvents()
        self.assertGreaterEqual(w.widget.minimumWidth(), MIN_WINDOW[0])
        self.assertGreaterEqual(w.widget.minimumHeight(), MIN_WINDOW[1])

    def test_a_smaller_remembered_size_is_raised_to_the_minimum(self):
        w = MainWindow()
        w.setup()
        w.restore_size(320, 330)
        w.restore_size(400, 400)
        w.widget.show()
        _app.processEvents()
        self.assertGreaterEqual(w.widget.width(), MIN_WINDOW[0])


class TestSettingsPieces(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings = Settings.load(pathlib.Path(self._tmp.name))
        self.downloads = []
        self.installed = False
        self.d = SettingsDialog(self.settings, on_download_model=lambda: self.downloads.append(1),
                                model_installed=lambda: self.installed)
        self.d.build()

    def test_the_speech_model_can_be_downloaded_from_settings(self):
        self.assertEqual(self.d.model_button.text(), "Download")
        self.assertTrue(self.d.model_button.isEnabled())
        self.d.model_button.click()
        self.assertEqual(self.downloads, [1])

    def test_progress_and_the_installed_state_show_on_the_row(self):
        self.d.set_model_state("Downloading… 40%", True)
        self.assertEqual(self.d.model_row.description_label.text(), "Downloading… 40%")
        self.assertFalse(self.d.model_button.isEnabled())
        self.installed = True
        self.d.set_model_state("", False)
        self.assertIn("Installed", self.d.model_row.description_label.text())
        self.assertFalse(self.d.model_button.isEnabled())

    def test_cancel_leaves_the_window_view_and_size_alone(self):
        self.d._original = dict(self.settings.preferences)         # as taken when the window opened
        self.settings.preferences["mini_mode"] = True               # the user went to the mini view meanwhile
        self.settings.preferences["window_width"] = 500
        self.settings.preferences["theme"] = "dark"                 # and a setting was changed live
        self.d.revert()
        self.assertTrue(self.settings.preferences["mini_mode"])
        self.assertEqual(self.settings.preferences["window_width"], 500)
        self.assertEqual(self.settings.preferences["theme"], self.d._original["theme"])


if __name__ == "__main__":
    unittest.main()
