"""A bounded history of the user's sorting decisions, walked backwards by undo.

Each entry knows how to reverse itself. The history keeps only the most recent
:data:`HISTORY_LIMIT` entries, so it cannot grow without end however long Quill
runs; the oldest entry quietly drops off when a new one arrives.
"""

from __future__ import annotations
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

#: Most recent actions that can be undone.
HISTORY_LIMIT = 100


@dataclass
class HistoryEntry:
    """One undoable action."""

    label: str
    """What was done, in plain words ("Added ‘teal’ to Color")."""
    undo: Callable[[], list[str]]
    """Reverses it; returns notes about anything it could not put back."""


class History:
    """A capped stack of :class:`HistoryEntry` (newest last).

    Args:
        limit: Maximum entries kept (default :data:`HISTORY_LIMIT`).
    """

    def __init__(self, limit: int = HISTORY_LIMIT) -> None:
        self._entries: deque[HistoryEntry] = deque(maxlen=limit)
        self._group: list[HistoryEntry] | None = None
        self._label = ""

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def push(self, label: str, undo: Callable[[], list[str]]) -> None:
        """Record an action (inside :meth:`group`, it joins the open group)."""
        entry = HistoryEntry(label, undo)
        if self._group is not None:
            self._group.append(entry)
        else:
            self._entries.append(entry)

    @contextmanager
    def group(self, label: str) -> Iterator[None]:
        """Make everything pushed inside count as one action ("Added 4 terms").

        Groups do not nest; an inner ``group`` simply joins the outer one.
        """
        if self._group is not None:
            yield
            return
        self._group, self._label = [], label
        try:
            yield
        finally:
            self._flush_group()
            self._group = None

    def _flush_group(self) -> None:
        """Turn what the open group has collected so far into one entry."""
        parts, self._group = self._group or [], []
        if len(parts) == 1:
            self._entries.append(parts[0])
        elif parts:
            self._entries.append(HistoryEntry(self._label, lambda: _undo_all(parts)))

    def pop(self) -> HistoryEntry | None:
        """Remove and return the newest entry, or None when empty."""
        if self._group:
            self._flush_group()      # an undo mid-group must see what was just done
        return self._entries.pop() if self._entries else None


def _undo_all(parts: list[HistoryEntry]) -> list[str]:
    notes: list[str] = []
    for entry in reversed(parts):
        notes += entry.undo()
    return notes
