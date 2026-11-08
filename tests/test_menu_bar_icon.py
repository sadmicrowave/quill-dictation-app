"""The menu bar icon: the quill feather of the app icon (outline while idle, solid while listening)."""
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

    @staticmethod
    def covered(img):
        return sum(1 for x in range(64) for y in range(64) if alpha_at(img, x, y) > 128)

    def test_listening_is_a_solid_feather_and_idle_an_outline_of_it(self):
        solid, outline = image(make_icon(True)), image(make_icon(False))
        self.assertGreater(self.covered(solid), 1.2 * self.covered(outline))         # the outline leaves the middle hollow
        self.assertEqual(alpha_at(solid, 2, 2), 0)                                   # nothing in the corners
        self.assertEqual(alpha_at(outline, 2, 2), 0)

    def test_the_rib_is_cut_out_of_the_solid_feather(self):
        from quill.ui import feather
        scale, (cx, cy) = 0.55, (32 - 0.55 * 68, 32 - 0.55 * 60)
        (x, y) = feather.SHAFT[round(0.6 * (len(feather.SHAFT) - 1))]
        self.assertLess(alpha_at(image(make_icon(True)), round(cx + scale * x), round(cy + scale * y)), 128)

    def test_the_feather_is_centred(self):
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
