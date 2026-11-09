"""Small widgets: the footer buttons."""
import unittest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

class TestFooterButtonIdleOpacity(unittest.TestCase):
    def test_idle_icon_is_fainter_than_selected(self):
        from quill.ui.widgets import FooterButton

        def ink(button):
            image = button.icon().pixmap(14, 14).toImage()
            return max(image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height()))

        button = FooterButton("bug", "Log", idle_opacity=0.45)
        idle = ink(button)
        button.setChecked(True)
        self.assertLess(idle, ink(button) * 0.6)
