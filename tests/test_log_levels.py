"""Log messages have a type: errors and warnings are labelled and coloured, and an error opens a collapsed log."""
import unittest

from PySide6.QtWidgets import QApplication

from quill.ui.main_window import LOG_LEVELS, MainWindow

_app = QApplication.instance() or QApplication([])


class TestLogLevels(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()

    def colours(self):
        """The text colour of each line (None = the default)."""
        from PySide6.QtGui import QTextFormat
        result = []
        block = self.w.log.document().begin()
        while block.isValid():
            fmt = block.begin().fragment().charFormat()
            has = fmt.hasProperty(QTextFormat.Property.ForegroundBrush)
            result.append(fmt.foreground().color().name().upper() if has else None)
            block = block.next()
        return result

    def test_errors_are_labelled_and_red_and_info_is_plain(self):
        self.w.append_log("All fine")
        self.w.append_log("Could not save the row: x", "error")
        self.w.append_log("Later, all fine again")
        lines = self.w.log.toPlainText().splitlines()
        self.assertNotIn("Error", lines[0])
        self.assertIn("Error  Could not save the row: x", lines[1])
        self.assertEqual(self.colours(), [None, LOG_LEVELS["error"][1], None])     # the red does not carry on

    def test_every_error_is_the_same_red_and_warnings_differ(self):
        self.w.append_log("a", "error")
        self.w.append_log("b", "error")
        self.w.append_log("c", "warning")
        one, two, three = self.colours()
        self.assertEqual(one, two)
        self.assertNotEqual(one, three)
        self.assertIn("Warning", self.w.log.toPlainText().splitlines()[2])

    def test_an_error_opens_a_collapsed_log_but_info_and_warnings_do_not(self):
        self.w.set_log_collapsed(True)
        self.w.append_log("fine")
        self.w.append_log("careful", "warning")
        self.assertTrue(self.w.log_collapsed)
        self.w.append_log("broken", "error")
        self.assertFalse(self.w.log_collapsed)

    def test_an_open_log_stays_open(self):
        self.w.set_log_collapsed(False)
        self.w.append_log("broken", "error")
        self.assertFalse(self.w.log_collapsed)
