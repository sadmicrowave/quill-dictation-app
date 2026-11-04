"""Learning for amounts, and learning from delete-and-redo (a line deleted, then said again with its column's name)."""
import datetime as dt
import pathlib
import tempfile
import unittest

import openpyxl

from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import Controller
from quill.learning import LinkStore
from quill.parser.phrase_parser import parse
from quill.parser.vocab import Vocabulary
from tests.test_learning import TODAY, Case, whales


def shop(directory: pathlib.Path) -> pathlib.Path:
    """A sheet with two money columns (Price, Cost) and a date column: nothing here says which one "paid" means."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock"
    ws.append(["Item", "Price", "Cost", "Sale Date"])
    ws.append(["shirt", 20, 8, dt.date(2026, 1, 1)])
    for row in range(2, 30):
        ws.cell(row, 4).number_format = "yyyy-mm-dd"
    path = directory / "shop.xlsx"
    wb.save(path)
    return path


class AmountVocab(unittest.TestCase):
    def vocab(self, store=None):
        vocab = Vocabulary()
        vocab.load({}, ["Item", "Price", "Cost"])
        vocab.numeric_columns = ["Price", "Cost"]
        vocab.links = store
        return vocab

    def test_a_bare_amount_goes_to_the_first_money_column_without_links(self):
        self.assertEqual(list(parse("paid thirty dollars", self.vocab()).updates), ["Price"])

    def test_a_learned_word_chooses_among_all_amount_columns(self):
        store = LinkStore()
        store.teach("paid", "Cost")
        result = parse("paid thirty dollars", self.vocab(store))
        self.assertEqual(result.updates, {"Cost": 30.0})
        self.assertIn("'paid' used for Cost (learned)", result.assumptions)

    def test_a_named_column_beats_a_link(self):
        store = LinkStore()
        store.teach("paid", "Cost")
        self.assertEqual(list(parse("price thirty dollars paid", self.vocab(store)).updates), ["Price"])

    def test_the_amounts_own_words_are_never_context(self):
        result = parse("paid thirty dollars", self.vocab())
        self.assertEqual(result.context["Price"], ["paid"])                   # not "dollars", not "thirty"

    def test_a_link_to_a_column_that_is_not_an_amount_column_is_ignored(self):
        store = LinkStore()
        store.teach("paid", "Item")
        self.assertEqual(list(parse("paid thirty dollars", self.vocab(store)).updates), ["Price"])


class AmountCase(Case):
    def setUp(self):
        super().setUp()
        self.path = shop(self.dir)
        self.controller = Controller(XlsxBridge(self.path), self.settings, on_event=self.events.append, today=lambda: TODAY)
        self.controller.connect()
        self.controller.handle_transcript("start listening")


class TestAmountCorrection(AmountCase):
    def test_the_menu_offers_the_other_amount_columns(self):
        self.controller.handle_transcript("paid thirty dollars")
        self.assertEqual(self.controller.columns_for_change("Price"), ["Cost"])

    def test_changing_an_amount_asks_to_remember_and_two_corrections_teach_it(self):
        for round_ in (1, 2):
            self.controller.handle_transcript("paid thirty dollars")
            self.assertTrue(self.controller.change_field("Price", "Cost"))
            self.assertEqual(self.events[-1].kind, "learn_offer")
            self.controller.answer_learn_offer(True)
            kinds = [e.kind for e in self.events]
            self.controller.handle_transcript("delete row")
        self.assertIn("learned", kinds[-3:])
        self.controller.handle_transcript("paid thirty dollars")
        self.assertEqual(self.controller.session.record, {"Cost": 30.0})

    def test_a_date_does_not_go_to_an_amount_column(self):
        self.controller.handle_transcript("sold yesterday")
        self.assertEqual(self.controller.columns_for_change("Sale Date"), [])


class TestDeleteAndRedo(Case):
    def delete_line(self, column="Observation Date"):
        self.assertTrue(self.controller.remove_field(column))

    def test_saying_it_again_with_a_column_name_offers_the_lesson(self):
        self.controller.handle_transcript("spotted yesterday")
        self.delete_line()
        self.controller.handle_transcript("departure date yesterday")
        offer = [e for e in self.events if e.kind == "learn_offer"]
        self.assertEqual(offer[-1].detail, "Remember that 'spotted' means Departure Date?")

    def test_it_counts_like_any_other_correction(self):
        for _ in range(2):
            self.controller.handle_transcript("spotted yesterday")
            self.delete_line()
            self.controller.handle_transcript("departure date yesterday")
            self.controller.answer_learn_offer(True)
            last = self.events[-1].kind
            self.controller.handle_transcript("delete row")
        self.assertEqual(last, "learned")
        self.controller.handle_transcript("spotted today")
        self.assertEqual(list(self.controller.session.record), ["Departure Date"])

    def test_the_same_column_again_is_not_a_correction(self):
        self.controller.handle_transcript("spotted yesterday")
        self.delete_line()
        self.controller.handle_transcript("observation date yesterday")
        self.assertNotIn("learn_offer", [e.kind for e in self.events])

    def test_a_column_quill_guessed_is_not_a_correction(self):
        self.controller.handle_transcript("left yesterday")                      # placed by sheet order: Observation Date
        self.delete_line()
        self.controller.handle_transcript("humpback")
        self.controller.handle_transcript("spotted today")                       # a bare date again: Quill guesses
        self.assertNotIn("learn_offer", [e.kind for e in self.events])

    def test_a_different_sort_of_value_is_not_a_correction(self):
        self.controller.handle_transcript("spotted yesterday")
        self.delete_line()
        self.controller.handle_transcript("pod size four")
        self.assertNotIn("learn_offer", [e.kind for e in self.events])

    def test_it_only_waits_for_two_phrases(self):
        self.controller.handle_transcript("spotted yesterday")
        self.delete_line()
        self.controller.handle_transcript("humpback")
        self.controller.handle_transcript("pod size four")
        self.controller.handle_transcript("departure date yesterday")
        self.assertNotIn("learn_offer", [e.kind for e in self.events])

    def test_a_finished_row_forgets_the_deleted_line(self):
        self.controller.handle_transcript("spotted yesterday")
        self.delete_line()
        self.controller.handle_transcript("next row")
        self.controller.handle_transcript("departure date yesterday")
        self.assertNotIn("learn_offer", [e.kind for e in self.events])

    def test_a_line_with_no_words_around_it_teaches_nothing(self):
        self.controller.session.record["Observation Date"] = dt.date(2026, 1, 1)
        self.delete_line()
        self.controller.handle_transcript("departure date yesterday")
        self.assertNotIn("learn_offer", [e.kind for e in self.events])

    def test_with_asking_off_the_redo_is_counted_without_a_question(self):
        self.settings.preferences["learn_ask"] = False
        self.controller.handle_transcript("spotted yesterday")
        self.delete_line()
        self.controller.handle_transcript("departure date yesterday")
        self.assertNotIn("learn_offer", [e.kind for e in self.events])
        self.assertEqual(self.events[-1].kind, "learning")

    def test_a_word_of_the_sheet_is_never_the_lesson(self):
        self.controller.handle_transcript("spotted yesterday")
        self.controller.session.context["Observation Date"] = ["species"]
        self.delete_line()
        self.controller.handle_transcript("departure date yesterday")
        self.assertNotIn("learn_offer", [e.kind for e in self.events])

    def test_a_redo_of_an_amount(self):
        shop_path = shop(self.dir)
        controller = Controller(XlsxBridge(shop_path), self.settings, on_event=self.events.append, today=lambda: TODAY)
        controller.connect()
        controller.handle_transcript("start listening")
        controller.handle_transcript("paid thirty dollars")
        controller.remove_field("Price")
        controller.handle_transcript("cost thirty")
        self.assertEqual([e for e in self.events if e.kind == "learn_offer"][-1].detail,
                         "Remember that 'paid' means Cost?")


if __name__ == "__main__":
    unittest.main()
