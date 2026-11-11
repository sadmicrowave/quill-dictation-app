"""Which of the words just heard Quill understood, and which column each one filled (for the Voice Stream).

The words are run through the same parser that fills the row, so what is drawn as a pill is exactly what was
understood, not a second opinion. A word that is part of a spoken command ("next row") counts as understood
too, but belongs to no column. Pure and fast, since it runs on every partial result.
"""

from __future__ import annotations
import datetime as dt
from dataclasses import dataclass

from quill.parser.commands import CommandMatcher
from quill.parser.phrase_parser import parse
from quill.parser.tokens import tokenize
from quill.parser.vocab import Vocabulary


@dataclass(frozen=True)
class WordMatch:
    """What Quill made of one heard word."""

    known: bool
    """True if the word is part of something understood (a column value or a command)."""

    column: str | None = None
    """The column the word filled, or None for a command or a word that was not understood."""

    command: bool = False
    """True if the word is part of a spoken command ("next row"); the stream leaves those words out."""

    span: int | None = None
    """Which understood value the word belongs to: words with the same span are one value ("you hear me") and share one pill."""

    pending: bool = False
    """True while the word is waiting in the Term Helper (it is drawn as a grey pill until it is answered); words with the same span
    are one term and share one pill."""


def match_words(words: list[str], vocab: Vocabulary, matcher: CommandMatcher | None = None,
                today: dt.date | None = None) -> list[WordMatch]:
    """For each of *words*, what Quill understood by it.

    Args:
        words: The words heard, in order.
        vocab: The workbook's vocabulary (columns and list values).
        matcher: Finds the spoken commands ("next row", "stop"); their words are marked as commands.
        today: Replaces today's date (tests), for "today" / "march 3".
    """
    tokens: list[str] = []
    owner: list[int] = []                       # which word each token came from ("t-shirt" is two tokens)
    for n, word in enumerate(words):
        for token in tokenize(word):
            tokens.append(token)
            owner.append(n)
    matches = [WordMatch(False) for _ in words]
    if not tokens:
        return matches

    result = parse(" ".join(tokens), vocab, today or dt.date.today())
    for number, (start, end, column) in enumerate(result.spans):
        for k in range(start, min(end, len(tokens))):
            if not matches[owner[k]].known:
                matches[owner[k]] = WordMatch(True, column, span=number)

    if matcher is not None:
        for k in matcher.command_positions(" ".join(tokens)):
            matches[owner[k]] = WordMatch(True, command=True)
    return matches
