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

    def test_the_play_icon_is_drawn_in_the_colour_used_on_the_accent(self):
        self.assertEqual(self.icon_colour(), "#FFFFFF")

    def test_the_graph_is_a_still_flat_line_until_listening_then_streams(self):
        wave = self.w.wave
        self.assertFalse(wave.active)
        self.assertFalse(wave._timer.isActive())                    # (an idle window runs nothing)
        self.assertEqual(wave.trace(), [])
        self.w.set_listening_indicator(True)
        self.assertTrue(wave.active and wave._timer.isActive())
        wave.set_level(0.8)
        wave._tick()
        for _ in range(6):
            wave._tick()
        first = [p.y() for p in wave.trace()]
        for _ in range(5):
            wave._tick()
        self.assertNotEqual(first[3:8], [p.y() for p in wave.trace()[3:8]])          # it moves
        self.w.set_listening_indicator(False)
        self.assertFalse(wave._timer.isActive())
        self.assertEqual(wave.trace(), [])                                              # and is back to rest

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
        self.assertEqual(w.widget.width(), MIN_WINDOW[0])
        self.assertEqual(w.widget.height(), max(MIN_WINDOW[1], w._fit_height()))        # (a window with a ribbon above Start needs more than the least height)

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
    def graph(self):
        graph = StreamGraph()
        graph.resize(160, 30)
        graph.set_active(True)
        return graph

    def swing(self, graph):
        return max(abs(p.y() - graph.height() / 2) for p in graph.trace())

    def test_a_quiet_room_is_a_small_ripple_and_a_voice_makes_peaks_and_troughs(self):
        graph = self.graph()
        for _ in range(40):
            graph._tick()
        quiet = self.swing(graph)
        for _ in range(40):
            graph.set_level(1.0)
            graph._tick()
        loud = self.swing(graph)
        self.assertLess(quiet, graph.height() / 2 * 0.3)
        self.assertGreater(loud, quiet * 3)
        self.assertLessEqual(loud, graph.height() / 2)

    def test_room_noise_keeps_the_lines_flat(self):
        graph = self.graph()
        for _ in range(60):
            graph.set_level(graph.GATE * 0.9)                  # below the gate: not a voice
            graph._tick()
        self.assertEqual(self.swing(graph), 0.0)

    def test_the_ring_follows_the_exact_share_left_not_whole_seconds(self):
        from quill.ui.listen_button import ListenButton
        button = ListenButton()
        button.set_countdown(7, 1.0)
        self.assertEqual(button.icon_label.ring, 1.0)
        button.set_countdown(7, 0.93)
        self.assertAlmostEqual(button.icon_label.ring, 0.93)           # still "7s", but the ring has moved on
        button.set_countdown(7)
        self.assertAlmostEqual(button.icon_label.ring, 1.0)             # no share: whole seconds, as before

    def test_new_sound_enters_at_the_left_and_moves_right(self):
        graph = self.graph()
        graph.set_level(1.0)
        graph._tick()
        newest = graph._samples[0]
        for _ in range(5):
            graph._tick()
        self.assertEqual(graph._samples[5], newest)                 # five readings later it is five steps to the right
        self.assertEqual(graph.trace()[5].x(), graph.LEAD + 5 * graph.STEP)

    def test_it_never_keeps_more_readings_than_the_graph_is_wide(self):
        graph = self.graph()
        for _ in range(500):
            graph._tick()
        self.assertLessEqual(len(graph._samples), int(graph.width() / graph.STEP) + 2)

    def test_it_falls_back_when_the_voice_stops(self):
        graph = self.graph()
        graph.set_level(1.0)
        for _ in range(3):
            graph._tick()
        high = graph.level
        for _ in range(40):
            graph._tick()
        self.assertLess(graph.level, high / 3)

    def test_the_listener_measures_loudness(self):
        import struct

        from quill.listener.listener import Listener
        silence = struct.pack("<800h", *([0] * 800))
        speech = struct.pack("<800h", *([3000, -3000] * 400))
        self.assertEqual(Listener.loudness(silence), 0.0)
        self.assertGreater(Listener.loudness(speech), 0.8)
        self.assertEqual(Listener.loudness(b""), 0.0)


from quill.ui.listen_button import StreamGraph  # noqa: E402


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
        from quill.ui.listen_button import ListenButton
        self.b = ListenButton()
        self.b.resize(420, 48)
        self.b.show()
        _app.processEvents()

    def x_of(self, widget):
        return widget.mapTo(self.b, widget.rect().topLeft()).x()

    def test_from_the_left_the_disc_with_the_icon_then_the_words_then_the_screen(self):
        self.assertLess(self.x_of(self.b.icon_label), 12)
        self.assertLess(self.x_of(self.b.icon_label), self.x_of(self.b.text_pill))
        self.assertLess(self.x_of(self.b.text_pill), self.x_of(self.b.screen))
        self.assertTrue(self.b.screen.isAncestorOf(self.b.wave))

    def test_the_screen_takes_the_room_after_the_words(self):
        screen = self.b.screen
        self.assertGreater(screen.width(), 150)
        self.assertGreater(screen.mapTo(self.b, screen.rect().topRight()).x(), self.b.width() - 20)     # (to near the right edge)
        self.assertLess(screen.height(), self.b.height())                                               # (inset, not against the edges)

    def test_the_countdown_is_inside_the_screen_after_the_graph_and_the_ring_follows_it(self):
        self.b.set_active(True)
        self.b.set_countdown(7)
        _app.processEvents()
        self.assertTrue(self.b.screen.isAncestorOf(self.b.countdown_label))
        self.assertGreater(self.x_of(self.b.countdown_label), self.x_of(self.b.wave))
        self.assertEqual(self.b.countdown_label.text(), "7s")
        self.assertEqual(self.b.icon_label.ring, 1.0)
        self.b.set_countdown(3)
        self.assertAlmostEqual(self.b.icon_label.ring, 3 / 7)
        self.b.set_countdown(None)
        self.assertIsNone(self.b.icon_label.ring)
        self.assertFalse(self.b.countdown_label.isVisibleTo(self.b))

    def test_the_notice_replaces_start_listening_in_the_same_button(self):
        self.b.set_notice(True, "Why")
        _app.processEvents()
        self.assertEqual(self.b.text_pill.text(), "File not connected")
        self.assertEqual(self.b.toolTip(), "Why")
        self.assertTrue(self.b.isEnabled())                        # (it can still be pressed: that is how it says no)
        self.b.set_notice(False)
        self.assertEqual(self.b.text_pill.text(), "Start Listening")
