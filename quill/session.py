"""Listening gate, row building, and sorting of unrecognised terms.

A :class:`Session` is a pure state machine: it consumes recognised text and
returns :class:`Event` objects describing what happened. It touches no
workbook, audio or UI, so the whole dictation flow is testable on any machine;
:class:`quill.controller.Controller` carries the events out.

Flow:
  * Speech is ignored until a START_LISTENING keyword opens the gate.
  * Each spoken segment updates the record (the row being built).
  * NEXT_ROW commits the record; DELETE_ROW discards it.
  * Words that match nothing are *terms to sort*. They are collected while the
    row is built; when the row ends (NEXT_ROW) or listening stops they become
    *pending* and the UI lists them ("You said '90s' - is that an Era?").
  * Each pending term is resolved with a :class:`Decision`: add it as a new
    value of a column, say it is another name for an existing value (alias), or
    ignore it. A voice "yes" accepts every suggestion; "no" ignores them all.
  * A term heard in a row that was already saved remembers that row, so
    resolving it can back-fill the empty cell.
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

#: A term to sort: (suggested column or None, spoken words).
TermKey = tuple["str | None", str]


def _join(items: list[str]) -> str:
    """Join with commas and a final 'and': ``["a", "b", "c"]`` -> ``"a, b and c"``."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def prompt_text(pending: list[TermKey]) -> str:
    """Build the spoken question when every pending term has a suggested column.

    Example:
        "I heard a new value. Obsidian isn't in the Color list. Add it? Say yes or no."
    """
    groups: dict[str, list[str]] = {}
    for column, term in pending:
        groups.setdefault(column or "", []).append(display_name(term))
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


@dataclass(frozen=True)
class Decision:
    """What to do with one pending term.

    ``kind`` is ``"add"`` (new value of *column*; *value* defaults to the
    capitalised term), ``"alias"`` (the term is another name for the existing
    value *value* of *column*), or ``"ignore"``.
    """

    kind: str
    column: str = ""
    value: str = ""

    @classmethod
    def add(cls, column: str, value: str = "") -> "Decision":
        return cls("add", column, value)

    @classmethod
    def alias(cls, column: str, canonical: str) -> "Decision":
        return cls("alias", column, canonical)

    @classmethod
    def ignore(cls) -> "Decision":
        return cls("ignore")


@dataclass
class Event:
    """Something that happened while processing speech."""

    kind: str
    """One of: started, stopped, updated, committed, discarded, ignored,
    search, clear_search, sort_terms, confirm, add_values, alias_added, skipped,
    expired, error. The controller rewrites ``search``/``clear_search`` into
    ``searched`` / ``cleared`` (or ``unsure`` / ``error``) once it has acted."""

    record: dict | None = None
    detail: str = ""
    values: list | None = None
    terms: list | None = None
    """committed: the terms heard in that row (so their cells can be back-filled)."""
    cells: list | None = None
    """add_values/alias_added: ``(sheet, row, column, value)`` cells to back-fill."""


@dataclass
class Session:
    """Dictation state for one workbook.

    Args:
        vocab: Vocabulary loaded from the workbook (mutated as terms are taught).
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
    pool: dict = field(default_factory=dict)        # TermKey -> times heard, not yet shown
    row_terms: set = field(default_factory=set)     # pool keys heard in the current row
    pending: list | None = None                     # TermKey list awaiting a decision
    origins: dict = field(default_factory=dict)     # TermKey -> (sheet, row) it was heard in
    _voice_open: bool = False                       # may a spoken yes/no answer apply now?
    _reask: bool = False                            # speak the question again at next pause

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def feed(self, text: str) -> list[Event]:
        """Process one recognised phrase and return the events it caused."""
        events: list[Event] = []
        tokens = tokenize(text)
        if self.pending and self._voice_open and tokens and tokens[0] in YES_WORDS | NO_WORDS:
            events += self._answer(tokens[0] in YES_WORDS)
            text = " ".join(tokens[1:])

        for segment in self.matcher.split(text):
            if isinstance(segment, CommandEvent):
                events += self._command(segment)
            else:
                events += self._segment(segment)
        return events

    def apply(self, action: Action) -> list[Event]:
        """Run a command without speech (a tray click, a menu item)."""
        return self._command(CommandEvent(action))

    def expire_prompt(self) -> list[Event]:
        """No spoken answer in time: stop accepting one; ask again at the next pause.

        The terms stay pending, so the Needs-sorting list is unaffected.
        """
        if not self.pending or not self._voice_open:
            return []
        self._voice_open = False
        self._reask = True
        return [Event("expired", detail="No answer. I'll ask again at the next pause.")]

    def restore(self, record: dict) -> None:
        """Put back a record whose write failed, so nothing the user said is lost."""
        self.record = {**record, **self.record}
        self.committed = max(0, self.committed - 1)

    def defer(self, key: TermKey) -> None:
        """Move a pending term to the end of the list without deciding it."""
        if self.pending and key in self.pending:
            self.pending.remove(key)
            self.pending.append(key)

    def tag_origin(self, terms: list[TermKey], sheet: str, row: int) -> None:
        """Remember which saved row each of *terms* was heard in."""
        for key in terms:
            self.origins[key] = (sheet, row)

    def resolve(self, key: TermKey, decision: Decision, term: str | None = None) -> list[Event]:
        """Apply *decision* to one pending term.

        Args:
            key: The pending term, as listed in ``pending``.
            decision: Add as new value, alias of an existing value, or ignore.
            term: The words as the user corrected them (default: as heard).
        """
        if not self.pending or key not in self.pending:
            return []
        self.pending.remove(key)
        origin = self.origins.pop(key, None)
        if not self.pending:
            self.pending, self._voice_open = None, False
        words = " ".join(tokenize(term if term is not None else key[1])) or key[1]

        if decision.kind == "ignore":
            return [Event("skipped", detail=f"Ignored '{words}'")]

        column = decision.column
        if decision.kind == "alias":
            if not self.vocab.add_alias(column, words, decision.value):
                return [Event("error", detail=f"'{decision.value}' is not a {column} value")]
            value, kind = decision.value, "alias_added"
            values = [(column, words, decision.value)]
            detail = f"'{words}' now means {decision.value} in {column}"
        else:
            value, kind = decision.value or display_name(words), "add_values"
            self.vocab.add(column, value)
            values = [(column, value)]
            detail = f"Added {value} to {column}"
        cells = [(origin[0], origin[1], column, self._canonical(column, value))] if origin else []
        return [Event(kind, detail=detail, values=values, cells=cells)]

    def _canonical(self, column: str, value: str) -> str:
        known = {v.lower(): v for v in self.vocab.values_for(column)}
        return known.get(value.lower(), value)

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
        for cand in result.candidates:
            key = (cand.column, cand.term)
            self.pool[key] = self.pool.get(key, 0) + 1
            self.row_terms.add(key)
        events: list[Event] = []
        if result.updates or result.candidates:
            detail = ", ".join(f"{k}={_show(v)}" for k, v in result.updates.items())
            if result.candidates:
                heard = ", ".join(f"'{c.term}'" for c in result.candidates)
                detail = (detail + "; " if detail else "") + f"to sort: {heard}"
            events.append(Event("updated", detail=detail))
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
        if action is Action.SORT_TERMS:
            return [Event("sort_terms")]
        return []

    def _commit(self) -> list[Event]:
        events: list[Event] = []
        if self.record:
            row, self.record = dict(self.record), {}
            terms = sorted(self.row_terms, key=lambda k: (k[0] or "", k[1]))
            self.row_terms.clear()
            self.committed += 1
            events.append(Event("committed", record=row, terms=terms))
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
        """Move newly heard terms to pending and announce them."""
        if not self.pool and not self._reask:
            return []
        pending = list(self.pending or [])
        pending += [k for k in sorted(self.pool, key=lambda k: (k[0] or "", k[1])) if k not in pending]
        self.pool, self._reask = {}, False
        if not pending:
            return []
        self.pending = pending
        suggested = all(column for column, _ in pending)
        self._voice_open = suggested
        if suggested:
            detail = prompt_text(pending)
        else:
            n = len(pending)
            detail = (f"I need help sorting {n} term{'s' if n != 1 else ''}. "
                      "Please check the Quill window.")
        return [Event("confirm", detail=detail, values=list(pending))]

    def _answer(self, yes: bool) -> list[Event]:
        """Handle a spoken yes/no: yes accepts every suggestion, no ignores them all."""
        events: list[Event] = []
        for key in list(self.pending or []):
            if yes and key[0]:
                events += self.resolve(key, Decision.add(key[0]))
            elif not yes:
                events += self.resolve(key, Decision.ignore())
        if not yes and len(events) > 1:
            events = [Event("skipped", detail="Not added")]
        return events


def _show(value: object) -> str:
    """Compact text for a field value in log lines."""
    return value.isoformat() if isinstance(value, dt.date) else str(value)
