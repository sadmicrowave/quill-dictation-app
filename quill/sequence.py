"""Numbering a column continues: a column whose last values count up by one (41, 42, 43; or A-0041, A-0042, A-0043) is a counter, and
the row being built gets the next number unless the user says a value for it.

Nothing here looks at a heading: the sheet's own data says it. A column is a counter when its **last three or more non-blank values are
consecutive** (each one more than the one before, with the same text around the number and the same zero padding). Dates, text, a
column that jumps, or one that holds a formula (a formula's text is not a number) is not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Fewest values in the run before a column counts as a counter (fewer is too easily a coincidence, such as a quantity that went 1, 2, 3).
MIN_RUN = 3
#: Most values shown in the explanation ("41, 42, 43 → 44").
SHOWN = 3

_PARTS = re.compile(r"^(?P<pre>.*?)(?P<num>\d+)(?P<suf>\D*)$", re.DOTALL)


@dataclass(frozen=True)
class Sequence:
    """A counter column and what comes next in it."""

    next: object
    """The value for the new row: an ``int`` when the column holds numbers, else text in the column's own form (``A-0044``)."""
    seen: tuple[str, ...]
    """The last values, as text, oldest first."""

    @property
    def explanation(self) -> str:
        """The run Quill saw and what it continues it with: ``A-0041, A-0042, A-0043 → A-0044``."""
        return f"{', '.join(self.seen[-SHOWN:])} → {self.next}"


def _parts(value: object) -> tuple[str, int, str, int] | None:
    """``(text before, number, text after, digits)`` of a cell (the number is its *last* run of digits; *digits* is how many it was written
    with), or None when it is not a counting value."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer() or value < 0:
            return None
        value = int(value)
    if isinstance(value, int):
        return ("", value, "", len(str(value))) if value >= 0 else None
    if not isinstance(value, str):
        return None
    found = _PARTS.match(value.strip())
    if found is None:
        return None
    digits = found["num"]
    return found["pre"], int(digits), found["suf"], len(digits)


def _follows(before: tuple[str, int, str, int], after: tuple[str, int, str, int]) -> bool:
    """Is *after* the next value after *before*: the same text around the number, one more, written the same way (the same number of
    digits, or one more digit only where no zero was padding it: 9 then 10, never 01 then 002)."""
    (pre, number, suffix, width), (pre2, number2, suffix2, width2) = before, after
    if (pre, suffix) != (pre2, suffix2) or number + 1 != number2:
        return False
    return width == width2 or (width == len(str(number)) and width2 == len(str(number2)))


def _shown(value: object) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value).strip()


def detect(values: list[object]) -> Sequence | None:
    """The counter the last of *values* (a column's non-blank cells, in sheet order) belong to, or None.

    The run is the longest stretch at the end where each value is one more than the one before, with the same text before and after
    the number. It must be at least :data:`MIN_RUN` long."""
    parts = [_parts(v) for v in values]
    if not parts or parts[-1] is None:
        return None
    run = 1
    for before, after in zip(reversed(parts[:-1]), reversed(parts[1:]), strict=True):
        if before is None or not _follows(before, after):
            break
        run += 1
    if run < MIN_RUN:
        return None
    prefix, number, suffix, width = parts[-1]
    successor = number + 1
    if not prefix and not suffix and all(isinstance(v, (int, float)) for v in values[-run:]):
        return Sequence(successor, tuple(_shown(v) for v in values[-run:]))            # (numbers stay numbers)
    return Sequence(f"{prefix}{str(successor).zfill(width)}{suffix}", tuple(_shown(v) for v in values[-run:]))
