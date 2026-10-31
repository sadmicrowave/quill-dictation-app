"""Live-updating settings, Cancel reverting, wheel-safe controls, pointer cursors, the bundled model."""
import pathlib
import tempfile
import unittest

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.listener.model import find_model, is_model_dir
from quill.ui import theme
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.settings_widgets import GuardedCombo, GuardedSlider, GuardedSpinBox
from tests.test_sorting import DemoCase

_app = QApplication.instance() or QApplication([])


def wheel(widget, delta=120):
    return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                       Qt.ScrollPhase.NoScrollPhase, False)


class LiveCase(DemoCase):
    def setUp(self):
        super().setUp()
        self.app = QuillApp(_app, self.settings, XlsxBridge(self.path), listener_factory=lambda *a: None,
                            model_finder=lambda c: None, sound_player=lambda p: None)
        self.app.start()
        self.changes = []
        self.d = SettingsDialog(self.settings, on_change=lambda: (self.changes.append(1),
                                                                  self.app.apply_settings(quiet=True)))
        self.dlg = self.d.build()
        self.dlg.show()


class TestLiveUpdate(LiveCase):
    def test_a_change_is_applied_straight_away_without_saving(self):
        self.d.accent_combo.setCurrentIndex(self.d.accent_combo.findData("forest"))
        self.assertEqual(self.settings.preferences["accent"], "forest")
        self.assertIn(theme.colors_for(False, "forest")["accent"], _app.styleSheet())
        self.assertNotIn("forest", (self.dir / "cfg" / "keywords.toml").read_text()
                         if (self.dir / "cfg" / "keywords.toml").exists() else "")

    def test_every_kind_of_control_updates_live(self):
        d = self.d
        before = len(self.changes)
        d.theme_combo._buttons[2].click()          # a real click on the Dark button
        d.spacing_combo.setCurrentIndex(1)
        d.font_spin.setValue(15)
        d.opacity_slider.setValue(60)
        d.blur_slider.setValue(30)
        d.history_spin.setValue(20)
        d.speak_check.setChecked(True)
        d.auto_sort_check.setChecked(True)
        d.feedback_combo.setCurrentIndex(2)
        d.pack_combo.setCurrentIndex(3)
        d.echo_combo.setCurrentIndex(1)
        self.assertGreaterEqual(len(self.changes) - before, 11)   # one per control
        p = self.settings.preferences
        self.assertEqual((p["theme"], p["spacing"], p["font_size"], p["opacity"], p["blur"]),
                         ("dark", "comfortable", 15, 60, 30))
        self.assertEqual((p["history_limit"], p["speak_sort_prompts"], p["auto_voice_sort"]), (20, True, True))

    def test_the_running_window_follows_the_slider(self):
        self.d.blur_slider.setValue(0)
        self.d.opacity_slider.setValue(50)
        self.assertAlmostEqual(self.app.window.widget.windowOpacity(), 0.5, 2)
        self.d.opacity_slider.setValue(100)
        self.assertAlmostEqual(self.app.window.widget.windowOpacity(), 1.0, 2)

    def test_live_changes_are_not_logged_as_saved(self):
        self.d.font_spin.setValue(13)
        self.assertNotIn("Settings Saved", self.app.window.log.toPlainText())

    def test_cancel_puts_everything_back(self):
        original = dict(self.settings.preferences)
        self.d.accent_combo.setCurrentIndex(self.d.accent_combo.findData("rose"))
        self.d.opacity_slider.setValue(30)
        self.d.blur_slider.setValue(90)
        self.d.font_spin.setValue(18)
        self.dlg.reject()
        self.assertEqual(self.settings.preferences, original)
        self.assertIsNone(self.app.window.root.graphicsEffect())
        self.assertIn(theme.colors_for(False, original["accent"])["accent"], _app.styleSheet())
        self.assertEqual(_app.font().pointSize(), original["font_size"])

    def test_cancel_after_cancel_is_harmless_and_nothing_reaches_disk(self):
        self.d.speak_check.setChecked(True)
        self.dlg.reject()
        self.assertFalse(Settings.load(self.dir / "cfg").preferences["speak_sort_prompts"])

    def test_ok_keeps_and_saves_the_live_values(self):
        self.d.accent_combo.setCurrentIndex(self.d.accent_combo.findData("ocean"))
        self.d.blur_slider.setValue(20)
        self.assertTrue(self.d.try_accept())
        self.assertEqual(Settings.load(self.dir / "cfg").preferences["accent"], "ocean")
        self.assertEqual(Settings.load(self.dir / "cfg").preferences["blur"], 20)
        self.assertEqual(self.settings.preferences["accent"], "ocean")      # accepting does not revert

    def test_a_cancelled_keyword_edit_is_never_applied(self):
        before = dict(self.settings.keywords)
        self.d.add_row("zorp", list(before.values())[0])
        self.dlg.reject()
        self.assertEqual(self.settings.keywords, before)

    def test_the_settings_window_follows_opacity_but_never_below_the_floor(self):
        self.d.blur_slider.setValue(0)
        self.d.opacity_slider.setValue(30)
        self.assertAlmostEqual(self.d._dialog.windowOpacity(), SettingsDialog.MIN_DIALOG_OPACITY / 100, 2)
        self.d.opacity_slider.setValue(85)
        self.assertAlmostEqual(self.d._dialog.windowOpacity(), 0.85, 2)
        self.d.opacity_slider.setValue(100)
        self.assertAlmostEqual(self.d._dialog.windowOpacity(), 1.0, 2)

    def test_open_settings_wires_live_updates_and_cancel_through_the_app(self):
        # The app's own dialog: change, cancel, and everything is as it was.
        original = dict(self.settings.preferences)
        import quill.app as app_module
        captured = {}

        class Probe(SettingsDialog):
            def open(self, on_done=None):
                self.build()
                self._on_done = on_done
                self._dialog.finished.connect(self._finished)
                captured["dialog"] = self
                self.accent_combo.setCurrentIndex(self.accent_combo.findData("violet"))
                captured["live"] = self._settings.preferences["accent"]
                self._dialog.reject()

        original_class = app_module.SettingsDialog
        app_module.SettingsDialog = Probe
        try:
            self.app.open_settings()
        finally:
            app_module.SettingsDialog = original_class
        self.assertEqual(captured["live"], "violet")
        remembered = ("settings_page", "settings_width", "settings_height")      # kept even when cancelled
        self.assertEqual({k: v for k, v in self.settings.preferences.items() if k not in remembered},
                         {k: v for k, v in original.items() if k not in remembered})


class TestWheelSafety(unittest.TestCase):
    def test_wheel_is_ignored_until_the_control_is_focused(self):
        for widget in (GuardedCombo(), GuardedSpinBox(), GuardedSlider()):
            if isinstance(widget, GuardedCombo):
                widget.addItems(["a", "b", "c"])
                widget.setCurrentIndex(1)
                get = widget.currentIndex
            else:
                widget.setRange(0, 100)
                widget.setValue(50)
                get = widget.value
            before = get()
            event = wheel(widget)
            widget.wheelEvent(event)
            self.assertEqual(get(), before, type(widget).__name__)
            self.assertFalse(event.isAccepted(), "the page must be able to scroll instead")

    def test_a_focused_control_does_respond(self):
        spin = GuardedSpinBox()
        spin.setRange(0, 100)
        spin.setValue(50)
        spin.show()
        spin.setFocus()
        _app.processEvents()
        if spin.hasFocus():
            spin.wheelEvent(wheel(spin))
            self.assertNotEqual(spin.value(), 50)

    def test_keyword_table_actions_cannot_be_changed_by_scrolling(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = SettingsDialog(Settings.load(pathlib.Path(tmp)))
            d.build()
            before = d.collect_rows()
            for r in range(d.table.rowCount()):
                combo = d.table.cellWidget(r, 1)
                combo.wheelEvent(wheel(combo))
                combo.wheelEvent(wheel(combo, -120))
            self.assertEqual(d.collect_rows(), before)

    def test_every_settings_combo_and_number_box_is_guarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = SettingsDialog(Settings.load(pathlib.Path(tmp)))
            d.build()
            for control in (d.accent_combo, d.spacing_combo, d.feedback_combo, d.pack_combo, d.echo_combo):
                self.assertIsInstance(control, GuardedCombo)
            for control in (d.font_spin, d.history_spin):
                self.assertIsInstance(control, GuardedSpinBox)
            for control in (d.opacity_slider, d.blur_slider):
                self.assertIsInstance(control, GuardedSlider)


class TestPointersAndKeywordCells(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = SettingsDialog(Settings.load(pathlib.Path(self._tmp.name)))
        self.dlg = self.d.build()

    def tearDown(self):
        self._tmp.cleanup()

    def test_sliders_show_a_pointing_hand(self):
        for slider in (self.d.opacity_slider, self.d.blur_slider):
            self.assertEqual(slider.cursor().shape(), Qt.CursorShape.PointingHandCursor)

    def test_toggles_dropdowns_buttons_and_the_sidebar_show_a_pointing_hand(self):
        for control in (self.d.speak_check, self.d.accent_combo, self.d.pack_combo):
            self.assertEqual(control.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        for button in self.dlg.findChildren(QPushButton):
            self.assertEqual(button.cursor().shape(), Qt.CursorShape.PointingHandCursor, button.text())
        self.assertEqual(self.d.nav.viewport().cursor().shape(), Qt.CursorShape.PointingHandCursor)

    def test_keyword_cells_are_tall_enough_for_their_text(self):
        self.d.nav.setCurrentRow(self.d._nav_row("Keywords"))
        self.dlg.show()
        _app.processEvents()
        for r in range(self.d.table.rowCount()):
            combo = self.d.table.cellWidget(r, 1)
            needed = combo.fontMetrics().height() + 10 + 2          # text + padding + border
            self.assertGreaterEqual(combo.height(), needed, r)
            self.assertGreaterEqual(self.d.table.rowHeight(r), combo.minimumHeight() + 6)


class TestBundledModel(unittest.TestCase):
    """The model ships compressed (about 41 MB) and is unpacked once, on first launch."""

    ROOT = pathlib.Path(__file__).resolve().parents[1] / "quill" / "model"
    ZIP = ROOT / "vosk-model-small-en-us-0.15.zip"

    def test_the_compressed_model_ships_in_the_repo(self):
        import zipfile
        self.assertTrue(self.ZIP.is_file())
        self.assertLess(self.ZIP.stat().st_size, 50_000_000)          # not the 68 MB unpacked size
        with zipfile.ZipFile(self.ZIP) as zf:
            names = zf.namelist()
        self.assertIn("vosk-model-small-en-us-0.15/am/final.mdl", names)
        self.assertIn("vosk-model-small-en-us-0.15/conf/model.conf", names)

    def test_bundled_archive_is_found(self):
        from quill.listener.model import bundled_archive
        self.assertEqual(bundled_archive([self.ROOT]), self.ZIP)
        self.assertIsNone(bundled_archive([self.ROOT / "nowhere"]))

    def test_unpacking_produces_a_model_vosk_can_use(self):
        from quill.listener.model import unpack_bundled
        with tempfile.TemporaryDirectory() as tmp:
            model = unpack_bundled(pathlib.Path(tmp))
            self.assertTrue(is_model_dir(model))
            self.assertTrue((model / "am" / "final.mdl").exists())

    def test_first_launch_unpacks_once_and_later_launches_reuse_it(self):
        from quill.listener import model as model_module
        with tempfile.TemporaryDirectory() as tmp:
            original = model_module.user_model_dir
            model_module.user_model_dir = lambda: pathlib.Path(tmp) / "model"
            try:
                self.assertIsNone(find_model(search_dirs=[pathlib.Path(tmp) / "model"]))
                first = model_module.ensure_model()
                self.assertTrue(is_model_dir(first))
                mtime = (first / "am" / "final.mdl").stat().st_mtime_ns
                again = model_module.ensure_model()
                self.assertEqual(again, first)
                self.assertEqual((first / "am" / "final.mdl").stat().st_mtime_ns, mtime)   # not re-extracted
            finally:
                model_module.user_model_dir = original

    def test_a_configured_model_path_wins_over_unpacking(self):
        from quill.listener.model import ensure_model
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "mine"
            (fake / "am").mkdir(parents=True)
            (fake / "conf").mkdir()
            self.assertEqual(ensure_model(str(fake)), fake)

    def test_a_missing_archive_and_no_model_gives_none_not_a_crash(self):
        from quill.listener import model as model_module
        with tempfile.TemporaryDirectory() as tmp:
            saved = (model_module.bundled_archive, model_module.user_model_dir, model_module.default_search_dirs)
            model_module.bundled_archive = lambda *a: None
            model_module.user_model_dir = lambda: pathlib.Path(tmp) / "empty"
            model_module.default_search_dirs = lambda: [pathlib.Path(tmp) / "empty"]
            try:
                self.assertIsNone(model_module.ensure_model())
            finally:
                (model_module.bundled_archive, model_module.user_model_dir, model_module.default_search_dirs) = saved

    def test_the_zip_is_tracked_and_an_unpacked_copy_is_ignored(self):
        import subprocess
        repo = self.ROOT.parents[1]
        tracked = subprocess.run(["git", "check-ignore", "-q", str(self.ZIP)], cwd=repo, capture_output=True)
        self.assertEqual(tracked.returncode, 1, "the zip must not be ignored")
        unpacked = subprocess.run(["git", "check-ignore", "-q", str(self.ROOT / "vosk-model-small-en-us-0.15" / "am" / "final.mdl")],
                                  cwd=repo, capture_output=True)
        self.assertEqual(unpacked.returncode, 0, "an unpacked copy must stay out of git")

    def test_packaging_includes_it(self):
        for spec in ("quill_mac.spec", "quill_win.spec"):
            text = (self.ROOT.parents[1] / "packaging" / spec).read_text()
            self.assertIn('(r("quill", "model"), "quill/model")', text)
            self.assertIn("ROOT = os.path.abspath(os.path.join(SPECPATH", text)       # paths anchored to the repo root

    def test_the_app_unpacks_through_its_default_finder(self):
        from quill.listener.model import ensure_model
        from quill.app import QuillApp
        import inspect
        default = inspect.signature(QuillApp.__init__).parameters["model_finder"].default
        self.assertIs(default, ensure_model)


if __name__ == "__main__":
    unittest.main()
