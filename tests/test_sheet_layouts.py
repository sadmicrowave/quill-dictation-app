"""Where a sheet's data is (the headings row, the starting row and which way the headings run) belongs to that sheet of that workbook,
not to the user: another sheet, or another workbook, may be laid out differently. Quill keeps it per workbook and sheet."""
import pathlib
import tempfile
import unittest

from quill.config.settings import Settings, SheetLayout
from tests.fixtures import make_workbook
from tests.test_app import AppCase


class TestTheStore(unittest.TestCase):
    def test_layouts_are_kept_between_runs_per_workbook_and_sheet(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings.load(pathlib.Path(folder))
            settings.set_layout("/a/one.xlsx", "Inventory", SheetLayout(5, 6, True))
            settings.set_layout("/a/one.xlsx", "Config", SheetLayout(2, 0, False))
            settings.set_layout("/a/two.xlsx", "Inventory", SheetLayout(9, 0, False))
            settings.save()
            again = Settings.load(pathlib.Path(folder))
            self.assertEqual(again.layout_for("/a/one.xlsx", "Inventory"), SheetLayout(5, 6, True))
            self.assertEqual(again.layout_for("/a/one.xlsx", "Config"), SheetLayout(2, 0, False))
            self.assertEqual(again.layout_for("/a/two.xlsx", "Inventory"), SheetLayout(9, 0, False))
            self.assertEqual(again.layout_for("/a/two.xlsx", "Other"), SheetLayout())          # (never set: the default)

    def test_a_default_layout_is_not_kept(self):
        settings = Settings({})
        settings.set_layout("/a.xlsx", "S", SheetLayout(3, 0, False))
        settings.set_layout("/a.xlsx", "S", SheetLayout())
        self.assertEqual(settings.layouts, {})

    def test_the_oldest_are_dropped_past_the_limit(self):
        from quill.config.settings import MAX_LAYOUTS
        settings = Settings({})
        for n in range(MAX_LAYOUTS + 5):
            settings.set_layout(f"/f{n}.xlsx", "S", SheetLayout(1, 0, False))
        self.assertEqual(len(settings.layouts), MAX_LAYOUTS)
        self.assertEqual(settings.layout_for("/f0.xlsx", "S"), SheetLayout())

    def test_nonsense_in_the_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            Settings.load(folder).save()
            (folder / Settings.KEYWORDS_FILE).write_text(
                (folder / Settings.KEYWORDS_FILE).read_text() + '\n[[layouts]]\npath = "/x.xlsx"\nsheet = "S"\nheadings_row = "abc"\n', encoding="utf-8")
            self.assertEqual(Settings.load(folder).layouts, {})


class TestFollowingTheSheet(AppCase):
    def controller(self):
        return self.quill.controller

    def test_changes_belong_to_the_open_sheet_and_the_next_sheet_starts_at_the_default(self):
        c = self.controller()
        c.set_headings_row(3)
        c.set_start_row(5)
        self.assertEqual(self.settings.layout_for(c._connected_to, "Inventory"), SheetLayout(3, 5, False))
        self.quill.controller.bridge.set_active_sheet("Config")
        self.assertTrue(c.follow_sheet())
        self.assertEqual((c.settings.preferences["headings_row"], c.settings.preferences["start_row"]), (0, 0))
        self.assertEqual(c.bridge._headings_row, 0)
        self.quill.controller.bridge.set_active_sheet("Inventory")
        c.follow_sheet()
        self.assertEqual((c.settings.preferences["headings_row"], c.settings.preferences["start_row"]), (3, 5))
        self.assertEqual((c.bridge._headings_row, c.bridge._start_row), (3, 5))

    def test_the_panel_shows_the_layout_of_the_sheet_that_is_open(self):
        c = self.controller()
        c.set_headings_row(3)
        shown = []
        original = self.quill.window.panel.set_options
        self.quill.window.panel.set_options = lambda *a, **k: (shown.append(a), original(*a, **k))
        c.bridge.set_active_sheet("Config")
        c.follow_sheet()
        self.assertEqual(shown[-1][3], 0)                           # headings row
        c.bridge.set_active_sheet("Inventory")
        c.follow_sheet()
        self.assertEqual(shown[-1][3], 3)

    def test_the_headings_direction_is_per_sheet_too(self):
        c = self.controller()
        c.set_vertical(True)
        self.assertTrue(c.bridge.set_active_sheet("Config"))        # (a sheet can be chosen whichever way the headings run)
        c.follow_sheet()
        self.assertFalse(c.vertical)
        self.assertFalse(c.bridge.vertical)
        c.bridge.set_active_sheet("Inventory")
        c.follow_sheet()
        self.assertTrue(c.vertical)

    def test_another_workbook_starts_at_the_default_and_the_first_one_is_remembered(self):
        c = self.controller()
        first = c._connected_to
        c.set_headings_row(3)
        other = make_workbook(self.dir / "other.xlsx")
        c.connect(str(other))
        self.assertEqual(c.settings.preferences["headings_row"], 0)
        c.connect(first)
        self.assertEqual(c.settings.preferences["headings_row"], 3)
        self.assertEqual(c.bridge._headings_row, 3)

    def test_it_survives_a_restart(self):
        c = self.controller()
        c.set_headings_row(3)
        c.set_vertical(False)
        path = c._connected_to
        again = Settings.load(self.dir / "cfg")
        self.assertEqual(again.layout_for(path, "Inventory").headings_row, 3)

    def test_setting_back_to_automatic_forgets_it(self):
        c = self.controller()
        c.set_headings_row(3)
        c.set_headings_row(0)
        self.assertEqual(c.settings.layouts, {})


class TestTheFileSettingsGear(AppCase):
    def gear(self):
        return self.quill.window.panel.settings_button

    def test_it_works_with_a_file_connected(self):
        self.assertTrue(self.gear().isEnabled())
        self.assertIn("File settings", self.gear().toolTip())

    def test_it_is_muted_and_disabled_without_a_file_and_comes_back_with_one(self):
        self.quill.controller.detach()
        self.quill.window.panel.set_active("")                      # (what the app does when a file is let go)
        self.assertFalse(self.gear().isEnabled())
        self.assertIn("once a file is connected", self.gear().toolTip())
        self.quill.window.panel.set_active("plants.xlsx", "Inventory", str(self.path), "Excel")
        self.assertTrue(self.gear().isEnabled())

    def test_a_file_let_go_closes_the_open_settings_overlay(self):
        panel = self.quill.window.panel
        panel.settings.show()
        panel.set_active("")
        self.assertFalse(panel.settings.isVisible())

    def test_the_app_disables_it_when_the_file_closes(self):
        self.quill.controller.detach()
        self.quill.window.update_workbooks([])                      # (what the app does when the file was closed)
        self.assertFalse(self.gear().isEnabled())
        self.quill.window.update_workbooks([self.path.name], self.path.name)
        self.assertTrue(self.gear().isEnabled())


if __name__ == "__main__":
    unittest.main()
