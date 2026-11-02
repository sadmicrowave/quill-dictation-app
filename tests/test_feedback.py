"""Audible feedback (sounds / spoken word), its settings, the configurable undo cap and the look."""
import pathlib
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from quill import feedback as fb
from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.history import History
from quill.session import Event
from quill.speaker.speaker import Speaker
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.theme import TOKENS, apply_theme, colors_for, palette_for, stylesheet_for
from tests.test_sorting import SENTENCE, DemoCase

_app = QApplication.instance() or QApplication([])


class Prefs:
    def __init__(self, **prefs):
        self.preferences = {"feedback": "sounds", "sound_pack": "chime", "echo_style": "okay", **prefs}


class Rig:
    """A Feedback wired to recorders."""

    def __init__(self, **prefs):
        self.played, self.said, self.busy = [], [], []
        self.fb = fb.Feedback(Prefs(**prefs), self.played.append, self.said.append, self.busy.append)

    def cues(self):
        return [p.stem for p in self.played]


class TestWhichCue(unittest.TestCase):
    def cue(self, kind, **kw):
        return fb.cue_for(Event(kind, **kw))

    def test_clean_row_is_a_success(self):
        self.assertEqual(self.cue("committed", terms=[]), ("success", ""))

    def test_row_with_terms_waits_for_the_sorting_cue(self):
        self.assertIsNone(self.cue("committed", terms=[(None, "teal")]))
        self.assertEqual(self.cue("confirm"), ("sort", ""))

    def test_successes(self):
        for kind in ("add_values", "alias_added", "searched", "cleared"):
            self.assertEqual(self.cue(kind)[0], "success", kind)

    def test_ignore_undo_delete_share_the_dismiss_cue(self):
        self.assertEqual(self.cue("skipped"), ("dismiss", "Ignored"))
        self.assertEqual(self.cue("undone"), ("dismiss", "Undone"))
        self.assertEqual(self.cue("discarded"), ("dismiss", "Deleted"))

    def test_errors(self):
        self.assertEqual(self.cue("error")[0], "error")
        self.assertEqual(self.cue("unsure")[0], "error")
        self.assertEqual(self.cue("sorting", record={"heard": "x", "problem": True})[0], "error")

    def test_quiet_events(self):
        for kind in ("started", "stopped", "updated", "ignored", "sorting", "expired"):
            self.assertIsNone(self.cue(kind), kind)


class TestPlaying(unittest.TestCase):
    def test_sound_files_exist_for_every_pack_and_cue(self):
        for pack in fb.PACKS:
            for cue in fb.CUES:
                path = fb.sound_path(pack, cue)
                self.assertTrue(path.exists(), path)
                self.assertGreater(fb.duration_s(path), 0.1)

    def test_five_packs(self):
        self.assertEqual(len(fb.PACKS), 5)
        self.assertEqual(len(fb.ECHO_WORDS), 3)

    def test_the_chosen_pack_plays(self):
        rig = Rig(sound_pack="walkie")
        rig.fb.request(Event("committed", terms=[]))
        self.assertEqual(rig.fb.flush(), "success")
        self.assertEqual(rig.played[0].parent.name, "walkie")
        self.assertEqual(rig.played[0].stem, "success")

    def test_only_the_most_important_cue_of_a_burst_plays(self):
        rig = Rig()
        for kind in ("add_values", "skipped", "add_values"):
            rig.fb.request(Event(kind))
        rig.fb.request(Event("error"))
        rig.fb.request(Event("add_values"))
        rig.fb.flush()
        self.assertEqual(rig.cues(), ["error"])
        self.assertIsNone(rig.fb.flush())             # nothing left over

    def test_sort_beats_success_and_dismiss(self):
        rig = Rig()
        for event in (Event("add_values"), Event("skipped"), Event("confirm")):
            rig.fb.request(event)
        rig.fb.flush()
        self.assertEqual(rig.cues(), ["sort"])

    def test_off_is_silent(self):
        rig = Rig(feedback="off")
        rig.fb.request(Event("error"))
        self.assertIsNone(rig.fb.flush())
        self.assertEqual((rig.played, rig.said), ([], []))

    def test_microphone_is_muted_for_the_length_of_the_sound(self):
        rig = Rig()
        rig.fb.request(Event("error"))
        rig.fb.flush()
        self.assertAlmostEqual(rig.busy[0], fb.duration_s(rig.played[0]) + 0.15, places=3)

    def test_echo_speaks_a_word(self):
        rig = Rig(feedback="echo", echo_style="got_it")
        for event in (Event("committed", terms=[]), Event("skipped"), Event("undone"),
                      Event("discarded"), Event("confirm"), Event("error")):
            rig.fb.request(event)
            rig.fb.flush()
        self.assertEqual(rig.said, ["Got It", "Ignored", "Undone", "Deleted", "Please Sort", "Problem"])
        self.assertEqual(rig.played, [])

    def test_each_echo_style_has_its_own_success_word(self):
        words = {fb.Feedback(Prefs(echo_style=key), print, print).word("success") for key in fb.ECHO_WORDS}
        self.assertEqual(words, {"Okay", "Done", "Got It"})

    def test_preview_overrides_the_settings(self):
        rig = Rig(feedback="off")
        rig.fb.cue("success", mode="sounds", pack="marimba")
        self.assertEqual(rig.played[0].parent.name, "marimba")

    def test_lead_in_only_in_sound_mode(self):
        self.assertGreater(Rig().fb.lead_in_s(), 0.3)
        self.assertEqual(Rig(feedback="echo").fb.lead_in_s(), 0)
        self.assertEqual(Rig(feedback="off").fb.lead_in_s(), 0)

    def test_unknown_values_fall_back(self):
        self.assertEqual(fb.sound_path("nope", "error").parent.name, "chime")
        self.assertEqual(Rig(feedback="weird").fb.mode, "sounds")


class TestSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_defaults(self):
        prefs = Settings.load(self.dir).preferences
        self.assertEqual((prefs["feedback"], prefs["sound_pack"], prefs["echo_style"], prefs["history_limit"]),
                         ("sounds", "chime", "okay", 100))

    def test_round_trip(self):
        s = Settings.load(self.dir)
        s.preferences.update(feedback="echo", sound_pack="glass", echo_style="done", history_limit=40)
        s.save()
        prefs = Settings.load(self.dir).preferences
        self.assertEqual((prefs["feedback"], prefs["sound_pack"], prefs["echo_style"], prefs["history_limit"]),
                         ("echo", "glass", "done", 40))

    def test_bad_values_are_repaired_and_the_cap_clamped(self):
        (self.dir / "keywords.toml").write_text(
            '[preferences]\nfeedback = "loud"\nsound_pack = "x"\necho_style = "y"\nhistory_limit = 100000\n')
        prefs = Settings.load(self.dir).preferences
        self.assertEqual((prefs["feedback"], prefs["sound_pack"], prefs["echo_style"]),
                         ("sounds", "chime", "okay"))
        self.assertEqual(prefs["history_limit"], 500)
        (self.dir / "keywords.toml").write_text("[preferences]\nhistory_limit = 1\n")
        self.assertEqual(Settings.load(self.dir).preferences["history_limit"], 5)


class TestDialogOptions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = Settings.load(pathlib.Path(self._tmp.name))
        self.previews = []
        self.dlg = SettingsDialog(self.settings, on_preview=lambda *a: self.previews.append(a))
        self.dlg.build()
        self.dlg.show_errors = lambda errors: None

    def tearDown(self):
        self._tmp.cleanup()

    def test_shows_the_current_choices(self):
        self.assertEqual(self.dlg.history_spin.value(), 100)
        self.assertEqual(self.dlg.feedback_combo.currentData(), "sounds")
        self.assertEqual(self.dlg.pack_combo.count(), 5)
        self.assertEqual(self.dlg.echo_combo.count(), 3)

    def test_only_the_relevant_choice_is_enabled(self):
        self.assertTrue(self.dlg.pack_combo.isEnabled() and not self.dlg.echo_combo.isEnabled())
        self.dlg.feedback_combo.setCurrentIndex(fb.MODES.index("echo"))
        self.assertTrue(self.dlg.echo_combo.isEnabled() and not self.dlg.pack_combo.isEnabled())
        self.dlg.feedback_combo.setCurrentIndex(fb.MODES.index("off"))
        self.assertFalse(self.dlg.echo_combo.isEnabled() or self.dlg.pack_combo.isEnabled())

    def test_saving_keeps_the_choices(self):
        self.dlg.history_spin.setValue(50)
        self.dlg.feedback_combo.setCurrentIndex(fb.MODES.index("echo"))
        self.dlg.echo_combo.setCurrentIndex(self.dlg.echo_combo.findData("done"))
        self.dlg.pack_combo.setCurrentIndex(self.dlg.pack_combo.findData("digital"))
        self.assertTrue(self.dlg.try_accept())
        prefs = Settings.load(pathlib.Path(self._tmp.name)).preferences
        self.assertEqual((prefs["history_limit"], prefs["feedback"], prefs["echo_style"], prefs["sound_pack"]),
                         (50, "echo", "done", "digital"))

    def test_the_spinner_stops_at_the_limits(self):
        self.dlg.history_spin.setValue(10**6)
        self.assertEqual(self.dlg.history_spin.value(), 500)
        self.dlg.history_spin.setValue(0)
        self.assertEqual(self.dlg.history_spin.value(), 5)

    def test_play_sample_previews_the_unsaved_choices(self):
        self.dlg.pack_combo.setCurrentIndex(self.dlg.pack_combo.findData("glass"))
        self.dlg.play_sample()
        self.assertEqual(self.previews, [("sounds", "glass", "okay")])


class TestHistoryCap(DemoCase):
    def test_new_cap_applies_to_the_running_history(self):
        for n in range(30):
            self.ctl.history.push(str(n), lambda: [])
        self.settings.preferences["history_limit"] = 10
        self.ctl.apply_settings()
        self.assertEqual(len(self.ctl.history), 10)
        self.assertEqual(self.ctl.history.pop().label, "29")      # the newest are kept

    def test_cap_comes_from_settings_at_start(self):
        self.settings.preferences["history_limit"] = 7
        from quill.controller import Controller
        self.assertEqual(Controller(self.ctl.bridge, self.settings).history.limit, 7)

    def test_history_limit_can_grow(self):
        history = History(2)
        history.limit = 5
        for n in range(8):
            history.push(str(n), lambda: [])
        self.assertEqual(len(history), 5)


class TestSpeakerLeadIn(unittest.TestCase):
    def test_lead_in_waits_before_speaking(self):
        import time
        calls = []
        speaker = Speaker(enabled=True, platform="none", run_in_thread=False)
        start = time.monotonic()
        speaker.say("hello", on_done=lambda: calls.append(time.monotonic() - start), lead_in=0.15)
        self.assertGreaterEqual(calls[0], 0.14)


class TestAppFeedback(DemoCase):
    def setUp(self):
        super().setUp()
        self.played, self.spoken = [], []
        self.app = QuillApp(_app, self.settings, XlsxBridge(self.path),
                            listener_factory=lambda *a: None, model_finder=lambda c: None,
                            sound_player=self.played.append,
                            echo_speaker=type("E", (), {"say": lambda s, w, on_done=None: self.spoken.append(w)})())
        self.app.start()

    def hear(self, *phrases):
        for phrase in phrases:
            self.app.controller.handle_transcript(phrase)
        self.app.feedback.flush()      # the timer would do this a moment later

    def cues(self):
        return [p.stem for p in self.played]

    def test_clean_row_plays_success(self):
        self.hear("start listening")
        self.hear("t-shirt next row")
        self.assertEqual(self.cues(), ["success"])

    def test_row_with_unknown_terms_plays_sort_and_shows_the_window(self):
        self.hear("start listening")
        self.hear(SENTENCE, "next row")
        self.assertEqual(self.cues(), ["sort"])
        self.assertTrue(self.app.sorting.widget.isVisible())

    def test_a_click_on_ignore_makes_no_sound(self):
        self.hear("start listening", SENTENCE, "next row")
        self.played.clear()
        key = self.app.controller.pending_terms()[0]
        from quill.session import Decision
        self.app.resolve_term(key, Decision.ignore(), key[1])
        self.app.feedback.flush()
        self.assertEqual(self.cues(), [])                              # clicks confirm themselves on screen

    def test_saying_ignore_plays_the_dismiss_cue(self):
        self.hear("start listening", SENTENCE, "next row")
        self.played.clear()
        self.app.controller.start_voice_sort()
        self.hear("ignore")
        self.assertIn("dismiss", self.cues())

    def test_a_voice_chain_gives_one_cue(self):
        self.hear("start listening", SENTENCE, "next row")
        self.played.clear()
        self.app.controller.start_voice_sort()
        self.hear("same as xl color same as 1990s")
        self.assertEqual(len(self.cues()), 1)

    def test_not_understood_in_voice_sorting_plays_error(self):
        self.hear("start listening", SENTENCE, "next row")
        self.played.clear()
        self.app.controller.start_voice_sort()
        self.hear("blah blah")
        self.assertEqual(self.cues(), ["error"])

    def test_echo_mode_speaks_instead(self):
        self.settings.preferences["feedback"] = "echo"
        self.hear("start listening")
        self.hear("t-shirt next row")
        self.assertEqual((self.cues(), self.spoken), ([], ["Okay"]))

    def test_off_mode_is_silent(self):
        self.settings.preferences["feedback"] = "off"
        self.hear("start listening")
        self.hear("t-shirt next row")
        self.assertEqual((self.cues(), self.spoken), ([], []))

    def test_play_sample_plays_only_the_selected_sound(self):
        self.app.preview_feedback("sounds", "glass", "okay")
        self.assertEqual([(p.parent.name, p.stem) for p in self.played], [("glass", "success")])

    def test_play_sample_in_spoken_mode_says_only_the_selected_word(self):
        self.app.preview_feedback("echo", "glass", "done")
        self.assertEqual((self.played, self.spoken), ([], ["Done"]))

    def test_spoken_question_waits_for_the_sort_cue(self):
        self.assertGreater(self.app.controller.lead_in_s, 0.3)
        self.settings.preferences["feedback"] = "echo"
        self.app.apply_settings()
        self.assertEqual(self.app.controller.lead_in_s, 0)


class TestLook(unittest.TestCase):
    def test_both_schemes_have_every_token(self):
        self.assertEqual(TOKENS["light"].keys(), TOKENS["dark"].keys())

    def test_stylesheet_uses_the_tokens(self):
        for dark, name in ((False, "light"), (True, "dark")):
            sheet = stylesheet_for(dark)
            self.assertIn(colors_for(dark)["accent"], sheet)
            self.assertIn(TOKENS[name]["bg"], sheet)
            self.assertNotIn("{t[", sheet)

    def test_palette_follows_the_scheme(self):
        from PySide6.QtGui import QPalette
        light = palette_for(False).color(QPalette.ColorRole.Window).name().upper()
        dark = palette_for(True).color(QPalette.ColorRole.Window).name().upper()
        self.assertEqual((light, dark), (TOKENS["light"]["bg"], TOKENS["dark"]["bg"]))

    def test_explicit_dark_and_light_apply_even_without_os_support(self):
        apply_theme(_app, "dark")
        self.assertIn(TOKENS["dark"]["bg"], _app.styleSheet())
        apply_theme(_app, "light")
        self.assertIn(TOKENS["light"]["bg"], _app.styleSheet())
        self.assertTrue(_app.property("quillFusion"))


if __name__ == "__main__":
    unittest.main()
