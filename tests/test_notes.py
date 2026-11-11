"""Notes and descriptions: a long note is dictated across pauses and stays open until it is closed.

A notes-style column (Notes, Comments, Description, Remarks, Details) keeps every word that follows, to the end of the phrase and
through the phrases after it (the recogniser ends a phrase at every pause). Column names, list values, numbers and dates inside it
are ordinary words. It ends on ``end note``, ``next row`` (or any other command), or a phrase that begins with another column's name.
The saved note gets a capital and a full stop.
"""
import datetime as dt
import pathlib
import tempfile
import unittest

import openpyxl

from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import Controller
from quill.parser.commands import Action, CommandMatcher
from quill.parser.phrase_parser import finish_note
from quill.parser.vocab import Vocabulary
from quill.session import Session
from tests.fixtures import make_workbook
from tests.test_controller import FakeSpeaker

LISTS = {"Species": ["Fern", "Cactus"], "Light": ["Low", "Bright"]}
HEADERS = ["Species", "Light", "Price", "Acquired", "Notes", "Description"]
KEYWORDS = {"start listening": Action.START_LISTENING, "stop listening": Action.STOP_LISTENING, "next row": Action.NEXT_ROW,
            "cancel": Action.DELETE_ROW, "end note": Action.END_NOTE, "end notes": Action.END_NOTE}


def listening():
    vocab = Vocabulary()
    vocab.load(LISTS, HEADERS)
    session = Session(vocab, CommandMatcher(KEYWORDS), today=lambda: dt.date(2026, 10, 30))
    session.feed("start listening")
    return session


def say(session, *phrases):
    events = []
    for phrase in phrases:
        events += session.feed(phrase)
    return events


class TestOneLongPhrase(unittest.TestCase):
    def test_a_column_name_inside_the_note_does_not_cut_it(self):
        s = listening()
        say(s, "species fern notes needs repotting soon and keep it out of bright light")
        self.assertEqual(s.record, {"Species": "Fern", "Notes": "needs repotting soon and keep it out of bright light"})
        self.assertFalse(s.pending)

    def test_a_note_that_begins_with_a_column_name_is_still_the_note(self):
        s = listening()
        say(s, "notes the price went up last spring and the buyer was happy")
        self.assertEqual(s.record, {"Notes": "the price went up last spring and the buyer was happy"})
        self.assertFalse(s.pending)                                            # (none of its words is sent to be sorted)
        self.assertFalse(s.pool)

    def test_a_date_inside_the_note_stays_in_the_note(self):
        s = listening()
        say(s, "notes sold on march 3 2025 to a neighbour")
        self.assertEqual(s.record, {"Notes": "sold on march 3 2025 to a neighbour"})

    def test_the_other_notes_style_headings_work_the_same(self):
        s = listening()
        say(s, "description a tall plant with long leaves and a price tag")
        self.assertEqual(s.record, {"Description": "a tall plant with long leaves and a price tag"})
        self.assertEqual(s.open_note, "Description")


class TestAcrossPauses(unittest.TestCase):
    def test_the_next_phrase_goes_on_with_the_note(self):
        s = listening()
        say(s, "species fern notes needs repotting soon", "and keep it away from the cold window")
        self.assertEqual(s.record, {"Species": "Fern", "Notes": "needs repotting soon and keep it away from the cold window"})
        self.assertFalse(s.pending)

    def test_the_note_can_be_started_and_the_words_come_after_a_pause(self):
        s = listening()
        say(s, "notes", "needs repotting", "and water weekly")
        self.assertEqual(s.record, {"Notes": "needs repotting and water weekly"})

    def test_a_list_value_after_a_pause_is_a_word_of_the_note(self):
        s = listening()
        say(s, "notes keep it in", "bright light is bad")
        self.assertEqual(s.record, {"Notes": "keep it in bright light is bad"})

    def test_a_phrase_that_begins_with_the_notes_own_name_goes_on_with_it(self):
        s = listening()
        say(s, "notes needs repotting", "notes and water weekly")
        self.assertEqual(s.record, {"Notes": "needs repotting and water weekly"})

    def test_every_step_is_reported_with_the_whole_note_so_far(self):
        s = listening()
        events = say(s, "notes needs repotting", "and water weekly")
        self.assertEqual([e.detail for e in events], ["Notes=needs repotting", "Notes=needs repotting and water weekly"])


class TestEndingTheNote(unittest.TestCase):
    def test_end_note_closes_it_and_the_words_after_it_are_ordinary_again(self):
        s = listening()
        say(s, "notes needs repotting end note light bright")
        self.assertEqual(s.record, {"Notes": "Needs repotting.", "Light": "Bright"})
        self.assertIsNone(s.open_note)

    def test_end_note_said_on_its_own_after_a_pause(self):
        s = listening()
        events = say(s, "notes needs repotting", "end note", "light bright")
        self.assertEqual(s.record, {"Notes": "Needs repotting.", "Light": "Bright"})
        self.assertIn("Notes=Needs repotting.", [e.detail for e in events])      # the log shows what the cell holds now

    def test_end_notes_is_the_same(self):
        s = listening()
        say(s, "notes needs repotting", "end notes")
        self.assertEqual(s.record["Notes"], "Needs repotting.")

    def test_end_note_with_no_note_open_says_so(self):
        s = listening()
        events = say(s, "end note")
        self.assertEqual([(e.kind, e.detail) for e in events], [("ignored", "No note is open")])
        say(s, "notes done", "end note")
        self.assertEqual([(e.kind, e.detail) for e in say(s, "end note")], [("ignored", "No note is open")])   # (already closed)

    def test_end_note_while_not_listening_is_ignored(self):
        s = listening()
        say(s, "notes keep", "stop listening")
        events = say(s, "end note")
        self.assertEqual(events[0].kind, "ignored")

    def test_a_phrase_that_begins_with_another_column_name_closes_the_note_and_is_read(self):
        s = listening()
        say(s, "notes needs repotting", "light bright")
        self.assertEqual(s.record, {"Notes": "Needs repotting.", "Light": "Bright"})
        self.assertIsNone(s.open_note)
        say(s, "and more words")                                               # (the note is closed: these are not part of it)
        self.assertEqual(s.record["Notes"], "Needs repotting.")

    def test_a_second_note_column_closes_the_first(self):
        s = listening()
        say(s, "notes needs repotting", "description a tall fern")
        self.assertEqual(s.record, {"Notes": "Needs repotting.", "Description": "a tall fern"})
        self.assertEqual(s.open_note, "Description")

    def test_next_row_closes_the_note_and_the_row_is_saved_with_it(self):
        s = listening()
        events = say(s, "species fern notes needs repotting", "and water weekly", "next row")
        row = [e for e in events if e.kind == "committed"][0].record
        self.assertEqual(row, {"Species": "Fern", "Notes": "Needs repotting and water weekly."})
        self.assertIsNone(s.open_note)

    def test_the_next_row_does_not_inherit_the_note(self):
        s = listening()
        say(s, "notes first row text", "next row", "species cactus")
        self.assertEqual(s.record, {"Species": "Cactus"})

    def test_delete_row_throws_the_note_away_and_closes_it(self):
        s = listening()
        say(s, "notes some words", "cancel", "and more words")
        self.assertEqual(s.record, {})
        self.assertIsNone(s.open_note)

    def test_stopping_listening_closes_the_note(self):
        s = listening()
        say(s, "notes needs repotting", "stop listening")
        self.assertEqual(s.record["Notes"], "Needs repotting.")
        self.assertIsNone(s.open_note)
        say(s, "start listening", "and water weekly")                          # (a new start does not reopen it)
        self.assertEqual(s.record["Notes"], "Needs repotting.")

    def test_taking_the_note_off_the_row_closes_it(self):
        s = listening()
        say(s, "notes needs repotting")
        s.record.pop("Notes")
        s.open_note = None
        say(s, "light bright")
        self.assertEqual(s.record, {"Light": "Bright"})


class TestFinishingTheNote(unittest.TestCase):
    def test_a_capital_and_a_full_stop(self):
        self.assertEqual(finish_note("needs repotting soon"), "Needs repotting soon.")

    def test_a_stop_already_there_is_kept_once(self):
        for text in ("Done.", "really?", "stop!"):
            self.assertEqual(finish_note(text)[-2:], text[-2:])
            self.assertEqual(finish_note(text).count(text[-1]), 1)

    def test_nothing_is_added_to_an_empty_note_and_spaces_are_trimmed(self):
        self.assertEqual(finish_note("   "), "")
        self.assertEqual(finish_note("  ok "), "Ok.")

    def test_a_note_opened_and_never_filled_leaves_the_cell_empty(self):
        s = listening()
        say(s, "notes", "next row")
        self.assertEqual(s.record, {})


class TestWhatIsHeardWhileSpeaking(unittest.TestCase):
    """The row grid shows the words of the phrase still being spoken: with a note open they go into the note."""

    def test_words_go_on_with_the_open_note_unless_they_begin_with_another_column(self):
        s = listening()
        say(s, "notes needs repotting")
        self.assertEqual(s.note_words(["and", "water"]), ["and", "water"])
        self.assertEqual(s.note_words(["bright", "light"]), ["bright", "light"])
        self.assertEqual(s.note_words(["notes", "and", "water"]), ["and", "water"])
        self.assertIsNone(s.note_words(["light", "bright"]))
        self.assertIsNone(s.note_words([]))

    def test_with_no_note_open_nothing_is_a_note_word(self):
        self.assertIsNone(listening().note_words(["and", "water"]))


class TestTheKeyword(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)

    def test_it_ships_as_a_default(self):
        keywords = Settings.defaults().keywords
        self.assertEqual(keywords["end note"], Action.END_NOTE)
        self.assertEqual(keywords["end notes"], Action.END_NOTE)

    def test_a_keyword_file_saved_before_it_existed_gains_it(self):
        (self.dir / Settings.KEYWORDS_FILE).write_text('keywords_version = 3\n[keywords]\n"go" = "START_LISTENING"\n', encoding="utf-8")
        loaded = Settings.load(self.dir).keywords
        self.assertEqual(loaded["end note"], Action.END_NOTE)
        self.assertNotIn("next row", loaded)                                   # (a phrase the user removed stays removed)

    def test_a_user_who_renamed_it_keeps_their_phrase_and_gains_no_second_one_when_current(self):
        (self.dir / Settings.KEYWORDS_FILE).write_text('keywords_version = 4\n[keywords]\n"finish note" = "END_NOTE"\n', encoding="utf-8")
        loaded = Settings.load(self.dir).keywords
        self.assertEqual(loaded, {"finish note": Action.END_NOTE})

    def test_the_action_has_a_description_for_the_settings_list(self):
        import json
        defaults = json.loads((pathlib.Path(__file__).parent.parent / "quill" / "config" / "defaults.json").read_text(encoding="utf-8"))
        self.assertIn("END_NOTE", defaults["actions"])
        self.assertEqual(sorted(defaults["actions"]), sorted(a.name for a in Action if a is not Action.NONE))

    def test_it_is_not_a_yes_or_no_answer_word(self):
        from quill.parser.commands import RESERVED_ANSWER_WORDS
        self.assertFalse({"end", "note", "notes"} & RESERVED_ANSWER_WORDS)


class TestWholeFlowIntoARealWorkbook(unittest.TestCase):
    """Speech in, a saved note out: the phrases of a long note arrive one by one (as the recogniser delivers them) and the cell holds them all."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.path = make_workbook(self.dir / "plants.xlsx")
        self.ctl = Controller(XlsxBridge(self.path), Settings.load(self.dir / "cfg"), FakeSpeaker(), on_event=lambda e: None,
                              today=lambda: dt.date(2026, 10, 30))
        self.ctl.connect()

    def say(self, *phrases):
        for phrase in phrases:
            self.ctl.handle_transcript(phrase)

    def cells(self, row):
        ws = openpyxl.load_workbook(self.path)["Inventory"]
        return {ws.cell(3, c).value: ws.cell(row, c).value for c in range(1, ws.max_column + 1) if ws.cell(3, c).value}

    def test_a_note_spoken_in_pieces_is_saved_whole_and_the_next_row_is_clean(self):
        self.say("start listening", "fern bright notes the plant came from a friend",
                 "it needs repotting in the spring and a size up", "and the price depends on the color of the leaves",
                 "next row", "cactus small next row")
        first, second = self.cells(4), self.cells(5)
        self.assertEqual(first["Notes"], "The plant came from a friend it needs repotting in the spring and a size up and the price "
                                          "depends on the color of the leaves.")
        self.assertEqual((first["Species"], first["Light"]), ("Fern", "Bright"))
        self.assertIsNone(first.get("Price"))                                  # ("price" and "color" inside the note did not fill anything)
        self.assertEqual(second["Species"], "Cactus")
        self.assertIsNone(second.get("Notes"))

    def test_end_note_lets_the_row_go_on_with_other_columns(self):
        self.say("start listening", "notes keep out of the draft end note price twelve dollars", "next row")
        row = self.cells(4)
        self.assertEqual((row["Notes"], row["Price"]), ("Keep out of the draft.", 12.0))

    def test_the_old_one_phrase_row_still_lands(self):
        self.say("start listening", "fern small bright price twelve dollars notes needs water", "next row")
        self.assertEqual(self.cells(4)["Notes"], "Needs water.")


if __name__ == "__main__":
    unittest.main()
