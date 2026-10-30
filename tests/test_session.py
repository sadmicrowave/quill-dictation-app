"""Session state-machine tests: gate, rows, and the unknown-value question."""
import datetime as dt
import unittest

from quill.parser.commands import Action, CommandMatcher
from quill.parser.vocab import Vocabulary
from quill.session import Session, prompt_text

LISTS = {
    "Species": ["Fern", "Cactus", "Orchid"],
    "Light": ["Low", "Bright"],
    "Health": ["Thriving", "Okay"],
}
KEYWORDS = {
    "start listening": Action.START_LISTENING,
    "stop listening": Action.STOP_LISTENING,
    "next row": Action.NEXT_ROW,
    "cancel": Action.DELETE_ROW,
    "search for": Action.SEARCH_FOR,
}


def make_session():
    vocab = Vocabulary()
    vocab.load(LISTS, ["Species", "Light", "Health", "Price"])
    return Session(vocab, CommandMatcher(KEYWORDS), today=lambda: dt.date(2026, 10, 30))


def kinds(events):
    return [e.kind for e in events]


class TestGate(unittest.TestCase):
    def test_speech_ignored_until_started(self):
        s = make_session()
        self.assertEqual(s.feed("fern bright"), [])
        self.assertEqual(s.record, {})
        self.assertEqual(s.ignored_while_stopped, 1)

    def test_start_then_dictate(self):
        s = make_session()
        s.feed("start listening")
        events = s.feed("fern bright")
        self.assertEqual(kinds(events), ["updated"])
        self.assertEqual(s.record, {"Species": "Fern", "Light": "Bright"})

    def test_stop_closes_gate(self):
        s = make_session()
        s.feed("start listening")
        s.feed("stop listening")
        s.feed("fern")
        self.assertEqual(s.record, {})

    def test_commands_other_than_start_ignored_while_stopped(self):
        s = make_session()
        self.assertEqual(kinds(s.feed("next row")), ["ignored"])

    def test_start_and_dictate_in_one_phrase(self):
        s = make_session()
        s.feed("start listening fern")
        self.assertEqual(s.record, {"Species": "Fern"})


class TestRows(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        self.s.feed("start listening")

    def test_next_row_commits_and_resets(self):
        self.s.feed("fern bright")
        events = self.s.feed("next row")
        self.assertEqual(kinds(events), ["committed"])
        self.assertEqual(events[0].record, {"Species": "Fern", "Light": "Bright"})
        self.assertEqual((self.s.record, self.s.committed), ({}, 1))

    def test_one_phrase_with_two_rows(self):
        events = self.s.feed("fern next row cactus next row")
        self.assertEqual([e.record["Species"] for e in events if e.kind == "committed"],
                         ["Fern", "Cactus"])

    def test_next_row_with_empty_record(self):
        self.assertEqual(kinds(self.s.feed("next row")), ["ignored"])
        self.assertEqual(self.s.committed, 0)

    def test_cancel_discards(self):
        self.s.feed("fern")
        events = self.s.feed("cancel")
        self.assertEqual(kinds(events), ["discarded"])
        self.assertEqual(self.s.record, {})

    def test_cancel_with_nothing(self):
        self.assertEqual(kinds(self.s.feed("cancel")), ["ignored"])

    def test_record_accumulates_across_phrases_and_later_wins(self):
        self.s.feed("fern")
        self.s.feed("light low")
        self.s.feed("cactus")
        self.assertEqual(self.s.record, {"Species": "Cactus", "Light": "Low"})

    def test_amounts_and_dates_in_record(self):
        self.s.feed("price 5 dollars")
        self.assertEqual(self.s.record["Price"], 5.0)

    def test_search_reports_argument(self):
        events = self.s.feed("search for fern")
        self.assertEqual((events[0].kind, events[0].detail), ("search", "fern"))

    def test_restore_after_failed_write(self):
        self.s.feed("fern")
        row = self.s.feed("next row")[0].record
        self.s.feed("bright")
        self.s.restore(row)
        self.assertEqual(self.s.record, {"Species": "Fern", "Light": "Bright"})
        self.assertEqual(self.s.committed, 0)


class TestQuestionFlow(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        self.s.feed("start listening")

    def hear_unknown(self):
        self.s.feed("fern light dim")           # "dim" is hinted -> Light
        return self.s.feed("next row")

    def test_question_asked_at_next_row(self):
        events = self.hear_unknown()
        self.assertEqual(kinds(events), ["committed", "confirm"])
        self.assertEqual(events[1].values, [("Light", "dim")])
        self.assertIn("Dim isn't in the Light list", events[1].detail)

    def test_question_asked_at_stop(self):
        self.s.feed("light dim")
        events = self.s.feed("stop listening")
        self.assertEqual(kinds(events), ["stopped", "confirm"])

    def test_yes_adds_to_vocab_and_reports_values(self):
        self.hear_unknown()
        events = self.s.feed("yes")
        self.assertEqual(kinds(events), ["add_values"])
        self.assertEqual(events[0].values, [("Light", "Dim")])
        self.assertIn("Dim", self.s.vocab.values_for("Light"))
        self.assertIsNone(self.s.pending)

    def test_no_discards(self):
        self.hear_unknown()
        events = self.s.feed("no")
        self.assertEqual(kinds(events), ["skipped"])
        self.assertNotIn("Dim", self.s.vocab.values_for("Light"))

    def test_cancel_answers_no_when_question_pending(self):
        self.hear_unknown()
        self.s.feed("fern")
        self.assertEqual(kinds(self.s.feed("cancel")), ["skipped"])
        self.assertEqual(self.s.record, {"Species": "Fern"})   # row not discarded

    def test_answer_then_continue_in_same_phrase(self):
        self.hear_unknown()
        self.s.feed("yes cactus")
        self.assertEqual(self.s.record, {"Species": "Cactus"})

    def test_answer_works_after_listening_stopped(self):
        self.s.feed("light dim")
        self.s.feed("stop listening")
        self.assertEqual(kinds(self.s.feed("yes")), ["add_values"])

    def test_unrelated_speech_keeps_question_open(self):
        self.hear_unknown()
        self.s.feed("cactus")
        self.assertIsNotNone(self.s.pending)

    def test_expired_question_is_asked_again_at_next_pause(self):
        self.hear_unknown()
        self.assertEqual(kinds(self.s.expire_prompt()), ["expired"])
        self.s.feed("cactus")
        events = self.s.feed("next row")
        self.assertEqual(kinds(events), ["committed", "confirm"])
        self.assertEqual(events[1].values, [("Light", "dim")])

    def test_expire_with_nothing_pending(self):
        self.assertEqual(self.s.expire_prompt(), [])

    def test_discarded_row_does_not_ask(self):
        self.s.feed("light dim")
        self.s.feed("cancel")
        self.assertEqual(self.s.feed("next row")[-1].kind, "ignored")
        self.assertEqual(self.s.pool, {})

    def test_repeated_unknown_asked_once(self):
        self.s.feed("light dim")
        self.s.feed("light dim")
        events = self.s.feed("next row")
        self.assertEqual(events[-1].values, [("Light", "dim")])

    def test_multiple_unknowns_group_into_one_question(self):
        self.s.feed("light dim health wilting")
        events = self.s.feed("next row")
        confirm = events[-1]
        self.assertEqual(len(confirm.values), 2)
        self.assertIn("new values", confirm.detail)

    def test_unhinted_unknown_with_unclear_column_is_reported_not_pooled(self):
        events = self.s.feed("zorblax")
        self.assertEqual(kinds(events), ["updated", "unsure"])
        self.assertIn("couldn't tell", events[1].detail)
        self.assertEqual(self.s.pool, {})


class TestPromptText(unittest.TestCase):
    def test_single(self):
        self.assertEqual(
            prompt_text([("Color", "obsidian")]),
            "I heard a new value. Obsidian isn't in the Color list. Add it? Say yes or no.")

    def test_grouped_by_column(self):
        text = prompt_text([("Brand", "gucci"), ("Brand", "hugo boss"), ("Color", "teal")])
        self.assertIn("Gucci and Hugo Boss aren't in the Brand list.", text)
        self.assertIn("Teal isn't in the Color list.", text)
        self.assertTrue(text.endswith("Add them? Say yes or no."))


if __name__ == "__main__":
    unittest.main()
