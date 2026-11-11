"""Counter columns (an ID or record number that counts up by one): Quill continues the count unless the user says a value.

The numbers are offered to the row being built while listening, written only with the row, checked again just before they are written
(the file may have gained rows meanwhile), and never written over a cell the sheet already filled.
"""
import csv
import datetime as dt
import pathlib
import tempfile
import unittest

import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation

from quill.bridge.csv_bridge import CsvBridge
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import Controller
from quill.session import Event, Session
from tests.test_controller import FakeSpeaker


def make_book(path, ids=(1, 2, 3, 4, 5), id_header="ID"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock"
    ws.append([id_header, "Species", "Price", "Notes", "Qty"])
    for i, n in enumerate(ids):
        ws.append([n, "Fern", 10, "ok", 100 - i])                    # (Qty goes down: not a counter)
    dv = DataValidation(type="list", formula1='"Fern,Cactus,Orchid"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("B2:B60")
    wb.save(path)
    return path


class Case(unittest.TestCase):
    ids = (1, 2, 3, 4, 5)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.path = make_book(self.dir / "stock.xlsx", self.ids)
        self.events = []
        self.ctl = Controller(XlsxBridge(self.path), Settings.load(self.dir / "cfg"), FakeSpeaker(), on_event=self.events.append,
                              today=lambda: dt.date(2026, 10, 30))
        self.ctl.connect()

    def say(self, *phrases):
        for phrase in phrases:
            self.ctl.handle_transcript(phrase)

    def sheet(self):
        return openpyxl.load_workbook(self.path)["Stock"]

    def column(self, letter="A"):
        return [c.value for c in self.sheet()[letter]][1:]


class TestFindingTheCounters(Case):
    def test_only_the_column_that_counts_up_is_a_counter(self):
        self.assertEqual(list(self.ctl.counters), ["ID"])
        self.assertEqual(self.ctl.counters["ID"].next, 6)

    def test_a_list_a_note_a_price_and_a_countdown_are_not(self):
        self.assertNotIn("Species", self.ctl.counters)
        self.assertNotIn("Notes", self.ctl.counters)
        self.assertNotIn("Price", self.ctl.counters)
        self.assertNotIn("Qty", self.ctl.counters)

    def test_no_heading_is_looked_at(self):
        path = make_book(self.dir / "other.xlsx", id_header="Pottery Number")
        ctl = Controller(XlsxBridge(path), Settings.load(self.dir / "cfg2"), FakeSpeaker(), on_event=lambda e: None)
        ctl.connect()
        self.assertEqual(list(ctl.counters), ["Pottery Number"])

    def test_a_column_that_does_not_count_has_none(self):
        path = make_book(self.dir / "jumpy.xlsx", ids=(1, 2, 4, 7, 9))
        ctl = Controller(XlsxBridge(path), Settings.load(self.dir / "cfg3"), FakeSpeaker(), on_event=lambda e: None)
        ctl.connect()
        self.assertEqual(ctl.counters, {})

    def test_text_ids_with_a_prefix_and_padding(self):
        path = make_book(self.dir / "text.xlsx", ids=("A-0041", "A-0042", "A-0043"))
        ctl = Controller(XlsxBridge(path), Settings.load(self.dir / "cfg4"), FakeSpeaker(), on_event=lambda e: None)
        ctl.connect()
        self.assertEqual(ctl.counters["ID"].next, "A-0044")

    def test_the_tips_say_what_to_do(self):
        tips = self.ctl.column_tips()
        self.assertEqual(sorted(tips), ["ID", "Notes"])
        self.assertIn("1, 2, 3 → 6"[-4:], tips["ID"])                       # (the run it saw and what it continues it with)
        self.assertIn("3, 4, 5 → 6", tips["ID"])
        self.assertIn("end note", tips["Notes"])
        self.assertIn("next row", tips["Notes"])

    def test_the_sample_is_the_end_of_the_column(self):
        samples = self.ctl.bridge.column_samples(keep=3)
        self.assertEqual(samples["ID"], [3, 4, 5])
        self.assertEqual(samples["Species"], ["Fern"] * 3)


class TestTheRowBeingBuilt(Case):
    def test_nothing_is_offered_until_listening(self):
        self.assertEqual(self.ctl.session.auto, {})
        self.say("start listening")
        self.assertEqual(self.ctl.session.auto, {"ID": 6})

    def test_stopping_takes_the_offer_away(self):
        self.say("start listening", "stop listening")
        self.assertEqual(self.ctl.session.auto, {})

    def test_the_number_is_not_a_spoken_value(self):
        self.say("start listening", "species fern")
        self.assertEqual(self.ctl.session.record, {"Species": "Fern"})
        self.assertEqual(self.ctl.session.auto, {"ID": 6})

    def test_rows_get_one_number_each_in_a_row(self):
        self.say("start listening", "species fern", "next row", "species cactus", "next row", "species orchid", "next row")
        self.assertEqual(self.column(), [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(self.ctl.session.auto, {"ID": 9})

    def test_the_log_says_what_was_filled_in(self):
        self.say("start listening", "species fern", "next row")
        notes = [e.detail for e in self.events if e.detail.startswith("Assumed: ID")]
        self.assertEqual(notes, ["Assumed: ID = 6 (continues the column's numbering)"])

    def test_the_saved_row_event_carries_it_and_says_it_was_not_spoken(self):
        self.say("start listening", "species fern", "next row")
        saved = [e for e in self.events if e.kind == "committed"][0]
        self.assertEqual(saved.record, {"ID": 6, "Species": "Fern"})
        self.assertEqual(saved.auto, ["ID"])

    def test_a_value_the_user_says_is_used_instead(self):
        self.say("start listening", "id fifty seven species fern", "next row")
        self.assertEqual(self.column()[-1], 57)
        saved = [e for e in self.events if e.kind == "committed"][0]
        self.assertEqual(saved.auto, [])
        self.assertFalse([e for e in self.events if e.detail.startswith("Assumed: ID")])

    def test_a_row_with_nothing_said_is_not_saved_for_the_number_alone(self):
        self.say("start listening", "next row")
        self.assertEqual(self.column(), [1, 2, 3, 4, 5])
        self.assertIn("Nothing to save yet", [e.detail for e in self.events])

    def test_removing_the_line_leaves_that_row_without_it_and_the_next_row_gets_one(self):
        self.say("start listening", "species fern")
        self.assertTrue(self.ctl.remove_field("ID"))
        self.say("next row", "species cactus", "next row")
        self.assertEqual(self.column()[-2:], [None, 6])                     # (the first row went without; the counter was not moved)

    def test_removing_a_column_that_is_neither_said_nor_filled_in_is_refused(self):
        self.say("start listening", "species fern")
        self.assertFalse(self.ctl.remove_field("Price"))

    def test_rows_added_meanwhile_are_not_numbered_twice(self):
        self.say("start listening", "species fern")
        self.ctl.bridge.append_row("Stock", {"ID": 6, "Species": "Cactus"})      # (somebody else added a row while this one was being dictated)
        self.say("next row")
        self.assertEqual(self.column(), [1, 2, 3, 4, 5, 6, 7])

    def test_a_column_that_stopped_counting_meanwhile_is_left_empty(self):
        self.say("start listening", "species fern")
        self.ctl.bridge.append_row("Stock", {"ID": 99, "Species": "Cactus"})
        self.say("next row")
        self.assertEqual(self.column(), [1, 2, 3, 4, 5, 99, None])

    def test_a_turn_that_adds_to_a_row_has_no_number_to_give(self):
        self.ctl.set_turn_mode("append")
        self.say("start listening")
        self.assertEqual(self.ctl.session.auto, {})

    def test_turning_append_on_while_listening_takes_the_offer_away_and_off_brings_it_back(self):
        self.say("start listening")
        self.ctl.set_turn_mode("append")
        self.assertEqual(self.ctl.session.auto, {})
        self.ctl.set_turn_mode("next_row")
        self.ctl.refresh_counters()
        self.assertEqual(self.ctl.session.auto, {"ID": 6})

    def test_a_failed_write_keeps_what_was_said_and_not_what_quill_filled_in(self):
        session = Session(self.ctl.vocab, self.ctl.session.matcher)
        session.restore({"ID": 6, "Species": "Fern"}, ["ID"])
        self.assertEqual(session.record, {"Species": "Fern"})


class TestACellTheSheetFilled(Case):
    def test_a_formula_the_sheet_put_in_the_new_rows_cell_is_left_alone_and_the_row_still_found(self):
        wb = openpyxl.load_workbook(self.path)
        wb["Stock"]["A7"] = "=ROW()-1"                                      # (as a sheet that fills its counter down for new rows)
        wb.save(self.path)
        ctl = Controller(XlsxBridge(self.path), Settings.load(self.dir / "cfgf"), FakeSpeaker(), on_event=lambda e: None)
        ctl.connect()
        self.assertEqual(ctl.counters["ID"].next, 6)                       # (a formula is not a value that counts: the numbers before it are)
        ctl.handle_transcript("start listening")
        ctl.handle_transcript("species fern")
        ctl.handle_transcript("next row")
        sheet = openpyxl.load_workbook(self.path)["Stock"]
        self.assertEqual((sheet["A7"].value, sheet["B7"].value), ("=ROW()-1", "Fern"))

    def test_a_sheet_that_counts_with_formulas_has_no_counter(self):
        wb = openpyxl.load_workbook(self.path)
        sheet = wb["Stock"]
        for r in range(2, 7):
            sheet.cell(r, 1, "=ROW()-1")
        wb.save(self.path)
        ctl = Controller(XlsxBridge(self.path), Settings.load(self.dir / "cfgg"), FakeSpeaker(), on_event=lambda e: None)
        ctl.connect()
        self.assertEqual(ctl.counters, {})


class TestOtherLayouts(Case):
    def test_headings_that_run_down_have_no_counters(self):
        self.ctl.settings.preferences["vertical_layout"] = True
        self.ctl.reload_vocab()
        self.assertEqual(self.ctl.counters, {})

    def test_a_csv_counts_too(self):
        path = self.dir / "stock.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["No", "Item"], [1, "a"], [2, "b"], [3, "c"]])
        ctl = Controller(CsvBridge(path), Settings.load(self.dir / "cfg5"), FakeSpeaker(), on_event=lambda e: None)
        ctl.connect()
        self.assertEqual(ctl.counters["No"].next, "4")                             # (the cells of a csv are text, and so is the number)
        ctl.handle_transcript("start listening")
        self.assertEqual(ctl.session.auto, {"No": "4"})
        ctl.handle_transcript("item b")
        ctl.handle_transcript("next row")
        self.assertEqual(path.read_text(encoding="utf-8").splitlines()[-1], "4,b")


class TestSessionKeepsItApart(unittest.TestCase):
    def test_what_is_said_wins_and_the_offer_is_cleared_with_the_row(self):
        from quill.parser.commands import Action, CommandMatcher
        from quill.parser.vocab import Vocabulary
        vocab = Vocabulary()
        vocab.load({}, ["ID", "Item"])
        session = Session(vocab, CommandMatcher({"start listening": Action.START_LISTENING, "next row": Action.NEXT_ROW}))
        session.feed("start listening")
        session.auto = {"ID": 6, "Item": "x"}
        events = session.feed("item bolt") + session.feed("next row")
        saved = [e for e in events if e.kind == "committed"][0]
        self.assertEqual(saved.record, {"ID": 6, "Item": "bolt"})
        self.assertEqual(saved.auto, ["ID"])
        self.assertEqual(session.auto, {})


if __name__ == "__main__":
    unittest.main()
