"""Unrecognised terms: sorting decisions, aliases, back-fill, and the Needs-sorting window."""
import datetime as dt
import importlib.util
import pathlib
import tempfile
import unittest

import openpyxl
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import Controller
from quill.parser.commands import Action, CommandMatcher
from quill.parser.vocab import Vocabulary
from quill.session import Decision, Session
from quill.ui.sorting_window import PLACEHOLDER, SortingWindow, question_for

_app = QApplication.instance() or QApplication([])

_spec = importlib.util.spec_from_file_location(
    "make_demo_workbook", pathlib.Path(__file__).resolve().parents[1] / "examples" / "make_demo_workbook.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

SENTENCE = ("this next item is an extra large t-shirt made in the 90s "
            "mainly teal and could sell for thirty five dollars")


class DemoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.path = demo.build(self.dir / "demo.xlsx")
        self.settings = Settings.load(self.dir / "cfg")
        self.events = []
        self.ctl = Controller(XlsxBridge(self.path), self.settings, None,
                              on_event=self.events.append, today=lambda: dt.date(2026, 10, 30))
        self.ctl.connect()

    def tearDown(self):
        self._tmp.cleanup()

    def say(self, *phrases):
        for phrase in phrases:
            self.ctl.handle_transcript(phrase)

    def cells(self, row):
        ws = openpyxl.load_workbook(self.path)["Inventory"]
        return {h.value: ws.cell(row=row, column=i).value for i, h in enumerate(ws[1], 1)}


class TestTheExample(DemoCase):
    """'an extra large t-shirt made in the 90s, mainly teal, could sell for $35'."""

    def setUp(self):
        super().setUp()
        self.say("start listening", SENTENCE, "next row")

    def test_known_parts_are_saved_immediately(self):
        row = self.cells(6)
        self.assertEqual((row["Type"], row["Appraisal"]), ("T-Shirt", 35.0))
        self.assertIsNone(row["Size"] or row["Era"] or row["Color"])

    def test_unplaced_terms_are_listed_with_suggestions_where_possible(self):
        pending = self.ctl.pending_terms()
        self.assertIn(("Era", "90s"), pending)          # looks like the Era values
        self.assertIn((None, "teal"), pending)           # nothing to go on: ask
        self.assertIn((None, "extra large"), pending)
        self.assertEqual(len(pending), 3)

    def test_filler_words_are_not_treated_as_terms(self):
        terms = {t for _, t in self.ctl.pending_terms()}
        self.assertFalse(terms & {"mainly", "made", "could", "sell", "next", "item"})

    def test_sorting_them_adds_values_and_fills_the_saved_row(self):
        self.ctl.resolve_term((None, "teal"), Decision.add("Color"))
        self.ctl.resolve_term((None, "extra large"), Decision.alias("Size", "XL"))
        self.ctl.resolve_term(("Era", "90s"), Decision.alias("Era", "1990s"))
        self.assertEqual(self.ctl.pending_terms(), [])
        row = self.cells(6)
        self.assertEqual((row["Size"], row["Era"], row["Color"]), ("XL", "1990s", "Teal"))
        self.assertIn("Teal", self.ctl.bridge.get_lists()["Color"])
        self.assertIn("filled Size on row 6", " ".join(e.detail for e in self.events))

    def test_aliases_persist_and_work_next_time(self):
        self.ctl.resolve_term((None, "extra large"), Decision.alias("Size", "XL"))
        self.assertEqual(Settings.load(self.dir / "cfg").aliases, {"Size": {"extra large": "XL"}})
        again = Controller(XlsxBridge(self.path), Settings.load(self.dir / "cfg"), None)
        again.connect()
        again.handle_transcript("start listening")
        again.handle_transcript("extra large jeans")
        self.assertEqual(again.session.record["Size"], "XL")
        self.assertEqual(again.session.record["Type"], "Jeans")

    def test_added_value_is_recognised_afterwards(self):
        self.ctl.resolve_term((None, "teal"), Decision.add("Color"))
        self.say("teal")
        self.assertEqual(self.ctl.session.record["Color"], "Teal")

    def test_ignore_leaves_the_cell_empty(self):
        self.ctl.resolve_term((None, "teal"), Decision.ignore())
        self.assertIsNone(self.cells(6)["Color"])
        self.assertNotIn((None, "teal"), self.ctl.pending_terms())

    def test_edited_words_are_used(self):
        self.ctl.resolve_term((None, "teal"), Decision.add("Color"), term="Sea Green")
        self.assertIn("Sea Green", self.ctl.bridge.get_lists()["Color"])
        self.assertEqual(self.cells(6)["Color"], "Sea Green")


class TestBackfillRules(DemoCase):
    def test_never_overwrites_a_cell_the_user_filled(self):
        self.say("start listening", "teal t-shirt", "next row")
        self.ctl.bridge._grid.write("Inventory", 6, 5, "Mint")   # user typed a colour by hand
        self.ctl.resolve_term((None, "teal"), Decision.add("Color"))
        self.assertEqual(self.cells(6)["Color"], "Mint")

    def test_term_from_unsaved_row_is_not_backfilled(self):
        self.say("start listening", "teal t-shirt", "stop listening")
        self.ctl.resolve_term((None, "teal"), Decision.add("Color"))
        self.assertIn("Teal", self.ctl.bridge.get_lists()["Color"])
        self.assertIsNone(self.cells(6)["Type"])        # nothing was written

    def test_alias_to_unknown_value_is_an_error(self):
        self.say("start listening", "zorblax", "next row")
        self.events.clear()
        self.ctl.resolve_term((None, "zorblax"), Decision.alias("Size", "ENORMOUS"))
        self.assertEqual(self.events[-1].kind, "error")

    def test_resolving_something_not_pending_is_a_noop(self):
        self.ctl.resolve_term((None, "nothing"), Decision.ignore())
        self.assertEqual(self.events, [])

    def test_failed_list_add_does_not_backfill(self):
        wb = openpyxl.load_workbook(self.path)
        cfg = wb["Config"]
        for r in range(2, 20):                  # fill every Condition slot: list now full
            cfg.cell(row=r, column=5).value = cfg.cell(row=r, column=5).value or f"c{r}"
        wb.save(self.path)
        self.ctl.refresh()
        self.say("start listening", "condition mint t-shirt", "next row")
        self.ctl.resolve_term(("Condition", "mint"), Decision.add("Condition"))
        self.assertIsNone(self.cells(6)["Condition"])
        self.assertTrue(any(e.kind == "error" for e in self.events))


class TestBareAmounts(DemoCase):
    def test_dollars_without_a_field_word_use_the_amount_column(self):
        self.say("start listening", "thirty five dollars")
        self.assertEqual(self.ctl.session.record["Appraisal"], 35.0)

    def test_plain_number_without_currency_is_ignored(self):
        self.say("start listening", "thirty five")
        self.assertNotIn("Appraisal", self.ctl.session.record)

    def test_named_column_still_wins(self):
        self.say("start listening", "appraisal twelve")
        self.assertEqual(self.ctl.session.record["Appraisal"], 12.0)


class TestSettingsAliases(unittest.TestCase):
    def test_roundtrip_and_tolerance(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Settings.load(pathlib.Path(tmp))
            s.add_alias("Size", " Extra Large ", "XL")
            s.add_alias('Odd "col"', "x y", "Z")
            s.save()
            self.assertEqual(Settings.load(pathlib.Path(tmp)).aliases,
                             {"Size": {"extra large": "XL"}, 'Odd "col"': {"x y": "Z"}})
            (pathlib.Path(tmp) / Settings.KEYWORDS_FILE).write_text(
                '[aliases]\nSize = "not a table"\n[aliases.Ok]\n"a" = "b"\n"n" = 5\n', encoding="utf-8")
            self.assertEqual(Settings.load(pathlib.Path(tmp)).aliases, {"Ok": {"a": "b"}})


class TestVocabAlias(unittest.TestCase):
    def test_alias_only_for_existing_values(self):
        v = Vocabulary()
        v.load({"Size": ["S", "XL"]})
        self.assertTrue(v.add_alias("Size", "extra large", "xl"))
        self.assertFalse(v.add_alias("Size", "huge", "XXXL"))
        self.assertFalse(v.add_alias("Nope", "x", "y"))
        self.assertFalse(v.add_alias("Size", "  ", "XL"))
        self.assertEqual(v.matches_at(["extra", "large"], 0), [("Size", "XL", 2)])
        v.add_alias("Size", "extra large", "XL")          # idempotent
        self.assertEqual(len(v.matches_at(["extra", "large"], 0)), 1)


class TestSessionVoiceAndExpiry(unittest.TestCase):
    def make(self):
        v = Vocabulary()
        v.load({"Light": ["Low"]}, ["Light"])
        s = Session(v, CommandMatcher({"start listening": Action.START_LISTENING,
                                       "next row": Action.NEXT_ROW}))
        s.feed("start listening")
        s.feed("light dim")
        return s

    def test_voice_no_ignores_every_pending_term(self):
        s = self.make()
        s.feed("next row")
        events = s.feed("no")
        self.assertEqual([e.kind for e in events], ["skipped"])
        self.assertIsNone(s.pending)

    def test_expiry_keeps_terms_listed_and_reasks_later(self):
        s = self.make()
        s.feed("next row")
        self.assertEqual(s.expire_prompt()[0].kind, "expired")
        self.assertEqual(s.pending, [("Light", "dim")])      # still in the list
        self.assertEqual(s.feed("yes"), [])                  # voice answer window closed
        self.assertEqual(s.feed("light dim next row")[-1].kind, "confirm")


# ---------------------------------------------------------------- window ----

class TestSortingWindow(unittest.TestCase):
    def setUp(self):
        self.vocab = Vocabulary()
        self.vocab.load({"Era": ["1980s", "1990s"], "Color": ["Black", "Navy Blue"]}, [])
        self.calls = []
        self.win = SortingWindow(self.vocab, lambda k, d, t: self.calls.append((k, d, t)))
        self.win.setup()

    def test_prompts_match_the_experience(self):
        self.assertEqual(question_for("Era", "90s"), "You said ‘90s’ — is that an Era?")
        self.assertEqual(question_for("Color", "teal"), "You said ‘teal’ — is that a Color?")
        self.assertEqual(question_for(None, "teal"), "You said ‘teal’ — which column is that?")

    def test_one_row_per_term_with_suggestion_selected(self):
        self.win.set_items([("Era", "90s"), (None, "teal")])
        self.assertEqual(len(self.win.rows), 2)
        era, teal = self.win.rows
        self.assertEqual(era.column, "Era")
        self.assertIsNone(teal.column)
        self.assertEqual(teal.combo.itemText(0), PLACEHOLDER)
        self.assertIn("is that an Era", era.prompt.text())

    def test_add_needs_a_column(self):
        self.win.set_items([(None, "teal")])
        row = self.win.rows[0]
        self.assertFalse(row.add_button.isEnabled())
        self.assertFalse(row.same_button.isEnabled())
        row.combo.setCurrentIndex(row.combo.findData("Color"))
        self.assertTrue(row.add_button.isEnabled())

    def test_add_reports_decision_with_capitalised_value(self):
        self.win.set_items([(None, "teal")])
        row = self.win.rows[0]
        row.combo.setCurrentIndex(row.combo.findData("Color"))
        row.add_button.click()
        key, decision, words = self.calls[0]
        self.assertEqual(key, (None, "teal"))
        self.assertEqual((decision.kind, decision.column, decision.value), ("add", "Color", "Teal"))

    def test_edited_words_are_reported(self):
        self.win.set_items([(None, "mainly teal")])
        row = self.win.rows[0]
        row.edit.setText("teal")
        row.combo.setCurrentIndex(row.combo.findData("Color"))
        row.add_button.click()
        self.assertEqual(self.calls[0][2], "teal")
        self.assertEqual(self.calls[0][1].value, "Teal")

    def test_same_as_menu_lists_existing_values_of_chosen_column(self):
        self.win.set_items([("Era", "90s")])
        row = self.win.rows[0]
        row._fill_same_menu()
        self.assertEqual([a.text() for a in row.same_menu.actions()], ["1980s", "1990s"])
        row.same_menu.actions()[1].trigger()
        decision = self.calls[0][1]
        self.assertEqual((decision.kind, decision.column, decision.value), ("alias", "Era", "1990s"))

    def test_ignore(self):
        self.win.set_items([(None, "teal")])
        self.win.rows[0].ignore_button.click()
        self.assertEqual(self.calls[0][1].kind, "ignore")

    def test_bulk_buttons(self):
        self.win.set_items([("Era", "90s"), (None, "teal"), ("Color", "red")])
        self.win.add_all()
        self.assertEqual([c[0] for c in self.calls], [("Era", "90s"), ("Color", "red")])
        self.calls.clear()
        self.win.ignore_all()
        self.assertEqual(len(self.calls), 3)

    def test_title_counts_and_empty_hides(self):
        self.win.set_items([("Era", "90s")])
        self.assertEqual(self.win.widget.windowTitle(), "Needs sorting (1)")
        self.win.show()
        self.win.set_items([])
        self.assertEqual(self.win.widget.windowTitle(), "Needs sorting")
        self.assertFalse(self.win.widget.isVisible())

    def test_removed_rows_leave_the_screen_immediately(self):
        self.win.set_items([("Era", "90s"), (None, "teal")])
        old = list(self.win.rows)
        self.win.set_items([(None, "teal")])
        self.assertTrue(all(r.isHidden() and r.parent() is None for r in old))

    def test_is_resizable_and_scrollable(self):
        self.win.set_items([(None, f"term{i}") for i in range(30)])
        self.assertTrue(self.win.scroll.widgetResizable())
        self.assertGreater(self.win.widget.minimumWidth(), 0)
        self.win.widget.resize(700, 500)
        self.assertEqual(self.win.widget.width(), 700)


class TestAppSorting(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.path = demo.build(self.dir / "demo.xlsx")
        self.quill = QuillApp(_app, Settings.load(self.dir / "cfg"), XlsxBridge(self.path),
                              listener_factory=lambda m, t, e: type("L", (), {
                                  "start": lambda s: None, "mute": lambda s: None,
                                  "unmute": lambda s: None})(),
                              model_finder=lambda c: self.dir,
                              speaker=type("S", (), {"enabled": True,
                                                     "say": lambda s, t, on_done=None, lead_in=0.0: on_done and on_done()})())
        self.quill.start()

    def tearDown(self):
        self._tmp.cleanup()

    def hear(self, *phrases):
        for p in phrases:
            self.quill.relay.transcript.emit(p)

    def test_terms_appear_in_window_and_button_after_row_ends(self):
        self.hear("start listening", SENTENCE)
        self.assertFalse(self.quill.window.sorting_button.isVisible() or self.quill.sorting.rows)
        self.hear("next row")
        self.assertEqual(len(self.quill.sorting.rows), 3)
        self.assertEqual(self.quill.window.badge_label.text(), "3")
        self.assertFalse(self.quill.window.sorting_button.isHidden())

    def test_deciding_in_the_window_updates_list_workbook_and_log(self):
        self.hear("start listening", SENTENCE, "next row")
        teal = next(r for r in self.quill.sorting.rows if r.key == (None, "teal"))
        teal.combo.setCurrentIndex(teal.combo.findData("Color"))
        teal.add_button.click()
        self.assertEqual(len(self.quill.sorting.rows), 2)
        self.assertEqual(self.quill.window.badge_label.text(), "2")
        self.assertIn("Added Teal to Color", self.quill.window.log.toPlainText())
        ws = openpyxl.load_workbook(self.path)["Inventory"]
        self.assertEqual(ws["E6"].value, "Teal")

    def test_resolving_the_last_one_hides_everything(self):
        self.hear("start listening", "zorblax", "next row")
        self.quill.sorting.ignore_all()
        self.assertEqual(self.quill.sorting.rows, [])
        self.assertTrue(self.quill.window.sorting_button.isHidden())

    def test_button_reopens_the_window(self):
        self.hear("start listening", "zorblax", "next row")
        self.quill.sorting.widget.hide()
        self.quill.window.sorting_button.click()
        self.assertTrue(self.quill.sorting.widget.isVisible())


if __name__ == "__main__":
    unittest.main()
