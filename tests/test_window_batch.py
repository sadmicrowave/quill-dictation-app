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
        self.assertRegex(self.w.log.toPlainText(), r"^\d\d:\d\d:\d\d\thello\.$")


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
        self.d = SettingsDialog(self.settings, on_download_model=lambda quality: self.downloads.append(quality),
                                model_installed=lambda quality: self.installed)
        self.d.build()

    def test_the_speech_model_can_be_downloaded_from_settings(self):
        row = self.d.model_rows["standard"]
        self.assertFalse(row.download_button.isHidden())
        self.assertTrue(row.download_button.isEnabled())
        row.download_button.click()
        self.assertEqual(self.downloads, ["standard"])

    def test_progress_and_the_installed_state_show_on_the_row(self):
        row = self.d.model_rows["standard"]
        self.d.set_model_state("Downloading… 40%", True)
        self.assertEqual(row.description_label.text(), "Downloading… 40%")
        self.assertFalse(row.download_button.isEnabled())
        self.installed = True
        self.d.set_model_state("", False)
        self.assertFalse(row.uninstall_button.isHidden())                    # installed: Uninstall shows, no pill
        self.assertNotIn("Installed", row.description_label.text())
        self.assertTrue(row.download_button.isHidden())

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


class TestVoiceReactiveWave(unittest.TestCase):
    def test_a_quiet_room_is_a_short_loop_and_a_voice_makes_it_taller(self):
        wave = WaveMeter()
        wave.set_active(True)
        for _ in range(12):
            wave._tick()
        quiet = max(wave.bar_heights())
        for _ in range(12):
            wave.set_level(1.0)
            wave._tick()
        loud = max(wave.bar_heights())
        self.assertLess(quiet, 0.5)
        self.assertGreater(loud, quiet + 0.3)
        self.assertLessEqual(loud, 1.0)

    def test_it_falls_back_when_the_voice_stops(self):
        wave = WaveMeter()
        wave.set_active(True)
        wave.set_level(1.0)
        for _ in range(3):
            wave._tick()
        high = wave.level
        for _ in range(40):
            wave._tick()
        self.assertLess(wave.level, high / 3)

    def test_the_listener_measures_loudness(self):
        import struct

        from quill.listener.listener import Listener
        silence = struct.pack("<800h", *([0] * 800))
        speech = struct.pack("<800h", *([3000, -3000] * 400))
        self.assertEqual(Listener.loudness(silence), 0.0)
        self.assertGreater(Listener.loudness(speech), 0.8)
        self.assertEqual(Listener.loudness(b""), 0.0)


from quill.ui.widgets import WaveMeter  # noqa: E402


class TestTermHelperSoundsSetting(unittest.TestCase):
    def make(self, on):
        from quill.feedback import Feedback
        from quill.session import Event
        settings = Settings.defaults()
        settings.preferences["sorting_sounds"] = on
        played = []
        fb = Feedback(settings, play=played.append, say=lambda w: None)
        return fb, played, Event

    def test_on_by_default_and_plays_for_an_added_term(self):
        self.assertTrue(Settings.defaults().preferences["sorting_sounds"])
        fb, played, Event = self.make(True)
        fb.request(Event("add_values", detail="Added x"))
        self.assertEqual(fb.flush(), "success")

    def test_off_silences_term_helper_answers_but_not_other_cues(self):
        fb, played, Event = self.make(False)
        for kind in ("add_values", "alias_added", "skipped"):
            fb.request(Event(kind))
        self.assertIsNone(fb.flush())
        fb.request(Event("committed", record={"a": 1}))
        self.assertEqual(fb.flush(), "success")


class TestListenButtonLayout(unittest.TestCase):
    def setUp(self):
        from quill.ui.widgets import ListenButton
        self.b = ListenButton()
        self.b.resize(420, 40)
        self.b.show()
        _app.processEvents()

    def test_the_icon_is_inside_the_pill_at_its_start_and_the_pill_is_at_the_left(self):
        pill = self.b.pill
        self.assertTrue(pill.isAncestorOf(self.b.icon_label))
        self.assertLess(self.b.icon_label.x(), self.b.text_pill.x())
        self.assertLess(pill.mapTo(self.b, pill.rect().topLeft()).x(), 20)

    def test_the_pill_has_a_border_and_no_fill(self):
        from quill.ui import theme
        sheet = theme.stylesheet_for(False)
        rule = sheet[sheet.index('QFrame[listenPill="true"] {'):]
        rule = rule[:rule.index("}")]
        self.assertIn("background: transparent", rule)
        self.assertIn("border: 1px solid", rule)

    def test_the_countdown_is_right_of_the_pill_not_inside_it(self):
        self.b.set_active(True)
        self.b.set_countdown(7)
        _app.processEvents()
        self.assertFalse(self.b.pill.isAncestorOf(self.b.countdown_label))
        self.assertGreater(self.b.countdown_label.x(), self.b.pill.x() + self.b.pill.width() - 1)
        self.assertEqual(self.b.countdown_label.text(), "7s")

    def test_the_notice_chip_replaces_the_pill_at_the_left(self):
        from PySide6.QtWidgets import QLabel
        chip = QLabel("File not connected")
        self.b.set_chip(chip)
        chip.show()
        self.b.set_notice(True)
        _app.processEvents()
        self.assertFalse(self.b.pill.isVisibleTo(self.b))
        self.assertLess(chip.x(), 20)
