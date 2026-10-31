"""Keyword matcher tests (S5, part): token-based matching and splitting."""
import unittest

from quill.parser.commands import Action, CommandEvent, CommandMatcher

KEYWORDS = {
    "start listening": Action.START_LISTENING,
    "stop listening": Action.STOP_LISTENING,
    "next row": Action.NEXT_ROW,
    "new record": Action.NEXT_ROW,
    "cancel": Action.DELETE_ROW,
    "search for": Action.SEARCH_FOR,
}


class TestMatch(unittest.TestCase):
    def setUp(self):
        self.m = CommandMatcher(KEYWORDS)

    def test_keyword_at_start(self):
        ev = self.m.match("next row fern")
        self.assertEqual((ev.action, ev.remainder), (Action.NEXT_ROW, "fern"))

    def test_keyword_in_middle(self):
        self.assertEqual(self.m.match("fern next row").action, Action.NEXT_ROW)

    def test_case_and_punctuation_ignored(self):
        self.assertEqual(self.m.match("Next, Row!").action, Action.NEXT_ROW)

    def test_no_match(self):
        ev = self.m.match("fern bright")
        self.assertEqual((ev.action, ev.remainder), (Action.NONE, "fern bright"))

    def test_keyword_inside_another_word_does_not_fire(self):
        self.assertEqual(self.m.match("cancellation").action, Action.NONE)

    def test_longest_phrase_wins(self):
        m = CommandMatcher({"stop": Action.NEXT_ROW, "stop listening": Action.STOP_LISTENING})
        self.assertEqual(m.match("stop listening").action, Action.STOP_LISTENING)

    def test_blank_phrase_ignored(self):
        m = CommandMatcher({"": Action.NEXT_ROW, "  ": Action.NEXT_ROW})
        self.assertEqual(m.match("anything").action, Action.NONE)


class TestSplit(unittest.TestCase):
    def setUp(self):
        self.m = CommandMatcher(KEYWORDS)

    def test_text_command_text(self):
        segs = self.m.split("fern small next row bright")
        self.assertEqual(segs, ["fern small", CommandEvent(Action.NEXT_ROW), "bright"])

    def test_command_only(self):
        self.assertEqual(self.m.split("start listening"), [CommandEvent(Action.START_LISTENING)])

    def test_consecutive_commands(self):
        segs = self.m.split("next row stop listening")
        self.assertEqual([s.action for s in segs], [Action.NEXT_ROW, Action.STOP_LISTENING])

    def test_plain_text(self):
        self.assertEqual(self.m.split("fern small"), ["fern small"])

    def test_empty(self):
        self.assertEqual(self.m.split(""), [])

    def test_argument_action_swallows_following_words(self):
        segs = self.m.split("search for blue fern next row")
        self.assertEqual(segs, [CommandEvent(Action.SEARCH_FOR, "blue fern"),
                                CommandEvent(Action.NEXT_ROW)])


class TestFromDefaults(unittest.TestCase):
    def test_shipped_defaults_work(self):
        m = CommandMatcher.from_defaults()
        self.assertEqual(m.match("start listening").action, Action.START_LISTENING)
        self.assertEqual(m.match("new record").action, Action.NEXT_ROW)
        self.assertEqual(m.match("cancel").action, Action.DELETE_ROW)


if __name__ == "__main__":
    unittest.main()


class TestEndOfSpeechKeywords(unittest.TestCase):
    """"next" and "stop" mean "next row", but only as the last word said (they are everywhere in ordinary speech)."""

    def setUp(self):
        self.matcher = CommandMatcher.from_defaults()

    def test_the_last_word_next_or_stop_ends_the_row(self):
        for text in ("navy shirt large next", "navy shirt large stop"):
            segments = self.matcher.split(text)
            self.assertEqual(segments[0], "navy shirt large")
            self.assertEqual(segments[-1].action, Action.NEXT_ROW)

    def test_in_the_middle_of_a_sentence_they_are_just_words(self):
        self.assertEqual(self.matcher.split("this next item is a navy shirt"), ["this next item is a navy shirt"])
        self.assertEqual(self.matcher.split("stop the presses navy"), ["stop the presses navy"])

    def test_next_item_works_the_same_way(self):
        segments = self.matcher.split("navy shirt large next item")
        self.assertEqual(segments[0], "navy shirt large")
        self.assertEqual(segments[-1].action, Action.NEXT_ROW)
        self.assertEqual(self.matcher.split("this next item"), ["this next item"])          # "this next item" is a sentence
        self.assertEqual(self.matcher.split("now the next item is a shirt"), ["now the next item is a shirt"])

    def test_command_words_are_reported_so_they_can_be_left_out_of_the_stream(self):
        self.assertEqual(self.matcher.command_positions("navy shirt next item"), {2, 3})
        self.assertEqual(self.matcher.command_positions("navy next row shirt"), {1, 2})
        self.assertEqual(self.matcher.command_positions("this next item is a shirt"), set())

    def test_stop_listening_still_stops_listening(self):
        self.assertEqual(self.matcher.split("stop listening")[0].action, Action.STOP_LISTENING)
