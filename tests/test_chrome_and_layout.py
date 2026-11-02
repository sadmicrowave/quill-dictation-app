"""OS window chrome, the collapsible log, the one-line last-saved status, font size, drop-down styling."""
import datetime as dt
import pathlib
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QWidget

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import FONT_SIZE_RANGE, Settings
from quill.ui import chrome, theme
from quill.ui.main_window import MainWindow
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.widgets import TOOLTIP_LINES, ElidedLabel, tooltip_lines
from tests.test_sorting import SENTENCE, DemoCase

_app = QApplication.instance() or QApplication([])

COLORS = {"bg": "#FAF9F5", "text": "#1F1E1D", "border": "#E3E0D6"}


class TestWindowsChrome(unittest.TestCase):
    def test_colorref_is_blue_green_red(self):
        self.assertEqual(chrome.colorref("#112233"), 0x332211)

    def test_dark_mode_colours_and_rounding_are_set(self):
        calls = []
        self.assertTrue(chrome.windows_chrome(77, True, COLORS, lambda h, a, v: calls.append((h, a, v))))
        self.assertEqual(calls[0], (77, chrome.DWMWA_USE_IMMERSIVE_DARK_MODE, 1))
        attrs = {a: v for _, a, v in calls}
        self.assertEqual(attrs[chrome.DWMWA_CAPTION_COLOR], chrome.colorref("#FAF9F5"))
        self.assertEqual(attrs[chrome.DWMWA_TEXT_COLOR], chrome.colorref("#1F1E1D"))
        self.assertEqual(attrs[chrome.DWMWA_BORDER_COLOR], chrome.colorref("#E3E0D6"))
        self.assertEqual(attrs[chrome.DWMWA_WINDOW_CORNER_PREFERENCE], chrome.DWMWCP_ROUND)

    def test_light_mode_turns_dark_title_bar_off(self):
        calls = []
        chrome.windows_chrome(1, False, COLORS, lambda h, a, v: calls.append((a, v)))
        self.assertIn((chrome.DWMWA_USE_IMMERSIVE_DARK_MODE, 0), calls)

    def test_attributes_an_older_windows_rejects_are_skipped(self):
        def picky(hwnd, attribute, value):
            if attribute != chrome.DWMWA_USE_IMMERSIVE_DARK_MODE:
                raise OSError("not on this build")
        self.assertTrue(chrome.windows_chrome(1, True, COLORS, picky))

    def test_without_dwm_nothing_happens(self):
        self.assertFalse(chrome.windows_chrome(1, True, COLORS))      # no ctypes.windll here


class Rect:
    def __init__(self, width, height):
        self.size = type("S", (), {"width": width, "height": height})()


class Colour(tuple):
    def CGColor(self): return self


class FakeStrip:
    """The title bar tint: a plain view with a layer."""
    instances = []

    def __init__(self): self.props, self._layer = {}, type("L", (), {"setBackgroundColor_": lambda s, c: self.props.__setitem__("colour", c)})()
    def alloc(self): s = FakeStrip(); FakeStrip.instances.append(s); return s
    def initWithFrame_(self, frame): return self
    def setIdentifier_(self, v): self.props["id"] = v
    def identifier(self): return self.props.get("id")
    def setWantsLayer_(self, v): pass
    def setAutoresizingMask_(self, v): self.props["mask"] = v
    def setFrame_(self, frame): self.props["frame"] = frame
    def layer(self): return self._layer
    def removeFromSuperview(self): self.props["removed"] = True


class FakeView:
    def __init__(self, identifier=None):
        self._id, self.removed = identifier, False
        self.props = {}

    def identifier(self): return self._id
    def removeFromSuperview(self): self.removed = True
    def setIdentifier_(self, v): self._id = v
    def setMaterial_(self, v): self.props["material"] = v
    def setBlendingMode_(self, v): self.props["blending"] = v
    def setState_(self, v): self.props["state"] = v
    def setAutoresizingMask_(self, v): self.props["mask"] = v
    def setAlphaValue_(self, v): self.props["alpha"] = v
    def frame(self): return Rect(100, 80)
    def initWithFrame_(self, frame): return self
    def alloc(self): return self


class FakeHolder:
    def __init__(self, subviews=()):
        self._subviews, self.added = list(subviews), []

    def subviews(self): return self._subviews
    def bounds(self): return Rect(100, 100)
    def addSubview_positioned_relativeTo_(self, view, where, relative): self.added.append((view, where, relative))


class FakeWindow:
    def __init__(self):
        self.calls = []

    def setTitlebarAppearsTransparent_(self, v): self.calls.append(("transparent", v))
    def setBackgroundColor_(self, c): self.calls.append(("bg", c))
    def setAppearance_(self, a): self.calls.append(("appearance", a))
    def setOpaque_(self, v): self.calls.append(("opaque", v))
    def invalidateShadow(self): self.calls.append(("shadow",))


class FakeAppKit:
    def __init__(self, window, holder=None):
        self._window = window
        self.holder = holder if holder is not None else FakeHolder()
        self.NSColor = type("C", (), {"colorWithDeviceRed_green_blue_alpha_":
                                      staticmethod(lambda r, g, b, a: Colour((round(r, 2), round(g, 2), round(b, 2), round(a, 2))))})
        self.NSAppearance = type("A", (), {"appearanceNamed_": staticmethod(lambda n: n)})
        self.effect = FakeView()
        self.NSVisualEffectView = self.effect
        FakeStrip.instances = []
        self.NSView = FakeStrip()

    def view_for(self, view_id):
        window, holder = self._window, self.holder
        return type("V", (), {"window": lambda s: window, "superview": lambda s: holder,
                              "frame": lambda s: Rect(100, 80)})()


class TestMacChrome(unittest.TestCase):
    def test_transparent_title_bar_with_theme_colour_and_appearance(self):
        window = FakeWindow()
        self.assertTrue(chrome.mac_chrome(5, True, COLORS, appkit=FakeAppKit(window), blur=0))
        self.assertEqual(window.calls, [("transparent", True), ("opaque", True),
                                        ("bg", (0.98, 0.98, 0.96, 1.0)),
                                        ("appearance", "NSAppearanceNameDarkAqua"), ("shadow",)])

    def test_light_appearance(self):
        window = FakeWindow()
        chrome.mac_chrome(5, False, COLORS, appkit=FakeAppKit(window), blur=0)
        self.assertIn(("appearance", "NSAppearanceNameAqua"), window.calls)

    def test_a_view_without_a_window_is_left_alone(self):
        self.assertFalse(chrome.mac_chrome(5, True, COLORS, appkit=FakeAppKit(None)))

    def test_blur_adds_one_vibrancy_view_behind_the_content(self):
        window, kit = FakeWindow(), FakeAppKit(FakeWindow())
        window = kit._window
        chrome.mac_chrome(5, False, COLORS, appkit=kit, blur=60)
        self.assertEqual(len(kit.holder.added), 3)                    # the blur, the frost wash over it and the title bar tint
        view, where, _ = kit.holder.added[0]
        self.assertEqual(where, -1)                                   # below the content
        self.assertEqual(view.identifier(), chrome.BLUR_ID)
        self.assertEqual((view.props["material"], view.props["blending"], view.props["state"]), (7, 0, 1))
        self.assertEqual(view.props["mask"], 18)                      # grows with the window
        self.assertIn(("opaque", False), window.calls)                # blur needs a see-through window
        self.assertIn(("bg", (0.98, 0.98, 0.96, 1.0)), window.calls)         # title bar solid at 100% opacity
        self.assertEqual(view.props["alpha"], 1.0)                           # always the whole blur (the slider sets the frost)
        frost, where, _ = kit.holder.added[1]
        self.assertEqual(frost.identifier(), chrome.FROST_ID)
        self.assertEqual(frost.props["colour"][3], round(chrome.FROST_MAX * 0.6, 2))
        tint, where, _ = kit.holder.added[2]
        self.assertEqual(tint.props["colour"][3], 1.0)                       # the title bar tint is solid at full opacity
        self.assertEqual(tint.props["frame"], ((0, 80), (100, 20)))          # over the title bar only

    def test_blur_is_not_added_twice_but_its_strength_updates(self):
        existing = FakeView(chrome.BLUR_ID)
        kit = FakeAppKit(FakeWindow(), FakeHolder([existing]))
        chrome.mac_chrome(5, False, COLORS, appkit=kit, blur=30)
        self.assertEqual([v.identifier() for v, *_ in kit.holder.added], [chrome.FROST_ID, chrome.TINT_ID])   # only these are new
        self.assertEqual(existing.props["alpha"], 1.0)

    def test_zero_blur_is_solid_and_has_no_view(self):
        kit = FakeAppKit(FakeWindow())
        chrome.mac_chrome(5, False, COLORS, appkit=kit, blur=0)
        self.assertEqual(kit.holder.added, [])
        self.assertIn(("opaque", True), kit._window.calls)

    def test_turning_blur_off_removes_the_view(self):
        ours, other = FakeView(chrome.BLUR_ID), FakeView("something else")
        kit = FakeAppKit(FakeWindow(), FakeHolder([ours, other]))
        chrome.mac_chrome(5, False, COLORS, appkit=kit, blur=0)
        self.assertTrue(ours.removed)
        self.assertFalse(other.removed)

    def test_opacity_below_full_also_needs_a_see_through_window(self):
        kit = FakeAppKit(FakeWindow())
        chrome.mac_chrome(5, False, COLORS, appkit=kit, opacity=70)
        self.assertIn(("opaque", False), kit._window.calls)
        self.assertIn(("bg", (0.98, 0.98, 0.96, 1.0)), kit._window.calls)   # no blur: the backdrop stays solid; the window fades as a whole
        kit = FakeAppKit(FakeWindow())
        chrome.mac_chrome(5, False, COLORS, appkit=kit, opacity=70, blur=100)
        self.assertTrue(any(call[0] == "bg" and call[1][3] < 1 for call in kit._window.calls))   # blur: the backdrop thins out

    def test_full_opacity_and_no_blur_is_a_solid_window(self):
        kit = FakeAppKit(FakeWindow())
        chrome.mac_chrome(5, False, COLORS, appkit=kit, opacity=100, blur=0)
        self.assertIn(("opaque", True), kit._window.calls)
        self.assertIn(("bg", (0.98, 0.98, 0.96, 1.0)), kit._window.calls)


class TestWindowsBlur(unittest.TestCase):
    def test_acrylic_backdrop_and_extended_frame_when_blurred(self):
        calls, extended = [], []
        chrome.windows_chrome(9, False, COLORS, lambda h, a, v: calls.append((a, v)), blur=40,
                              extend_frame=extended.append)
        self.assertIn((chrome.DWMWA_SYSTEMBACKDROP_TYPE, chrome.BACKDROP_ACRYLIC), calls)
        self.assertEqual(extended, [9])

    def test_no_backdrop_when_not_blurred(self):
        calls, extended = [], []
        chrome.windows_chrome(9, False, COLORS, lambda h, a, v: calls.append((a, v)), blur=0,
                              extend_frame=extended.append)
        self.assertIn((chrome.DWMWA_SYSTEMBACKDROP_TYPE, chrome.BACKDROP_NONE), calls)
        self.assertEqual(extended, [])

    def test_older_windows_without_the_backdrop_attribute_still_works(self):
        def picky(hwnd, attribute, value):
            if attribute == chrome.DWMWA_SYSTEMBACKDROP_TYPE:
                raise OSError("unknown attribute")
        self.assertTrue(chrome.windows_chrome(1, True, COLORS, picky, blur=50, extend_frame=lambda h: None))


class TestApplyChrome(unittest.TestCase):
    def test_nothing_is_applied_under_the_offscreen_plugin(self):
        # A fake window id handed to PyObjC would crash the process; the guard must stop it.
        widget = QWidget()
        for platform in ("darwin", "win32", "linux"):
            self.assertIsNone(chrome.apply_chrome(widget, True, COLORS, platform=platform))

    def test_errors_never_escape(self):
        class Broken:
            def winId(self):
                raise RuntimeError("boom")
        chrome._native_platform = lambda platform: True
        try:
            self.assertIsNone(chrome.apply_chrome(Broken(), True, COLORS, platform="win32"))
        finally:
            del chrome._native_platform


class TestCollapsibleLog(unittest.TestCase):
    def setUp(self):
        self.toggled = []
        self.w = MainWindow(on_log_toggled=self.toggled.append)
        self.w.setup()
        self.w.widget.show()

    def test_starts_open_with_an_up_arrow(self):
        self.assertFalse(self.w.log_collapsed)
        self.assertTrue(self.w.log.isVisible())
        self.assertIn("▴", self.w.log_toggle.text())
        self.assertTrue(self.w.log_toggle.text().startswith("Log"))

    def test_clicking_the_heading_collapses_and_expands(self):
        self.w.log_toggle.click()
        self.assertTrue(self.w.log_collapsed)
        self.assertFalse(self.w.log.isVisible())
        self.assertIn("▾", self.w.log_toggle.text())
        self.w.log_toggle.click()
        self.assertTrue(self.w.log.isVisible())
        self.assertEqual(self.toggled, [True, False])

    def test_the_log_keeps_collecting_while_collapsed(self):
        self.w.log_toggle.click()
        self.w.append_log("hello")
        self.w.log_toggle.click()
        self.assertIn("hello", self.w.log.toPlainText())

    def test_can_start_collapsed(self):
        w = MainWindow(log_collapsed=True)
        w.setup()
        w.widget.show()
        self.assertFalse(w.log.isVisible())
        self.assertIn("▾", w.log_toggle.text())


class TestLastSaved(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.resize(360, 520)
        self.w.widget.show()

    def test_short_row_reads_naturally(self):
        self.w.set_last_saved("Row 4", {"Type": "Fern", "Price": 12.0})
        self.assertEqual(self.w.last_label.full_text, "Last Saved: Row 4 · 2 fields · Type: Fern, Price: 12.0")

    def test_one_field_is_singular(self):
        self.w.set_last_saved("Row 4", {"Type": "Fern"})
        self.assertIn("1 field ·", self.w.last_label.full_text)

    def test_a_huge_row_is_still_one_short_line(self):
        record = {f"Column {n}": "a fairly long spoken value " * 3 for n in range(40)}
        self.w.set_last_saved("Row 9", record)
        label = self.w.last_label
        self.assertLessEqual(label.sizeHint().height(), label.fontMetrics().height() * 2)
        self.assertTrue(label.text().startswith("Last Saved: Row 9 · 40 fields"))
        self.assertTrue(label.text().endswith("…"))
        self.assertLess(len(label.text()), len(label.full_text))

    def test_the_tooltip_has_the_fields_capped_at_a_screenful(self):
        record = {f"Column {n}": str(n) for n in range(100)}
        self.w.set_last_saved("Row 9", record)
        tip = self.w.last_label.toolTip().splitlines()
        self.assertEqual(tip[0], "Row 9")
        self.assertEqual(tip[1], "Column 0: 0")
        self.assertEqual(tip[-1], f"…and {100 - TOOLTIP_LINES} more")
        self.assertEqual(len(tip), 1 + TOOLTIP_LINES + 1)

    def test_dates_are_shown_as_dates(self):
        self.w.set_last_saved("Row 2", {"Acquired": dt.date(2026, 10, 30)})
        self.assertIn("Acquired: 2026-10-30", self.w.last_label.full_text)

    def test_row_only_form_still_works(self):
        self.w.set_last_saved("Row 4")
        self.assertEqual(self.w.last_label.full_text, "Last Saved: Row 4")

    def test_elided_label_follows_its_width(self):
        label = ElidedLabel()
        label.resize(120, 20)
        label.setText("x" * 200)
        short = len(label.text())
        label.resize(900, 20)
        label.setText("x" * 200)
        self.assertGreater(len(label.text()), short)

    def test_tooltip_lines_without_overflow_has_no_footer(self):
        self.assertEqual(tooltip_lines([("a", "1"), ("b", "2")]), "a: 1\nb: 2")


class TestFontSize(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        theme.apply_theme(_app, "light", font_size=12)

    def test_default_is_twelve_and_is_clamped_on_load(self):
        self.assertEqual(Settings.load(self.dir).preferences["font_size"], 12)
        (self.dir / "keywords.toml").write_text("[preferences]\nfont_size = 90\n")
        self.assertEqual(Settings.load(self.dir).preferences["font_size"], FONT_SIZE_RANGE[1])
        (self.dir / "keywords.toml").write_text("[preferences]\nfont_size = 2\n")
        self.assertEqual(Settings.load(self.dir).preferences["font_size"], FONT_SIZE_RANGE[0])

    def test_the_app_font_follows_the_setting(self):
        theme.apply_theme(_app, "light", font_size=12)
        self.assertEqual(_app.font().pointSize(), 12)
        theme.apply_theme(_app, "light", font_size=16)
        self.assertEqual(_app.font().pointSize(), 16)

    def test_every_text_is_the_same_size(self):
        """Titles, buttons, notes, values and placeholders differ in colour and style, never in size."""
        self.assertNotIn("font-size", theme.stylesheet_for(False, font_size=12))
        self.assertNotIn("font-size", theme.stylesheet_for(True, font_size=16))

    def test_dialog_has_a_text_size_box_that_saves(self):
        settings = Settings.load(self.dir)
        dlg = SettingsDialog(settings)
        dlg.build()
        self.assertEqual(dlg.font_spin.value(), 12)
        dlg.font_spin.setValue(14)
        self.assertTrue(dlg.try_accept())
        self.assertEqual(Settings.load(self.dir).preferences["font_size"], 14)
        dlg.font_spin.setValue(99)
        self.assertEqual(dlg.font_spin.value(), FONT_SIZE_RANGE[1])


class TestDropdownStyle(unittest.TestCase):
    def test_arrows_are_custom_images_that_exist(self):
        for dark in (False, True):
            sheet = theme.stylesheet_for(dark)
            self.assertIn("QComboBox::down-arrow", sheet)
            self.assertIn("QSpinBox::up-arrow", sheet)
            for path in self.icon_paths(sheet):
                self.assertTrue(pathlib.Path(path).exists(), path)
                self.assertIn("<polyline", pathlib.Path(path).read_text())

    @staticmethod
    def icon_paths(sheet):
        return [part.split(")")[0] for part in sheet.split("url(")[1:]]

    def test_icons_follow_the_scheme_colours(self):
        light = pathlib.Path(self.icon_paths(theme.stylesheet_for(False))[0]).read_text()
        dark = pathlib.Path(self.icon_paths(theme.stylesheet_for(True))[0]).read_text()
        self.assertIn(theme.TOKENS["light"]["muted"], light)
        self.assertIn(theme.TOKENS["dark"]["muted"], dark)

    def test_popup_opens_below_the_box_with_roomy_items(self):
        sheet = theme.stylesheet_for(False)
        self.assertIn("combobox-popup: 0", sheet)
        self.assertIn("QAbstractItemView::item", sheet)


class TestAppRemembersLog(DemoCase):
    def test_collapsing_the_log_is_saved(self):
        app = QuillApp(_app, self.settings, XlsxBridge(self.path), listener_factory=lambda *a: None,
                       model_finder=lambda c: None, sound_player=lambda p: None)
        app.start()
        self.assertTrue(app.window.log_collapsed)                      # minimized by default
        app.window.log_toggle.click()                                  # open it
        self.assertFalse(Settings.load(self.dir / "cfg").preferences["log_collapsed"])
        again = QuillApp(_app, Settings.load(self.dir / "cfg"), XlsxBridge(self.path),
                         listener_factory=lambda *a: None, model_finder=lambda c: None,
                         sound_player=lambda p: None)
        again.start()
        self.assertFalse(again.window.log_collapsed)                   # the user's choice is remembered

    def test_saved_row_shows_the_count(self):
        app = QuillApp(_app, self.settings, XlsxBridge(self.path), listener_factory=lambda *a: None,
                       model_finder=lambda c: None, sound_player=lambda p: None)
        app.start()
        app.controller.handle_transcript("start listening")
        app.controller.handle_transcript("t-shirt thirty five dollars")
        app.controller.handle_transcript("next row")
        self.assertIn("2 fields", app.window.last_label.full_text)
        self.assertIn("Row 6", app.window.last_label.full_text)


if __name__ == "__main__":
    unittest.main()
