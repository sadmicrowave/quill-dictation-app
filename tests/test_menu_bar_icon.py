"""The menu bar icon: the small rounded square of the app icon with its sound lines."""
import unittest

from PySide6.QtWidgets import QApplication

from quill.ui.main_window import MainWindow
from quill.ui.tray import TrayIcon, make_icon

_app = QApplication.instance() or QApplication([])


def image(icon, size=64):
    return icon.pixmap(size, size).toImage()


def alpha_at(img, x, y):
    return img.pixelColor(x, y).alpha()


class TestGlyph(unittest.TestCase):
    def test_idle_and_listening_look_different(self):
        self.assertNotEqual(image(make_icon(False)), image(make_icon(True)))

    def test_listening_is_a_solid_square_with_the_lines_cut_out(self):
        img = image(make_icon(True))
        self.assertGreater(alpha_at(img, 14, 14), 200)                  # the solid body near a corner
        self.assertGreater(alpha_at(img, 12, 32), 200)                  # solid left of the lines
        self.assertEqual(alpha_at(img, 32, 32), 0)                      # centre line cut out
        self.assertEqual(alpha_at(img, 4, 4), 0)                        # nothing outside the square

    def test_idle_is_an_outline_with_the_lines_drawn_in(self):
        img = image(make_icon(False))
        self.assertEqual(alpha_at(img, 18, 18), 0)                      # hollow inside the outline
        self.assertGreater(alpha_at(img, 32, 32), 200)                  # the centre line is solid
        self.assertGreater(alpha_at(img, 10, 32), 200)                  # the outline's left edge
        self.assertEqual(alpha_at(img, 4, 32), 0)

    def test_the_square_is_centred(self):
        for listening in (False, True):
            img = image(make_icon(listening))
            xs = [x for x in range(64) for y in range(64) if alpha_at(img, x, y) > 128]
            ys = [y for x in range(64) for y in range(64) if alpha_at(img, x, y) > 128]
            self.assertAlmostEqual((min(xs) + max(xs)) / 2, 31.5, delta=1.5)
            self.assertAlmostEqual((min(ys) + max(ys)) / 2, 31.5, delta=1.5)

    def test_it_is_a_mask_so_the_system_tints_it_for_light_and_dark_menu_bars(self):
        self.assertTrue(make_icon(False).isMask())
        self.assertTrue(make_icon(True).isMask())

    def test_the_shapes_are_black_in_mask_form(self):
        img = image(make_icon(False))
        self.assertEqual(img.pixelColor(32, 32).red(), 0)

    def test_a_badge_makes_it_a_coloured_icon_not_a_mask(self):
        icon = make_icon(False, badge=3, badge_color="#2F6FB5")
        self.assertFalse(icon.isMask())
        self.assertIn("#2f6fb5", {image(icon).pixelColor(x, y).name() for x in range(40, 64) for y in range(24)})

    def test_with_a_badge_the_shapes_follow_the_menu_bar_colour(self):
        light = image(make_icon(False, badge=2, dark=False)).pixelColor(20, 32)      # inside a line, clear of the badge
        dark = image(make_icon(False, badge=2, dark=True)).pixelColor(20, 32)
        self.assertEqual((light.red(), dark.red()), (0, 255))

    def test_the_badge_does_not_cover_the_whole_glyph(self):
        plain, badged = image(make_icon(True)), image(make_icon(True, badge=4))
        self.assertEqual(alpha_at(plain, 20, 50), alpha_at(badged, 20, 50))


class TestTrayDark(unittest.TestCase):
    def test_changing_the_menu_bar_colour_redraws_only_when_it_changes(self):
        window = MainWindow()
        window.setup()
        tray = TrayIcon(_app, window, on_start=lambda: None, on_stop=lambda: None)
        tray.setup()
        calls = []
        tray._redraw = lambda: calls.append(1)
        tray.set_dark(False)
        self.assertEqual(calls, [])
        tray.set_dark(True)
        tray.set_dark(True)
        self.assertEqual(calls, [1])

    def test_the_menu_has_no_mini_view_item(self):
        window = MainWindow()
        window.setup()
        tray = TrayIcon(_app, window, on_start=lambda: None, on_stop=lambda: None)
        tray.setup()
        self.assertNotIn("Mini View", [a.text() for a in tray._menu.actions()])


if __name__ == "__main__":
    unittest.main()
