"""Listening gate, row building, and the new-values question.

A :class:`Session` is a pure state machine: it consumes recognised text and
returns :class:`Event` objects describing what happened. It touches no
workbook, audio or UI, so the whole dictation flow is testable on any machine;
:class:`quill.controller.Controller` carries the events out.

Flow:
  * Speech is ignored until a START_LISTENING keyword opens the gate.
  * Each spoken segment updates the record (the row being built).
  * NEXT_ROW commits the record; DELETE_ROW discards it.
  * Unknown values are pooled. When the row ends (NEXT_ROW) or listening stops,
    one question is asked: "... Add them? Say yes or no." A yes adds them to
    the vocabulary (and, via the controller, the workbook); a no discards them.
"""

from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

from quill.parser.commands import (
    NO_WORDS, YES_WORDS, Action, CommandEvent, CommandMatcher,
)
from quill.parser.phrase_parser import parse
from quill.parser.tokens import display_name, tokenize
from quill.parser.vocab import Vocabulary


def _join(items: list[str]) -> str:
    """Join with commas and a final 'and': ``["a", "b", "c"]`` -> ``"a, b and c"``."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def prompt_text(pending: list[tuple[str, str]]) -> str:
    """Build the spoken question for pending ``(column, term)`` pairs.

    Example:
        "I heard a new value. Obsidian isn't in the Color list. Add it? Say yes or no."
    """
    groups: dict[str, list[str]] = {}
    for column, term in pending:
        groups.setdefault(column, []).append(display_name(term))
    sentences = [
        f"{_join(terms)} {'isn' if len(terms) == 1 else 'aren'}'t in the {column} list."
        for column, terms in groups.items()
    ]
    many = len(pending) > 1
    return (
        f"I heard {'new values' if many else 'a new value'}. "
        + " ".join(sentences)
        + f" Add {'them' if many else 'it'}? Say yes or no."
    )


@dataclass
class Event:
    """Something that happened while processing speech."""

    kind: str
    """One of: started, stopped, updated, committed, discarded, ignored, unsure,
    search, clear_search, confirm, add_values, skipped, expired, error.
    The controller rewrites ``search``/``clear_search`` into ``searched`` /
    ``cleared`` (or ``unsure`` / ``error``) once it has acted on them."""

    record: dict | None = None
    detail: str = ""
    values: list | None = None


@dataclass
class Session:
    """Dictation state for one workbook.

    Args:
        vocab: Vocabulary loaded from the workbook (mutated when values are added).
        matcher: Keyword matcher built from the user's settings.
        today: Callable giving today's date (injectable for tests).
    """

    vocab: Vocabulary
    matcher: CommandMatcher
    today: Callable[[], dt.date] = dt.date.today
    listening: bool = False
    record: dict = field(default_factory=dict)
    committed: int = 0
    ignored_while_stopped: int = 0
    pool: dict = field(default_factory=dict)        # (column, term) -> times heard
    row_terms: set = field(default_factory=set)     # pool keys heard in the current row
    pending: list | None = None                     # (column, term) awaiting yes/no

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def feed(self, text: str) -> list[Event]:
        """Process one recognised phrase and return the events it caused."""
        events: list[Event] = []
        tokens = tokenize(text)
        if self.pending is not None and tokens and tokens[0] in YES_WORDS | NO_WORDS:
            events += self._answer(tokens[0] in YES_WORDS)
            text = " ".join(tokens[1:])

        for segment in self.matcher.split(text):
            if isinstance(segment, CommandEvent):
                events += self._command(segment)
            else:
                events += self._segment(segment)
        return events

    def expire_prompt(self) -> list[Event]:
        """No answer in time: keep the values and ask again at the next pause."""
        if self.pending is None:
            return []
        for key in self.pending:
            self.pool[key] = self.pool.get(key, 0) + 1
        self.pending = None
        return [Event("expired", detail="No answer. I'll ask again at the next pause.")]

    def apply(self, action: Action) -> list[Event]:
        """Run a command without speech (a tray click, a menu item)."""
        return self._command(CommandEvent(action))

    def restore(self, record: dict) -> None:
        """Put back a record whose write failed, so nothing the user said is lost."""
        self.record = {**record, **self.record}
        self.committed = max(0, self.committed - 1)

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _segment(self, text: str) -> list[Event]:
        if not text:
            return []
        if not self.listening:
            self.ignored_while_stopped += 1
            return []

        result = parse(text, self.vocab, self.today(), filled=set(self.record))
        self.record.update(result.updates)
        events: list[Event] = []
        unsure: list[str] = []
        for cand in result.candidates:
            if cand.column is None:
                unsure.append(cand.term)
                continue
            key = (cand.column, cand.term)
            self.pool[key] = self.pool.get(key, 0) + 1
            self.row_terms.add(key)
        if result.updates or result.candidates:
            detail = ", ".join(f"{k}={_show(v)}" for k, v in result.updates.items())
            events.append(Event("updated", detail=detail))
        for term in unsure:
            events.append(Event(
                "unsure",
                detail=(f"Heard '{term}' but couldn't tell which column it belongs to. "
                        "Say the column name first, like 'color obsidian'."),
            ))
        for note in result.assumptions:
            events.append(Event("ignored", detail=f"Assumed: {note}"))
        return events

    def _command(self, command: CommandEvent) -> list[Event]:
        action = command.action
        if action is Action.START_LISTENING:
            self.listening = True
            return [Event("started", detail="Listening")]
        if action is Action.STOP_LISTENING:
            self.listening = False
            return [Event("stopped", detail="Not listening")] + self._ask_if_needed()
        if not self.listening:
            return [Event("ignored", detail=f"{action.name.replace('_', ' ').title()} heard while stopped")]
        if action is Action.NEXT_ROW:
            return self._commit()
        if action is Action.DELETE_ROW:
            return self._discard()
        if action is Action.SEARCH_FOR:
            if not command.remainder:
                return [Event("ignored", detail="Say what to search for, like 'search for black shirts under 50'")]
            return [Event("search", detail=command.remainder)]
        if action is Action.CLEAR_SEARCH:
            return [Event("clear_search")]
        return []

    def _commit(self) -> list[Event]:
        events: list[Event] = []
        if self.record:
            row, self.record = dict(self.record), {}
            self.row_terms.clear()
            self.committed += 1
            events.append(Event("committed", record=row))
        else:
            events.append(Event("ignored", detail="Nothing to save yet"))
        return events + self._ask_if_needed()

    def _discard(self) -> list[Event]:
        if not self.record and not self.row_terms:
            return [Event("ignored", detail="Nothing to discard")]
        for key in self.row_terms:
            self.pool.pop(key, None)
        self.row_terms.clear()
        row, self.record = dict(self.record), {}
        return [Event("discarded", record=row, detail="Row discarded")]

    def _ask_if_needed(self) -> list[Event]:
        if not self.pool:
            return []
        items = sorted(self.pool)
        self.pool = {}
        if self.pending is None:
            self.pending = items
        else:
            self.pending += [k for k in items if k not in self.pending]
        return [Event("confirm", detail=prompt_text(self.pending), values=list(self.pending))]

    def _answer(self, yes: bool) -> list[Event]:
        pending, self.pending = self.pending, None
        if not yes:
            return [Event("skipped", detail="Not added")]
        values = []
        for column, term in pending:
            value = display_name(term)
            self.vocab.add(column, value)
            values.append((column, value))
        return [Event("add_values", detail="Added", values=values)]


def _show(value: object) -> str:
    """Compact text for a field value in log lines."""
    return value.isoformat() if isinstance(value, dt.date) else str(value)
