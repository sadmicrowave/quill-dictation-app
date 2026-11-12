"""No window of its own appears for a moment while another is built.

A widget that has no parent yet and is made visible (``setVisible(True)``, or ``setVisible(bool(text))`` with some text) opens as a top-level window until it is
put in a layout: a small window flashing on the screen. It happened for the speech models' cost lines when Settings opened, and for the Term Helper's "Same As M"
button. Here every window that is shown while such a thing is built is listed: only the one that was asked for may be there.
"""
import pathlib
import tempfile
import unittest

from PySide6.QtCore import QEvent, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from quill.config.settings import Settings
from quill.parser.vocab import Vocabulary
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.sorting_window import TermRow
from quill.ui.theme import apply_theme

_app = QApplication.instance() or QApplication([])


class Watch(QObject):
    def __init__(self):
        super().__init__()
        self.windows = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.windows.append(f"{obj.metaObject().className()}:{obj.windowTitle() or obj.objectName() or '-'}")
        return False


class TestNothingFlashes(unittest.TestCase):
    def setUp(self):
        apply_theme(_app, "light")
        self.watch = Watch()
        _app.installEventFilter(self.watch)
        self.addCleanup(_app.removeEventFilter, self.watch)

    def test_a_term_row_with_a_short_code_suggestion_shows_no_window_of_its_own(self):
        vocab = Vocabulary()
        vocab.load({"Size": ["XS", "S", "M", "L", "XL"]}, ["Size"])
        row = TermRow(("Size", "medium"), vocab, lambda *a: None)
        QTest.qWait(100)
        self.assertEqual(row.short_code, "M")
        self.assertEqual(self.watch.windows, [])
        row.deleteLater()

    def test_a_term_row_without_one_shows_no_window_either(self):
        vocab = Vocabulary()
        vocab.load({"Color": ["Red", "Blue"]}, ["Color"])
        row = TermRow((None, "teal"), vocab, lambda *a: None)
        QTest.qWait(100)
        self.assertEqual(self.watch.windows, [])
        row.deleteLater()

    def test_building_settings_shows_only_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            dialog = SettingsDialog(Settings.load(pathlib.Path(folder)), None)
            dialog.open()
            QTest.qWait(400)
            dialog.close_now()
        self.assertEqual([w for w in self.watch.windows if "Quill Settings" not in w], [], self.watch.windows)


if __name__ == "__main__":
    unittest.main()
