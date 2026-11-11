"""Generalised spoken phrase parser.

Turns a speech transcript into a dict of column -> value mappings, using only
the vocabulary loaded from the active workbook. No domain-specific terms
appear here: the workbook's headers and drop-down lists are the whole grammar.

Spoken grammar:
  * A **field word** (any column header) sets that column:
      - list column:    ``"color navy"``   -> value from that column's list
      - amount:         ``"price 25"``, ``"cost forty two dollars and fifty cents"``
      - date:           ``"acquired today"``, ``"date october 30 2026"``
      - text column:    ``"notes faded on one side"`` (runs to the next field word)
  * A **known value** is recognised on its own, with no field word:
    ``"nike black"`` fills Brand and Color if the workbook lists them.
  * A value that appears in several lists goes to the earlier column and the
    choice is reported in ``ParseResult.assumptions``.
  * Words that match nothing are pooled as *candidates* (unknown values) that
    the session later asks about; see :mod:`quill.session`.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from quill.parser.fillers import FILLER_WORDS
from quill.parser.numbers import parse_amount, parse_date, parse_number
from quill.parser.tokens import tokenize
from quill.parser.vocab import Vocabulary

#: Words that are never values. A run of unknown words stops at one of these.
COMMON_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "with", "of", "it", "its", "is", "are", "was", "be",
    "this", "that", "there", "to", "in", "on", "at", "for", "from", "by", "as", "so", "some",
    "nice", "okay", "ok", "yeah", "yes", "no", "um", "uh", "like", "just", "really", "pretty",
    "cool", "great", "fine", "thing", "stuff", "called", "name", "item", "also", "has", "have",
    "had", "about", "looks", "look", "very", "little", "big", "lot", "more", "less",
    "mainly", "mostly", "maybe", "probably", "around", "roughly", "approximately", "made",
    "make", "sell", "sells", "sold", "could", "would", "should", "will", "can", "next", "worth",
    "which", "who", "what", "when", "where", "then", "they", "them", "their", "these", "those",
})

#: Everything above plus the broad list of everyday words (see :mod:`quill.parser.fillers`).
COMMON_WORDS = COMMON_WORDS | FILLER_WORDS

#: Unit words that mark a spoken number as money ("thirty five dollars").
CURRENCY_WORDS = frozenset({"dollar", "dollars", "buck", "bucks", "cent", "cents"})

#: Words that may sit between a field word and its value ("cost of 25").
FILLERS = frozenset({"of", "is", "was", "at", "for", "a", "an", "the", "to", "as"})

#: Header words that mean "free text" even when the first word is a number.
TEXT_HINTS = frozenset({
    "note", "notes", "comment", "comments", "description", "remarks", "details",
})

#: Words that, right before a free-text header, show it is just a noun in a
#: sentence ("this next *item* is…") rather than a field word ("item vintage tee").
DETERMINERS = frozenset({
    "this", "that", "next", "the", "a", "an", "new", "another", "each", "every", "my", "our",
})

#: Longest run of unknown words read as a single new value ("hugo boss").
MAX_VALUE_WORDS = 4

#: Fraction of a column's values that must share a shape for a shape-based guess.
_SHAPE_AGREEMENT = 0.6


def _is_verb_form(word: str) -> bool:
    """True for a word that looks like an English verb form ("observed", "departing"): never a list value."""
    return len(word) >= 5 and word.endswith(("ed", "ing"))


@dataclass
class Candidate:
    """A spoken value that is not in the workbook's lists."""

    term: str
    """The spoken words, lowercase."""

    column: str | None
    """The list it probably belongs to, or None when it could not be told."""

    hinted: bool
    """True when the speaker said the field word (so *column* is certain)."""

    alias_of: tuple[str, str] | None = None
    """``(column, value)`` when the term looks like the long form of a short code (``medium`` for ``M``)."""


@dataclass
class ParseResult:
    """Output of a single parse call."""

    updates: dict[str, object] = field(default_factory=dict)
    """column -> value (``str`` for list/text, ``float`` for amounts, ``date``)."""

    candidates: list[Candidate] = field(default_factory=list)
    """Unknown values to ask the user about."""

    unmatched: list[str] = field(default_factory=list)
    """Words heard that matched nothing and were not value candidates."""

    assumptions: list[str] = field(default_factory=list)
    """Human-readable notes about guesses made (e.g. ``'red' taken as Color``)."""

    spans: list[tuple[int, int, str]] = field(default_factory=list)
    """``(first_token, end_token, column)`` for each part of the phrase that filled a column (end is exclusive).
    The Voice Stream uses these to colour the words that were understood, and to un-colour them if the
    user removes the matching row."""

    corrections: dict[str, str] = field(default_factory=dict)
    """Words that were taken as a similar-sounding known word: ``{"waste": "waist"}``."""

    context: dict[str, list[str]] = field(default_factory=dict)
    """For a date placed without its column's name: the words spoken around it, nearest first. They are what a
    correction of its column teaches (see :mod:`quill.learning`)."""

    additive: set[str] = field(default_factory=set)
    """Columns filled by a known value spoken without the column's name. A second different value for such a
    column is added under the first (one value per line of the cell) instead of replacing it."""

    open_note: str | None = None
    """The notes-style column this phrase began (a note is read to the end of the phrase, and the next phrases go on with it
    until the note is closed: see :class:`quill.session.Session`)."""


def is_note_column(vocab: Vocabulary, column: str) -> bool:
    """True for a column with no list whose heading ends in a notes-style word (notes, comments, description ...): its value is long text."""
    last = tokenize(column)[-1] if tokenize(column) else ""
    return last in TEXT_HINTS and not vocab.is_list_column(column)


def finish_note(text: str) -> str:
    """A note as it is written to the cell: the recogniser gives no capitals or full stops, so the first letter is a capital and the
    note ends with a full stop (unless it already ends with ``.``, ``!`` or ``?``)."""
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def merge_values(existing: object, new: object) -> str:
    """Put *new* under *existing* in one cell (a value per line), unless it is already there."""
    lines = str(existing).split("\n")
    for line in str(new).split("\n"):
        if line.lower() not in (x.lower() for x in lines):
            lines.append(line)
    return "\n".join(lines)


def parse(
    text: str,
    vocab: Vocabulary,
    today: dt.date | None = None,
    filled: set[str] | None = None,
) -> ParseResult:
    """Parse one transcript segment into field values.

    Args:
        text: Raw transcript text from the speech recogniser.
        vocab: Vocabulary loaded from the active workbook.
        today: Date used for "today"/"yesterday" (default: the real today).
        filled: Columns already set in the record being built; used only to
            guess which list an unknown value belongs to.

    Returns:
        A :class:`ParseResult` with matched fields and unknown terms.
    """
    return _Parser(tokenize(text), vocab, today or dt.date.today(), filled or set()).run()


class _Parser:
    """One-shot parser over a token list (keeps the per-call state tidy)."""

    def __init__(self, tokens, vocab, today, filled) -> None:
        self.tokens: list[str] = tokens
        self.vocab = vocab
        self.today = today
        self.filled = set(filled)
        self.result = ParseResult()
        self.run_words: list[str] = []   # consecutive unknown words
        self.i = 0
        self._set_count = 0              # how many values were set so far (to notice that a step set one)

    # ------------------------------------------------------------------ #
    # Main loop                                                            #
    # ------------------------------------------------------------------ #

    def run(self) -> ParseResult:
        n = len(self.tokens)
        while self.i < n:
            field_hit = self.vocab.field_at(self.tokens, self.i)
            if field_hit and self._is_prose_use(field_hit[0]):
                self._flush()
                self.result.unmatched.append(self.tokens[self.i])
                self.i += field_hit[1]
                continue
            if field_hit:
                self._flush()
                column, length = field_hit
                self._take_field(column, length)
                continue

            matches = self.vocab.matches_at(self.tokens, self.i)
            if matches:
                self._flush()
                self._take_value(matches)
                continue

            if self._take_bare_amount():
                continue

            if self._take_bare_date():
                continue

            if self._take_sound_alike():
                continue

            word = self.tokens[self.i]
            if self._is_common(word) or parse_number(self.tokens, self.i)[0] is not None:
                self._flush()
                self.result.unmatched.append(word)
            else:
                self.result.unmatched.append(word)
                self.run_words.append(word)
            self.i += 1
        self._flush()
        self._assign_guesses()
        return self.result

    def _take_field(self, column: str, length: int) -> None:
        """A column name was spoken: read the value that follows it."""
        field_start = self.i
        self.i += length
        before = self._set_count
        self._read_field_value(column, field_start)
        if self._set_count > before:
            self.result.spans.append((field_start, self.i, column))

    def _take_bare_date(self) -> bool:
        """Read a date said with no column name ("… and I bought it yesterday") into the date column it suits.

        The real date is written, not the words. Without any date column in the sheet the words are just
        skipped (they are never a list value to sort).
        """
        date, used = parse_date(self.tokens, self.i, self.today)
        if date is None:
            return False
        while self.run_words and _is_verb_form(self.run_words[-1]):
            self.run_words.pop()                       # "… observed yesterday": the verb leads into the date
            self.result.unmatched.pop()
        self._flush()
        column, note = self.vocab.date_column_for(self.tokens, self.i, self.filled, self.i + used)
        if column is None:
            self.result.unmatched.append(" ".join(self.tokens[self.i:self.i + used]))
        else:
            self._set(column, date, self.i, self.i + used)
            self.result.context[column] = self.vocab.context_words(self.tokens, self.i, self.i + used)[:2]
            if note:
                self.result.assumptions.append(note)
        self.i += used
        return True

    def _take_sound_alike(self) -> bool:
        """Take the word at the cursor as a similar-sounding column name or value ("waste" for "waist")."""
        heard = self.vocab.sound_alike_at(self.tokens, self.i)
        if heard is None:
            return False
        kind, column, canonical, known = heard
        word = self.tokens[self.i]
        self._flush()
        self.result.corrections[word] = known
        self.result.assumptions.append(f"heard '{word}' as '{known}'")
        if kind == "field":
            self._take_field(column, 1)
        else:
            self._set(column, canonical, self.i, self.i + 1, additive=True)
            self.i += 1
        return True

    def _is_prose_use(self, column: str) -> bool:
        """True when a free-text header word is just a noun after "this", "the", ..."""
        if self.vocab.is_list_column(column) or self.i == 0:
            return False
        last = tokenize(column)[-1] if tokenize(column) else ""
        return last not in TEXT_HINTS and self.tokens[self.i - 1] in DETERMINERS

    def _take_bare_amount(self) -> bool:
        """Read "thirty five dollars" with no field word into the default amount column."""
        amount, used = parse_amount(self.tokens, self.i)
        if amount is None or not CURRENCY_WORDS & set(self.tokens[self.i:self.i + used]):
            return False
        self._flush()
        column, note = self.vocab.amount_column_for(self.tokens, self.i, self.i + used)
        if column is None:
            self.result.unmatched.append(" ".join(self.tokens[self.i:self.i + used]))
        else:
            self._set(column, amount, self.i, self.i + used)
            self.result.context[column] = self.vocab.context_words(self.tokens, self.i, self.i + used)[:2]
            if note:
                self.result.assumptions.append(note)
        self.i += used
        return True

    # ------------------------------------------------------------------ #
    # Known values                                                         #
    # ------------------------------------------------------------------ #

    def _take_value(self, matches: list[tuple[str, str, int]]) -> None:
        """Record the best of several vocabulary matches at the cursor."""
        order = {c: k for k, c in enumerate(self.vocab.columns())}
        matches.sort(key=lambda m: (-m[2], order.get(m[0], len(order))))
        free = [m for m in matches if m[0] not in self.result.updates]       # prefer a column that has no value yet in this phrase
        column, canonical, length = (free or matches)[0]
        phrase = " ".join(self.tokens[self.i:self.i + length])
        columns = {m[0] for m in matches if m[2] == length}
        if len(columns) > 1:
            self.result.assumptions.append(f"'{phrase}' taken as {column}")
        self._set(column, canonical, self.i, self.i + length, additive=True)
        self.i += length

    def _set(self, column: str, value: object, start: int | None = None, end: int | None = None,
             additive: bool = False) -> None:
        """Record a value for *column*; *start* / *end* (token positions) say which words it came from.

        With *additive* a different value already given for the column in this phrase is kept and *value* goes
        under it in the same cell."""
        if additive:
            if column in self.result.updates:
                value = merge_values(self.result.updates[column], value)
            self.result.additive.add(column)
        self.result.updates[column] = value
        self.filled.add(column)
        self._set_count += 1
        if start is not None and end is not None:
            self.result.spans.append((start, end, column))

    # ------------------------------------------------------------------ #
    # Field words                                                          #
    # ------------------------------------------------------------------ #

    def _read_field_value(self, column: str, field_start: int) -> None:
        """Consume the value that follows the field word (at *field_start*)."""
        if is_note_column(self.vocab, column):
            self._read_note(column)                          # (a note keeps its small words: "the price went up")
            return
        while self.i < len(self.tokens) and self.tokens[self.i] in FILLERS:
            self.i += 1
        if self.vocab.is_list_column(column):
            self._read_list_value(column)
        else:
            self._read_free_value(column, field_start)

    def _read_list_value(self, column: str) -> None:
        hinted = [m for m in self.vocab.matches_at(self.tokens, self.i) if m[0] == column]
        if hinted:
            hinted.sort(key=lambda m: -m[2])
            _, canonical, length = hinted[0]
            self._set(column, canonical)
            self.i += length
            return

        number, used = parse_number(self.tokens, self.i)
        if number is not None:  # numeric list entry, e.g. a size of 10
            text = str(int(number)) if number == int(number) else str(number)
            known = {v.lower(): v for v in self.vocab.values_for(column)}
            if text in known:
                self._set(column, known[text])
                self.i += used
                return

        words = self._collect_unknown_words()
        if not words:
            self.result.unmatched.append(column.lower())
            return
        term = " ".join(words)
        close = self.vocab.fuzzy(term)
        if close and close[0] == column:
            self._set(column, close[1])
        else:
            self.result.candidates.append(self._candidate(term, column, True))

    def _read_note(self, column: str) -> None:
        """Take every word to the end of the phrase as the note: column names, list values, numbers and dates inside it are
        just words. The note stays open for the phrases that follow."""
        words = self.tokens[self.i:]
        if words:
            self._set(column, " ".join(words))
        self.result.open_note = column
        self.i = len(self.tokens)

    def _read_free_value(self, column: str, start: int) -> None:
        """Read an amount, date or free text for a column with no list."""
        last_word = tokenize(column)[-1] if tokenize(column) else ""
        if last_word not in TEXT_HINTS:
            date, used = parse_date(self.tokens, self.i, self.today)
            if date is not None:
                self._set(column, date)
                self.i += used
                return
            amount, used = parse_amount(self.tokens, self.i)
            if amount is not None:
                self._set(column, amount)
                self.i += used
                return

        end = self.i
        while (end < len(self.tokens) and self.vocab.field_at(self.tokens, end) is None
               and not self._starts_date(end)):                  # a date ends the text: it goes in a date column
            end += 1
        text_end = end
        while (end < len(self.tokens) and self._starts_date(end)           # only when a date interrupted the text
               and text_end > self.i and self._is_common(self.tokens[text_end - 1])):
            text_end -= 1                                         # "… it was" leads into the date, it is not text
        if text_end == self.i:
            if end == self.i:
                self.result.unmatched.append(" ".join(self.tokens[start:self.i]))
            self.i = end
            return
        self._set(column, " ".join(self.tokens[self.i:text_end]))
        self.i = end

    def _starts_date(self, j: int) -> bool:
        """True where a spoken date begins at ``tokens[j]`` and the sheet has a date column to put it in."""
        return bool(self.vocab.date_columns) and parse_date(self.tokens, j, self.today)[0] is not None

    def _collect_unknown_words(self) -> list[str]:
        """Take up to ``MAX_VALUE_WORDS`` words that are not a boundary."""
        words: list[str] = []
        while (
            self.i < len(self.tokens)
            and len(words) < MAX_VALUE_WORDS
            and not self._is_boundary(self.i)
        ):
            words.append(self.tokens[self.i])
            self.i += 1
        return words

    def _is_common(self, word: str) -> bool:
        """An everyday word, or one the user taught Quill to skip: never part of a new value."""
        return word in COMMON_WORDS or word in self.vocab.skip_words

    def _is_boundary(self, j: int) -> bool:
        """True where a run of unknown words should stop."""
        word = self.tokens[j]
        return (
            self._is_common(word)
            or self.vocab.field_at(self.tokens, j) is not None
            or bool(self.vocab.matches_at(self.tokens, j))
            or parse_number(self.tokens, j)[0] is not None
            or self.vocab.sound_alike_at(self.tokens, j) is not None
        )

    # ------------------------------------------------------------------ #
    # Unknown runs                                                         #
    # ------------------------------------------------------------------ #

    def _flush(self) -> None:
        """Turn the pending run of unknown words into candidates.

        A word that closely matches a known value ("levi" for "Levi's") is
        split out first, so "hugo boss levi" yields one candidate and one match.
        """
        if not self.run_words:
            return
        words, self.run_words = self.run_words, []
        # These words were optimistically logged as unmatched; they are
        # candidates now, so take them back out.
        for _ in words:
            self.result.unmatched.pop()

        first = self.i - len(words)               # the run ends just before the cursor
        buffer: list[str] = []
        for offset, word in enumerate([*words, None]):
            close = self.vocab.fuzzy(word) if word else None
            if word is None or close:
                self._emit(buffer)
                buffer = []
                if close:
                    self._set(close[0], close[1], first + offset, first + offset + 1, additive=True)
            else:
                buffer.append(word)

    def _emit(self, words: list[str]) -> None:
        term = " ".join(words)
        if len(term) < 2 or term.isdigit():
            if term:
                self.result.unmatched.append(term)
            return
        self.result.candidates.append(self._candidate(term, None, False))

    def _candidate(self, term: str, column: str | None, hinted: bool) -> Candidate:
        """A candidate for the Term Helper; when it looks like a short code's long form, say so ("medium" for M)."""
        hint = self.vocab.abbreviation_for(term)
        if hint and (column is None or column == hint[0]):
            return Candidate(term, hint[0], hinted, alias_of=hint)
        return Candidate(term, column, hinted)

    # ------------------------------------------------------------------ #
    # Guessing the column for unhinted candidates                          #
    # ------------------------------------------------------------------ #

    def _assign_guesses(self) -> None:
        for cand in self.result.candidates:
            if cand.column is None:
                cand.column = self._guess_column(cand.term)

    def _guess_column(self, term: str) -> str | None:
        """Pick the list an unknown value most likely belongs to, or None.

        Two domain-free signals, in order:
          1. *shape* — if exactly one list's values mostly look like the term
             (same pattern of letters and digits, e.g. ``1990s``), use it;
          2. *elimination* — if exactly one list column is still unfilled in
             this record, use it.
        Otherwise it is better to say "I couldn't tell" than to guess wrong.
        """
        shape = _shape(term)
        by_shape = [
            col for col in self.vocab.columns_for(term)           # type check first: text is never a date or a number
            if self._shape_matches(col, shape)
        ]
        if len(by_shape) == 1:
            return by_shape[0]
        unfilled = [c for c in self.vocab.columns_for(term) if c not in self.filled]
        return unfilled[0] if len(unfilled) == 1 else None

    def _shape_matches(self, column: str, shape: str) -> bool:
        values = self.vocab.values_for(column)
        if not values:
            return False
        same = sum(1 for v in values if _shape(v) == shape)
        return same / len(values) >= _SHAPE_AGREEMENT


def _shape(text: str) -> str:
    """Collapse text to a letter/digit pattern: ``"1990s"`` -> ``"9a"``."""
    pattern = re.sub(r"\d+", "9", text.lower())
    return re.sub(r"[^\W\d_]+", "a", pattern)
