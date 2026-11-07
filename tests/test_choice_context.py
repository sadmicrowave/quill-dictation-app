"""Picking from a short list by voice: the nearest sounding choice, and the two-step blink that confirms it."""
import unittest

from PySide6.QtWidgets import QApplication

from quill.parser.sounds import closest_choice
from quill.parser.vocab import Vocabulary
from quill.ui.sorting_window import TermRow

_app = QApplication.instance() or QApplication([])

COLUMNS = ["Category", "Gender", "Size", "Brand", "Color", "Era", "Condition"]


class TestClosestChoice(unittest.TestCase):
    def test_sound_alikes_find_their_column(self):
        self.assertEqual(closest_choice("sighs", COLUMNS), "Size")
        self.assertEqual(closest_choice("bran", COLUMNS), "Brand")
        self.assertEqual(closest_choice("colour", COLUMNS), "Color")

    def test_nothing_close_is_none(self):
        for word in ("shirt", "medium", "ok", "banana"):
            self.assertIsNone(closest_choice(word, COLUMNS), word)

    def test_a_tie_is_not_a_guess(self):
        self.assertIsNone(closest_choice("sighs", ["Size", "Sighs "]))

    def test_works_for_any_subject(self):
        self.assertEqual(closest_choice("depart", ["Observation Date", "Departure Date"]), "Departure Date")


class TestChoiceBlink(unittest.TestCase):
    def make_row(self):
        vocab = Vocabulary()
        vocab.load({"Size": ["S", "M"], "Color": ["Teal"]}, ["Size", "Color"])
        return TermRow((None, "jumbo"), vocab, lambda *a: None)

    def test_choosing_selects_it_and_marks_the_row(self):
        row = self.make_row()
        row.choose("Size")
        self.assertEqual(row.column, "Size")
        self.assertTrue(row.chosen)

    def test_an_unknown_column_changes_nothing(self):
        row = self.make_row()
        row.choose("Nope")
        self.assertFalse(row.chosen)
        self.assertIsNone(row.column)


class TestRebuiltWindowWatcher(unittest.TestCase):
    def test_headless_windows_are_never_reported_rebuilt(self):
        from PySide6.QtWidgets import QWidget

        from quill.platforms.macos import chrome
        widget = QWidget()
        called = []
        chrome.watch_native_window(widget, lambda: called.append(1))
        widget.show()
        for _ in range(5):
            _app.processEvents()
        self.assertFalse(chrome.native_window_rebuilt(widget))
        self.assertEqual(called, [])
