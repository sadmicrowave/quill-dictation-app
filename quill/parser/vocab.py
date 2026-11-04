"""Build and query the runtime vocabulary from workbook list data.

Vocabulary is populated entirely from the workbook's data-validation lists
via WorkbookBridge.get_lists(). No domain-specific terms are hard-coded here.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from quill.learning import LinkStore, link_word
from quill.parser.fillers import is_filler
from quill.parser.sounds import initials_match, same_subject, sounds_like
from quill.parser.tokens import tokenize

#: Header words that suggest an amount of money (picks a default amount column).
MONEY_WORDS = frozenset({
    "price", "cost", "amount", "total", "paid", "value", "fee", "msrp",
    "appraisal", "worth", "estimate",
})


_NUMBER_VALUE = re.compile(r"^[-+]?[$€£]?\s*\d[\d,]*(\.\d+)?\s*%?$")
_DATE_VALUE = re.compile(r"^(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|"
                         r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(,?\s+\d{2,4})?)$", re.I)


def value_kind(text: str) -> str:
    """What kind of thing *text* is: ``"number"``, ``"date"`` or ``"text"`` (a simple check, not a parse)."""
    stripped = text.strip()
    if _NUMBER_VALUE.match(stripped):
        return "number"
    if _DATE_VALUE.match(stripped):
        return "date"
    from quill.parser.numbers import parse_number
    tokens = tokenize(stripped)
    if tokens:
        number, used = parse_number(tokens, 0)
        if number is not None and used == len(tokens):      # spoken: "thirty five"
            return "number"
        if tokens[0] in ("today", "yesterday") and len(tokens) == 1:
            return "date"
    return "text"


def money_header(column: str) -> bool:
    """True if any word of *column*'s header suggests an amount of money."""
    return any(t in MONEY_WORDS for t in tokenize(column))


@dataclass
class VocabEntry:
    """One recognised value in the vocabulary pool."""
    canonical: str       # The exact string to write into the workbook
    column: str          # Which column this value belongs to
    tokens: list[str]    # Lowercased word tokens for matching

    def __str__(self) -> str:
        return self.canonical


class Vocabulary:
    """Searchable vocabulary built from a column → options mapping."""

    _FUZZY_MIN_LEN = 4       # only fuzzy-match terms this long or longer
    _FUZZY_THRESHOLD = 0.85  # difflib ratio threshold

    def __init__(self) -> None:
        self._entries: list[VocabEntry] = []
        # column_name -> list of canonical values (preserves insert order)
        self._by_column: dict[str, list[str]] = {}
        # (tokens, column header) for every spoken field word, longest first
        self._fields: list[tuple[tuple[str, ...], str]] = []
        self._headers: list[str] = []   # every field word's column, in load order
        self.numeric_columns: list[str] = []
        """Headers whose data is numeric; set by the controller from the bridge."""
        self.date_columns: list[str] = []
        """Headers whose data is dates, in sheet order; set by the controller from the bridge."""
        self.links: LinkStore | None = None
        """What the user taught Quill about which column a word means (set by the controller; None: nothing learned)."""
        self.learn_after = 2
        """Corrections of one word to one column before its link is used (the ``learn_after`` setting)."""

    # ------------------------------------------------------------------ #
    # Loading                                                              #
    # ------------------------------------------------------------------ #

    def load(self, lists: dict[str, list[str]], headers: list[str] | None = None) -> None:
        """Populate the vocabulary from a column → values mapping.

        Clears any previously loaded entries first.

        Args:
            lists: Column header -> valid values (from ``bridge.get_lists()``).
            headers: Every header of the target sheet (from
                ``bridge.get_headers()``). These become spoken *field words*,
                so columns without a drop-down (a price, notes) can be
                dictated too. List columns are always field words as well.
        """
        self._entries.clear()
        self._by_column.clear()
        self._fields = []
        self._headers = []
        for name in [*(headers or []), *lists.keys()]:
            self._add_field(name)
        for column, values in lists.items():
            col_list: list[str] = []
            for value in values:
                if not value or not str(value).strip():
                    continue
                canonical = str(value).strip()
                tokens = _tokenize(canonical.lower())
                self._entries.append(VocabEntry(canonical, column, tokens))
                col_list.append(canonical)
            self._by_column[column] = col_list

    def add(self, column: str, value: str) -> None:
        """Add a single new value to an existing column's list."""
        canonical = value.strip()
        if not canonical:
            return
        existing = self._by_column.get(column, [])
        if canonical.lower() in (v.lower() for v in existing):
            return
        tokens = _tokenize(canonical.lower())
        self._entries.append(VocabEntry(canonical, column, tokens))
        self._by_column.setdefault(column, []).append(canonical)
        self._add_field(column)

    def _add_field(self, column: str) -> None:
        """Register *column*'s header as a spoken field word (once)."""
        tokens = tuple(_tokenize(column))
        if not tokens or any(f == (tokens, column) for f in self._fields):
            return
        self._fields.append((tokens, column))
        self._headers.append(column)
        self._fields.sort(key=lambda f: len(f[0]), reverse=True)

    # ------------------------------------------------------------------ #
    # Querying                                                             #
    # ------------------------------------------------------------------ #

    def columns(self) -> list[str]:
        """Return all column names that have at least one value."""
        return list(self._by_column.keys())

    def values_for(self, column: str) -> list[str]:
        """Return canonical values for a column (empty list if unknown)."""
        return list(self._by_column.get(column, []))

    def column_kind(self, column: str) -> str:
        """``"number"`` or ``"date"`` if every value in the column's list is one, otherwise ``"text"``."""
        kinds = {value_kind(v) for v in self._by_column.get(column, [])}
        return kinds.pop() if len(kinds) == 1 else "text"

    def accepts(self, column: str, term: str) -> bool:
        """Could *term* be a new value of *column*? A list of numbers only takes numbers and a list of
        dates only dates ("teal" is never either); a list of words takes anything."""
        kind = self.column_kind(column)
        return kind == "text" or value_kind(term) == kind

    def columns_for(self, term: str) -> list[str]:
        """The list columns *term* could be added to, in sheet order."""
        return [c for c in self._by_column if self.accepts(c, term)]

    def add_alias(self, column: str, phrase: str, canonical: str) -> bool:
        """Teach that spoken *phrase* means the existing value *canonical*.

        Example: ``add_alias("Size", "extra large", "XL")``. Does nothing (and
        returns False) if *canonical* isn't a value of *column*.
        """
        known = {v.lower(): v for v in self._by_column.get(column, [])}
        actual = known.get(canonical.strip().lower())
        tokens = _tokenize(phrase)
        if actual is None or not tokens:
            return False
        if not any(e.column == column and e.canonical == actual and e.tokens == tokens
                   for e in self._entries):
            self._entries.append(VocabEntry(actual, column, tokens))
        return True

    def remove(self, column: str, value: str) -> None:
        """Forget a value added with :meth:`add` (and any synonyms that pointed at it)."""
        target = value.strip().lower()
        self._by_column[column] = [v for v in self._by_column.get(column, [])
                                   if v.lower() != target]
        self._entries[:] = [e for e in self._entries
                            if not (e.column == column and e.canonical.lower() == target)]

    def remove_alias(self, column: str, phrase: str, canonical: str) -> None:
        """Forget a synonym taught with :meth:`add_alias` (the value itself stays)."""
        tokens = _tokenize(phrase)
        self._entries[:] = [e for e in self._entries
                            if not (e.column == column and e.tokens == tokens
                                    and e.canonical.lower() == canonical.lower()
                                    and tokens != _tokenize(e.canonical.lower()))]

    def amount_columns(self) -> list[str]:
        """The columns a bare amount could belong to: non-list columns that hold numbers or have a money-like header."""
        return [c for c in self.headers()
                if not self.is_list_column(c) and (c in self.numeric_columns or money_header(c))]

    def amount_column_for(self, tokens: list[str], i: int, end: int) -> tuple[str | None, str | None]:
        """The column a bare amount at ``tokens[i:end]`` belongs to: a word the user taught (nearest first, among every
        amount column), else the sheet's own default (see :meth:`default_amount_column`)."""
        if self.links is not None:
            chosen = self.links.choose(self.context_words(tokens, i, end), self.amount_columns(), self.learn_after)
            if chosen is not None:
                return chosen[0], f"'{chosen[1]}' used for {chosen[0]} (learned)"
        return self.default_amount_column()

    def default_amount_column(self) -> tuple[str | None, str | None]:
        """The column a bare amount ("under 50", "thirty dollars") belongs to.

        Candidates are non-list columns that hold numbers or have a money-like
        header; money-like headers win, and the leftmost is used.

        Returns:
            ``(column_or_None, note_or_None)``; the note says when other
            candidates existed so the user can choose another by name.
        """
        cands = [c for c in self.headers()
                 if not self.is_list_column(c) and (c in self.numeric_columns or money_header(c))]
        pool = [c for c in cands if money_header(c)] or cands
        if not pool:
            return None, None
        if len(pool) == 1:
            return pool[0], None
        return pool[0], (f"'{pool[0]}' used for the amount; say a column name to use "
                         f"another ({', '.join(pool[1:])})")

    #: Header words that only say "this is a date"; they never identify *which* date column is meant.
    _DATE_NOISE = frozenset({"date", "dated", "day", "time", "when", "on", "of", "the"})

    @staticmethod
    def context_words(tokens: list[str], i: int, end: int | None = None) -> list[str]:
        """The words spoken around the value at ``tokens[i:end]`` (one word by default), nearest first, that a link can be made
        from (no small words or numbers; the value's own words are never included)."""
        end = i + 1 if end is None else end
        order = [*range(i - 1, max(i - 7, -1), -1), *range(end, min(end + 3, len(tokens)))]
        return [tokens[j] for j in order if link_word(tokens[j]) is not None]

    def date_column_for(self, tokens: list[str], i: int, filled: set[str],
                        end: int | None = None) -> tuple[str | None, str | None]:
        """The date column a spoken date at ``tokens[i]`` belongs to when no column name was said.

        Nothing here knows any subject. Three things decide; the last two come from the spreadsheet itself:

        1. a word the user taught (see :mod:`quill.learning`), nearest first: "spotted" -> Observation Date;
        2. a word spoken near the date that is a form of a word in a date column's header ("departed" near
           a "Departure Date" column, "observed" near "Observation Date") picks that column;
        3. otherwise the first date column, in sheet order, that is still empty in this row (so a second
           bare date goes to the second date column).

        Returns:
            ``(column_or_None, note_or_None)``; the note says when other date columns existed so the
            user can choose another by naming it.
        """
        if not self.date_columns:
            return None, None
        spoken = self.context_words(tokens, i, end)
        if self.links is not None:
            chosen = self.links.choose(spoken, self.date_columns, self.learn_after)
            if chosen is not None:
                return chosen[0], f"'{chosen[1]}' used for {chosen[0]} (learned)"
        nearby = [w for w in spoken if not is_filler(w)]                  # (a header's own words are matched by plain words only)
        headers = {c: [w for w in tokenize(c) if w not in self._DATE_NOISE] for c in self.date_columns}
        for word in nearby:
            for column, header in headers.items():
                if any(same_subject(word, h) for h in header):
                    return column, None
        open_columns = [c for c in self.date_columns if c not in filled]
        column = (open_columns or self.date_columns)[0]
        others = [c for c in self.date_columns if c != column]
        note = (f"'{column}' used for the date; say a column name to use another ({', '.join(others)})"
                if others else None)
        return column, note

    def headers(self) -> list[str]:
        """Every known column: sheet headers in sheet order, then list-only columns."""
        return list(self._headers)

    def is_list_column(self, column: str) -> bool:
        """True if *column* has a drop-down list of known values."""
        return column in self._by_column

    def field_at(self, tokens: list[str], i: int) -> tuple[str, int] | None:
        """Return ``(column, length)`` if a field word starts at ``tokens[i]``."""
        for toks, column in self._fields:
            n = len(toks)
            if tuple(tokens[i:i + n]) == toks:
                return column, n
        return None

    def matches_at(self, tokens: list[str], i: int) -> list[tuple[str, str, int]]:
        """Return ``[(column, canonical, length)]`` for values matching at ``tokens[i]``.

        A leading "the" is optional, so "north face" matches "The North Face".
        """
        found = []
        for entry in self._entries:
            variants = [entry.tokens]
            if len(entry.tokens) > 1 and entry.tokens[0] == "the":
                variants.append(entry.tokens[1:])
            for toks in variants:
                n = len(toks)
                if n and tokens[i:i + n] == toks:
                    found.append((entry.column, entry.canonical, n))
                    break
        return found

    def sound_alike_at(self, tokens: list[str], i: int) -> tuple[str, str, str | None, str] | None:
        """A single heard word that is probably a mis-hearing of a column name or a list value.

        Only called when nothing matched exactly. Returns ``(kind, column, canonical, known_word)`` with
        *kind* ``"field"`` (``canonical`` is None) or ``"value"``, or None when there is no single clear
        candidate (two different targets would be a guess). Fillers and numbers are never corrected.
        """
        word = tokens[i]
        if len(word) < 4 or is_filler(word) or any(ch.isdigit() for ch in word):
            return None
        found: dict[tuple[str, str, str | None], str] = {}
        for toks, column in self._fields:
            if len(toks) == 1 and sounds_like(word, toks[0]):
                found[("field", column, None)] = toks[0]
        for entry in self._entries:
            if len(entry.tokens) == 1 and sounds_like(word, entry.tokens[0]):
                found[("value", entry.column, entry.canonical)] = entry.tokens[0]
        if len(found) != 1:
            return None
        (kind, column, canonical), known = next(iter(found.items()))
        return kind, column, canonical, known

    def abbreviation_for(self, term: str) -> tuple[str, str] | None:
        """The short code a spoken *term* is probably the long form of: "medium" for ``M``, "extra large" for ``XL``.

        Only columns made up mostly of short codes (like sizes) are considered, and the answer must be the
        only match. It is a suggestion for the Term Helper, never written without the user's yes.
        """
        words = tokenize(term)
        if not 1 <= len(words) <= 3:
            return None
        hits = []
        for column, values in self._by_column.items():
            codes = [v for v in values if len(v) <= 3 and v.isalpha()]
            if len(codes) * 10 < len(values) * 6:            # fewer than 60% of the values are short codes
                continue
            hits += [(column, v) for v in codes if initials_match(v, words)]
        return hits[0] if len(hits) == 1 else None

    def fuzzy(self, term: str) -> tuple[str, str] | None:
        """Close-spelling match to a known value, e.g. ``"levi"`` for ``"Levi's"``.

        Returns ``(column, canonical)`` or None. Needs at least
        ``_FUZZY_MIN_LEN`` letters so short words must match exactly.
        """
        text = " ".join(_tokenize(term))
        if len(text) < self._FUZZY_MIN_LEN:
            return None
        best: tuple[float, str, str] | None = None
        for entry in self._entries:
            cand = " ".join(entry.tokens)
            if len(cand) < self._FUZZY_MIN_LEN:
                continue
            ratio = difflib.SequenceMatcher(None, text, cand).ratio()
            if ratio >= self._FUZZY_THRESHOLD and (best is None or ratio > best[0]):
                best = (ratio, entry.column, entry.canonical)
        return (best[1], best[2]) if best else None

    def match(self, term: str) -> VocabEntry | None:
        """Find the best vocabulary entry for a spoken term.

        First tries an exact (case-insensitive) match, then a fuzzy match
        against multi-word canonical values, then token-level fuzzy matching.
        Returns None if no confident match is found.
        """
        lower = term.lower().strip()
        tokens = _tokenize(lower)

        # 1. Exact canonical match (case-insensitive)
        for entry in self._entries:
            if entry.canonical.lower() == lower:
                return entry

        # 2. Fuzzy match against the full canonical string
        best_entry: VocabEntry | None = None
        best_ratio = 0.0
        for entry in self._entries:
            if len(lower) < self._FUZZY_MIN_LEN:
                continue
            ratio = difflib.SequenceMatcher(None, lower, entry.canonical.lower()).ratio()
            if ratio > best_ratio and ratio >= self._FUZZY_THRESHOLD:
                best_ratio = ratio
                best_entry = entry
        if best_entry:
            return best_entry

        # 3. Token-level match: every spoken token appears in the entry's tokens
        if tokens:
            for entry in self._entries:
                if all(t in entry.tokens for t in tokens):
                    return entry

        return None

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return (
            f"Vocabulary({len(self._entries)} entries, "
            f"{len(self._by_column)} columns)"
        )


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _tokenize(text: str) -> list[str]:
    """Split text into lowercase word/number tokens (see ``tokens.tokenize``)."""
    return tokenize(text)
