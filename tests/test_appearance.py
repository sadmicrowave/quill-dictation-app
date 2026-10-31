"""Appearance settings: accent colour and spacing (compact / comfortable)."""
import pathlib
import tempfile
import unittest

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config import settings as cfg
from quill.config.settings import Settings
from quill.ui import theme
from quill.ui.settings_dialog import SettingsDialog
from tests.test_sorting import SENTENCE, DemoCase

_app = QApplication.instance() or QApplication([])


class TestAccents(unittest.TestCase):
    def test_five_accents_and_two_spacings_match_the_settings_lists(self):
        self.assertEqual(tuple(theme.ACCENTS), cfg.ACCENTS)
        self.assertEqual(len(cfg.ACCENTS), 5)
        self.assertEqual(tuple(theme.DENSITIES), cfg.SPACINGS)

    def test_violet_is_the_default(self):
        self.assertEqual(colors_light("terracotta")["accent"], "#C9623F")
        self.assertEqual(theme.DEFAULT_ACCENT, "violet")

    def test_every_accent_themes_every_scheme(self):
        seen = set()
        for key in theme.ACCENTS:
            for dark in (False, True):
                t = theme.colors_for(dark, key)
                self.assertIn(t["accent"], theme.stylesheet_for(dark, key))
                self.assertEqual(theme.palette_for(dark, key).color(QPalette.ColorRole.Highlight).name().upper(),
                                 t["accent"].upper())
                seen.add(t["accent"])
        self.assertEqual(len(seen), 10)                      # all distinct

    def test_unknown_accent_falls_back(self):
        self.assertEqual(theme.colors_for(False, "nope"), theme.colors_for(False, "violet"))

    def test_text_on_the_accent_is_light_on_light_scheme_and_dark_on_dark(self):
        self.assertEqual(theme.colors_for(False, "ocean")["on_accent"], "#FFFFFF")
        self.assertEqual(theme.colors_for(True, "ocean")["on_accent"], "#1F1E1D")

    def test_text_on_the_accent_is_readable(self):
        for key in theme.ACCENTS:
            for dark in (False, True):
                t = theme.colors_for(dark, key)
                self.assertGreaterEqual(contrast(t["accent"], t["on_accent"]), 3.5, (key, dark))


def colors_light(key):
    return theme.colors_for(False, key)


def luminance(color):
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestSpacing(unittest.TestCase):
    def build(self):
        widget = QWidget()
        outer = QVBoxLayout(widget)
        inner = QHBoxLayout()
        inner.addWidget(QPushButton("x"))
        outer.addLayout(inner)
        return widget, outer, inner

    def test_comfortable_adds_room_and_compact_restores_the_defaults(self):
        widget, outer, inner = self.build()
        default = (outer.contentsMargins().left(), outer.spacing())
        theme.apply_spacing(widget, "comfortable")
        self.assertEqual((outer.contentsMargins().left(), outer.spacing()), (20, 12))
        self.assertEqual(inner.spacing(), 12)
        self.assertEqual(inner.contentsMargins().left(), 0)   # nested layouts get no extra margin
        theme.apply_spacing(widget, "compact")
        self.assertEqual((outer.contentsMargins().left(), outer.spacing()), default)

    def test_comfortable_style_sheet_pads_controls_more(self):
        self.assertIn("padding: 6px 14px", theme.stylesheet_for(False, "terracotta", "compact"))
        self.assertIn("padding: 9px 20px", theme.stylesheet_for(False, "terracotta", "comfortable"))

    def test_unknown_spacing_means_compact(self):
        widget, outer, _ = self.build()
        theme.apply_spacing(widget, "nope")
        self.assertEqual(outer.spacing(), 6)


class TestSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_defaults_round_trip_and_repair(self):
        s = Settings.load(self.dir)
        self.assertEqual((s.preferences["accent"], s.preferences["spacing"]), ("violet", "compact"))
        s.preferences.update(accent="violet", spacing="comfortable")
        s.save()
        again = Settings.load(self.dir).preferences
        self.assertEqual((again["accent"], again["spacing"]), ("violet", "comfortable"))
        (self.dir / "keywords.toml").write_text('[preferences]\naccent = "lime"\nspacing = "huge"\n')
        again = Settings.load(self.dir).preferences
        self.assertEqual((again["accent"], again["spacing"]), ("violet", "compact"))

    def test_dialog_offers_the_choices_and_saves_them(self):
        s = Settings.load(self.dir)
        dlg = SettingsDialog(s)
        dlg.build()
        self.assertEqual([dlg.accent_combo.itemData(i) for i in range(dlg.accent_combo.count())],
                         list(cfg.ACCENTS))
        self.assertFalse(dlg.accent_combo.itemIcon(0).isNull())
        self.assertEqual(dlg.spacing_combo.count(), 2)
        dlg.accent_combo.setCurrentIndex(dlg.accent_combo.findData("forest"))
        dlg.spacing_combo.setCurrentIndex(dlg.spacing_combo.findData("comfortable"))
        self.assertTrue(dlg.try_accept())
        saved = Settings.load(self.dir).preferences
        self.assertEqual((saved["accent"], saved["spacing"]), ("forest", "comfortable"))


class TestInTheApp(DemoCase):
    def setUp(self):
        super().setUp()
        self.app = QuillApp(_app, self.settings, XlsxBridge(self.path),
                            listener_factory=lambda *a: None, model_finder=lambda c: None,
                            sound_player=lambda p: None)
        self.app.start()

    def margins(self):
        return self.app.window.widget.centralWidget().layout().contentsMargins().left()

    def test_changing_accent_and_spacing_restyles_the_running_app(self):
        compact = self.margins()
        self.settings.preferences.update(accent="ocean", spacing="comfortable")
        self.app.apply_settings()
        self.assertIn(theme.colors_for(False, "ocean")["accent"], _app.styleSheet())
        self.assertIn("padding: 9px 20px", _app.styleSheet())
        self.assertEqual(self.margins(), 20)
        self.settings.preferences.update(accent="terracotta", spacing="compact")
        self.app.apply_settings()
        self.assertEqual(self.margins(), compact)
        self.assertIn("padding: 6px 14px", _app.styleSheet())

    def test_new_rows_in_the_sorting_list_use_the_current_spacing(self):
        self.settings.preferences["spacing"] = "comfortable"
        self.app.apply_settings()
        self.app.controller.handle_transcript("start listening")
        self.app.controller.handle_transcript(SENTENCE)
        self.app.controller.handle_transcript("next row")
        self.assertTrue(self.app.sorting.rows)
        self.assertEqual(self.app.sorting.rows[0].layout().contentsMargins().left(), 20)
        self.settings.preferences["spacing"] = "compact"
        self.app.apply_settings()


if __name__ == "__main__":
    unittest.main()
