"""Words that tripped the Term Helper wear a muted grey pill in the heard words; answered, they become ordinary pills (added or matched to
a known word) or plain text again (ignored)."""
import unittest

from PySide6.QtTest import QTest

from quill.session import Decision
from quill.ui.theme import PILL_MIN_CONTRAST, TOKENS, contrast_ratio, grey_pill
from tests.test_app import AppCase


def look(window, word):
    """What the stream made of *word*: 'grey', 'purple' or 'plain'."""
    for heard, match in window._stream_words:
        if heard == word:
            return "grey" if match.pending else ("purple" if match.known else "plain")
    raise AssertionError(f"{word!r} is not in the heard words: {[w for w, _ in window._stream_words]}")


class TestGreyPills(AppCase):
    def setUp(self):
        super().setUp()
        self.window = self.quill.window
        self.hear("start listening")

    def pending(self, text):
        return next(k for k in self.quill.controller.pending_terms() if text in k[1])

    def settle(self):
        QTest.qWait(150)

    def test_a_word_that_tripped_the_term_helper_gets_a_grey_pill_and_known_words_stay_purple(self):
        self.hear("fern gobbledygook small")
        self.assertEqual([look(self.window, w) for w in ("fern", "gobbledygook", "small")], ["purple", "grey", "purple"])

    def test_adding_it_turns_the_grey_pill_purple(self):
        self.hear("fern gobbledygook")
        key = self.pending("gobbledygook")
        self.quill.resolve_term(key, Decision.add("Species"), key[1])
        self.assertEqual(look(self.window, "gobbledygook"), "purple")
        self.assertEqual(dict(self.window._stream_words)["gobbledygook"].column, "Species")

    def test_matching_it_to_a_known_word_turns_the_grey_pill_purple_too(self):
        self.hear("fern gobbledygook")
        key = self.pending("gobbledygook")
        self.quill.resolve_term(key, Decision.alias("Species", "Fern"), key[1])
        self.assertEqual(look(self.window, "gobbledygook"), "purple")

    def test_ignoring_it_takes_the_pill_away_and_it_reads_as_plain_text(self):
        self.hear("fern gobbledygook")
        key = self.pending("gobbledygook")
        self.quill.resolve_term(key, Decision.ignore(), key[1])
        self.assertEqual(look(self.window, "gobbledygook"), "plain")
        html = self.window.stream.toHtml()
        grey, _ = grey_pill(self.window._text_color)
        self.assertNotIn(grey.lower(), html.lower(), "no grey pill is drawn any more")

    def test_ignore_all_clears_every_grey_pill_at_once(self):
        self.hear("gobbledygook fern flibbertigibbet")                    # (a known word between them: two terms)
        self.assertEqual(len(self.quill.controller.pending_terms()), 2)
        self.assertEqual({look(self.window, "gobbledygook"), look(self.window, "flibbertigibbet")}, {"grey"})
        with self.quill.controller.batch("Ignore all"):
            for key in list(self.quill.controller.pending_terms()):
                self.quill.controller.resolve_term(key, Decision.ignore(), key[1])
        self.assertEqual({look(self.window, "gobbledygook"), look(self.window, "flibbertigibbet")}, {"plain"})

    def test_undoing_the_answer_brings_the_grey_pill_back(self):
        self.hear("fern gobbledygook")
        key = self.pending("gobbledygook")
        self.quill.resolve_term(key, Decision.add("Species"), key[1])
        self.assertEqual(look(self.window, "gobbledygook"), "purple")
        self.quill.undo()
        self.settle()
        self.assertEqual(look(self.window, "gobbledygook"), "grey")

    def test_a_term_of_several_words_is_one_grey_pill(self):
        self.hear("fern gobbledygook flibbertigibbet")
        key = next((k for k in self.quill.controller.pending_terms() if " " in k[1]), None)
        self.assertIsNotNone(key, "the two unknown words next to each other are one term")
        words = [w for w, m in self.window._stream_words if m.pending]
        self.assertEqual(len(words), 2)
        html = self.window.stream.toHtml()
        grey, _ = grey_pill(self.window._text_color)
        pills = html.lower().count(grey.lower())
        spans = {m.span for _, m in self.window._stream_words if m.pending}
        self.assertEqual(pills, len(spans), "one pill per waiting term, however many words it has")

    def test_words_still_being_spoken_are_not_grey(self):
        self.quill._on_partial_heard("fern gobbledygook")
        self.assertFalse([w for w, m in self.window._stream_partial if m.pending])

    def test_the_same_word_heard_again_is_grey_again_wherever_it_is_in_the_row(self):
        self.hear("fern gobbledygook", "small gobbledygook")
        self.assertEqual([m.pending for w, m in self.window._stream_words if w == "gobbledygook"], [True, True])

    def test_the_row_being_discarded_takes_the_grey_pills_with_it(self):
        self.hear("fern gobbledygook")
        self.hear("delete row")
        self.settle()
        self.assertFalse([w for w, m in self.window._stream_words if m.pending])


class TestTheGreyPillReads(unittest.TestCase):
    def test_the_text_on_it_has_enough_contrast_in_both_themes(self):
        for scheme, tokens in TOKENS.items():
            fill, ink = grey_pill(tokens["text"])
            self.assertGreaterEqual(contrast_ratio(ink, fill), PILL_MIN_CONTRAST, scheme)

    def test_it_is_a_grey_not_the_accent_and_not_the_window(self):
        for scheme, tokens in TOKENS.items():
            fill, _ = grey_pill(tokens["text"])
            r, g, b = (int(fill[i:i + 2], 16) for i in (1, 3, 5))
            self.assertLess(max(r, g, b) - min(r, g, b), 12, f"{scheme}: {fill} is not a grey")
            self.assertGreater(contrast_ratio(fill, tokens["bg"]), 1.3, f"{scheme}: the pill must stand out from the window")

    def test_a_theme_with_colours_close_together_is_nudged_until_it_reads(self):
        fill, ink = grey_pill("#8A8A8A")                    # (a mid grey text colour, the worst case for a pill made from it)
        self.assertGreaterEqual(contrast_ratio(ink, fill), PILL_MIN_CONTRAST)


if __name__ == "__main__":
    unittest.main()
