"""Which of the words just heard Quill already knows (shown as pills in the Voice Stream).

A word counts as recognised when it is part of something the parser understands: a column name, a value from
one of the workbook's lists, a number, amount or date, or one of the spoken commands. Everything else
(sentence filler, brand-new words) stays plain. Pure and fast, since it runs on every partial result.
"""

from __future__ import annotations
import datetime as dt
from typing import Iterable

from quill.parser.numbers import parse_amount, parse_date, parse_number
from quill.parser.tokens import tokenize
from quill.parser.vocab import Vocabulary


def recognized_words(words: list[str], vocab: Vocabulary, phrases: Iterable[str] = (),
                     today: dt.date | None = None) -> list[bool]:
    """For each of *words*, whether it is part of something Quill understands.

    Args:
        words: The words heard, in order.
        vocab: The workbook's vocabulary (columns and list values).
        phrases: Spoken command phrases ("next row", "start listening").
        today: Replaces today's date (tests), for "today" / "march 3".
    """
    tokens: list[str] = []
    owner: list[int] = []                       # which word each token came from ("t-shirt" is two tokens)
    for n, word in enumerate(words):
        for token in tokenize(word):
            tokens.append(token)
            owner.append(n)
    commands = [t for t in (tokenize(p) for p in phrases) if t]
    today = today or dt.date.today()
    flags = [False] * len(words)
    i = 0
    while i < len(tokens):
        used = _known_span(tokens, i, vocab, commands, today)
        if used:
            for k in range(i, i + used):
                flags[owner[k]] = True
            i += used
        else:
            i += 1
    return flags


def _known_span(tokens: list[str], i: int, vocab: Vocabulary, commands: list[list[str]],
                today: dt.date) -> int:
    """How many tokens from *i* form something known (0 if none)."""
    best = 0
    for command in commands:
        if tokens[i:i + len(command)] == command:
            best = max(best, len(command))
    field = vocab.field_at(tokens, i)
    if field:
        best = max(best, field[1])
    for _, _, length in vocab.matches_at(tokens, i):
        best = max(best, length)
    for read in (lambda: parse_amount(tokens, i), lambda: parse_number(tokens, i),
                 lambda: parse_date(tokens, i, today)):
        _, used = read()
        best = max(best, used)
    return best
