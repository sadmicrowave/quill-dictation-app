"""Count badges (tray + inline), button icons, supporting-note styling and window opacity."""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QApplication, QWidget

from quill import platforms
from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import BLUR_RANGE, OPACITY_RANGE, Settings
from quill.ui import glass, icons, theme
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
        self.assertFalse(w.open_file_button.icon().isNull())      # a folder icon, no text
        self.assertEqual(w.open_file_button.text(), "")
        self.assertFalse(w.toggle_icon.pixmap().isNull())
        self.assertEqual(w.toggle_button.text_pill.text(), "Start Listening")      # a pill in the middle of the button

    def test_start_and_stop_draw_different_icons(self):
        w = MainWindow()
        w.setup()
        start = w.toggle_icon.pixmap().toImage()
        w.set_listening_indicator(True)
        stop = w.toggle_icon.pixmap().toImage()
        self.assertTrue(w.wave.active)
        self.assertNotEqual(start, stop)

    def test_icons_take_the_theme_colours(self):
        w = MainWindow()
        w.setup()
        w.set_listening_indicator(True)                  # the glyph is drawn in the on-accent colour while listening
        w.refresh_icons("#00FF00", "#FF0000")
        image = w.toggle_icon.pixmap().toImage()
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
        self.assertEqual(self.w.sorting_button.accessibleName(), "Term Helper (4)")

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
        self.assertEqual(tray._sorting_action.text(), "Term Helper (3)…")
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
        self.assertIn('QLabel[note="true"] { font-style: italic;', sheet)


# macOS thins only the background; elsewhere, without blur, the whole window fades (theme.apply_opacity)
_THINS = platforms.offered(sys.platform, "OPACITY_THINS_BACKGROUND", False)


class TestOpacityAndBlur(unittest.TestCase):
    """Opacity thins the window's background; blur then blurs what shows through it (macOS; see below for the rest).

    The pixels are checked on a real screen by ``tools/verify_window_effects.py`` (a striped window behind Quill):
    opacity 100 is solid at any blur; opacity 50 shows sharp stripes at blur 0 and none at blur 60 or 100. These
    tests check the settings that produce that: the backdrop alpha, the opaque window, the window server's radius.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        theme.apply_theme(_app, "light")

    def make_app(self, **prefs):
        settings = Settings.load(self.dir)
        settings.preferences.update(prefs)
        app = QuillApp(_app, settings, XlsxBridge(self.dir / "none.xlsx"), listener_factory=lambda *a: None,
                       model_finder=lambda c: None, sound_player=lambda p: None)
        app.start()
        return app

    @staticmethod
    def faded(root):
        opacity = round(root.window().windowOpacity(), 2)
        return None if opacity >= 1 else opacity

    def test_rgba_helper(self):
        self.assertEqual(theme.rgba("#FF8000", 0.5), "rgba(255, 128, 0, 128)")
        self.assertEqual(theme.rgba("#000000", 2), "rgba(0, 0, 0, 255)")

    def test_defaults_and_clamping(self):
        prefs = Settings.load(self.dir).preferences
        self.assertEqual((prefs["opacity"], prefs["blur"]), (100, 60))
        (self.dir / "keywords.toml").write_text("[preferences]\nopacity = 2\nblur = 400\n")
        prefs = Settings.load(self.dir).preferences
        self.assertEqual((prefs["opacity"], prefs["blur"]), (OPACITY_RANGE[0], 100))
        (self.dir / "keywords.toml").write_text("[preferences]\nblur = -5\n")
        self.assertEqual(Settings.load(self.dir).preferences["blur"], 0)

    def test_the_scales_run_to_the_ends(self):
        self.assertEqual(OPACITY_RANGE, (10, 100))
        self.assertEqual(BLUR_RANGE, (0, 100))

    # -- the bug: a window at 100 % must be completely solid, whatever the blur ----------------

    def test_full_opacity_is_solid_even_with_blur_turned_up(self):
        app = self.make_app(opacity=100, blur=100)
        for root in (app.window.root, app.sorting.root):
            self.assertIsNone(root.graphicsEffect(), "no fade at 100%")
        self.assertEqual(_app.property("quillBackdrop"), 1.0)         # the background is painted fully solid
        self.assertEqual(app.window.widget.windowOpacity(), 1.0)

    def test_the_style_sheet_never_contains_a_see_through_colour_for_surfaces(self):
        for dark in (False, True):
            sheet = theme.stylesheet_for(dark)
            for selector in ("QWidget#mainRoot, QFrame#sidePanel, QWidget#settingsRoot, QWidget#sortingRoot, QWidget#helpRoot", "QPushButton", "QLineEdit, QSpinBox, QComboBox",
                             "QPlainTextEdit, QTextEdit, QTableWidget", "QFrame#termRow"):
                start = sheet.index(selector + " {")
                rule = sheet[start: sheet.index("}", start)]
                first = rule.split("background:")[1].split(";")[0]
                self.assertNotIn("rgba", first, selector)

    def test_palette_is_solid(self):
        from PySide6.QtGui import QPalette
        for dark in (False, True):
            self.assertEqual(theme.palette_for(dark).color(QPalette.ColorRole.Window).alphaF(), 1.0)

    def test_the_old_per_colour_glass_is_gone(self):
        for name in ("window_alpha", "surface_alpha", "GLASS_WINDOW_ALPHA", "GLASS_SURFACE_ALPHA"):
            self.assertFalse(hasattr(theme, name), name)

    # -- opacity fades the whole root: background, controls and text together --------------------

    def test_lower_opacity_thins_the_background_not_the_window(self):
        app = self.make_app(opacity=60, blur=0)
        if _THINS:
            self.assertIsNone(self.faded(app.window.root))               # the window itself stays opaque: the blur needs that
            self.assertAlmostEqual(_app.property("quillBackdrop"), 0.6)   # its background is what is see-through
        else:                                                            # Windows without blur: the whole window fades instead
            self.assertEqual(self.faded(app.window.root), 0.6)
            self.assertEqual(_app.property("quillBackdrop"), 1.0)
        self.assertTrue(app.sorting.root.property("quillSolid"))          # the Term Helper stays solid by default
        app.settings.preferences["sorting_follows_opacity"] = True
        app.apply_settings(quiet=True)
        self.assertFalse(app.sorting.root.property("quillSolid"))         # ... unless it is told to follow

    def test_the_opacity_works_with_and_without_blur_alike(self):
        for blur in (0, 40, 100):
            app = self.make_app(blur=blur)
            app.settings.preferences["opacity"] = 35
            app.apply_settings(quiet=True)
            self.assertAlmostEqual(_app.property("quillBackdrop"), theme.backdrop_alpha(35, blur), msg=f"blur {blur}")
            app.settings.preferences["opacity"] = 100
            app.apply_settings(quiet=True)
            self.assertEqual(_app.property("quillBackdrop"), 1.0, f"blur {blur}")

    def test_the_window_stays_opaque_on_macos_and_fades_as_a_whole_elsewhere_without_blur(self):
        root = QWidget()
        with mock.patch("quill.ui.theme.sys.platform", "darwin"):
            theme.apply_opacity(root, 40, 0)
            self.assertEqual(root.windowOpacity(), 1.0)
        with mock.patch("quill.ui.theme.sys.platform", "win32"):
            theme.apply_opacity(root, 40, 0)
            self.assertAlmostEqual(root.windowOpacity(), 0.4)               # the older behaviour, kept where it was not changed
            theme.apply_opacity(root, 40, 80)
            self.assertEqual(root.windowOpacity(), 1.0)

    def test_no_graphics_effect_is_ever_left_on_a_window(self):
        root = QWidget()
        root.setGraphicsEffect(QGraphicsOpacityEffect(root))          # one left over from an older version
        theme.apply_opacity(root, 90)
        self.assertIsNone(root.graphicsEffect())

    def test_apply_opacity_clamps(self):
        root = QWidget()
        with mock.patch("quill.ui.theme.sys.platform", "win32"):
            theme.apply_opacity(root, -50)
            self.assertEqual(root.windowOpacity(), 0.0)
            theme.apply_opacity(root, 500)
            self.assertEqual(root.windowOpacity(), 1.0)

    def test_the_background_alpha_follows_the_opacity_on_macos_whatever_the_blur(self):
        with mock.patch("quill.ui.theme.sys.platform", "darwin"):
            self.assertEqual(theme.backdrop_alpha(100, 100), 1.0)             # solid window: solid background
            self.assertEqual(theme.backdrop_alpha(100, 0), 1.0)
            self.assertEqual(theme.backdrop_alpha(50, 0), 0.5)                # and without blur too (it used to stay solid)
            self.assertEqual(theme.backdrop_alpha(50, 100), 0.5)
            self.assertLess(theme.backdrop_alpha(50, 100), theme.backdrop_alpha(80, 100))
            self.assertGreater(theme.backdrop_alpha(0, 100), 0.05)            # never fully clear
        with mock.patch("quill.ui.theme.sys.platform", "win32"):
            self.assertEqual(theme.backdrop_alpha(50, 0), 1.0)                # (elsewhere the window fades as a whole)

    @staticmethod
    def _restore_theme(before):
        sheet, palette, key, backdrop = before
        _app.setStyleSheet(sheet)
        _app.setPalette(palette)
        _app.setProperty("quillThemeKey", key)
        _app.setProperty("quillBackdrop", backdrop)

    def test_a_window_can_ask_for_a_floor_under_its_background_alpha(self):
        before = (_app.styleSheet(), _app.palette(), _app.property("quillThemeKey"), _app.property("quillBackdrop"))
        self.addCleanup(self._restore_theme, before)                                # (the theme is put back: other tests share the app)
        theme.apply_theme(_app, "light", "violet", "compact", backdrop=0.2)       # (not left to whichever test ran before)
        theme.set_backdrop(_app, 0.2)
        root = QWidget()
        root.setObjectName("settingsRoot")
        theme.install_backdrop(root)
        root.setProperty("quillMinAlpha", 0.7)
        root.resize(40, 40)
        self.assertAlmostEqual(root.grab().toImage().pixelColor(5, 5).alpha() / 255, 0.7, delta=0.01)
        theme.set_backdrop(_app, 1.0)

    def test_a_windows_background_is_painted_with_the_backdrop_alpha_and_controls_are_restyled_only_in_steps(self):
        theme.apply_theme(_app, "light", "violet", "compact", backdrop=0.61)
        key = _app.property("quillThemeKey")
        sheet = _app.styleSheet()
        theme.set_backdrop(_app, 0.62)                                     # inside the same 5 % step: no re-styling
        self.assertEqual(_app.styleSheet(), sheet)
        self.assertEqual(_app.property("quillThemeKey"), key)
        theme.set_backdrop(_app, 0.4)                                      # a new step: the controls' fills follow
        self.assertNotEqual(_app.styleSheet(), sheet)
        self.assertEqual(_app.property("quillBackdrop"), 0.4)
        root = QWidget()
        root.setObjectName("mainRoot")
        theme.install_backdrop(root)
        root.resize(40, 40)
        pixel = root.grab().toImage().pixelColor(5, 5)
        self.assertEqual(pixel.alpha(), round(0.4 * 255))                  # painted by the backdrop painter, see-through
        theme.set_backdrop(_app, 1.0)
        self.assertEqual(root.grab().toImage().pixelColor(5, 5).alpha(), 255)

    def test_the_style_sheet_leaves_the_root_background_to_the_painter(self):
        sheet = theme.stylesheet_for(False)
        rule = sheet[sheet.index("QWidget#mainRoot"): sheet.index("}", sheet.index("QWidget#mainRoot"))]
        self.assertIn("transparent", rule)

    def test_the_window_itself_is_transparent_so_only_the_root_paints(self):
        sheet = theme.stylesheet_for(False)
        start = sheet.index("QMainWindow, QDialog")
        self.assertIn("background: transparent", sheet[start: sheet.index("}", start)])

    def test_windows_are_built_translucent_with_a_painting_root(self):
        w = MainWindow()
        w.setup()
        self.assertTrue(w.widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertEqual(w.root.objectName(), "mainRoot")
        self.assertTrue(w.root.testAttribute(Qt.WidgetAttribute.WA_StyledBackground))
        dlg = SettingsDialog(Settings.load(self.dir))
        dlg.build()
        self.assertTrue(dlg._dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertEqual(dlg.root.objectName(), "settingsRoot")

    def test_blur_is_not_part_of_the_style_sheet_any_more(self):
        before = theme.stylesheet_for(False)
        theme.apply_theme(_app, "light")
        self.assertEqual(_app.styleSheet(), before)

    # -- the settings controls ---------------------------------------------------------------------

    def test_dialog_slider_and_blur_slider_save(self):
        settings = Settings.load(self.dir)
        dlg = SettingsDialog(settings)
        dlg.build()
        self.assertEqual((dlg.opacity_slider.value(), dlg.blur_slider.value()), (100, 60))
        dlg.opacity_slider.setValue(75)
        dlg.blur_slider.setValue(0)
        self.assertEqual((dlg.opacity_label.text(), dlg.blur_label.text()), ("75%", "0%"))
        self.assertTrue(dlg.try_accept())
        prefs = Settings.load(self.dir).preferences
        self.assertEqual((prefs["opacity"], prefs["blur"]), (75, 0))
        dlg.opacity_slider.setValue(1)
        self.assertEqual(dlg.opacity_slider.value(), OPACITY_RANGE[0])
        dlg.blur_slider.setValue(1000)
        self.assertEqual(dlg.blur_slider.value(), 100)

    def test_the_help_text_explains_how_the_two_relate(self):
        dlg = SettingsDialog(Settings.load(self.dir))
        dlg.build()
        texts = {r.title: r.description_label.text() for r in dlg.rows}
        self.assertIn("100%", texts["Window Opacity"])
        self.assertIn("show through", texts["Window Opacity"])
        self.assertIn("blurred", texts["Window Blur"])
        self.assertIn("below 100%", texts["Window Blur"])


class TestThemeSwitching(unittest.TestCase):
    def tearDown(self):
        theme.apply_theme(_app, "light")

    def test_light_after_dark_changes_the_background_immediately(self):
        root = QWidget()
        root.setObjectName("mainRoot")
        theme.install_backdrop(root)
        root.resize(30, 30)
        for mode in ("dark", "light", "dark", "light"):
            theme.apply_theme(_app, mode)
            painted = root.grab().toImage().pixelColor(5, 5).name().upper()
            self.assertEqual(painted, theme.TOKENS[mode]["bg"].upper(), mode)      # never a leftover of the other theme
            self.assertEqual(theme.is_dark(_app), mode == "dark")

    def test_is_dark_follows_the_explicit_mode_at_once(self):
        theme.apply_theme(_app, "dark")
        self.assertTrue(theme.is_dark(_app))
        theme.apply_theme(_app, "light")
        self.assertFalse(theme.is_dark(_app))

    def test_auto_follows_the_operating_system(self):
        from PySide6.QtCore import Qt as _Qt
        theme.apply_theme(_app, "dark")
        theme.apply_theme(_app, "auto")
        system = _app.styleHints().colorScheme()
        self.assertEqual(theme.is_dark(_app), system == _Qt.ColorScheme.Dark)
        # and the palette and style sheet agree with it (no half-dark, half-light mix)
        from PySide6.QtGui import QPalette
        window = _app.palette().color(QPalette.ColorRole.Window).name().upper()
        self.assertEqual(window, theme.TOKENS["dark" if theme.is_dark(_app) else "light"]["bg"])

    def test_switching_modes_repeatedly_never_mixes_schemes(self):
        from PySide6.QtGui import QPalette
        for mode in ("dark", "auto", "light", "auto", "dark", "light"):
            theme.apply_theme(_app, mode)
            dark = theme.is_dark(_app)
            self.assertEqual(_app.palette().color(QPalette.ColorRole.Window).name().upper(),
                             theme.TOKENS["dark" if dark else "light"]["bg"], mode)
            self.assertIn(theme.TOKENS["dark" if dark else "light"]["text"], _app.styleSheet(), mode)


class TestSettingsWindowLooksTheNewTheme(unittest.TestCase):
    """The Settings window used to be dressed before the theme changed, so it lagged one step behind."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = Settings.load(pathlib.Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()
        theme.apply_theme(_app, "light")

    def test_the_app_restyles_before_the_dialog_dresses_itself(self):
        order = []
        d = SettingsDialog(self.settings, on_change=lambda: (order.append("app"),
                                                              theme.apply_theme(_app, self.settings.preferences["theme"])))
        d.build()
        original = d._apply_dialog_look
        d._apply_dialog_look = lambda: (order.append("dialog"), original())
        d.theme_combo._buttons[2].click()                         # Dark
        self.assertEqual(order, ["app", "dialog"])

    def test_the_dialog_sees_the_new_scheme_when_it_dresses(self):
        seen = []
        d = SettingsDialog(self.settings, on_change=lambda: theme.apply_theme(
            _app, self.settings.preferences["theme"]))
        d.build()
        original = d._apply_dialog_look
        d._apply_dialog_look = lambda: (seen.append(theme.is_dark(_app)), original())
        d.theme_combo._buttons[2].click()                         # Dark
        d.theme_combo._buttons[1].click()                         # Light
        self.assertEqual(seen, [True, False])


class TestSystemSchemeFollowing(unittest.TestCase):
    def tearDown(self):
        theme.apply_theme(_app, "light")

    def test_the_app_restyles_when_the_system_changes_in_auto_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.load(pathlib.Path(tmp))
            settings.preferences["theme"] = "auto"
            app = QuillApp(_app, settings, XlsxBridge(pathlib.Path(tmp) / "none.xlsx"),
                           listener_factory=lambda *a: None, model_finder=lambda c: None,
                           sound_player=lambda p: None)
            app.start()
            calls = []
            app._apply_look = lambda: calls.append(1)
            app._system_scheme_changed()
            self.assertEqual(calls, [1])
            settings.preferences["theme"] = "dark"
            app._system_scheme_changed()
            self.assertEqual(calls, [1])                       # an explicit choice ignores the system


if __name__ == "__main__":
    unittest.main()


class TestControlsFollowTheOpacity(unittest.TestCase):
    def test_text_boxes_drop_downs_and_buttons_fill_with_the_backdrop_alpha_and_keep_solid_text(self):
        solid = theme.stylesheet_for(False, backdrop=1.0)
        thin = theme.stylesheet_for(False, backdrop=0.5)
        t = theme.colors_for(False, "violet")
        for selector in ("QPushButton {", "QLineEdit, QSpinBox, QComboBox {", "QPlainTextEdit, QTextEdit, QTableWidget {",
                         "QFrame#termRow {", "QFrame#fileSettings {"):
            rule = thin[thin.index(selector): thin.index("}", thin.index(selector))]
            self.assertIn(theme.rgba(t["surface"], glass.control_alpha(0.5, False)), rule, selector)
            self.assertNotIn(f"background: {t['surface']}", rule, selector)
            solid_rule = solid[solid.index(selector): solid.index("}", solid.index(selector))]
            self.assertIn(f"background: {t['surface']}", solid_rule)          # and at 100 the fill is the plain colour
        popup = thin[thin.index("QComboBox QAbstractItemView {"): thin.index("}", thin.index("QComboBox QAbstractItemView {"))]
        self.assertIn(t["surface"], popup)                                    # a pop-up list stays solid: nothing is behind it to read against

    def test_a_fill_never_goes_clearer_than_the_floor(self):
        sheet = theme.stylesheet_for(False, backdrop=0.0)
        t = theme.colors_for(False, "violet")
        self.assertIn(theme.rgba(t["surface"], glass.CONTROL_FLOOR), sheet)


class TestMeasuredAlphas(unittest.TestCase):
    """The painted alphas come from tables measured on a real screen (quill/ui/glass.py); these keep them sane."""

    def test_a_window_with_one_layer_is_painted_as_thick_as_the_slider_says(self):
        for dark in (False, True):
            for thick in (0.1, 0.35, 0.5, 0.9):
                self.assertAlmostEqual(glass.paint_alpha(thick, dark, 1), thick, places=6)

    def test_a_window_with_two_layers_is_painted_thinner_and_rises_with_the_slider(self):
        for dark in (False, True):
            values = [glass.paint_alpha(t / 10, dark, 2) for t in range(1, 10)]
            self.assertEqual(values, sorted(values))
            self.assertTrue(all(v < t / 10 for v, t in zip(values, range(1, 10))))

    def test_every_alpha_rises_with_the_slider_stays_in_range_and_is_solid_at_one(self):
        for dark in (False, True):
            for fn in (lambda t: glass.paint_alpha(t, dark, 2), lambda t: glass.bar_alpha(t, dark), lambda t: glass.control_alpha(t, dark)):
                values = [fn(t / 20) for t in range(1, 20)]
                self.assertEqual(values, sorted(values))
                self.assertTrue(all(0.0 <= v <= 1.0 for v in values))
                self.assertEqual(fn(1.0), 1.0)

    def test_the_tables_have_a_value_for_every_knot(self):
        for table in glass.TABLES.values():
            for values in table.values():
                self.assertEqual(len(values), len(glass.KNOTS))

    def test_the_calibration_tool_can_force_the_alphas(self):
        from unittest import mock
        with mock.patch.dict(glass.OVERRIDE, {"paint": 0.3, "bar": 0.4, "control": 0.1}):
            self.assertEqual((glass.paint_alpha(0.9, False, 2), glass.bar_alpha(0.9, False), glass.control_alpha(0.9, False)),
                             (0.3, 0.4, 0.1))
