"""Undo: a capped history of sorting decisions that can be walked backwards."""
import datetime as dt
import pathlib
import tempfile
import unittest

import openpyxl
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import Controller
from quill.history import HISTORY_LIMIT, History
from quill.session import Decision
from tests.fixtures import make_workbook
from tests.test_sorting import SENTENCE, DemoCase

_app = QApplication.instance() or QApplication([])


class TestHistory(unittest.TestCase):
    def test_keeps_only_the_most_recent_entries(self):
        history = History(limit=3)
        for n in range(5):
            history.push(str(n), lambda: [])
        self.assertEqual(len(history), 3)
        self.assertEqual([history.pop().label for _ in range(3)], ["4", "3", "2"])
        self.assertIsNone(history.pop())

    def test_default_cap_is_one_hundred(self):
        self.assertEqual(HISTORY_LIMIT, 100)
        history = History()
        for n in range(250):
            history.push(str(n), lambda: [])
        self.assertEqual(len(history), 100)
        self.assertEqual(history.pop().label, "249")

    def test_a_group_is_one_step_that_undoes_newest_first(self):
        history, order = History(), []
        with history.group("Several"):
            for n in range(3):
                history.push(str(n), lambda n=n: order.append(n) or [])
        self.assertEqual(len(history), 1)
        history.pop().undo()
        self.assertEqual(order, [2, 1, 0])

    def test_a_group_of_one_keeps_its_own_label(self):
        history = History()
        with history.group("Several"):
            history.push("Only", lambda: [])
        self.assertEqual(history.pop().label, "Only")

    def test_popping_inside_a_group_sees_what_was_just_pushed(self):
        history = History()
        with history.group("Several"):
            history.push("a", lambda: [])
            history.push("b", lambda: [])
            self.assertEqual(history.pop().label, "Several")


class TestUndoDecisions(DemoCase):
    def setUp(self):
        super().setUp()
        self.say("start listening", SENTENCE, "next row")
        self.before = self.ctl.pending_terms()          # jumbo, teal, 90s

    def lists(self):
        return self.ctl.bridge.get_lists()

    def test_nothing_to_undo(self):
        self.assertEqual(self.ctl.undo(), ["Nothing to undo"])

    def test_undo_an_ignore_puts_the_term_back_in_place(self):
        self.ctl.resolve_term(self.before[1], Decision.ignore())
        self.assertEqual(len(self.ctl.pending_terms()), 2)
        self.ctl.undo()
        self.assertEqual(self.ctl.pending_terms(), self.before)

    def test_undo_an_add_removes_the_value_and_empties_the_filled_cell(self):
        self.ctl.resolve_term((None, "teal"), Decision.add("Color", "Teal"))
        self.assertIn("Teal", self.lists()["Color"])
        self.assertEqual(self.cells(6)["Color"], "Teal")
        notes = self.ctl.undo()
        self.assertEqual(notes, ["Undid: Added Teal to Color"])
        self.assertNotIn("Teal", self.lists()["Color"])
        self.assertNotIn("Teal", self.ctl.vocab.values_for("Color"))
        self.assertIsNone(self.cells(6)["Color"])
        self.assertEqual(self.ctl.pending_terms(), self.before)

    def test_undone_add_is_not_recognised_until_redone(self):
        self.ctl.resolve_term((None, "teal"), Decision.add("Color", "Teal"))
        self.ctl.undo()
        self.say("teal next row")
        self.assertIn((None, "teal"), self.ctl.pending_terms())

    def test_undo_keeps_a_value_that_was_already_in_the_list(self):
        self.ctl.resolve_term((None, "teal"), Decision.add("Color", "Black"))   # already a value
        self.ctl.undo()
        self.assertIn("Black", self.lists()["Color"])

    def test_undo_leaves_a_cell_the_user_changed(self):
        self.ctl.resolve_term((None, "teal"), Decision.add("Color", "Teal"))
        self.ctl.bridge.clear_value("Inventory", 6, "Color", "Teal")
        self.ctl.bridge.set_value("Inventory", 6, "Color", "Navy")
        notes = self.ctl.undo()
        self.assertTrue(any("was changed" in n for n in notes))
        self.assertEqual(self.cells(6)["Color"], "Navy")

    def test_undo_a_same_as_forgets_the_synonym(self):
        self.ctl.resolve_term((None, "jumbo"), Decision.alias("Size", "XL"))
        self.assertEqual(self.cells(6)["Size"], "XL")
        self.assertEqual(self.settings.aliases["Size"]["jumbo"], "XL")
        self.ctl.undo()
        self.assertNotIn("Size", self.settings.aliases)
        self.assertIsNone(self.cells(6)["Size"])
        self.assertEqual(self.ctl.pending_terms(), self.before)
        saved = (self.dir / "cfg" / "keywords.toml").read_text()
        self.assertNotIn("jumbo", saved)
        self.say("jumbo next row")                  # no longer understood
        self.assertIn((None, "jumbo"), self.ctl.pending_terms())

    def test_undo_restores_the_synonym_it_replaced(self):
        self.settings.add_alias("Size", "jumbo", "L")
        self.ctl.vocab.add_alias("Size", "jumbo", "L")
        self.ctl.resolve_term((None, "jumbo"), Decision.alias("Size", "XL"))
        self.ctl.undo()
        self.assertEqual(self.settings.aliases["Size"]["jumbo"], "L")

    def test_undo_a_defer(self):
        self.ctl.defer_term(self.before[0])
        self.assertEqual(self.ctl.pending_terms()[-1], self.before[0])
        self.ctl.undo()
        self.assertEqual(self.ctl.pending_terms(), self.before)

    def test_deferring_the_last_term_changes_nothing_so_is_not_an_undo_step(self):
        self.ctl.defer_term(self.before[-1])
        self.assertEqual(len(self.ctl.history), 0)

    def test_steps_walk_back_newest_first(self):
        self.ctl.resolve_term(self.before[0], Decision.alias("Size", "XL"))
        self.ctl.resolve_term(self.before[1], Decision.ignore())
        self.ctl.resolve_term(self.before[2], Decision.add("Era", "90s"))
        self.assertEqual(self.ctl.pending_terms(), [])
        self.ctl.undo()
        self.assertEqual(self.ctl.pending_terms(), [self.before[2]])
        self.ctl.undo(2)
        self.assertEqual(self.ctl.pending_terms(), self.before)
        self.assertEqual(self.ctl.undo(), ["Nothing to undo"])

    def test_undoing_the_last_answer_after_the_list_emptied(self):
        for key in list(self.before):
            self.ctl.resolve_term(key, Decision.ignore())
        self.assertIsNone(self.ctl.session.pending)
        self.ctl.undo()
        self.assertEqual(self.ctl.pending_terms(), [self.before[-1]])

    def test_bulk_answers_undo_together(self):
        with self.ctl.batch("Ignored terms"):
            for key in list(self.before):
                self.ctl.resolve_term(key, Decision.ignore())
        self.assertEqual(len(self.ctl.history), 1)
        self.ctl.undo()
        self.assertEqual(self.ctl.pending_terms(), self.before)

    def test_a_spoken_yes_for_many_terms_undoes_in_one_step(self):
        self.say("start listening", "fern next row")        # nothing new
        self.ctl.session.pending = [("Era", "90s"), ("Color", "teal")]
        self.ctl.session._voice_open = True
        count = len(self.ctl.history)
        self.say("yes")
        self.assertEqual(len(self.ctl.history), count + 1)
        self.ctl.undo()
        self.assertEqual(self.ctl.pending_terms(), [("Era", "90s"), ("Color", "teal")])

    def test_history_is_cleared_when_connecting_to_another_workbook(self):
        self.ctl.resolve_term(self.before[0], Decision.ignore())
        self.ctl.connect()
        self.assertEqual(len(self.ctl.history), 0)

    def test_history_never_exceeds_its_cap(self):
        for n in range(HISTORY_LIMIT + 20):
            self.ctl.session.pending = [(None, f"term{n}")]
            self.ctl.resolve_term((None, f"term{n}"), Decision.ignore())
        self.assertEqual(len(self.ctl.history), HISTORY_LIMIT)


class TestUndoByVoice(DemoCase):
    def setUp(self):
        super().setUp()
        self.say("start listening", SENTENCE, "next row")
        self.before = self.ctl.pending_terms()

    def test_undo_keyword_while_dictating(self):
        self.ctl.resolve_term(self.before[0], Decision.ignore())
        self.say("undo")
        self.assertEqual(self.ctl.pending_terms(), self.before)
        self.assertEqual(self.events[-1].kind, "undone")

    def test_undo_keyword_with_nothing_to_undo_is_harmless(self):
        self.say("undo")
        self.assertEqual(self.events[-1].kind, "ignored")
        self.assertEqual(self.events[-1].detail, "Nothing to undo")

    def test_undo_is_ignored_while_not_listening(self):
        self.ctl.resolve_term(self.before[0], Decision.ignore())
        self.say("stop listening", "undo")
        self.assertEqual(len(self.ctl.pending_terms()), 2)

    def test_undo_in_a_voice_sorting_chain(self):
        self.ctl.start_voice_sort()
        self.say("ignore ignore undo")
        self.assertEqual(self.ctl.pending_terms(), self.before[1:])

    def test_undo_a_count_in_voice_sorting(self):
        self.ctl.start_voice_sort()
        self.say("ignore ignore")
        self.say("undo two")
        self.assertEqual(self.ctl.pending_terms(), self.before)

    def test_undo_after_the_last_term_in_the_same_breath(self):
        self.ctl.start_voice_sort()
        self.say("ignore ignore ignore undo")
        self.assertEqual(self.ctl.pending_terms(), [self.before[-1]])
        self.assertIsNotNone(self.ctl.voice_sorter)         # still sorting: one term is back

    def test_oops_means_undo(self):
        self.ctl.start_voice_sort()
        self.say("ignore oops")
        self.assertEqual(self.ctl.pending_terms(), self.before)

    def test_ignore_all_is_one_undo_step(self):
        self.ctl.start_voice_sort()
        self.say("ignore all")
        self.assertEqual(self.ctl.pending_terms(), [])
        self.say("undo")      # sorting ended when the list emptied; the keyword does the same
        self.assertEqual(self.ctl.pending_terms(), self.before)

    def test_default_keyword_exists(self):
        self.assertEqual(Settings.defaults().keywords["undo"].name, "UNDO")


class TestSameAsIsNotTiedToAnyDomain(unittest.TestCase):
    """"same as <value>" works for whatever the workbook's lists contain (here: plants)."""

    def test_same_as_a_plant_species(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            ctl = Controller(XlsxBridge(make_workbook(tmp / "plants.xlsx")),
                             Settings.load(tmp / "cfg"), None, today=lambda: dt.date(2026, 10, 30))
            ctl.connect()
            ctl.handle_transcript("start listening")
            ctl.handle_transcript("ferny thing next row")
            ctl.session.pending = [(None, "boston")]
            ctl.start_voice_sort()
            ctl.handle_transcript("same as fern")
            self.assertEqual(ctl.settings.aliases, {"Species": {"boston": "Fern"}})
            ctl.undo()
            self.assertEqual(ctl.settings.aliases, {})


class TestUndoInTheApp(DemoCase):
    def setUp(self):
        super().setUp()
        self.app = QuillApp(_app, self.settings, XlsxBridge(self.path),
                            listener_factory=lambda *a: None, model_finder=lambda c: None)
        self.app.start()

    def test_buttons_follow_the_history(self):
        window, ctl = self.app.window, self.app.controller
        self.assertFalse(window.undo_button.isEnabled())                  # nothing to take back yet
        ctl.handle_transcript("start listening")
        ctl.handle_transcript(SENTENCE)
        ctl.handle_transcript("next row")
        key = ctl.pending_terms()[0]
        self.app.resolve_term(key, Decision.ignore(), key[1])
        self.assertTrue(window.undo_button.isEnabled())
        self.assertEqual(window.undo_button.text(), "")                     # just an icon, no count
        self.assertTrue(self.app.sorting.undo_button.isEnabled())
        self.app.undo()
        self.assertEqual(len(ctl.pending_terms()), 3)
        self.assertFalse(window.undo_button.isEnabled())
        self.assertIn("Undid: Ignored", window.log.toPlainText())

    def test_window_bulk_buttons_are_one_undo_step(self):
        ctl = self.app.controller
        ctl.handle_transcript("start listening")
        ctl.handle_transcript(SENTENCE)
        ctl.handle_transcript("next row")
        self.app.refresh_sorting(reveal=True)
        self.app.sorting.ignore_all()
        self.assertEqual(ctl.pending_terms(), [])
        self.app.undo()
        self.assertEqual(len(ctl.pending_terms()), 3)


if __name__ == "__main__":
    unittest.main()
