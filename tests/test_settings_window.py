"""The sidebar Settings window, its widgets, the collapsible Current row and the re-voiced sound packs."""
import pathlib
import struct
import sys
import tempfile
import unittest
import wave

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from quill import feedback as fb
from quill.config.settings import Settings
from quill.ui import theme
from quill.ui.main_window import MainWindow
from quill.ui.settings_dialog import GROUPS, SettingsDialog
from quill.ui.settings_widgets import FlatCombo, SegmentedControl, SettingRow, ToggleSwitch

_app = QApplication.instance() or QApplication([])


class DialogCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.settings = Settings.load(self.dir)
        self.previews = []
        self.d = SettingsDialog(self.settings, on_preview=lambda *a: self.previews.append(a))
        self.dlg = self.d.build()
        self.dlg.show()
        _app.processEvents()

    def tearDown(self):
        self._tmp.cleanup()

    def visible_pages(self):
        return [t for t, item in self.d._nav_items.items() if not item.isHidden()]


class TestLayout(DialogCase):
    def test_sidebar_has_a_search_box_and_grouped_pages(self):
        self.assertEqual(self.d.search.placeholderText(), "Search")
        names = [self.d.nav.item(i).text() for i in range(self.d.nav.count())]
        self.assertEqual(names, ["Preferences", "General", "Appearance", "Sounds",
                                 "Voice and Commands", "Keywords", "Speech Model", "Learned Words"])
        self.assertEqual([t for _, titles in GROUPS for t in titles], list(self.d._nav_items))

    def test_captions_cannot_be_selected(self):
        caption = self.d.nav.item(0)
        self.assertFalse(caption.flags() & Qt.ItemFlag.ItemIsSelectable)

    def test_picking_a_page_shows_it(self):
        for title in ("Sounds", "Keywords", "Appearance", "General"):
            self.d.nav.setCurrentRow(self.d._nav_row(title))
            self.assertEqual(self.d.pages.currentIndex(), self.d._page_index[title])

    def test_opens_on_general(self):
        self.assertEqual(self.d.nav.currentItem().text(), "General")

    def test_every_setting_lives_on_one_page_as_a_titled_row(self):
        self.assertEqual({r.title for r in self.d.rows},
                         {"Speak Sort Term Prompts", "Sort by Voice Automatically", "Undo Remembers", "Theme",
                          "Keep the Microphone Open When Not Listening", "Keep the Mini View on Top", "Hide the Dock Icon", "Check for Updates at Start", "Troubleshooting", "Open Files With", "Check for Changes",
                          "Accent Colour", "Spacing", "Text Size", "Window Opacity", "Window Blur", "Term Helper Follows Window Opacity",
                          "Confirm With", "Sound Set", "Spoken Word", "Stop Listening When Quiet",
                          "Quiet Time Before Stopping", "Quick", "Broad", "Careful", "Sounds for Term Helper Actions",
                          "Corrections Before Learning", "Ask Before Learning"})

    def test_the_keyword_table_gets_the_spare_height(self):
        self.d.nav.setCurrentRow(self.d._nav_row("Keywords"))
        _app.processEvents()
        self.assertGreaterEqual(self.d.table.height(), 280)
        self.assertGreater(self.d.table.height(), 330)             # was ~150 in the old dialog

    def test_window_is_roomy_and_resizable(self):
        self.assertGreaterEqual(self.dlg.width(), 900)
        self.assertGreaterEqual(self.dlg.height(), 700)
        self.assertLess(self.dlg.minimumWidth(), self.dlg.width())


class TestSearch(DialogCase):
    def test_filters_rows_and_hides_empty_groups(self):
        self.assertEqual(self.d.filter("blur"), 1)
        self.assertEqual(self.visible_pages(), ["Appearance"])
        self.assertEqual(self.d.nav.currentItem().text(), "Appearance")      # jumps to a page with matches
        shown = [r.title for r in self.d.rows if not r.isHidden()]
        self.assertEqual(shown, ["Window Blur"])

    def test_matches_descriptions_and_keywords_not_only_titles(self):
        self.d.filter("blurred")
        self.assertEqual([r.title for r in self.d.rows if not r.isHidden()], ["Window Blur"])
        self.d.filter("voice")
        titles = {r.title for r in self.d.rows if not r.isHidden()}
        self.assertIn("Sort by Voice Automatically", titles)

    def test_every_word_must_match(self):
        self.assertEqual(self.d.filter("text size"), 1)
        self.assertEqual(self.d.filter("text nonsense"), 0)

    def test_no_match_says_so_and_clearing_restores_everything(self):
        self.d.filter("zzzz")
        self.assertTrue(self.d.empty_label.isVisible())
        self.assertEqual(self.visible_pages(), [])
        self.assertEqual(self.d.filter(""), len(self.d.rows) + 1)           # +1: the keyword editor
        self.assertFalse(self.d.empty_label.isVisible())
        self.assertEqual(self.visible_pages(), ["General", "Appearance", "Sounds", "Keywords", "Speech Model", "Learned Words"])
        self.assertTrue(all(not r.isHidden() for r in self.d.rows))

    def test_search_finds_a_keyword_phrase(self):
        self.d.filter("next row")
        self.assertEqual(self.visible_pages(), ["Keywords"])
        self.assertEqual(self.d.nav.currentItem().text(), "Keywords")

    def test_captions_hide_with_their_pages(self):
        self.d.filter("blur")
        self.assertTrue(self.d._captions[1].isHidden())                      # "Voice and Commands"
        self.assertFalse(self.d._captions[0].isHidden())

    def test_typing_in_the_box_filters(self):
        self.d.search.setText("opacity")
        self.assertEqual(self.visible_pages(), ["Appearance"])


class TestWidgets(DialogCase):
    def test_toggle_switch_is_a_checkbox_with_a_switch_look(self):
        toggle = ToggleSwitch()
        self.assertFalse(toggle.isChecked())
        toggle.click()
        self.assertTrue(toggle.isChecked())
        self.assertEqual((toggle.sizeHint().width(), toggle.sizeHint().height()), (42, 24))
        off = toggle.grab().toImage()
        toggle.click()
        self.assertNotEqual(off, toggle.grab().toImage())

    def test_toggle_switch_ignores_clicks_outside_its_track(self):
        toggle = ToggleSwitch()
        toggle.resize(toggle.sizeHint())
        self.assertFalse(toggle.hitButton(toggle.rect().bottomRight() + toggle.rect().topRight() * 3))

    def test_segmented_control_behaves_like_a_selector(self):
        seg = SegmentedControl()
        for icon, label, data in (("monitor", "Auto", "auto"), ("sun", "Light", "light"), ("moon", "Dark", "dark")):
            seg.addItem(icon, label, data)
        self.assertEqual((seg.count(), seg.currentIndex(), seg.currentData()), (3, 0, "auto"))
        seen = []
        seg.currentIndexChanged.connect(seen.append)
        seg._buttons[2].click()
        self.assertEqual((seg.currentIndex(), seg.currentData(), seen), (2, "dark", [2]))
        seg.setCurrentIndex(1)
        self.assertEqual(seg.currentData(), "light")
        self.assertEqual(seg.findData("dark"), 2)
        self.assertEqual(seg.findData("x"), -1)
        self.assertTrue(all(not b.icon().isNull() for b in seg._buttons))

    def test_theme_selector_is_the_segmented_control(self):
        self.assertIsInstance(self.d.theme_combo, SegmentedControl)
        self.assertEqual(self.d.theme_combo.count(), 3)

    def test_dropdowns_are_flat(self):
        for combo in (self.d.accent_combo, self.d.spacing_combo, self.d.feedback_combo,
                      self.d.pack_combo, self.d.echo_combo):
            self.assertIsInstance(combo, FlatCombo)
            self.assertTrue(combo.property("flat"))

    def test_flat_style_has_no_border_and_a_hover_tint(self):
        sheet = theme.stylesheet_for(False)
        start = sheet.index('QComboBox[flat="true"], QSpinBox[flat="true"] {')
        rule = sheet[start: sheet.index("}", start)]
        self.assertIn("border: 1px solid transparent", rule)          # no visible box, but the focus ring has room
        self.assertIn("background: transparent", rule)
        self.assertIn('QComboBox[flat="true"]:hover', sheet)
        self.assertIn('QSpinBox[flat="true"]:hover', sheet)

    def test_setting_row_layout(self):
        control = ToggleSwitch()
        row = SettingRow("Title", "Some help", control, "extra")
        self.assertEqual((row.title_label.text(), row.description_label.text()), ("Title", "Some help"))
        self.assertTrue(row.matches("help extra"))
        self.assertFalse(row.matches("help nope"))
        self.assertTrue(row.description_label.property("muted"))
        bare = SettingRow("T", "", ToggleSwitch())
        self.assertTrue(bare.description_label.isHidden())


class TestSaving(DialogCase):
    def test_everything_round_trips_through_ok(self):
        d = self.d
        d.show_errors = lambda errors: None
        d.theme_combo.setCurrentIndex(2)
        d.accent_combo.setCurrentIndex(d.accent_combo.findData("violet"))
        d.spacing_combo.setCurrentIndex(1)
        d.font_spin.setValue(14)
        d.opacity_slider.setValue(40)
        d.blur_slider.setValue(85)
        d.history_spin.setValue(33)
        d.speak_check.setChecked(True)
        d.auto_sort_check.setChecked(True)
        d.feedback_combo.setCurrentIndex(fb.MODES.index("echo"))
        d.echo_combo.setCurrentIndex(d.echo_combo.findData("done"))
        d.pack_combo.setCurrentIndex(d.pack_combo.findData("walkie"))
        self.assertTrue(d.try_accept())
        p = Settings.load(self.dir).preferences
        self.assertEqual((p["theme"], p["accent"], p["spacing"], p["font_size"], p["opacity"], p["blur"]),
                         ("dark", "violet", "comfortable", 14, 40, 85))
        self.assertEqual((p["history_limit"], p["speak_sort_prompts"], p["auto_voice_sort"]), (33, True, True))
        self.assertEqual((p["feedback"], p["echo_style"], p["sound_pack"]), ("echo", "done", "walkie"))

    def test_keyword_errors_jump_to_the_keywords_page(self):
        shown = []
        self.d.show_errors = shown.append
        self.d.add_row("yes", self.d.collect_rows()[0][1])          # a bare answer word is not allowed
        self.d.nav.setCurrentRow(self.d._nav_row("General"))
        self.assertFalse(self.d.try_accept())
        self.assertEqual(self.d.nav.currentItem().text(), "Keywords")
        self.assertTrue(shown)

    def test_settings_window_stays_solid(self):
        self.settings.preferences["opacity"] = 20
        d = SettingsDialog(self.settings)
        d.build()
        # exec() applies chrome and opacity; verify via the helper it uses
        theme.apply_opacity(d._dialog, 100)
        self.assertEqual(d._dialog.windowOpacity(), 1.0)


class TestCurrentRowAlwaysVisible(unittest.TestCase):
    """The row being built is vital to every spoken turn, so it cannot be hidden."""

    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.resize(360, 620)
        self.w.widget.show()
        _app.processEvents()

    def test_there_is_no_heading_or_arrow_above_the_row_grid(self):
        self.assertFalse(hasattr(self.w, "row_heading"))
        self.assertFalse(hasattr(self.w, "row_toggle"))
        self.assertFalse(hasattr(self.w, "set_row_collapsed"))

    def test_the_table_is_always_shown(self):
        self.assertTrue(self.w.row_table.isVisible())
        self.w.set_mini(True)
        _app.processEvents()
        self.assertFalse(self.w.row_table.isVisible())          # not at the compact mini size
        self.w.set_mini(False)
        _app.processEvents()
        self.assertTrue(self.w.row_table.isVisible())


class TestSoundVariety(unittest.TestCase):
    @staticmethod
    def samples(pack, cue):
        with wave.open(str(fb.sound_path(pack, cue)), "rb") as f:
            return list(struct.unpack(f"<{f.getnframes()}h", f.readframes(f.getnframes()))), f.getframerate()

    def test_each_pack_has_its_own_character(self):
        for cue in fb.CUES:
            clips = {pack: self.samples(pack, cue)[0] for pack in fb.PACKS}
            for a in clips:
                for b in clips:
                    if a < b:
                        n = min(len(clips[a]), len(clips[b]), 6000)
                        diff = sum(abs(x - y) for x, y in zip(clips[a][:n], clips[b][:n])) / (n * 32767)
                        self.assertGreater(diff, 0.05, f"{a} and {b} sound alike for {cue}")

    def test_lengths_vary_across_packs(self):
        for cue in fb.CUES:
            lengths = {round(len(self.samples(p, cue)[0]) / 22050, 2) for p in fb.PACKS}
            self.assertGreaterEqual(len(lengths), 4, (cue, lengths))

    def test_pitch_character_differs(self):
        def zero_crossings(samples):
            return sum(1 for a, b in zip(samples, samples[1:]) if (a < 0) != (b < 0)) / len(samples)
        rates = {p: zero_crossings(self.samples(p, "success")[0]) for p in fb.PACKS}
        values = sorted(rates.values())
        self.assertTrue(all(b / a > 1.1 for a, b in zip(values, values[1:])), rates)

    def test_clips_are_short_and_not_clipping(self):
        for pack in fb.PACKS:
            for cue in fb.CUES:
                samples, rate = self.samples(pack, cue)
                self.assertLess(len(samples) / rate, 1.0, (pack, cue))
                self.assertLessEqual(max(abs(s) for s in samples), 32767)
                self.assertGreater(max(abs(s) for s in samples), 8000)

    def test_generator_is_deterministic(self):
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
        import make_sounds
        notes = make_sounds.PACKS["walkie"]["success"]
        self.assertEqual(make_sounds.render(notes), make_sounds.render(notes))        # seeded static


if __name__ == "__main__":
    unittest.main()


class TestAccountPageWireframe(unittest.TestCase):
    def build(self, shown):
        class Dialog(SettingsDialog):
            SHOW_ACCOUNT = shown
        dialog = Dialog(Settings.defaults())
        dialog.build()
        return dialog

    def test_the_account_page_is_not_in_the_window_yet(self):
        dialog = self.build(False)
        self.assertNotIn("Account", dialog._nav_items)
        self.assertFalse(hasattr(dialog, "sign_in_button"))

    def test_the_wireframe_shows_the_account_state_when_switched_on(self):
        dialog = self.build(True)
        self.assertIn("Account", dialog._nav_items)
        self.assertEqual(dialog.account_label.text(), "Not signed in")
        self.assertFalse(dialog.sign_in_button.isEnabled())           # no service to sign in to yet
        self.assertFalse(dialog.plan_button.isEnabled())


class TestAutoStopSettings(unittest.TestCase):
    def test_a_toggle_and_a_seconds_box_in_general_and_the_box_follows_the_toggle(self):
        dialog = SettingsDialog(Settings.defaults())
        dialog.build()
        self.assertTrue(dialog.auto_stop_check.isChecked())
        self.assertEqual(dialog.auto_stop_spin.value(), 10)
        self.assertTrue(dialog.auto_stop_spin.isEnabled())
        dialog.auto_stop_check.setChecked(False)
        self.assertFalse(dialog.auto_stop_spin.isEnabled())
        dialog.auto_stop_check.setChecked(True)
        dialog.auto_stop_spin.setValue(25)
        self.assertEqual((dialog._settings.preferences["auto_stop"], dialog._settings.preferences["auto_stop_seconds"]),
                         (True, 25))


class TestStyleInEveryMode(unittest.TestCase):
    """Settings controls look and line up the same in light and dark, compact and comfortable."""

    MODES = [(theme_name, spacing) for theme_name in ("light", "dark") for spacing in ("compact", "comfortable")]

    def make(self, theme_name, spacing, parent=None, lazy=False):
        theme.apply_theme(_app, theme_name, "violet", spacing)
        dialog = SettingsDialog(Settings.defaults(), parent)
        widget = dialog.build(lazy=lazy)
        widget.resize(900, 640)
        widget.show()
        _app.processEvents()
        return dialog, widget

    def value_controls(self, dialog):
        from PySide6.QtWidgets import QComboBox, QSpinBox
        return [row.control for row in dialog.rows
                if isinstance(row.control, (QComboBox, QSpinBox)) or row.control.property("valueControl")]

    def test_every_value_control_has_the_same_size_and_right_edge(self):
        from PySide6.QtCore import QPoint
        from quill.ui.settings_widgets import CONTROL_HEIGHT, CONTROL_WIDTH
        for theme_name, spacing in self.MODES:
            dialog, widget = self.make(theme_name, spacing)
            for title in ("General", "Appearance", "Sounds"):
                dialog.nav.setCurrentRow(dialog._nav_row(title))
                _app.processEvents()
                edges = set()
                for row in dialog._page_rows[title]:
                    control = row.control
                    if control not in self.value_controls(dialog):
                        continue
                    self.assertEqual(control.width(), CONTROL_WIDTH, (theme_name, spacing, row.title))
                    self.assertGreaterEqual(control.height(), CONTROL_HEIGHT, (theme_name, spacing, row.title))
                    edges.add(control.mapTo(widget, QPoint(control.width(), 0)).x())
                self.assertLessEqual(len(edges), 1, (theme_name, spacing, title))
            widget.close()

    def test_number_boxes_are_flat_like_the_drop_downs(self):
        for theme_name, spacing in self.MODES:
            dialog, widget = self.make(theme_name, spacing)
            for spin in (dialog.font_spin, dialog.history_spin, dialog.auto_stop_spin):
                self.assertTrue(spin.property("flat"))
            widget.close()

    def test_a_rows_text_does_not_move_when_the_spacing_mode_changes(self):
        gaps = {}
        for spacing in ("compact", "comfortable"):
            dialog, widget = self.make("light", spacing)
            dialog.nav.setCurrentRow(dialog._nav_row("Appearance"))
            _app.processEvents()
            row = dialog._page_rows["Appearance"][1]
            gaps[spacing] = row.description_label.y() - row.title_label.y()
            widget.close()
        self.assertEqual(gaps["compact"], gaps["comfortable"])

    def test_the_main_windows_spacing_does_not_reach_into_the_settings_window_or_its_drop_down_lists(self):
        for spacing in ("compact", "comfortable"):
            main = MainWindow()
            main.setup()
            dialog, widget = self.make("light", spacing, parent=main.widget)
            combo = dialog.spacing_combo
            dialog.nav.setCurrentRow(dialog._nav_row("Appearance"))
            combo.showPopup()
            combo.hidePopup()
            main.apply_density("comfortable" if spacing == "compact" else "compact")    # a live change of the spacing
            _app.processEvents()
            combo.showPopup()
            _app.processEvents()
            popup = combo.view().window()
            row_height = combo.view().sizeHintForRow(0)
            self.assertGreaterEqual(popup.height(), combo.count() * row_height, spacing)      # every item is visible
            longest = max(combo.view().fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count()))
            self.assertGreater(popup.width(), longest + 20, spacing)                             # and none is cut short
            combo.hidePopup()
            widget.close()

    def test_the_popup_list_is_lined_up_with_the_controls_right_edge(self):
        from PySide6.QtCore import QPoint
        dialog, widget = self.make("light", "comfortable")
        combo = dialog.accent_combo
        combo.showPopup()
        _app.processEvents()
        popup = combo.view().window()
        self.assertEqual(popup.x() + popup.width(), combo.mapToGlobal(QPoint(combo.width(), 0)).x())
        combo.hidePopup()
        widget.close()


class TestSettingsOpensQuickly(unittest.TestCase):
    def test_the_keywords_page_is_built_only_when_it_is_needed(self):
        theme.apply_theme(_app, "light", "violet", "compact")
        dialog = SettingsDialog(Settings.defaults())
        dialog.build(lazy=True)
        self.assertIsNone(dialog.table)
        self.assertEqual(dict(dialog.collect_rows()), Settings.defaults().keywords)       # saving works without opening it
        dialog.nav.setCurrentRow(dialog._nav_row("Keywords"))
        self.assertIsNotNone(dialog.table)
        self.assertEqual(dialog.table.rowCount(), len(Settings.defaults().keywords))

    def test_searching_looks_in_the_keywords_too(self):
        theme.apply_theme(_app, "light", "violet", "compact")
        dialog = SettingsDialog(Settings.defaults())
        dialog.build(lazy=True)
        self.assertGreater(dialog.filter("keyword"), 0)
        self.assertIsNotNone(dialog.table)

    def test_a_setting_row_never_forces_a_layout_pass_while_it_is_made(self):
        import time
        start = time.perf_counter()
        rows = [SettingRow(f"Title {i}", "A wrapped description. " * 8, ToggleSwitch()) for i in range(40)]
        self.assertLess(time.perf_counter() - start, 1.0, "making 40 rows took too long")
        self.assertEqual(len(rows), 40)


class TestChoosingASoundPlaysIt(unittest.TestCase):
    def test_there_is_no_play_button_or_preview_row_and_every_choice_plays_when_picked(self):
        from PySide6.QtWidgets import QPushButton
        dialog = SettingsDialog(Settings.defaults())
        widget = dialog.build()
        titles = {row.title for row in dialog.rows}
        self.assertNotIn("Preview", titles)
        self.assertNotIn("Play Sample", [b.text() for b in widget.findChildren(QPushButton)])
        played = []
        dialog._on_preview = lambda mode, pack, echo: played.append((mode, pack, echo))
        for combo in (dialog.feedback_combo, dialog.pack_combo, dialog.echo_combo):
            combo.activated.emit(0)
        self.assertEqual(len(played), 3)
