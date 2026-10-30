"""Count badges (tray + inline), button icons, supporting-note styling and window opacity."""
import pathlib
import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import OPACITY_RANGE, Settings
from quill.ui import icons, theme
from quill.ui.main_window import MainWindow
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.tray import TrayIcon, make_icon
from quill.ui.widgets import Pill
from tests.test_sorting import SENTENCE, DemoCase

_app = QApplication.instance() or QApplication([])


def pixels(icon, size=64):
    return icon.pixmap(size, size).toImage()


class TestIcons(unittest.TestCase):
    def test_every_icon_is_valid_svg_in_the_requested_colour(self):
        for name in icons.SHAPES:
            svg = icons.svg_for(name, "#123456")
            self.assertIn("#123456", svg)
            self.assertNotIn("COLOR", svg)
            image = icons.make_icon(name, "#123456").pixmap(18, 18).toImage()
            self.assertTrue(any(image.pixelColor(x, y).alpha() > 0
                                for x in range(image.width()) for y in range(image.height())), name)

    def test_buttons_have_icons(self):
        w = MainWindow()
        w.setup()
        self.assertFalse(w.settings_button.icon().isNull())
        self.assertEqual(w.settings_button.text(), "")             # icon only
        self.assertEqual(w.settings_button.toolTip(), "Settings")
        self.assertEqual(w.settings_button.accessibleName(), "Settings")
        self.assertFalse(w.toggle_button.icon().isNull())
        self.assertEqual(w.toggle_button.text(), "Start")

    def test_start_and_stop_draw_different_icons(self):
        w = MainWindow()
        w.setup()
        start = w.toggle_button.icon().pixmap(16, 16).toImage()
        w.set_listening_indicator(True)
        stop = w.toggle_button.icon().pixmap(16, 16).toImage()
        self.assertEqual(w.toggle_button.text(), "Stop")
        self.assertNotEqual(start, stop)

    def test_icons_take_the_theme_colours(self):
        w = MainWindow()
        w.setup()
        w.refresh_icons("#00FF00", "#FF0000")
        image = w.toggle_button.icon().pixmap(16, 16).toImage()
        reds = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())
                if image.pixelColor(x, y).alpha() > 200]
        self.assertTrue(reds and all(c.red() > 200 and c.green() < 60 for c in reds))


class TestInlineBadge(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.show()

    def test_count_is_a_pill_inside_the_button(self):
        self.w.set_sorting_count(4)
        self.assertTrue(self.w.sorting_button.isVisible())
        self.assertEqual(self.w.badge_label.text(), "4")
        self.assertIsInstance(self.w.badge_label, Pill)
        self.assertIs(self.w.badge_label.parent(), self.w.sorting_button)
        self.assertEqual(self.w.sorting_button.accessibleName(), "Needs sorting (4)")

    def test_the_button_is_filled_with_the_accent(self):
        self.assertTrue(self.w.sorting_button.property("accent"))

    def test_clicking_anywhere_on_it_opens_the_list(self):
        opened = []
        w = MainWindow(on_sorting=lambda: opened.append(1))
        w.setup()
        w.widget.show()
        w.set_sorting_count(2)
        w.sorting_button.click()
        self.assertEqual(opened, [1])
        self.assertTrue(w.badge_label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_pill_paints_in_its_colours_with_round_ends(self):
        pill = Pill("3")
        pill.set_colors("#FFFFFF", "#2F6FB5")
        pill.resize(pill.sizeHint())
        image = pill.grab().toImage()
        corner = image.pixelColor(0, 0)
        self.assertNotEqual(corner.name().upper(), "#FFFFFF")      # rounded: the corner is not filled
        mid = image.pixelColor(image.width() // 2, 2)
        self.assertEqual(mid.name().upper(), "#FFFFFF")

    def test_pill_is_at_least_as_wide_as_it_is_tall(self):
        for text in ("1", "12", "123"):
            hint = Pill(text).sizeHint()
            self.assertGreaterEqual(hint.width(), hint.height())


class TestTrayBadge(unittest.TestCase):
    def test_no_badge_means_no_extra_marks(self):
        plain = pixels(make_icon(True))
        badged = pixels(make_icon(True, badge=3, badge_color="#2F6FB5"))
        self.assertNotEqual(plain, badged)

    def test_badge_is_in_the_given_colour_at_the_top_right(self):
        image = pixels(make_icon(False, badge=3, badge_color="#2F6FB5"))
        seen = {image.pixelColor(x, y).name().upper() for x in range(40, 64) for y in range(0, 24)}
        self.assertIn("#2F6FB5", seen)

    def test_badge_follows_the_colour(self):
        a = {pixels(make_icon(False, 2, "#2F6FB5")).pixelColor(x, y).name() for x in range(40, 64) for y in range(24)}
        b = {pixels(make_icon(False, 2, "#C0446B")).pixelColor(x, y).name() for x in range(40, 64) for y in range(24)}
        self.assertIn("#2f6fb5", a)
        self.assertIn("#c0446b", b)
        self.assertNotIn("#c0446b", a)

    def test_ten_or_more_reads_nine_plus_and_still_draws(self):
        self.assertNotEqual(pixels(make_icon(False, 9)), pixels(make_icon(False, 12)))
        self.assertEqual(pixels(make_icon(False, 12)), pixels(make_icon(False, 50)))    # both "9+"

    def test_tray_menu_offers_the_list_only_while_terms_wait(self):
        opened = []
        window = MainWindow()
        window.setup()
        tray = TrayIcon(_app, window, on_start=lambda: None, on_stop=lambda: None,
                        on_open_sorting=lambda: opened.append(1))
        tray.setup()
        self.assertFalse(tray._sorting_action.isVisible())
        self.assertEqual(tray.badge, 0)
        tray.set_badge(3, "#2F6FB5")
        self.assertEqual(tray.badge, 3)
        self.assertTrue(tray._sorting_action.isVisible())
        self.assertEqual(tray._sorting_action.text(), "Needs sorting (3)…")
        tray._sorting_action.trigger()
        self.assertEqual(opened, [1])
        tray.set_badge(0)
        self.assertFalse(tray._sorting_action.isVisible())

    def test_listening_changes_keep_the_badge(self):
        window = MainWindow()
        window.setup()
        tray = TrayIcon(_app, window, on_start=lambda: None, on_stop=lambda: None)
        tray.setup()
        tray.set_badge(2)
        tray.set_listening(True)
        self.assertEqual(tray.badge, 2)


class TestBadgeInTheApp(DemoCase):
    def setUp(self):
        super().setUp()
        self.app = QuillApp(_app, self.settings, XlsxBridge(self.path), listener_factory=lambda *a: None,
                            model_finder=lambda c: None, sound_player=lambda p: None)
        self.app.start()

    def hear(self, *phrases):
        for phrase in phrases:
            self.app.controller.handle_transcript(phrase)

    def test_tray_and_button_show_the_count_and_clear_with_it(self):
        self.hear("start listening", SENTENCE, "next row")
        self.assertEqual((self.app.tray.badge, self.app.window.badge_label.text()), (3, "3"))
        self.app.controller.start_voice_sort()
        self.hear("ignore all")
        self.assertEqual(self.app.tray.badge, 0)
        self.assertTrue(self.app.window.sorting_button.isHidden())

    def test_badge_colour_follows_the_chosen_accent(self):
        self.settings.preferences["accent"] = "forest"
        self.app.apply_settings()
        self.assertEqual(self.app.tray._badge_color, theme.colors_for(False, "forest")["accent"])
        self.settings.preferences["accent"] = "rose"
        self.app.apply_settings()
        self.assertEqual(self.app.tray._badge_color, theme.colors_for(False, "rose")["accent"])


class TestNoteStyle(unittest.TestCase):
    def test_last_saved_is_a_smaller_italic_note(self):
        w = MainWindow()
        w.setup()
        self.assertTrue(w.last_label.property("note"))
        sheet = theme.stylesheet_for(False, font_size=12)
        self.assertIn('QLabel[note="true"] { font-size: 10pt; font-style: italic;', sheet)
        self.assertIn("font-size: 14pt; font-style: italic", theme.stylesheet_for(False, font_size=16))


class TestOpacity(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        theme.apply_theme(_app, "light", opacity=100)

    def test_rgba_helper(self):
        self.assertEqual(theme.rgba("#FF8000", 0.5), "rgba(255, 128, 0, 128)")
        self.assertEqual(theme.rgba("#000000", 2), "rgba(0, 0, 0, 255)")

    def test_default_is_fully_opaque_and_the_range_is_clamped(self):
        self.assertEqual(Settings.load(self.dir).preferences["opacity"], 100)
        (self.dir / "keywords.toml").write_text("[preferences]\nopacity = 5\n")
        self.assertEqual(Settings.load(self.dir).preferences["opacity"], OPACITY_RANGE[0])
        (self.dir / "keywords.toml").write_text("[preferences]\nopacity = 500\n")
        self.assertEqual(Settings.load(self.dir).preferences["opacity"], 100)

    def test_window_background_follows_opacity_but_cards_stay_more_solid(self):
        solid = theme.stylesheet_for(False, opacity=100)
        clear = theme.stylesheet_for(False, opacity=60)
        bg = theme.TOKENS["light"]["bg"]
        self.assertIn(f"background: {theme.rgba(bg, 1.0)}; }}", solid.split("\n")[1])
        window_rule = clear.split("\n")[1]
        self.assertIn(theme.rgba(bg, 0.6), window_rule)
        self.assertIn("QWidget#sortingWindow", window_rule)
        self.assertIn(theme.rgba(theme.TOKENS["light"]["surface"], 0.8), clear)    # (1 + 0.6) / 2

    def test_text_colours_are_never_made_see_through(self):
        clear = theme.stylesheet_for(True, opacity=55)
        text = theme.TOKENS["dark"]["text"]
        self.assertIn(f"color: {text}", clear)
        self.assertNotIn(theme.rgba(text, 0.55), clear)

    def test_palette_window_alpha(self):
        from PySide6.QtGui import QPalette
        self.assertAlmostEqual(theme.palette_for(False, opacity=70).color(QPalette.ColorRole.Window).alphaF(), 0.7, 2)

    def test_apply_theme_restyles_when_opacity_changes(self):
        theme.apply_theme(_app, "light", opacity=100)
        before = _app.styleSheet()
        theme.apply_theme(_app, "light", opacity=70)
        self.assertNotEqual(_app.styleSheet(), before)

    def test_windows_are_built_translucent_so_opacity_can_show(self):
        w = MainWindow()
        w.setup()
        self.assertTrue(w.widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        dlg = SettingsDialog(Settings.load(self.dir)).build()
        self.assertTrue(dlg.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))

    def test_dialog_slider_saves_and_is_limited(self):
        settings = Settings.load(self.dir)
        dlg = SettingsDialog(settings)
        dlg.build()
        self.assertEqual(dlg.opacity_slider.value(), 100)
        dlg.opacity_slider.setValue(75)
        self.assertEqual(dlg.opacity_label.text(), "75%")
        self.assertTrue(dlg.try_accept())
        self.assertEqual(Settings.load(self.dir).preferences["opacity"], 75)
        dlg.opacity_slider.setValue(1)
        self.assertEqual(dlg.opacity_slider.value(), OPACITY_RANGE[0])

    def test_app_applies_the_setting_live(self):
        app = QuillApp(_app, Settings.load(self.dir), XlsxBridge(self.dir / "none.xlsx"),
                       listener_factory=lambda *a: None, model_finder=lambda c: None, sound_player=lambda p: None)
        app.start()
        app.settings.preferences["opacity"] = 70
        app.apply_settings()
        self.assertIn(theme.rgba(theme.TOKENS["light"]["bg"], 0.7), _app.styleSheet())


if __name__ == "__main__":
    unittest.main()
