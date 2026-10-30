"""Column filters: the platform-neutral description of a spoken search.

A :class:`ColumnFilter` says "this column must equal one of these values" or
"this column must satisfy these numeric comparisons". Bridges translate it
into an Excel AutoFilter (live) or evaluate it directly (file bridge).
"""

from __future__ import annotations
from dataclasses import dataclass, field

#: Supported comparison operators.
OPERATORS = ("<", "<=", ">", ">=", "=")


@dataclass
class ColumnFilter:
    """One column's share of a search.

    A filter uses *either* ``values`` (text equality, any of) *or*
    ``comparisons`` (up to two numeric tests, all must hold), never both.
    """

    column: str
    values: list[str] = field(default_factory=list)
    comparisons: list[tuple[str, float]] = field(default_factory=list)

    def matches(self, cell: object) -> bool:
        """True if a cell value passes this filter (case-insensitive text)."""
        if self.values:
            text = "" if cell is None else str(cell).strip().lower()
            return text in {v.lower() for v in self.values}
        if not self.comparisons:
            return True
        if isinstance(cell, bool) or not isinstance(cell, (int, float)):
            return False
        return all(_compare(cell, op, limit) for op, limit in self.comparisons)

    def describe(self) -> str:
        """Short human text: ``Color = Black or Navy``, ``Price < 50``."""
        if self.values:
            return f"{self.column} = {' or '.join(self.values)}"
        return " and ".join(f"{self.column} {op} {limit:g}" for op, limit in self.comparisons)


def _compare(value: float, op: str, limit: float) -> bool:
    return {
        "<": value < limit, "<=": value <= limit,
        ">": value > limit, ">=": value >= limit, "=": value == limit,
    }[op]
