"""What the grid shows for the columns Quill helps with: a counter's next number in a grey pill (never the colour of spoken words), and
a small "i" after the name of a note or a counter whose help appears when the pointer rests on it.

The colours are measured on the painted grid, not read from a setting.
"""
import pathlib
import tempfile
import unittest

import openpyxl
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.ui.theme import grey_pill
from tests.test_app import FakeListener, FakeSpeaker
from tests.test_counters import make_book

_app = QApplication.instance() or QApplication([])


class GridCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.path = make_book(self.dir / "stock.xlsx")
        self.quill = QuillApp(_app, Settings.load(self.dir / "cfg"), XlsxBridge(self.path),
                              listener_factory=lambda m, t, e: FakeListener(m, t, e), model_finder=lambda c: self.dir / "model",
                              speaker=FakeSpeaker())
        self.quill.start()
        self.window = self.quill.window
        self.table = self.window.row_table
        self.addCleanup(self.window.widget.close)

    def hear(self, *phrases):
        for phrase in phrases:
            self.quill.relay.transcript.emit(phrase)

    def row_of(self, column):
        return next(r for r in range(self.table.rowCount()) if self.table.item(r, 0).text() == column)

    def pill_colour(self, column):
        """The colour painted at the left end of the value pill of *column* (inside its padding)."""
        self.table.resize(max(self.table.width(), 360), self.table.height())
        row = self.row_of(column)
        x = self.table.columnViewportPosition(1) + self.table.fontMetrics().averageCharWidth() // 4 + 7
        y = self.table.rowViewportPosition(row) + self.table.rowHeight(row) // 2
        return self.table.viewport().grab().toImage().pixelColor(x, y)

    def sheet(self):
        return openpyxl.load_workbook(self.path)["Stock"]


class TestTheGreyPill(GridCase):
    def test_the_number_shows_in_the_grid_once_listening_in_a_grey_pill(self):
        self.assertEqual(self.window.auto_lines(), [])
        self.hear("start listening")
        self.assertEqual(self.window.auto_lines(), [("ID", "6")])
        self.assertTrue(self.table.is_auto(self.row_of("ID")))
        self.assertFalse(self.table.is_auto(self.row_of("Species")))

    def test_it_is_not_one_of_the_heard_lines(self):
        self.hear("start listening", "species fern")
        self.assertEqual(self.window.heard_lines(), [("Species", "Fern")])
        self.assertEqual(self.window.auto_lines(), [("ID", "6")])
        self.assertEqual([self.table.item(r, 0).text() for r in range(2)], ["Species", "ID"])      # (after what was said)

    def test_the_painted_pill_is_grey_and_a_spoken_one_is_the_accent_colour(self):
        self.window.show()
        self.hear("start listening", "species fern")
        grey_fill = QColor(grey_pill(self.window._text_color)[0])
        accent = QColor(self.window._accent)
        spoken, filled = self.pill_colour("Species"), self.pill_colour("ID")
        self.assertEqual(spoken.name(), accent.name(), "a spoken value is in the accent colour")
        self.assertEqual(filled.name(), grey_fill.name(), "a value Quill filled in is in the muted grey")
        self.assertNotEqual(filled.name(), accent.name())

    def test_a_value_the_user_says_replaces_it_and_wears_the_spoken_colour(self):
        self.window.show()
        self.hear("start listening", "id fifty seven")
        self.assertEqual(self.window.auto_lines(), [])
        self.assertEqual([c for c, _ in self.window.heard_lines()], ["ID"])
        self.assertFalse(self.table.is_auto(self.row_of("ID")))
        self.assertEqual(self.pill_colour("ID").name(), QColor(self.window._accent).name())

    def test_its_line_can_be_removed_and_the_row_is_written_without_it(self):
        self.hear("start listening", "species fern")
        self.window._remove_row_requested("ID")
        self.assertEqual(self.window.auto_lines(), [])
        self.hear("next row")
        self.assertEqual([c.value for c in self.sheet()["A"]][-1], None)
        self.assertEqual(self.window.auto_lines(), [("ID", "6")])                  # (the next row is offered a number again)

    def test_the_next_row_shows_the_next_number_after_a_save(self):
        self.hear("start listening", "species fern", "next row")
        self.assertEqual(self.window.auto_lines(), [("ID", "7")])
        self.assertEqual(self.sheet()["A7"].value, 6)

    def test_stopping_listening_clears_the_grey_line(self):
        self.hear("start listening", "stop listening")
        self.assertEqual(self.window.auto_lines(), [])

    def test_the_log_says_what_was_filled_in(self):
        self.hear("start listening", "species fern", "next row")
        self.assertIn("Assumed: ID = 6", self.window.log.toPlainText())

    def test_the_grey_pill_is_not_offered_a_change_of_column(self):
        self.hear("start listening", "species fern")
        self.assertNotIn("ID", self.table._changeable)


class TestTheInformationIcon(GridCase):
    def test_a_note_and_a_counter_have_one_and_the_other_columns_do_not(self):
        self.assertEqual(sorted(self.table._tips), ["ID", "Notes"])
        self.assertTrue(self.table.has_tip(self.row_of("ID")))
        self.assertFalse(self.table.has_tip(self.row_of("Species")))

    def test_the_icons_are_there_before_anything_is_said_and_after_a_save(self):
        self.assertEqual(sorted(self.table._tips), ["ID", "Notes"])
        self.hear("start listening", "species fern", "next row")
        self.assertEqual(sorted(self.table._tips), ["ID", "Notes"])
        self.assertIn("4, 5, 6 → 7", self.table._tips["ID"])                       # (the help follows the numbering)

    def test_the_help_of_a_note_says_how_to_dictate_it(self):
        tip = self.table.tip_for(self.row_of("Notes"))
        for words in ("say the column's name", "end note", "next row"):
            self.assertIn(words, tip.replace("\n", " "))
        self.assertTrue(all(len(line) <= self.table.TIP_WIDTH + 12 for line in tip.splitlines()), "wrapped, not one long line")

    def test_the_help_of_a_counter_names_the_run_and_the_next_value(self):
        tip = self.table.tip_for(self.row_of("ID")).replace("\n", " ")
        self.assertIn("3, 4, 5 → 6", tip)
        self.assertIn("Say a value", tip)

    def test_resting_the_pointer_on_the_icon_shows_the_help_and_elsewhere_does_not(self):
        self.window.show()
        self.table.resize(max(self.table.width(), 360), self.table.height())
        row = self.row_of("Notes")
        icon = self.table.icon_rect(row).center()
        QTest.mouseMove(self.table.viewport(), icon)
        self.assertEqual(self.table.viewport().toolTip(), self.table.tip_for(row))
        QTest.mouseMove(self.table.viewport(), QPoint(self.table.columnWidth(0) + 30, icon.y()))
        self.assertEqual(self.table.viewport().toolTip(), "")
        species = self.table.rowViewportPosition(self.row_of("Species")) + 5
        QTest.mouseMove(self.table.viewport(), QPoint(self.table.icon_rect(row).center().x(), species))
        self.assertEqual(self.table.viewport().toolTip(), "")                          # (a column with no help has no icon to hit)

    def test_the_icon_is_painted_inside_the_name_cell_and_a_long_name_stops_short_of_it(self):
        self.window.show()
        self.table.resize(max(self.table.width(), 360), self.table.height())
        row = self.row_of("Notes")
        box = self.table.icon_rect(row)
        self.assertLess(box.right(), self.table.columnWidth(0))
        self.assertGreaterEqual(box.left(), 0)
        image = self.table.viewport().grab().toImage()
        disc = image.pixelColor(box.center().x() - 3, box.center().y() + 3)         # (inside the disc, away from the cut-out "i")
        background = image.pixelColor(2, box.center().y())
        self.assertNotEqual(disc.name(), background.name(), "the disc is drawn")

    def test_an_icon_does_not_make_the_column_changeable_or_removable(self):
        self.assertEqual(self.table._active, set())
        self.assertEqual(self.table._changeable, set())


if __name__ == "__main__":
    unittest.main()
