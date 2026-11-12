"""The default text size: 14 points suits a Mac (a point is one pixel there), but a point is 96/72 of a pixel on Windows, where 14 looked too large.
Each system's provider says its own default; everything else follows it."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from quill import platforms
from quill.config import settings as settings_module
from quill.config.settings import DEFAULT_PREFERENCES, Settings
from quill.ui import theme


class TestEachSystemsDefault(unittest.TestCase):
    def test_windows_starts_at_12_and_the_others_at_14(self):
        self.assertEqual(platforms.default_font_size("win32"), 12)
        self.assertEqual(platforms.default_font_size("darwin"), 14)
        self.assertEqual(platforms.default_font_size("linux"), 14)

    def test_the_settings_and_the_theme_follow_the_systems_default(self):
        self.assertEqual(DEFAULT_PREFERENCES["font_size"], platforms.default_font_size())
        self.assertEqual(theme.DEFAULT_FONT_SIZE, platforms.default_font_size())
        self.assertEqual(Settings.defaults().preferences["font_size"], platforms.default_font_size())

    def test_the_default_is_inside_the_range_the_setting_allows(self):
        low, high = settings_module.FONT_SIZE_RANGE
        for system in ("win32", "darwin", "linux"):
            self.assertTrue(low <= platforms.default_font_size(system) <= high)


class TestSettingsSavedBeforeTheDefaultWasPerSystem(unittest.TestCase):
    def write(self, folder, size, version):
        (folder / Settings.KEYWORDS_FILE).write_text(f"keywords_version = 4\n[preferences]\nfont_size = {size}\nprefs_version = {version}\n", encoding="utf-8")

    def load(self, size, version, default):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(DEFAULT_PREFERENCES, {"font_size": default}):
            path = pathlib.Path(folder)
            self.write(path, size, version)
            return Settings.load(path).preferences["font_size"]

    def test_on_windows_the_old_shared_14_becomes_12_once(self):
        self.assertEqual(self.load(14, 3, 12), 12)

    def test_a_size_the_user_chose_is_kept(self):
        self.assertEqual(self.load(16, 3, 12), 16)
        self.assertEqual(self.load(10, 3, 12), 10)

    def test_a_choice_of_14_made_after_the_change_is_kept(self):
        self.assertEqual(self.load(14, 4, 12), 14)

    def test_on_a_mac_14_stays_14(self):
        self.assertEqual(self.load(14, 3, 14), 14)


if __name__ == "__main__":
    unittest.main()
