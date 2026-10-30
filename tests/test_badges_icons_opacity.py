"""Count badges (tray + inline), button icons, supporting-note styling and window opacity."""
import pathlib
import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

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


class TestOpacityAndGlass(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        theme.apply_theme(_app, "light", blur=False)

    def make_app(self):
        app = QuillApp(_app, Settings.load(self.dir), XlsxBridge(self.dir / "none.xlsx"),
                       listener_factory=lambda *a: None, model_finder=lambda c: None, sound_player=lambda p: None)
        app.start()
        return app

    def test_rgba_helper(self):
        self.assertEqual(theme.rgba("#FF8000", 0.5), "rgba(255, 128, 0, 128)")
        self.assertEqual(theme.rgba("#000000", 2), "rgba(0, 0, 0, 255)")

    def test_defaults_and_clamping(self):
        prefs = Settings.load(self.dir).preferences
        self.assertEqual((prefs["opacity"], prefs["blur"]), (100, True))
        (self.dir / "keywords.toml").write_text("[preferences]\nopacity = 5\nblur = false\n")
        prefs = Settings.load(self.dir).preferences
        self.assertEqual((prefs["opacity"], prefs["blur"]), (OPACITY_RANGE[0], False))
        (self.dir / "keywords.toml").write_text("[preferences]\nopacity = 500\n")
        self.assertEqual(Settings.load(self.dir).preferences["opacity"], 100)

    def test_opacity_fades_the_whole_window_text_and_controls_included(self):
        w = QWidget()
        theme.apply_opacity(w, 70)
        self.assertAlmostEqual(w.windowOpacity(), 0.7, 2)
        theme.apply_opacity(w, 300)
        self.assertEqual(w.windowOpacity(), 1.0)

    def test_the_app_applies_opacity_to_every_window_live(self):
        app = self.make_app()
        app.settings.preferences["opacity"] = 70
        app.apply_settings()
        self.assertAlmostEqual(app.window.widget.windowOpacity(), 0.7, 2)
        self.assertAlmostEqual(app.sorting.widget.windowOpacity(), 0.7, 2)
        app.settings.preferences["opacity"] = 100
        app.apply_settings()
        self.assertEqual(app.window.widget.windowOpacity(), 1.0)

    def test_text_and_controls_are_not_individually_faded(self):
        # Opacity is window-wide; per-element alpha would double the fade.
        for glass in (False, True):
            sheet = theme.stylesheet_for(False, glass=glass)
            self.assertNotIn(theme.rgba(theme.TOKENS["light"]["text"], 0.5), sheet)

    def test_glass_makes_the_window_see_through_and_keeps_cards_more_solid(self):
        bg, surface = theme.TOKENS["light"]["bg"], theme.TOKENS["light"]["surface"]
        solid, glass = theme.stylesheet_for(False), theme.stylesheet_for(False, glass=True)
        self.assertIn(f"background: {theme.rgba(bg, 1.0)}; }}", solid.split("\n")[1])
        window_rule = glass.split("\n")[1]
        self.assertIn(theme.rgba(bg, theme.GLASS_WINDOW_ALPHA), window_rule)
        self.assertIn("QWidget#sortingWindow", window_rule)
        self.assertIn(theme.rgba(surface, theme.GLASS_SURFACE_ALPHA), glass)
        self.assertGreater(theme.GLASS_SURFACE_ALPHA, theme.GLASS_WINDOW_ALPHA)

    def test_palette_window_alpha_follows_glass(self):
        from PySide6.QtGui import QPalette
        self.assertEqual(theme.palette_for(False).color(QPalette.ColorRole.Window).alphaF(), 1.0)
        self.assertAlmostEqual(theme.palette_for(False, glass=True).color(QPalette.ColorRole.Window).alphaF(),
                               theme.GLASS_WINDOW_ALPHA, 2)

    def test_apply_theme_restyles_when_blur_changes(self):
        theme.apply_theme(_app, "light", blur=False)
        before = _app.styleSheet()
        theme.apply_theme(_app, "light", blur=True)
        self.assertNotEqual(_app.styleSheet(), before)

    def test_windows_are_built_translucent_so_blur_and_opacity_can_show(self):
        w = MainWindow()
        w.setup()
        self.assertTrue(w.widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        dlg = SettingsDialog(Settings.load(self.dir)).build()
        self.assertTrue(dlg.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))

    def test_dialog_slider_and_blur_box_save(self):
        settings = Settings.load(self.dir)
        dlg = SettingsDialog(settings)
        dlg.build()
        self.assertEqual((dlg.opacity_slider.value(), dlg.blur_check.isChecked()), (100, True))
        dlg.opacity_slider.setValue(75)
        dlg.blur_check.setChecked(False)
        self.assertEqual(dlg.opacity_label.text(), "75%")
        self.assertTrue(dlg.try_accept())
        prefs = Settings.load(self.dir).preferences
        self.assertEqual((prefs["opacity"], prefs["blur"]), (75, False))
        dlg.opacity_slider.setValue(1)
        self.assertEqual(dlg.opacity_slider.value(), OPACITY_RANGE[0])


if __name__ == "__main__":
    unittest.main()
