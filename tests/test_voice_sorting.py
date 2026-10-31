"""Voice sorting: answering the Needs-sorting list by speaking chains of commands."""
import pathlib
import tempfile
import unittest

import openpyxl
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.sorting_voice import VoiceSorter
from tests.test_sorting import SENTENCE, DemoCase, demo

_app = QApplication.instance() or QApplication([])


class VoiceCase(DemoCase):
    """The demo workbook with the t-shirt sentence already saved and three terms pending."""

    def setUp(self):
        super().setUp()
        self.say("start listening", SENTENCE, "next row")
        # pending order: (None,'extra large'), (None,'teal'), ('Era','90s')
        self.assertTrue(self.ctl.start_voice_sort())

    def sort(self, text):
        self.say(text)
        return [e for e in self.events if e.kind == "sorting"][-1]

    def pending(self):
        return self.ctl.pending_terms()


class TestChains(VoiceCase):
    def test_one_breath_resolves_the_whole_list(self):
        self.say("same as xl color same as 1990s")
        self.assertEqual(self.pending(), [])
        row = self.cells(6)
        self.assertEqual((row["Size"], row["Color"], row["Era"]), ("XL", "Teal", "1990s"))
        self.assertIsNone(self.ctl.voice_sorter)                    # finished: back to dictation
        self.assertEqual(self.events[-1].kind, "sort_voice_ended")
        self.assertEqual(self.events[-1].detail, "All sorted")

    def test_each_command_moves_the_next_term_to_the_top(self):
        self.say("same as xl")
        self.assertEqual(self.pending()[0], (None, "teal"))
        self.say("color")
        self.assertEqual(self.pending(), [("Era", "90s")])

    def test_yes_adds_to_the_suggested_column(self):
        self.say("ignore ignore")
        self.assertEqual(self.pending(), [("Era", "90s")])
        self.say("yes")
        self.assertIn("90s", self.ctl.bridge.get_lists()["Era"])

    def test_yes_without_a_column_asks_for_one_and_keeps_the_term(self):
        event = self.sort("yes")
        self.assertIn("Which column is ‘extra large’", event.detail)
        self.assertEqual(len(self.pending()), 3)

    def test_add_to_named_column_variants(self):
        self.say("add to size")
        self.assertIn("Extra Large", self.ctl.bridge.get_lists()["Size"])
        self.say("yes color")
        self.assertIn("Teal", self.ctl.bridge.get_lists()["Color"])

    def test_ignore_synonyms(self):
        self.say("no")
        self.say("drop")
        self.say("forget it")
        self.assertEqual(self.pending(), [])

    def test_later_moves_term_to_the_end(self):
        self.say("later")
        self.assertEqual(self.pending()[-1], (None, "extra large"))
        self.assertEqual(self.pending()[0], (None, "teal"))

    def test_ignore_all_and_add_all(self):
        self.say("add all")                      # only the Era term has a column
        self.assertEqual(len(self.pending()), 2)
        self.say("ignore all")
        self.assertEqual(self.pending(), [])

    def test_done_leaves_the_rest_pending(self):
        self.say("ignore done")
        self.assertEqual(len(self.pending()), 2)
        self.assertIsNone(self.ctl.voice_sorter)
        self.assertEqual(self.events[-1].detail, "Voice sorting off")

    def test_commands_after_done_are_not_executed(self):
        self.say("done ignore")
        self.assertEqual(len(self.pending()), 3)


class TestSameAs(VoiceCase):
    def test_value_in_next_phrase(self):
        event = self.sort("same")
        self.assertIn("same as which value", event.detail)
        self.say("xl")
        self.assertEqual(self.pending()[0], (None, "teal"))
        self.assertEqual(self.cells(6)["Size"], "XL")

    def test_spelled_letters_read_as_one_value(self):
        self.say("same as x l")
        self.assertEqual(self.cells(6)["Size"], "XL")

    def test_named_column_then_same(self):
        self.say("size same as xl")
        self.assertEqual(self.cells(6)["Size"], "XL")

    def test_number_words_match_numeric_values(self):
        self.ctl.bridge.add_to_list("Size", "10")
        self.ctl.reload_vocab()
        self.say("size same as ten")
        self.assertEqual(self.pending()[0], (None, "teal"))

    def test_ambiguous_value_across_columns_is_not_guessed(self):
        self.ctl.bridge.add_to_list("Color", "Large")     # "large" now in two lists
        self.ctl.bridge.add_to_list("Size", "Large")
        self.ctl.reload_vocab()
        event = self.sort("same as large")
        self.assertIn("I don't have", event.detail)
        self.assertEqual(len(self.pending()), 3)

    def test_unknown_value_keeps_term_and_says_so(self):
        event = self.sort("same as zzz")
        self.assertIn("I don't have ‘zzz’", event.detail)
        self.assertEqual(len(self.pending()), 3)

    def test_column_restricts_value_search(self):
        self.say("ignore")                      # top: teal
        self.say("same as xl")                  # xl is a Size value, but teal's column is unknown: inferred
        self.assertEqual(self.pending(), [("Era", "90s")])


class TestModeBehaviour(VoiceCase):
    def test_speech_is_not_dictated_while_sorting(self):
        self.say("fern bright")
        self.assertEqual(self.ctl.session.record, {})

    def test_unrecognised_speech_gives_help_and_stays_on(self):
        event = self.sort("blah blah")
        self.assertIn("Didn't catch a command", event.detail)
        self.assertIsNotNone(self.ctl.voice_sorter)

    def test_filler_words_are_tolerated(self):
        self.say("okay so um same as the xl please")
        self.assertEqual(self.cells(6)["Size"], "XL")

    def test_stop_restores_dictation(self):
        self.say("done")
        self.say("black jeans")
        self.assertEqual(self.ctl.session.record, {"Color": "Black", "Type": "Jeans"})
        self.assertIsNone(self.ctl.voice_sorter)

    def test_cannot_start_with_nothing_pending(self):
        self.say("ignore all")
        self.assertFalse(self.ctl.start_voice_sort())

    def test_progress_events_carry_what_was_heard(self):
        self.say("same as xl")
        sorting = [e for e in self.events if e.kind == "sorting"][-1]
        self.assertEqual(sorting.record["heard"], "same as xl")
        self.assertIn("now means XL", sorting.detail)


class TestKeywordStart(DemoCase):
    def test_sort_terms_keyword_starts_the_mode(self):
        self.say("start listening", SENTENCE, "next row")
        self.say("sort terms")
        self.assertIsNotNone(self.ctl.voice_sorter)

    def test_keyword_with_nothing_pending(self):
        self.say("start listening", "sort terms")
        self.assertIsNone(self.ctl.voice_sorter)
        self.assertEqual(self.events[-1].detail, "Nothing to sort")

    def test_default_keyword_is_valid(self):
        s = Settings.defaults()
        self.assertEqual(s.keywords["sort terms"].name, "SORT_TERMS")
        self.assertEqual(Settings.validate_keywords(list(s.keywords.items())), [])


class TestSorterUnit(unittest.TestCase):
    """The parser alone, against a stub controller."""

    class Stub:
        def __init__(self):
            from quill.parser.vocab import Vocabulary
            self.vocab = Vocabulary()
            self.vocab.load({"Color": ["Red"], "Size": ["S", "XL"]}, [])
            self.items = [(None, "teal"), ("Size", "huge")]
            self.log = []

        def pending_terms(self):
            return list(self.items)

        def resolve_term(self, key, decision, term=None):
            self.items.remove(key)
            self.log.append((key, decision.kind, decision.column, decision.value))

        def defer_term(self, key):
            self.items.remove(key)
            self.items.append(key)
            self.log.append((key, "defer"))

    def test_result_counts_and_finish(self):
        stub = self.Stub()
        result = VoiceSorter(stub).handle("color yes")
        self.assertEqual((result.resolved, result.finished), (2, True))
        self.assertEqual(stub.log[0][1:], ("add", "Color", "Teal"))
        self.assertEqual(stub.log[1][1:], ("add", "Size", "Huge"))

    def test_empty_phrase(self):
        result = VoiceSorter(self.Stub()).handle("")
        self.assertEqual(result.resolved, 0)
        self.assertTrue(result.messages)


# ------------------------------------------------------------------ UI ----

class Listener:
    def start(self): pass
    def mute(self): pass
    def unmute(self): pass


class Speaker:
    enabled = True

    def say(self, text, on_done=None, lead_in=0.0):
        if on_done:
            on_done()


class AppVoiceCase(unittest.TestCase):
    def make(self, **prefs):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.path = demo.build(self.dir / "demo.xlsx")
        settings = Settings.load(self.dir / "cfg")
        settings.preferences.update(prefs)
        quill = QuillApp(_app, settings, XlsxBridge(self.path), listener_factory=lambda m, t, e: Listener(),
                         model_finder=lambda c: self.dir, speaker=Speaker())
        quill.start()
        return quill

    def hear(self, quill, *phrases):
        for p in phrases:
            quill.relay.transcript.emit(p)


class TestAppVoiceSorting(AppVoiceCase):
    def setUp(self):
        self.quill = self.make()
        self.hear(self.quill, "start listening", SENTENCE, "next row")

    def test_button_starts_voice_sorting_and_highlights_first(self):
        s = self.quill.sorting
        self.assertFalse(s.voice_active)
        s.voice_button.click()
        self.assertTrue(s.voice_active)
        self.assertTrue(s.voice_button.isChecked())
        self.assertIn("Listening", s.voice_button.text())
        self.assertFalse(s.voice_status.isVisibleTo(s.widget))        # no stray text beside the button
        self.assertEqual(s.voice_button.toolTip(), s.VOICE_HINT)
        self.assertIn("highlight", s.rows[0].styleSheet())
        self.assertEqual(s.rows[1].styleSheet(), "")

    def test_clicking_the_first_term_starts_it(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        first = self.quill.sorting.rows[0]
        QTest.mouseClick(first, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
        self.assertIsNotNone(self.quill.controller.voice_sorter)

    def test_list_updates_live_as_words_are_spoken(self):
        s = self.quill.sorting
        s.voice_button.click()
        self.assertEqual(len(s.rows), 3)
        self.hear(self.quill, "same as xl")
        self.assertEqual([r.key for r in s.rows], [(None, "teal"), ("Era", "90s")])
        self.assertIn("highlight", s.rows[0].styleSheet())
        self.assertEqual(self.quill.window.badge_label.text(), "2")
        self.assertIn("&nbsp;same as xl&nbsp;", s.voice_status.text())
        self.assertIn("Heard", s.voice_status.text())
        self.hear(self.quill, "color")
        self.assertEqual([r.key for r in s.rows], [("Era", "90s")])

    def test_finishing_turns_voice_off_and_hides_window(self):
        s = self.quill.sorting
        s.voice_button.click()
        self.hear(self.quill, "ignore all")
        self.assertFalse(s.voice_active)
        self.assertEqual(s.rows, [])
        self.assertFalse(s.widget.isVisible())
        self.assertIn("All sorted", self.quill.window.log.toPlainText())

    def test_button_again_stops_it(self):
        s = self.quill.sorting
        s.voice_button.click()
        s.voice_button.click()
        self.assertFalse(s.voice_active)
        self.assertEqual(len(s.rows), 3)
        self.assertIsNone(self.quill.controller.voice_sorter)

    def test_voice_sort_is_logged(self):
        self.quill.sorting.voice_button.click()
        self.hear(self.quill, "ignore")
        self.assertIn("Voice Sort: Ignored ‘extra large’", self.quill.window.log.toPlainText())

    def test_button_with_nothing_to_sort(self):
        self.quill.sorting.set_items([])
        self.quill.controller.session.pending = None
        self.quill.toggle_voice_sorting()
        self.assertIn("Nothing to sort", self.quill.window.log.toPlainText())
        self.assertFalse(self.quill.sorting.voice_active)


class TestAutoStart(AppVoiceCase):
    def test_off_by_default(self):
        quill = self.make()
        self.hear(quill, "start listening", SENTENCE, "next row")
        self.assertIsNone(quill.controller.voice_sorter)

    def test_preference_starts_voice_sorting_when_terms_appear(self):
        quill = self.make(auto_voice_sort=True)
        self.hear(quill, "start listening", SENTENCE, "next row")
        self.assertIsNotNone(quill.controller.voice_sorter)
        self.assertTrue(quill.sorting.voice_active)

    def test_settings_dialog_persists_the_preference(self):
        from quill.ui.settings_dialog import SettingsDialog
        settings = Settings.load(pathlib.Path(tempfile.mkdtemp()))
        dlg = SettingsDialog(settings)
        dlg.build()
        dlg.auto_sort_check.setChecked(True)
        self.assertTrue(dlg.try_accept())
        self.assertTrue(Settings.load(settings._config_dir).preferences["auto_voice_sort"])


if __name__ == "__main__":
    unittest.main()
