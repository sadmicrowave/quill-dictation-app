"""Turn a spoken search ("black blouses under 50") into column filters.

Uses the same vocabulary as dictation, so it is domain-free: values are
looked up in the workbook's lists (plurals allowed: "blouses" finds "Blouse"),
and comparison phrases become numeric tests.

    "black blouses under 50"  ->  Color = Black, Type = Blouse, Purchase Price < 50

Comparison phrases: under/below/less than (<), at most/up to/no more than
(<=), over/above/more than/greater than (>), at least/no less than (>=),
exactly/equals (=). The number applies to a column named just before it
("sale price under 20"); otherwise to the first money-like numeric column,
with an assumption noted.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from quill.bridge.filters import ColumnFilter
from quill.parser.numbers import parse_number
from quill.parser.phrase_parser import COMMON_WORDS, FILLERS
from quill.parser.tokens import tokenize
from quill.parser.vocab import Vocabulary

#: Comparison phrases, tried longest first.
COMPARATORS: list[tuple[tuple[str, ...], str]] = sorted(
    [
        (("less", "than"), "<"), (("lower", "than"), "<"), (("cheaper", "than"), "<"),
        (("fewer", "than"), "<"), (("under",), "<"), (("below",), "<"),
        (("no", "more", "than"), "<="), (("at", "most"), "<="), (("up", "to"), "<="),
        (("more", "than"), ">"), (("greater", "than"), ">"), (("higher", "than"), ">"),
        (("over",), ">"), (("above",), ">"), (("exceeding",), ">"),
        (("at", "least"), ">="), (("no", "less", "than"), ">="),
        (("exactly",), "="), (("equal", "to"), "="), (("equals",), "="),
    ],
    key=lambda c: len(c[0]), reverse=True,
)

#: Longest value (in words) tried when matching a plural in a search.
_MAX_VALUE_WORDS = 4


@dataclass
class SearchQuery:
    """The result of parsing a spoken search."""

    filters: list[ColumnFilter] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    """Words that matched no list value or column."""
    assumptions: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    """Things that made part of the search unusable (e.g. no numeric column)."""


def _singulars(word: str) -> list[str]:
    """Plausible singular forms of *word* ("blouses" -> "blouse")."""
    out = []
    if word.endswith("ies") and len(word) > 4:
        out.append(word[:-3] + "y")
    if word.endswith("es") and len(word) > 3:
        out.append(word[:-2])
    if word.endswith("s") and len(word) > 2:
        out.append(word[:-1])
    return out


def _match_value(vocab: Vocabulary, tokens: list[str], i: int):
    """Longest vocabulary match at *i*, retrying with a singularised last word.

    Returns ``(matches, length)`` where matches is the vocab hit list.
    """
    hits = vocab.matches_at(tokens, i)
    if hits:
        return hits, max(h[2] for h in hits)
    for n in range(min(_MAX_VALUE_WORDS, len(tokens) - i), 0, -1):
        span = tokens[i:i + n]
        for singular in _singulars(span[-1]):
            hits = [h for h in vocab.matches_at([*span[:-1], singular], 0) if h[2] == n]
            if hits:
                return hits, n
    return [], 0


def _comparator_at(tokens: list[str], i: int):
    for words, op in COMPARATORS:
        if tuple(tokens[i:i + len(words)]) == words:
            return op, len(words)
    return None


def parse_search(text: str, vocab: Vocabulary, numeric_columns: list[str]) -> SearchQuery:
    """Parse spoken search words into per-column filters.

    Args:
        text: The words after "search for".
        vocab: Vocabulary of the active sheet.
        numeric_columns: Headers whose data is numeric (from the bridge).
    """
    vocab.numeric_columns = list(numeric_columns)
    tokens = tokenize(text)
    query = SearchQuery()
    values: dict[str, list[str]] = {}
    comparisons: dict[str, list[tuple[str, float]]] = {}
    order = {c: k for k, c in enumerate(vocab.columns())}
    named: str | None = None   # column named by the last field word
    i = 0
    while i < len(tokens):
        field_hit = vocab.field_at(tokens, i)
        if field_hit:
            named = field_hit[0]
            i += field_hit[1]
            continue

        comp = _comparator_at(tokens, i)
        if comp:
            op, length = comp
            j = i + length
            while j < len(tokens) and tokens[j] in FILLERS:
                j += 1
            number, used = parse_number(tokens, j)
            if number is None:
                query.unmatched.append(" ".join(tokens[i:j]))
                i = max(j, i + 1)
                continue
            column = named if named and not vocab.is_list_column(named) else None
            if column is None:
                column, note = vocab.default_amount_column()
                if note:
                    query.assumptions.append(note)
            if column is None:
                query.problems.append(
                    f"'{op} {number:g}' needs a number column, and I couldn't find one."
                )
            else:
                comparisons.setdefault(column, []).append((op, number))
            named = None
            i = j + used
            continue

        hits, length = _match_value(vocab, tokens, i)
        if hits:
            if named:
                preferred = [h for h in hits if h[0] == named]
                hits = preferred or hits
            hits.sort(key=lambda h: (-h[2], order.get(h[0], len(order))))
            column, canonical, _ = hits[0]
            if len({h[0] for h in hits if h[2] == hits[0][2]}) > 1:
                query.assumptions.append(f"'{canonical}' taken as {column}")
            bucket = values.setdefault(column, [])
            if canonical not in bucket:
                bucket.append(canonical)
            named = None
            i += max(length, 1)
            continue

        if tokens[i] not in COMMON_WORDS and tokens[i] not in FILLERS:
            query.unmatched.append(tokens[i])
        i += 1

    query.filters = [ColumnFilter(c, values=v) for c, v in values.items()]
    for column, tests in comparisons.items():
        query.filters.append(ColumnFilter(column, comparisons=tests[:2]))
    return query
