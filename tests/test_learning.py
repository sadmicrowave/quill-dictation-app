"""Learned links: words the user taught Quill to read as a column (store, speech, correction menu, settings list)."""
import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

import openpyxl
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QDialog

from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import Controller
from quill.learning import MAX_LINKS, LinkStore, link_word
from quill.parser.phrase_parser import parse
from quill.parser.vocab import Vocabulary
from quill.ui.confirm import ConfirmDialog
from quill.ui.learned_page import LearnedWordsPanel
from quill.ui.main_widgets import RowTable

_app = QApplication.instance() or QApplication([])
TODAY = dt.date(2026, 11, 4)


def whales(directory: pathlib.Path) -> pathlib.Path:
    """A sheet with nothing to do with inventory: two date columns, none of whose headings say "spotted" or "left"."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sightings"
    ws.append(["Species", "Observation Date", "Departure Date", "Pod Size"])
    ws.append(["humpback", dt.date(2026, 1, 1), dt.date(2026, 1, 3), 4])
    for row in range(2, 40):
        for col in (2, 3):
            ws.cell(row, col).number_format = "yyyy-mm-dd"
    path = directory / "whales.xlsx"
    wb.save(path)
    return path


class Dir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class TestStore(unittest.TestCase):
    def test_starts_empty(self):
        self.assertEqual(len(LinkStore()), 0)

    def test_a_correction_counts_and_takes_effect_after_enough_of_them(self):
        store = LinkStore()
        store.observe("spotted", "Observation Date", "/a.xlsx", "a.xlsx")
        self.assertIsNone(store.choose(["spotted"], ["Observation Date"], learn_after=2))
        store.observe("spotted", "Observation Date", "/a.xlsx", "a.xlsx")
        self.assertEqual(store.choose(["spotted"], ["Observation Date"], learn_after=2), ("Observation Date", "spotted"))

    def test_the_setting_decides_how_many(self):
        store = LinkStore()
        store.observe("spotted", "Observation Date")
        self.assertIsNotNone(store.choose(["spotted"], ["Observation Date"], learn_after=1))
        self.assertIsNone(store.choose(["spotted"], ["Observation Date"], learn_after=3))

    def test_a_taught_word_is_used_at_once(self):
        store = LinkStore()
        store.teach("spotted", "Observation Date")
        self.assertIsNotNone(store.choose(["spotted"], ["Observation Date"], learn_after=5))

    def test_forms_of_a_word_are_one_link(self):
        store = LinkStore()
        store.teach("selling", "Sale Date")
        self.assertEqual(store.choose(["sells"], ["Sale Date"], 2)[0], "Sale Date")

    def test_nearest_word_wins_and_only_listed_columns_are_considered(self):
        store = LinkStore()
        store.teach("left", "Departure Date")
        store.teach("spotted", "Observation Date")
        self.assertEqual(store.choose(["spotted", "left"], ["Observation Date", "Departure Date"], 2)[0], "Observation Date")
        self.assertIsNone(store.choose(["left"], ["Observation Date"], 2))              # (a link only chooses among columns that fit)

    def test_a_changed_mind_lowers_the_old_link_and_drops_it_at_zero(self):
        store = LinkStore()
        store.observe("sighted", "Observation Date")
        store.observe("sighted", "Departure Date")
        self.assertIsNone(store.get("sighted", "Observation Date"))
        self.assertEqual(store.get("sighted", "Departure Date").count, 1)

    def test_words_that_cannot_be_links(self):
        for word in ("it", "12", "the", "", "two words", "seven", "was"):
            self.assertIsNone(link_word(word), word)
        self.assertIsNone(LinkStore().observe("it", "Date"))

    def test_the_store_is_capped_and_the_least_recent_go_first(self):
        store = LinkStore()
        names = ["qx" + "".join(chr(97 + (n // 26 ** k) % 26) for k in range(3)) for n in range(MAX_LINKS + 5)]
        for name in names:
            store.teach(name, "Date")
        self.assertEqual(len(store), MAX_LINKS)
        self.assertIsNone(store.get(names[0], "Date"))
        self.assertIsNotNone(store.get(names[-1], "Date"))

    def test_files_are_remembered_and_forgotten(self):
        store = LinkStore()
        store.teach("spotted", "Observation Date", "/a.xlsx", "a.xlsx")
        store.observe("spotted", "Observation Date", "/b.xlsx", "b.xlsx")
        link = store.get("spotted", "Observation Date")
        self.assertEqual([s.name for s in link.sources], ["a.xlsx", "b.xlsx"])
        self.assertEqual(len(store.for_file("/b.xlsx")), 1)
        store.forget_file("/a.xlsx")
        self.assertEqual([s.name for s in store.get("spotted", "Observation Date").sources], ["b.xlsx"])
        store.forget_file("/b.xlsx")
        self.assertEqual(len(store), 0)

    def test_for_file_includes_words_for_columns_the_file_has(self):
        store = LinkStore()
        store.teach("sold", "Sale Date", "/other.xlsx", "other.xlsx")
        self.assertEqual(store.for_file("/a.xlsx"), [])
        self.assertEqual(len(store.for_file("/a.xlsx", ["Sale Date"])), 1)

    def test_round_trip_and_damaged_data(self):
        store = LinkStore()
        store.teach("spotted", "Observation Date", "/a.xlsx", "a.xlsx")
        again = LinkStore.from_list(store.to_list())
        self.assertEqual(again.get("spotted", "Observation Date").shown, "spotted")
        self.assertTrue(again.get("spotted", "Observation Date").taught)
        for junk in (None, "x", [1, {"word": 5}, {"word": "a", "column": ""}, {"word": "spott", "column": "D", "sources": "no"}]):
            LinkStore.from_list(junk)                                              # never raises


class TestSettings(Dir):
    def test_links_survive_a_restart_and_the_two_preferences_are_kept_in_range(self):
        settings = Settings.load(self.dir)
        settings.links.teach("spotted", "Observation Date", "/a.xlsx", "a.xlsx")
        settings.preferences["learn_after"] = 4
        settings.preferences["learn_ask"] = False
        settings.save()
        again = Settings.load(self.dir)
        self.assertIsNotNone(again.links.get("spotted", "Observation Date"))
        self.assertEqual((again.preferences["learn_after"], again.preferences["learn_ask"]), (4, False))
        again.preferences["learn_after"] = 99
        again.save()
        self.assertEqual(Settings.load(self.dir).preferences["learn_after"], 5)

    def test_defaults(self):
        settings = Settings.load(self.dir)
        self.assertEqual((settings.preferences["learn_after"], settings.preferences["learn_ask"]), (2, True))


class TestUsingLinks(unittest.TestCase):
    def vocab(self, store=None):
        vocab = Vocabulary()
        vocab.load({}, ["Species", "Observation Date", "Departure Date"])
        vocab.date_columns = ["Observation Date", "Departure Date"]
        vocab.links = store
        return vocab

    def test_without_links_sheet_order_decides(self):
        result = parse("left today", self.vocab(), TODAY)
        self.assertEqual(list(result.updates), ["Observation Date"])

    def test_a_learned_link_wins_and_the_log_says_so(self):
        store = LinkStore()
        store.teach("left", "Departure Date")
        result = parse("left today", self.vocab(store), TODAY)
        self.assertEqual(list(result.updates), ["Departure Date"])
        self.assertIn("'left' used for Departure Date (learned)", result.assumptions)

    def test_a_named_column_beats_a_link(self):
        store = LinkStore()
        store.teach("left", "Departure Date")
        result = parse("left observation date today", self.vocab(store), TODAY)
        self.assertEqual(list(result.updates), ["Observation Date"])

    def test_words_around_the_date_are_kept_for_learning(self):
        result = parse("spotted yesterday", self.vocab(), TODAY)
        self.assertEqual(result.context["Observation Date"][0], "spotted")


class Case(Dir):
    def setUp(self):
        super().setUp()
        self.path = whales(self.dir)
        self.settings = Settings.load(self.dir / "cfg")
        self.events = []
        self.controller = Controller(XlsxBridge(self.path), self.settings, on_event=self.events.append, today=lambda: TODAY)
        self.controller.connect()
        self.controller.handle_transcript("start listening")

    def kinds(self):
        return [e.kind for e in self.events]


class TestSpokenTeaching(Case):
    def test_word_means_column(self):
        self.controller.handle_transcript("left means departure date")
        self.assertEqual(self.events[-1].kind, "learned")
        self.controller.handle_transcript("left today")
        self.assertEqual(list(self.controller.session.record), ["Departure Date"])

    def test_it_is_saved_with_the_file_it_was_taught_in(self):
        self.controller.handle_transcript("left means departure date")
        link = Settings.load(self.dir / "cfg").links.get("left", "Departure Date")
        self.assertEqual([s.name for s in link.sources], ["whales.xlsx"])

    def test_only_the_exact_phrase_is_a_lesson(self):
        self.controller.handle_transcript("humpback means departure date today")
        self.assertNotIn("learned", self.kinds())
        self.assertEqual(len(self.settings.links), 0)

    def test_a_word_of_the_sheet_a_number_or_everyday_word_is_refused(self):
        for phrase in ("species means departure date", "it means departure date", "seven means departure date"):
            self.controller.handle_transcript(phrase)
            self.assertEqual(self.events[-1].kind, "ignored", phrase)
        self.assertEqual(len(self.settings.links), 0)

    def test_not_while_stopped(self):
        self.controller.handle_transcript("stop listening")
        self.controller.handle_transcript("left means departure date")
        self.assertEqual(len(self.settings.links), 0)


class TestChangingAColumn(Case):
    def say_and_change(self):
        self.controller.handle_transcript("spotted yesterday")
        return self.controller.change_field("Observation Date", "Departure Date")

    def test_the_menu_lists_only_other_columns_that_fit(self):
        self.controller.handle_transcript("spotted yesterday")
        self.assertEqual(self.controller.columns_for_change("Observation Date"), ["Departure Date"])
        self.assertEqual(self.controller.columns_for_change("Nothing"), [])

    def test_the_value_moves_and_a_value_already_there_swaps(self):
        self.controller.handle_transcript("spotted yesterday")
        self.controller.handle_transcript("left today")
        self.assertEqual(self.controller.session.record["Observation Date"], dt.date(2026, 11, 3))
        self.assertTrue(self.controller.change_field("Observation Date", "Departure Date"))
        record = self.controller.session.record
        self.assertEqual((record["Departure Date"], record["Observation Date"]), (dt.date(2026, 11, 3), dt.date(2026, 11, 4)))

    def test_a_column_that_does_not_fit_is_refused(self):
        self.controller.handle_transcript("spotted yesterday")
        self.assertFalse(self.controller.change_field("Observation Date", "Species"))
        self.assertIn("Observation Date", self.controller.session.record)

    def test_asks_to_remember_and_yes_counts_it_but_needs_two(self):
        self.say_and_change()
        offer = [e for e in self.events if e.kind == "learn_offer"][-1]
        self.assertEqual(offer.detail, "Remember that 'spotted' means Departure Date?")
        self.controller.answer_learn_offer(True)
        self.assertEqual(self.events[-1].kind, "learning")
        self.assertIn("1 of 2", self.events[-1].detail)
        self.controller.handle_transcript("delete row")
        self.say_and_change()
        self.controller.answer_learn_offer(True)
        self.assertEqual(self.events[-1].kind, "learned")
        self.controller.handle_transcript("delete row")
        self.controller.handle_transcript("spotted yesterday")
        self.assertEqual(list(self.controller.session.record), ["Departure Date"])

    def test_the_setting_changes_how_many(self):
        self.settings.preferences["learn_after"] = 1
        self.controller.apply_settings()
        self.say_and_change()
        self.controller.answer_learn_offer(True)
        self.assertEqual(self.events[-1].kind, "learned")

    def test_no_teaches_nothing(self):
        self.say_and_change()
        self.controller.answer_learn_offer(False)
        self.assertEqual(self.events[-1].kind, "learn_declined")
        self.assertEqual(len(self.settings.links), 0)

    def test_a_spoken_yes_answers_the_question(self):
        self.say_and_change()
        self.controller.handle_transcript("yes")
        self.assertEqual(self.events[-1].kind, "learning")
        self.assertIsNone(self.controller.learn_offer)

    def test_no_answer_in_time_teaches_nothing(self):
        self.say_and_change()
        self.controller.expire_learn_offer()
        self.controller.answer_learn_offer(True)
        self.assertEqual(len(self.settings.links), 0)

    def test_with_asking_off_every_change_is_counted_without_a_question(self):
        self.settings.preferences["learn_ask"] = False
        self.say_and_change()
        self.assertNotIn("learn_offer", self.kinds())
        self.assertEqual(self.events[-1].kind, "learning")

    def test_it_is_saved_to_the_settings_file(self):
        self.say_and_change()
        self.controller.answer_learn_offer(True)
        self.assertEqual(Settings.load(self.dir / "cfg").links.get("spotted", "Departure Date").count, 1)

    def test_a_word_of_the_sheet_is_never_offered(self):
        self.controller.handle_transcript("humpback sighted yesterday")        # "humpback" is not in a list here, "sighted" is the word
        self.controller.session.context["Observation Date"] = ["species", "sighted"]
        self.controller.change_field("Observation Date", "Departure Date")
        self.assertEqual([e.values[0][0] for e in self.events if e.kind == "learn_offer"][-1], "sighted")

    def test_a_line_with_no_words_around_it_changes_without_a_question(self):
        self.controller.session.record["Observation Date"] = dt.date(2026, 1, 1)
        self.controller.change_field("Observation Date", "Departure Date")
        self.assertNotIn("learn_offer", self.kinds())


class TestRowTable(unittest.TestCase):
    def table(self):
        table = RowTable(2, 2)
        table.resize(300, 100)
        for r, (name, value) in enumerate((("Observation Date", "2026-11-03"), ("Species", "humpback"))):
            from PySide6.QtWidgets import QTableWidgetItem
            table.setItem(r, 0, QTableWidgetItem(name))
            table.setItem(r, 1, QTableWidgetItem(value))
        table.set_changeable({"Observation Date"})
        return table

    def test_clicking_the_name_of_a_changeable_line_asks_for_the_menu(self):
        table = self.table()
        got = []
        table.row_change_requested.connect(lambda column, where: got.append(column))
        point = QPoint(20, table.rowViewportPosition(0) + 5)
        self.assertTrue(table._name_hit(0, point))
        self.assertFalse(table._name_hit(1, QPoint(20, table.rowViewportPosition(1) + 5)))
        self.assertFalse(table._name_hit(0, QPoint(table.columnWidth(0) + 20, 5)))


class TestConfirmDialog(unittest.TestCase):
    def test_cancel_is_the_default_and_the_action_is_red(self):
        dialog = ConfirmDialog(None, "Forget 3 learned words?", "This can't be undone.", "Forget 3 Words")
        self.assertTrue(dialog.cancel_button.isDefault())
        self.assertFalse(dialog.action_button.isDefault())
        self.assertTrue(dialog.action_button.property("danger"))
        dialog.action_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_cancel_backs_out(self):
        dialog = ConfirmDialog(None, "t", "m", "Do it")
        dialog.cancel_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)


class TestLearnedWordsList(unittest.TestCase):
    def setUp(self):
        self.store = LinkStore()
        self.store.teach("spotted", "Observation Date", "/a/whales.xlsx", "whales.xlsx")
        self.store.teach("left", "Departure Date", "/a/whales.xlsx", "whales.xlsx")
        self.store.teach("sold", "Sale Date", "/a/apparel.xlsx", "apparel.xlsx")
        self.active = ["/a/whales.xlsx", "whales.xlsx", ["Observation Date", "Departure Date"]]
        self.panel = LearnedWordsPanel(self.store, lambda: 2, lambda: tuple(self.active))

    def words(self):
        out = []
        for i in range(self.panel.tree.topLevelItemCount()):
            top = self.panel.tree.topLevelItem(i)
            out += [top.child(j).text(0) for j in range(top.childCount())] or [top.text(0)]
        return sorted(out)

    def test_grouped_by_file_by_default_and_other_groupings(self):
        self.assertEqual(self.panel.tree.topLevelItemCount(), 2)
        self.panel.grouping.setCurrentIndex(self.panel.grouping.findData("none"))
        self.assertEqual(self.words(), ["left", "sold", "spotted"])
        self.panel.grouping.setCurrentIndex(self.panel.grouping.findData("column"))
        self.assertEqual(self.panel.tree.topLevelItemCount(), 3)

    def test_search_matches_word_column_and_file(self):
        for query, expected in (("spot", ["spotted"]), ("sale", ["sold"]), ("whales", ["left", "spotted"]), ("zzz", [])):
            self.panel.search.setText(query)
            self.assertEqual(self.words() if expected else [], expected, query)
        self.assertEqual(self.panel.empty.text(), "No learned words match.")

    def test_this_file_shows_its_words(self):
        self.panel.show_this_file()
        self.assertEqual(self.words(), ["left", "spotted"])

    def test_empty_state(self):
        panel = LearnedWordsPanel(LinkStore(), lambda: 2, lambda: ("", "", []))
        self.assertFalse(panel.empty.isHidden())
        self.assertFalse(panel.forget_all_button.isEnabled())

    def test_status_follows_the_setting(self):
        store = LinkStore()
        store.observe("sighted", "Observation Date")
        shown = []
        panel = LearnedWordsPanel(store, lambda: shown[-1] if shown else 2, lambda: ("", "", []))
        panel.grouping.setCurrentIndex(panel.grouping.findData("none"))
        self.assertEqual(panel.tree.topLevelItem(0).text(3), "Learning (1 of 2)")
        shown.append(1)
        panel.refresh()
        self.assertEqual(panel.tree.topLevelItem(0).text(3), "In use")

    def test_forget_all_shown_asks_first_and_cancel_keeps_everything(self):
        with mock.patch("quill.ui.learned_page.confirm", return_value=False) as ask:
            self.panel.forget_shown()
        ask.assert_called_once()
        self.assertEqual(len(self.store), 3)

    def test_forget_all_shown_removes_only_what_is_shown(self):
        self.panel.show_this_file()
        saved = []
        self.panel.changed.connect(lambda: saved.append(True))
        with mock.patch("quill.ui.learned_page.confirm", return_value=True) as ask:
            self.panel.forget_shown()
        self.assertIn("2 learned words", ask.call_args.args[1])
        self.assertIn("current search and filter", ask.call_args.args[2])
        self.assertEqual([l.shown for l in self.store.links()], ["sold"])
        self.assertTrue(saved)

    def test_forgetting_several_selected_asks_but_one_does_not(self):
        self.panel.grouping.setCurrentIndex(self.panel.grouping.findData("none"))
        self.panel.tree.topLevelItem(0).setSelected(True)
        with mock.patch("quill.ui.learned_page.confirm") as ask:
            self.panel.forget_selected()
        ask.assert_not_called()
        self.assertEqual(len(self.store), 2)
        self.panel.tree.selectAll()
        with mock.patch("quill.ui.learned_page.confirm", return_value=True) as ask:
            self.panel.forget_selected()
        ask.assert_called_once()
        self.assertEqual(len(self.store), 0)


if __name__ == "__main__":
    unittest.main()
