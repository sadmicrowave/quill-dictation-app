"""A footer button drawn faded while off (the bug icon) keeps its size on a sharp (2x) screen."""
import unittest

from PySide6.QtWidgets import QApplication

from quill.ui.widgets import FooterButton

_app = QApplication.instance() or QApplication([])


def ink_width(button) -> int:
    image = button.icon().pixmap(FooterButton.ICON, FooterButton.ICON).toImage()
    xs = [x for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x, y).alpha() > 20]
    return max(xs) - min(xs)


class TestFadedFooterIcon(unittest.TestCase):
    def test_a_faded_icon_is_as_wide_as_a_full_one(self):
        full, faded = FooterButton("bug", "x"), FooterButton("bug", "x", idle_opacity=0.45)
        self.assertEqual(ink_width(faded), ink_width(full))

    def test_it_keeps_the_screens_pixel_ratio(self):
        full, faded = FooterButton("bug", "x"), FooterButton("bug", "x", idle_opacity=0.45)
        size = FooterButton.ICON
        self.assertEqual(faded.icon().pixmap(size, size).devicePixelRatio(), full.icon().pixmap(size, size).devicePixelRatio())


if __name__ == "__main__":
    unittest.main()
