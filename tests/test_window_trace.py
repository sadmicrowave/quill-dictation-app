"""The window trace a developer switches on (``QUILL_TRACE_WINDOWS``) to find a window that flickers: one line per show, hide, resize and move
of a top-level window, with its kind, title, size and time, and nothing the user typed."""
import pathlib
import tempfile
import unittest

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from quill.diagnostics import install_window_trace

_app = QApplication.instance() or QApplication([])


class TestWindowTrace(unittest.TestCase):
    def test_a_window_that_appears_and_goes_is_listed_with_its_size(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "trace.txt"
            tracer = install_window_trace(_app, path)
            window = QWidget()
            window.setObjectName("probe")
            window.setWindowTitle("Probe window")
            window.resize(321, 123)
            window.show()
            QTest.qWait(30)
            window.hide()
            QTest.qWait(30)
            _app.removeEventFilter(tracer)
            text = path.read_text(encoding="utf-8")
        shown = [line for line in text.splitlines() if " Show " in line and "Probe window" in line]
        self.assertTrue(shown, text)
        self.assertIn("321x123", shown[0])
        self.assertIn("name=probe", shown[0])
        self.assertTrue(any(" Hide " in line and "Probe window" in line for line in text.splitlines()))

    def test_child_widgets_and_their_text_are_not_written(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "trace.txt"
            tracer = install_window_trace(_app, path)
            window = QWidget()
            label = QLabel("a secret sentence the user said", window)
            window.show()
            QTest.qWait(30)
            window.hide()
            _app.removeEventFilter(tracer)
            text = path.read_text(encoding="utf-8")
        self.assertNotIn("secret", text)
        self.assertNotIn("QLabel", text)
        self.assertIs(label.parent(), window)


if __name__ == "__main__":
    unittest.main()
