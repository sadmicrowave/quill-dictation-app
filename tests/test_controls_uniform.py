"""Slider hit area and uniform text padding of drop-downs and number boxes."""
import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QVBoxLayout, QWidget

from quill.ui.settings_widgets import CONTROL_HEIGHT, CONTROL_WIDTH, FlatCombo, GuardedSlider, GuardedSpinBox
from quill.ui.theme import apply_theme

_app = QApplication.instance() or QApplication([])


class TestSlider(unittest.TestCase):
    def setUp(self):
        self.slider = GuardedSlider()
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(300)
        self.slider.show()

    def test_click_beside_the_groove_jumps(self):
        """A press near (not on) the thin groove still sets the value there."""
        y = self.slider.height() // 2 + 9
        QTest.mouseClick(self.slider, Qt.MouseButton.LeftButton, pos=QPoint(225, y))
        self.assertTrue(60 <= self.slider.value() <= 85, self.slider.value())

    def test_drag_follows_the_pointer(self):
        y = self.slider.height() // 2
        QTest.mousePress(self.slider, Qt.MouseButton.LeftButton, pos=QPoint(20, y))
        QTest.mouseMove(self.slider, QPoint(150, y))
        QTest.mouseRelease(self.slider, Qt.MouseButton.LeftButton, pos=QPoint(150, y))
        self.assertTrue(40 <= self.slider.value() <= 60, self.slider.value())

    def test_target_is_tall(self):
        self.assertGreaterEqual(self.slider.minimumHeight(), 28)


class TestUniformText(unittest.TestCase):
    def ink_left(self, window, widget):
        img = window.grab().toImage().copy(widget.geometry())
        for x in range(3, img.width()):
            for y in range(10, img.height() - 10):
                if img.pixelColor(x, y).lightness() < 90:
                    return x
        return None

    def test_text_starts_at_the_same_place(self):
        for spacing in ("compact", "comfortable"):
            apply_theme(_app, "light", "violet", spacing)
            window = QWidget()
            layout = QVBoxLayout(window)
            flat, spin, plain = FlatCombo(), GuardedSpinBox(), QComboBox()
            flat.addItems(["XXXXX"])
            plain.addItems(["XXXXX"])
            spin.setRange(0, 99999)
            spin.setValue(88888)
            for widget in (flat, spin, plain):
                widget.setFixedSize(CONTROL_WIDTH, CONTROL_HEIGHT)
                layout.addWidget(widget)
            window.show()
            _app.processEvents()
            starts = {self.ink_left(window, w) for w in (flat, spin, plain)}
            self.assertEqual(len(starts), 1, f"{spacing}: {starts}")
