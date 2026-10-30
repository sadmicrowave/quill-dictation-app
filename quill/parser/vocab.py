"""Build and query the runtime vocabulary from workbook list data.

Vocabulary is populated entirely from the workbook's data-validation lists
via WorkbookBridge.get_lists(). No domain-specific terms are hard-coded here.
"""

from __future__ import annotations
import difflib
from dataclasses import dataclass, field


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

    # ------------------------------------------------------------------ #
    # Loading                                                              #
    # ------------------------------------------------------------------ #

    def load(self, lists: dict[str, list[str]]) -> None:
        """Populate the vocabulary from a column → values mapping.

        Clears any previously loaded entries first.
        """
        self._entries.clear()
        self._by_column.clear()
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
        tokens = _tokenize(canonical.lower())
        self._entries.append(VocabEntry(canonical, column, tokens))
        self._by_column.setdefault(column, []).append(canonical)

    # ------------------------------------------------------------------ #
    # Querying                                                             #
    # ------------------------------------------------------------------ #

    def columns(self) -> list[str]:
        """Return all column names that have at least one value."""
        return list(self._by_column.keys())

    def values_for(self, column: str) -> list[str]:
        """Return canonical values for a column (empty list if unknown)."""
        return list(self._by_column.get(column, []))

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
    """Split text into lowercase alpha/digit tokens, dropping punctuation."""
    import re
    return re.findall(r"[a-z0-9]+", text.lower())
