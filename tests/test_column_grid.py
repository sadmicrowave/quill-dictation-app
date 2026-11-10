"""The heard-words grid lists the active sheet's columns as soon as the file is connected (muted, in sheet order); a column heard
in a turn turns to the normal colour at once and comes to the top, in the order the words were said."""
import unittest

from PySide6.QtWidgets import QApplication

from quill.ui.main_window import MainWindow
from tests.fixtures import HEADERS
from tests.test_app import AppCase

_app = QApplication.instance() or QApplication([])


def names(window):
    table = window.row_table
    return [table.item(r, 0).text() for r in range(table.rowCount())]


def muted(window, row):
    table = window.row_table
    return table.item(row, 0).foreground() == table.palette().placeholderText()


class TestTheColumnsAreListed(AppCase):
    def test_connecting_lists_every_column_of_the_sheet_in_its_order_and_muted(self):
        window = self.quill.window
        self.assertEqual(names(window), HEADERS)
        self.assertTrue(all(muted(window, r) for r in range(len(HEADERS))))
        self.assertEqual(window.heard_lines(), [])
        self.assertFalse(window.row_placeholder.isVisible())

    def test_a_column_heard_turns_normal_and_goes_to_the_top_while_the_words_are_still_being_said(self):
        self.hear("start listening")
        window = self.quill.window
        self.quill._on_partial_heard("small")                  # (a partial: the phrase is not finished)
        first = names(window)[0]
        self.assertEqual(first, "Pot Size")
        self.assertFalse(muted(window, 0))
        self.assertTrue(muted(window, 1))
        self.assertEqual(names(window)[1:], [h for h in HEADERS if h != "Pot Size"])        # the others keep the sheet's order

    def test_heard_columns_are_in_the_order_they_were_said(self):
        self.hear("start listening")
        window = self.quill.window
        self.quill._on_partial_heard("small fern")
        self.assertEqual(names(window)[:2], ["Pot Size", "Species"])
        self.quill.window.clear_stream()
        self.quill._on_partial_heard("fern small")
        self.assertEqual(names(window)[:2], ["Species", "Pot Size"])

    def test_columns_with_no_words_stay_muted(self):
        self.hear("start listening")
        window = self.quill.window
        self.quill._on_partial_heard("fern")
        self.assertTrue(all(muted(window, r) for r in range(1, len(HEADERS))))

    def test_the_value_shows_once_it_is_understood_and_the_next_row_starts_over_muted_in_sheet_order(self):
        self.hear("start listening", "fern small")
        window = self.quill.window
        self.assertEqual([line[0] for line in window.heard_lines()][:2], ["Species", "Pot Size"])
        self.assertEqual(window.row_table.item(0, 1).text(), "Fern")
        self.hear("next row")
        self.assertEqual(names(window), HEADERS)
        self.assertTrue(all(muted(window, r) for r in range(len(HEADERS))))
        self.assertEqual(window.row_table.item(0, 1).text(), "")

    def test_only_a_line_with_a_value_can_be_removed(self):
        self.hear("start listening")
        window = self.quill.window
        self.quill._on_partial_heard("fern")
        self.assertFalse(window.row_table._removable(0))          # heard, but no value yet
        self.hear("fern")
        self.assertTrue(window.row_table._removable(0))
        self.assertFalse(window.row_table._removable(3))          # a muted line

    def test_a_column_read_again_unchanged_does_not_restart_the_animation(self):
        window = self.quill.window
        started = []
        window.row_table.ease_in_rows = lambda animate=True: started.append(animate)
        window.set_columns(list(HEADERS))
        self.assertEqual(started, [])
        window.set_columns(HEADERS[:3])
        self.assertEqual(len(started), 1)

    def test_letting_go_of_the_file_empties_the_grid_and_brings_the_hint_back(self):
        self.quill.controller.detach()
        window = self.quill.window
        self.assertEqual(window.row_table.rowCount(), 0)
        self.assertFalse(window.row_placeholder.isHidden())


class TestTheColumnsEaseIn(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow()
        self.window.animation_ms = 240                         # (the test setup turns window animations off)
        self.window.setup()
        self.window.widget.show()
        _app.processEvents()

    def test_rows_appear_one_after_the_other_from_the_top_and_the_animation_ends_by_itself(self):
        table = self.window.row_table
        self.window.set_columns(["A", "B", "C", "D"])
        self.assertEqual(table.row_opacity(0), 0.0)
        table._reveal_step(1.5)
        self.assertEqual(table.row_opacity(0), 1.0)
        self.assertAlmostEqual(table.row_opacity(1), 0.5)
        self.assertEqual(table.row_opacity(2), 0.0)                # later rows have not started
        table._reveal_done()
        self.assertEqual([table.row_opacity(r) for r in range(4)], [1.0] * 4)

    def test_no_animation_when_the_window_is_not_on_screen_or_animations_are_off(self):
        self.window.animation_ms = 0
        self.window.set_columns(["A", "B"])
        self.assertEqual(self.window.row_table.row_opacity(0), 1.0)

    def test_the_animation_is_short_even_for_a_long_sheet(self):
        table = self.window.row_table
        self.window.set_columns([f"Column {n}" for n in range(60)])
        self.assertLessEqual(table._reveal.duration(), 1100)


if __name__ == "__main__":
    unittest.main()
