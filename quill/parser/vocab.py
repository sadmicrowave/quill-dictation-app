"""Build and query the runtime vocabulary from workbook list data.

Vocabulary is populated entirely from the workbook's data-validation lists
via WorkbookBridge.get_lists(). No domain-specific terms are hard-coded here.
"""

from __future__ import annotations
import difflib
from dataclasses import dataclass, field

from quill.parser.tokens import tokenize


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
