"""The Settings window opens once, where it stays: it was shown in the screen's corner and moved to the middle a moment later (a visible jump,
reported as a flicker on Windows). Its place is now worked out before it is shown."""
import pathlib
import tempfile
import unittest

from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from quill.config.settings import Settings
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.theme import apply_theme

_app = QApplication.instance() or QApplication([])


class Watch(QObject):
    """Notes where each top-level window is every time it is shown, or moves while it is visible."""

    def __init__(self):
        super().__init__()
        self.moves = []
        self.windows = []                                           # every top-level window shown: its class and title

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.windows.append(f"{obj.metaObject().className()}:{obj.windowTitle() or '-'}")
        if isinstance(obj, QWidget) and obj.isWindow() and obj.windowTitle() == "Quill Settings":
            if event.type() in (QEvent.Type.Show, QEvent.Type.Move):
                self.moves.append((event.type().name, obj.x(), obj.y(), obj.isVisible()))
        return False


class TestOpeningSettings(unittest.TestCase):
    def setUp(self):
        apply_theme(_app, "light")
        self.parent = QWidget()
        self.parent.setGeometry(300, 200, 453, 533)
        self.parent.show()
        self.watch = Watch()
        _app.installEventFilter(self.watch)
        self.addCleanup(_app.removeEventFilter, self.watch)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dialog = SettingsDialog(Settings.load(pathlib.Path(self.folder.name)), self.parent)
        self.addCleanup(self.dialog.close_now)

    def test_the_window_is_not_moved_once_it_is_on_screen(self):
        self.dialog.open()
        QTest.qWait(500)
        shown = [m for m in self.watch.moves if m[0] == "Show"]
        self.assertTrue(shown)
        first_visible = next(m for m in self.watch.moves if m[3])
        later = [m for m in self.watch.moves if m[3] and m is not first_visible and m[0] == "Move"]
        self.assertEqual(later, [], f"moved after it appeared: {self.watch.moves}")

    def test_no_other_window_flashes_up_while_it_is_built(self):
        """Three small windows (the speech models' cost lines) were shown for a moment before the real one: a widget with no parent yet
        that is made visible opens as a window of its own."""
        self.dialog.open()
        QTest.qWait(500)
        self.assertEqual([w for w in self.watch.windows if "Quill Settings" not in w], [], self.watch.windows)

    def test_it_opens_centred_on_the_window_it_belongs_to(self):
        self.dialog.open()
        QTest.qWait(500)
        window = self.dialog._dialog
        screen = self.parent.screen().availableGeometry()
        if window.width() > screen.width() or window.height() > screen.height():
            self.skipTest("the (headless) screen is smaller than the window: it is kept on the screen instead")
        parent_centre = self.parent.frameGeometry().center()
        dialog_centre = window.frameGeometry().center()
        self.assertLessEqual(abs(parent_centre.x() - dialog_centre.x()) + abs(parent_centre.y() - dialog_centre.y()), 60,
                             f"{parent_centre} against {dialog_centre}")

    def test_it_stays_on_the_screen_when_the_parent_is_near_an_edge(self):
        self.parent.move(-150, -80)
        self.dialog.open()
        QTest.qWait(500)
        screen = self.parent.screen().availableGeometry()
        frame = self.dialog._dialog.frameGeometry()
        self.assertGreaterEqual(frame.left(), screen.left() - 2)
        self.assertGreaterEqual(frame.top(), screen.top() - 2)


if __name__ == "__main__":
    unittest.main()
