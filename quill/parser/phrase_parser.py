"""Generalised spoken phrase parser.

Turns a raw speech transcript into a dict of column -> value mappings,
using only the vocabulary loaded from the active workbook. No domain-
specific terms appear here.

Implemented fully in Phase 5. This stub defines the public interface
so the rest of the app can import against it immediately.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from quill.parser.vocab import Vocabulary


@dataclass
class ParseResult:
    """Output of a single parse call."""
    updates: dict[str, str] = field(default_factory=dict)
    """column -> canonical value for terms that matched the vocabulary."""

    notes: str = ""
    """Free-text capture (anything following a 'note' keyword)."""

    price_purchase: float | None = None
    """Purchase / cost price parsed from speech."""

    price_sale: float | None = None
    """Sale / sold-for price parsed from speech."""

    date_purchase: str | None = None
    """Purchase date as ISO string (YYYY-MM-DD), if spoken."""

    date_sale: str | None = None
    """Sale date as ISO string (YYYY-MM-DD), if spoken."""

    unmatched: list[str] = field(default_factory=list)
    """Terms the parser heard but could not match to any column."""

    assumptions: list[str] = field(default_factory=list)
    """Human-readable notes about guesses made (e.g. 'assumed Brand')."""


def parse(text: str, vocab: Vocabulary) -> ParseResult:
    """Parse a spoken transcript segment into field values.

    Args:
        text:  Raw lowercase transcript from the speech recogniser.
        vocab: Vocabulary loaded from the active workbook.

    Returns:
        ParseResult with matched fields and any unmatched terms.

    Note:
        Full implementation in Phase 5. Currently returns an empty result.
    """
    # TODO (Phase 5): implement tokenisation, keyword detection,
    # price/date extraction, vocab matching, and unknown-term pooling.
    return ParseResult()
