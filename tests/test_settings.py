"""Settings tests (S5): defaults, persistence, validation, recovery."""
import pathlib
import tempfile
import unittest

from quill.config.settings import Settings
from quill.parser.commands import Action


class SettingsCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TestLoadSave(SettingsCase):
    def test_defaults_when_no_file(self):
        s = Settings.load(self.dir)
        self.assertEqual(s.keywords["next row"], Action.NEXT_ROW)
        self.assertEqual(s.preferences["theme"], "auto")

    def test_edits_persist_across_relaunch(self):
        s = Settings.load(self.dir)
        s.set_keywords([("go", Action.START_LISTENING), ("halt", Action.STOP_LISTENING),
                        ("commit", Action.NEXT_ROW)])
        s.preferences["theme"] = "dark"
        s.save()
        again = Settings.load(self.dir)
        self.assertEqual(again.keywords, {"go": Action.START_LISTENING,
                                          "halt": Action.STOP_LISTENING,
                                          "commit": Action.NEXT_ROW})
        self.assertEqual(again.preferences["theme"], "dark")

    def test_deleted_default_stays_deleted(self):
        s = Settings.load(self.dir)
        del s.keywords["new record"]
        s.save()
        self.assertNotIn("new record", Settings.load(self.dir).keywords)

    def test_reset_restores_defaults(self):
        s = Settings.load(self.dir)
        s.keywords = {"x": Action.NEXT_ROW}
        s.reset_keywords()
        self.assertEqual(s.keywords, Settings.defaults().keywords)

    def test_corrupt_file_falls_back_to_defaults(self):
        (self.dir / Settings.KEYWORDS_FILE).write_text("this is [not toml", encoding="utf-8")
        self.assertIn("next row", Settings.load(self.dir).keywords)

    def test_unknown_action_in_file_skipped(self):
        (self.dir / Settings.KEYWORDS_FILE).write_text(
            '[keywords]\n"go" = "START_LISTENING"\n"zap" = "TELEPORT"\n', encoding="utf-8")
        self.assertEqual(Settings.load(self.dir).keywords, {"go": Action.START_LISTENING})

    def test_bad_preference_types_and_theme_ignored(self):
        (self.dir / Settings.KEYWORDS_FILE).write_text(
            '[preferences]\ntheme = "neon"\nspeak_prompts = "yes"\nprompt_timeout_s = 5\n',
            encoding="utf-8")
        s = Settings.load(self.dir)
        self.assertEqual(s.preferences["theme"], "auto")
        self.assertIs(s.preferences["speak_prompts"], True)
        self.assertEqual(s.preferences["prompt_timeout_s"], 5)

    def test_windows_path_and_quotes_survive_roundtrip(self):
        s = Settings.load(self.dir)
        s.preferences["model_path"] = 'C:\\Users\\me\\"models"'
        s.save()
        self.assertEqual(Settings.load(self.dir).preferences["model_path"], 'C:\\Users\\me\\"models"')

    def test_phrases_are_lowercased(self):
        s = Settings.load(self.dir)
        s.set_keywords([("GO Now", Action.START_LISTENING), ("Halt", Action.STOP_LISTENING)])
        self.assertIn("go now", s.keywords)

    def test_config_dir_created(self):
        target = self.dir / "nested" / "quill"
        Settings.load(target).save()
        self.assertTrue((target / Settings.KEYWORDS_FILE).exists())


class TestValidation(SettingsCase):
    BASE = [("start", Action.START_LISTENING), ("stop", Action.STOP_LISTENING)]

    def test_valid(self):
        self.assertEqual(Settings.validate_keywords(self.BASE), [])

    def test_empty_phrase(self):
        self.assertTrue(Settings.validate_keywords(self.BASE + [("  ", Action.NEXT_ROW)]))

    def test_duplicate_ignoring_case_and_punctuation(self):
        errors = Settings.validate_keywords(self.BASE + [("Next Row", Action.NEXT_ROW),
                                                         ("next, row!", Action.DELETE_ROW)])
        self.assertTrue(any("Duplicate" in e for e in errors))

    def test_reserved_answer_word(self):
        errors = Settings.validate_keywords(self.BASE + [("yes", Action.NEXT_ROW)])
        self.assertTrue(any("reserved" in e for e in errors))

    def test_shipped_defaults_are_valid(self):
        rows = list(Settings.defaults().keywords.items())
        self.assertEqual(Settings.validate_keywords(rows), [])

    def test_reserved_word_inside_longer_phrase_is_fine(self):
        self.assertEqual(Settings.validate_keywords(self.BASE + [("yes next", Action.NEXT_ROW)]), [])

    def test_must_keep_start_and_stop(self):
        errors = Settings.validate_keywords([("next", Action.NEXT_ROW)])
        self.assertEqual(len(errors), 2)

    def test_set_keywords_rejects_invalid(self):
        s = Settings.load(self.dir)
        before = dict(s.keywords)
        with self.assertRaises(ValueError):
            s.set_keywords([("next", Action.NEXT_ROW)])
        self.assertEqual(s.keywords, before)


if __name__ == "__main__":
    unittest.main()


class TestWindowSizePreference(unittest.TestCase):
    def test_a_saved_size_round_trips_and_defaults_to_unset(self):
        import tempfile, pathlib
        from quill.config.settings import Settings
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.load(pathlib.Path(tmp))
            self.assertEqual((settings.preferences["window_width"], settings.preferences["window_height"]), (0, 0))
            settings.preferences["window_width"], settings.preferences["window_height"] = 410, 630
            settings.save()
            again = Settings.load(pathlib.Path(tmp))
            self.assertEqual((again.preferences["window_width"], again.preferences["window_height"]), (410, 630))
