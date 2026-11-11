"""Controller: carries out Session events against the workbook and speaker.

The glue between the pure pieces (Session, Vocabulary) and the outside world
(WorkbookBridge, Speaker). It has no Qt or audio code, so S4 ("unknown terms
are asked about, added to the workbook on yes") is testable end to end with a
file-based bridge.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Callable

from quill.bridge.base import BridgeError, BridgeLockedError, WorkbookBridge
from quill.config.settings import SheetLayout, Settings
from quill.history import History
from quill.learning import link_word
from quill.parser.commands import NO_WORDS, YES_WORDS, Action, CommandMatcher
from quill.parser.numbers import parse_number
from quill.parser.phrase_parser import COMMON_WORDS
from quill.parser.tokens import tokenize
from quill.parser.vocab import NO_COLUMNS_START_HELP, Vocabulary
from quill.search import parse_search
from quill.session import Decision, Event, Session, TermKey
from quill.sorting_voice import VoiceSorter

log = logging.getLogger("quill.controller")


def _kind(value: object) -> str:
    """What sort of value a line holds, for telling whether a re-said value is the one that was deleted."""
    if isinstance(value, dt.date):
        return "date"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    return "text"


class _Change:
    """One column change of the row being built, kept so Undo can put the row back (see :meth:`Controller.change_field`)."""

    def __init__(self, record: dict, before: dict, context: dict, column: str, to_column: str) -> None:
        self.record = record                    # the row's live dict: Undo only applies while this is still the row being built
        self.before = before                    # copy of the row's values before the change
        self.context_before = context           # copy of the words kept around each value
        self.column, self.to_column = column, to_column
        self.value: object = None               # the moved value (set once the change is made)
        self.counted: tuple[str, str, str] | None = None   # (word, column, file path) if the change was counted as a lesson


@dataclass
class _Redo:
    """A line the user deleted that had words around it: if the same sort of value is said again with a column's name, that
    is a correction Quill can learn from (see :meth:`Controller._check_redo`)."""

    column: str
    kind: str
    words: list[str]
    steps: int = 0

EventCallback = Callable[[Event], None]

#: Shown (in the not-connected chip's tooltip) and spoken whenever Quill is asked to listen with no spreadsheet.
NO_WORKBOOK_HELP = (
    "No spreadsheet is connected. Open a spreadsheet and Quill connects to it automatically, "
    "or choose Open File in the File menu."
)

class Controller:
    """Runs dictation: transcript in, workbook writes and UI events out.

    Args:
        bridge: Workbook to dictate into (need not be connected yet).
        settings: Keyword map and preferences.
        speaker: Object with ``say(text)``; None for silent operation.
        on_event: Called with every Event (including ``error`` events the
            controller itself raises). Must be cheap; runs on the caller's thread.
        on_speech: Called with True just before the speaker talks and False
            once it finishes, so the app can mute the microphone meanwhile.
        today: Callable giving today's date (injectable for tests).
    """

    def __init__(
        self,
        bridge: WorkbookBridge,
        settings: Settings,
        speaker=None,
        on_event: EventCallback | None = None,
        on_speech: Callable[[bool], None] | None = None,
        today: Callable[[], dt.date] = dt.date.today,
    ) -> None:
        self.bridge = bridge
        self.settings = settings
        self.speaker = speaker
        raw_event = on_event or (lambda event: None)
        self._spoken_depth = 0                              # above 0 while a spoken phrase is being carried out

        def tagged(event: Event) -> None:
            event.spoken = self._spoken_depth > 0           # said, or clicked? Only what was said makes a sound
            raw_event(event)

        self._on_event = tagged
        self._on_speech = on_speech or (lambda speaking: None)
        self.vocab = Vocabulary()
        self.session = Session(self.vocab, CommandMatcher(settings.keywords), today=today)
        self.session.start_blocked = self.start_blocked_reason
        self._sheet = ""
        self.sheet_headers: list[str] = []
        """The active sheet's columns in sheet order (empty when no workbook is connected)."""
        self.on_layout: Callable[[], None] = lambda: None
        """Told when the layout in force (headings row, starting row, headings direction) changed because the sheet or workbook did."""
        self.on_columns: Callable[[list[str]], None] = lambda columns: None
        """Told the active sheet's columns whenever they are read (and ``[]`` when the workbook is let go)."""
        self.connected = False
        """True while attached to a workbook."""
        self.voice_sorter: VoiceSorter | None = None
        """Set while the user is answering the Needs-sorting list by voice."""
        self.lead_in_s = 0.0
        """Seconds the spoken sorting question waits so a cue can play first (set by the app)."""
        self.history = History(int(settings.preferences["history_limit"]))
        self.batch_depth = 0                                   # > 0 while a batch of answers is being applied
        self.on_batch_done: Callable[[], None] = lambda: None  # told when the outermost batch ends (the lists then refresh once)
        """The most recent sorting decisions, newest last, for :meth:`undo`."""
        self._connected_to = ""
        """Which workbook the last :meth:`connect` reached (a different one clears the heard terms)."""
        self._append_target: tuple[str, int] | None = None
        """``(sheet, record)`` that "append to" turns keep adding to (None: the next turn starts a new record)."""
        self._redo: _Redo | None = None
        """The line just deleted, while a redo of it may still come (None: nothing to watch for)."""
        self.learn_offer: tuple[str, str] | None = None
        self._offer_change: _Change | None = None   # the column change the waiting question came from (so Undo can take it back)
        """``(word, column)`` Quill is asking "Remember ...?" about after a line's column was changed (None: no question open)."""

    # ------------------------------------------------------------------ #
    # Workbook connection                                                  #
    # ------------------------------------------------------------------ #

    def connect(self, workbook: str | None = None) -> None:
        """Connect the bridge and load the vocabulary from the workbook.

        Raises:
            BridgeError: if the workbook cannot be reached.
        """
        self.connected = False
        self._redo = None
        self.history.clear()   # undo steps belong to the workbook they were made in
        self._append_target = None
        self._give_layout(SheetLayout())                   # (the last workbook's layout means nothing here: its own is applied once the sheet is known)
        self.bridge.connect(workbook)
        here = str(getattr(self.bridge, "workbook_path", "") or workbook or "")
        if self._connected_to and here != self._connected_to:
            for event in self.session.drop_row("another file was chosen"):
                self._on_event(event)
            self.session.forget_terms()                    # other workbook: what was heard for the last one means nothing here
        self._connected_to = here
        self._apply_layout_for(self.bridge.active_sheet_name())
        self.reload_vocab()
        self.connected = True
        self.on_columns(list(self.sheet_headers))          # (again, now that it is connected: a sheet with no columns is told apart from no file)

    def try_connect(self, workbook: str | None = None) -> bool:
        """Like :meth:`connect` but returns False instead of raising."""
        try:
            self.connect(workbook)
        except BridgeError:
            return False
        return True

    def detach(self) -> None:
        """Let go of a workbook that was closed; closes the gate if it was open."""
        self.connected = False
        self.sheet_headers = []
        self.on_columns([])
        for event in self.session.drop_row("the file was closed"):      # its row was for that file: it must not be written into the next one
            self._on_event(event)
        with contextlib.suppress(BridgeError):
            self.bridge.disconnect()
        if self.session.listening:
            for event in self.session.apply(Action.STOP_LISTENING):
                self._on_event(event)

    def reload_vocab(self) -> None:
        """Re-read lists and headers (after a refresh or a sheet change)."""
        with getattr(self.bridge, "remembering", contextlib.nullcontext)():     # (the same cells are asked about several times: ask the program once)
            self.vocab.load(self.bridge.get_lists(), self.bridge.get_headers())
            self.vocab.numeric_columns = self.bridge.numeric_columns()
            self.vocab.date_columns = self.bridge.date_columns()
            self._apply_aliases()
            self._apply_learning()
            self._sheet = self.bridge.active_sheet_name()
            self.sheet_headers = list(self.bridge.get_headers())
        self.on_columns(list(self.sheet_headers))

    # ------------------------------------------------------------------ #
    # Where a sheet's data is (kept per workbook and sheet)                #
    # ------------------------------------------------------------------ #

    def _layout_now(self) -> SheetLayout:
        prefs = self.settings.preferences
        return SheetLayout(int(prefs["headings_row"]), int(prefs["start_row"]), bool(prefs["vertical_layout"]))

    def _give_layout(self, layout: SheetLayout) -> None:
        """Make *layout* the one in force: the preferences the panel shows, and the bridge that reads and writes."""
        prefs = self.settings.preferences
        prefs["headings_row"], prefs["start_row"], prefs["vertical_layout"] = layout.headings_row, layout.start_row, layout.vertical
        bridge = self.bridge
        if hasattr(bridge, "set_vertical"):
            bridge.set_vertical(layout.vertical)
            bridge.set_start_row(layout.start_row)
            bridge.set_headings_row(layout.headings_row)

    def _apply_layout_for(self, sheet: str) -> None:
        """The workbook or its open sheet changed: use the layout saved for *that* sheet of *that* workbook (the default if none)."""
        layout = self.settings.layout_for(self._connected_to, sheet)
        if layout != self._layout_now() or sheet != self._sheet:
            self._give_layout(layout)
            self._append_target = None
            self.on_layout()

    def _remember_layout(self) -> None:
        """The layout was changed for the sheet that is open: keep it for that sheet of that workbook."""
        if self._connected_to and self._sheet:
            self.settings.set_layout(self._connected_to, self._sheet, self._layout_now())

    def _apply_learning(self) -> None:
        """Give the vocabulary what the user taught Quill about words and columns (and how soon to use it)."""
        self.vocab.links = self.settings.links
        self.vocab.skip_words = frozenset(self.settings.skip_words)
        self.vocab.learn_after = int(self.settings.preferences["learn_after"])

    def _apply_aliases(self) -> None:
        """Re-teach the vocabulary the user's saved synonyms (e.g. "extra large" = XL)."""
        for column, mapping in self.settings.aliases.items():
            for phrase, canonical in mapping.items():
                self.vocab.add_alias(column, phrase, canonical)

    def refresh(self) -> None:
        """Re-read the workbook structure, then rebuild the vocabulary."""
        self.bridge.refresh()
        self.reload_vocab()

    def apply_settings(self) -> None:
        """Rebuild the keyword matcher after the user edited settings."""
        self.session.matcher = CommandMatcher(self.settings.keywords)
        self.history.limit = int(self.settings.preferences["history_limit"])
        self._apply_learning()

    # ------------------------------------------------------------------ #
    # Dictation                                                            #
    # ------------------------------------------------------------------ #

    def handle_transcript(self, text: str) -> None:
        """Process one recognised phrase end to end."""
        self._spoken_depth += 1
        try:
            self._handle_spoken(text)
        finally:
            self._spoken_depth -= 1

    def _handle_spoken(self, text: str) -> None:
        if self.voice_sorter is not None:
            self._voice_sort(text)
            return
        words = tokenize(text)
        if self.learn_offer is not None and len(words) == 1 and words[0] in YES_WORDS | NO_WORDS:
            self.answer_learn_offer(words[0] in YES_WORDS)           # a spoken yes or no answers the "Remember ...?" question
            return
        if not self.connected:
            self.try_connect()   # a workbook may have been opened since we last looked
        else:
            self._follow_active_sheet()
        before = set(self.session.record)
        with self.history.group("Sorted several terms"):   # a spoken "yes" can answer many
            for event in self._refuse_without_workbook(self.session.feed(text)):
                self._carry_out(event)
                self._on_event(event)
        self._check_redo(before)

    def _refuse_without_workbook(self, events: list[Event]) -> list[Event]:
        """With nothing to write to, swap "started" for guidance and keep the gate shut."""
        if self.connected or not any(e.kind == "started" for e in events):
            return events
        self.session.listening = False
        self.session.record.clear()
        self.session.open_note = None
        return [Event("error", detail=NO_WORKBOOK_HELP) if e.kind == "started" else e
                for e in events]

    def start_blocked_reason(self) -> str | None:
        """Why listening cannot start now, or None: a connected file whose open sheet has no columns has nothing to match the words to, so
        the words would only sit in the grid and never be saved. (The sheet's own headings count, not the vocabulary: its lists come
        from the whole workbook, so a blank sheet in a workbook with lists elsewhere would otherwise look fine.)"""
        return NO_COLUMNS_START_HELP if self.connected and not self.sheet_headers else None

    def set_listening(self, active: bool) -> None:
        """Open or close the listening gate without speech (tray / button)."""
        action = Action.START_LISTENING if active else Action.STOP_LISTENING
        if active and not self.connected and not self.try_connect():
            self._carry_out(Event("error", detail=NO_WORKBOOK_HELP))
            self._on_event(Event("error", detail=NO_WORKBOOK_HELP))
            return
        if active:                                       # back to dictating the row: speech is no longer an answer to the Term Helper
            self.stop_voice_sort("Voice sorting off: listening for the row")
        for event in self.session.apply(action):
            self._carry_out(event)
            self._on_event(event)

    def next_row(self) -> None:
        """Save the row being built (if anything valid was heard) and start the next one: the button's "next row"."""
        for event in self.session.apply(Action.NEXT_ROW):
            self._carry_out(event)
            self._on_event(event)

    # ------------------------------------------------------------------ #
    # How a turn is written                                                #
    # ------------------------------------------------------------------ #

    @property
    def turn_mode(self) -> str:
        """``"next_row"`` (every turn is a new row) or ``"append"`` (every turn adds to the same row)."""
        return str(self.settings.preferences["turn_mode"])

    @property
    def vertical(self) -> bool:
        """True while the sheet is read with its headings down the first column."""
        return bool(self.settings.preferences["vertical_layout"])

    def set_turn_mode(self, mode: str) -> None:
        """Choose how a turn is written (from the panel); the next turn starts a fresh row either way."""
        if mode in ("next_row", "append") and mode != self.turn_mode:
            self._on_event(self._turn_event("append_on" if mode == "append" else "append_off"))

    def set_vertical(self, vertical: bool) -> None:
        """Read the sheet with its headings across the first row (False) or down the first column (True) (from the panel)."""
        if bool(vertical) != self.vertical:
            self._on_event(self._turn_event("rows_down_on" if vertical else "rows_down_off"))

    def _turn_event(self, option: str) -> Event:
        """Apply the turn option *option* (``append_on`` ... ``rows_down_off``) and describe it as an event.

        The event is ``turn_on`` / ``turn_off`` (so it gets its own confirmation sound), or an ``error``.
        """
        on = option.endswith("_on")
        prefs = self.settings.preferences
        self._append_target = None
        if option.startswith("append"):
            prefs["turn_mode"] = "append" if on else "next_row"
            self.settings.save()
            return Event("turn_on" if on else "turn_off",
                         detail=f"Each turn adds to the same {self._unit()}" if on else f"Each turn is written to a new {self._unit()}")
        prefs["vertical_layout"] = on
        self._remember_layout()
        self.settings.save()
        self.history.clear()                   # row numbers mean something else now
        try:
            self.bridge.set_vertical(on)
            if self.connected:
                self.reload_vocab()
        except BridgeError as exc:
            return Event("error", detail=f"Could not change the layout: {exc}")
        return Event("turn_on" if on else "turn_off",
                     detail="Headings are read down the first column" if on else "Headings are read across the first row")

    def set_start_row(self, number: int) -> None:
        """The first row (or column, for Rows Down) a turn may write to; 0 means the first empty one."""
        number = max(0, int(number))
        if number == int(self.settings.preferences["start_row"]):
            return
        self.settings.preferences["start_row"] = number
        self._remember_layout()
        self.settings.save()
        self._append_target = None
        if hasattr(self.bridge, "set_start_row"):
            self.bridge.set_start_row(number)
        self._on_event(Event("ignored", detail=f"Turns start at {self._unit()} {self._where(number)}" if number else f"Turns start at the first empty {self._unit()}"))

    def set_headings_row(self, number: int) -> None:
        """The row (column, for Rows Down) that holds the headings; 0 finds it by itself."""
        number = max(0, int(number))
        if number == int(self.settings.preferences["headings_row"]):
            return
        self.settings.preferences["headings_row"] = number
        self._remember_layout()
        self.settings.save()
        self._append_target = None
        try:
            self.bridge.set_headings_row(number)
            if self.connected:
                self.reload_vocab()
        except BridgeError as exc:
            self._on_event(Event("error", detail=f"Could not use that headings row: {exc}"))
            return
        self._on_event(Event("ignored", detail=f"Headings are in {self._unit()} {self._where(number)}" if number else "Headings are found automatically"))

    def start_new_row(self) -> None:
        """Stop adding to the current row: the next turn starts a fresh one."""
        target, self._append_target = self._append_target, None
        if target is not None:
            self.bridge.select_record(target[0], target[1] + 1)          # the cursor moves on to the next row (column)
        self._on_event(Event("ignored", detail=f"The next turn starts a new {self._unit()}"))

    def remove_field(self, column: str) -> bool:
        """The user disagrees with one understood value of the row being built: drop it.

        A row is written to the workbook only when "next row" is said, so a value still in the row being
        built has not been written anywhere yet; removing it means it never will be.

        Returns:
            True if the row had that column.
        """
        if column not in self.session.record:
            return False
        value = self.session.record.pop(column)
        if self.session.open_note == column:
            self.session.open_note = None                  # (a note taken off the row is no longer being dictated)
        words = self.session.context.pop(column, [])
        self._redo = _Redo(column, _kind(value), words) if words else None
        log.debug("removed %s=%r from the row being built", column, value)
        return True

    # ------------------------------------------------------------------ #
    # Learned links: which column a word means                              #
    # ------------------------------------------------------------------ #

    def columns_for_change(self, column: str) -> list[str]:
        """The other columns the value on the row's *column* line could be changed to (empty when there are none).

        Only columns that fit the value: a date goes to the other date columns, a number to the other numeric ones,
        a word to the lists that already accept it.
        """
        if column not in self.session.record:
            return []
        value = self.session.record[column]
        if isinstance(value, dt.date):
            pool = self.vocab.date_columns
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            pool = self.vocab.amount_columns() or self.vocab.numeric_columns
        elif isinstance(value, str) and self.vocab.is_list_column(column):
            pool = self.vocab.columns_for(value.split("\n")[0])
        else:
            pool = []
        return [c for c in pool if c != column]

    def change_field(self, column: str, to_column: str) -> bool:
        """The user changed the column of one understood value of the row being built (it is written to *to_column* instead).

        A value already in *to_column* swaps places, so two dates in the wrong order are fixed by one change. The words
        spoken around the value are what Quill can learn from this (see :meth:`answer_learn_offer`).

        Returns:
            False if the change is not allowed (no such line, or the value does not fit *to_column*).
        """
        if to_column not in self.columns_for_change(column):
            return False
        record, context = self.session.record, self.session.context
        change = _Change(record, dict(record), {k: list(v) for k, v in context.items()}, column, to_column)
        value, words = record.pop(column), context.pop(column, [])
        if to_column in record:
            record[column], other = record[to_column], context.pop(to_column, [])
            if other:
                context[column] = other
        record[to_column] = value
        if words:
            context[to_column] = words
        change.value = value
        self.history.push(f"Changed {column} to {to_column}", lambda: self._undo_change(change))
        self._on_event(Event("changed", detail=f"Changed {column} to {to_column}"))
        self._offer_learning(words, to_column, change)
        return True

    def _undo_change(self, change: _Change) -> list[str]:
        """Put the row back as it was before a column change, and take back what the change taught (a waiting question
        goes away; a lesson already counted loses that count). Only possible while that row is still being built."""
        record = self.session.record
        if record is not change.record or record.get(change.to_column) != change.value:
            return ["That row has moved on, so the values were left as they are"]
        record.clear()
        record.update(change.before)
        context = self.session.context
        context.clear()
        context.update(change.context_before)
        notes: list[str] = []
        if self.learn_offer is not None and self.learn_offer[1] == change.to_column:
            self.learn_offer = None
        if change.counted is not None:
            word, column, path = change.counted
            if self.settings.links.unobserve(word, column, path):
                self.settings.save()
                notes.append(f"Forgot one count of '{word}' for {column}")
            change.counted = None
        return notes

    def _check_redo(self, before: set[str]) -> None:
        """After a phrase: was a deleted line said again, with a column's name, in another column? That is a correction, so
        what was said around the first one is offered as a lesson (delete-and-redo). Looks at the next two phrases only,
        and never when Quill itself guessed the new column: only a column the user named counts."""
        redo = self._redo
        if redo is None:
            return
        if self.session.row_ended:                          # "next row" with nothing to save still means the row is over
            self._redo = None
            return
        record, guessed = self.session.record, self.session.context
        for column in record:
            if column in before or column == redo.column or column in guessed or _kind(record[column]) != redo.kind:
                continue
            self._redo = None
            self._offer_learning(redo.words, column)
            return
        redo.steps += 1
        if redo.steps >= 2:
            self._redo = None

    def _offer_learning(self, words: list[str], column: str, change: _Change | None = None) -> None:
        """After a change: the first spoken word near the value that can be learned is asked about (or counted, if asking is off)."""
        word = next((w for w in words if self._learnable(w)), None)
        self.learn_offer = self._offer_change = None
        if word is None:
            return
        if self.settings.preferences["learn_ask"]:
            self.learn_offer, self._offer_change = (word, column), change
            self._on_event(Event("learn_offer", detail=f"Remember that '{word}' means {column}?", values=[(word, column)]))
        else:
            self._count_link(word, column, change)

    def _learnable(self, word: str) -> bool:
        """Can *word* become a link? Not a number or filler, and never a word of this sheet (a heading word or a list value)."""
        return (link_word(word) is not None and self.vocab.field_at([word], 0) is None
                and not self.vocab.matches_at([word], 0))

    def answer_learn_offer(self, yes: bool) -> None:
        """Yes or no to "Remember ...?": yes counts the change as a lesson, no teaches nothing."""
        offer, self.learn_offer = self.learn_offer, None
        change, self._offer_change = self._offer_change, None
        if offer is None:
            return
        if yes:
            self._count_link(*offer, change)
        else:
            self._on_event(Event("learn_declined", detail="Nothing remembered"))

    def expire_learn_offer(self) -> None:
        """No answer in time: the question goes away and nothing is learned."""
        self.learn_offer = self._offer_change = None

    def _source(self) -> tuple[str, str]:
        """The file a lesson is learned in: ``(path, name)``."""
        path = str(getattr(self.bridge, "workbook_path", "") or "")
        name = self._connected_to.rsplit("/", 1)[-1] if self._connected_to else ""
        with contextlib.suppress(BridgeError):
            name = self.bridge.workbook_name
        return path, name

    def _count_link(self, word: str, column: str, change: _Change | None = None) -> None:
        link = self.settings.links.observe(word, column, *self._source())
        if link is None:
            return
        if change is not None:
            change.counted = (word, column, self._source()[0])
        self.settings.save()
        need = int(self.settings.preferences["learn_after"])
        if link.is_active(need):
            self._on_event(Event("learned", detail=f"Learned: '{word}' means {column}"))
        else:
            self._on_event(Event("learning", detail=f"Noted: '{word}' for {column} ({link.count} of {need})"))

    def teach_link(self, word: str, column: str) -> Event:
        """"<word> means <column>", said outright: in force at once. Returns the event that says what happened."""
        if not self._learnable(word):
            return Event("ignored", detail=f"'{word}' can't be taught: it is a number, a short or everyday word, or a word already in this sheet")
        link = self.settings.links.teach(word, column, *self._source())
        if link is None:
            return Event("ignored", detail=f"'{word}' can't be taught")
        self.settings.save()
        return Event("learned", detail=f"Learned: '{word}' means {column}")

    def pending_terms(self) -> list[TermKey]:
        """Terms waiting to be sorted: ``(suggested column or None, words)``."""
        return list(self.session.pending or [])

    def resolve_term(self, key: TermKey, decision: Decision, term: str | None = None) -> None:
        """Apply the user's decision about one unrecognised term (undoable)."""
        for event in self.session.resolve(key, decision, term):
            self._carry_out(event)
            self._on_event(event)
        self._learn_skipped_words(key, decision, term)

    def _learn_skipped_words(self, key: TermKey, decision: Decision, term: str | None) -> None:
        """The user trimmed words off the start or end of a term before adding it ("ones teal" became "teal"): those words are
        not part of values, so Quill skips them from now on, here and in every file. Only whole words at the ends count; a term
        that was rewritten, or a word that is a heading, a list value or a number, teaches nothing."""
        if decision.kind not in ("add", "alias") or not term:
            return
        heard, kept = tokenize(key[1]), tokenize(term)
        size = len(kept)
        at = next((i for i in range(len(heard) - size + 1) if heard[i:i + size] == kept), None) if kept else None
        if at is None or size == len(heard):
            return
        vocab = self.vocab
        words = [w for w in heard[:at] + heard[at + size:]
                 if len(w) >= 2 and w.isalpha() and w not in COMMON_WORDS and w not in self.settings.skip_words
                 and vocab.field_at([w], 0) is None and not vocab.matches_at([w], 0) and parse_number([w], 0)[0] is None]
        learned = self.settings.add_skip_words(words)
        if not learned:
            return
        self.settings.save()
        self._apply_learning()
        shown = ", ".join(f"‘{w}’" for w in learned)
        self._on_event(Event("learning", detail=f"Quill will skip {shown} from now on (Settings > Learned Words lists them)"))

    def defer_term(self, key: TermKey) -> None:
        """Leave a term for later (moves it to the end of the list)."""
        pending = self.session.pending or []
        if key not in pending or pending[-1] == key:
            return
        index = pending.index(key)
        self.session.defer(key)
        self.history.push(f"Left ‘{key[1]}’ for later", lambda: self._restore(key, index, None))

    @contextlib.contextmanager
    def batch(self, label: str):
        """Context manager: decisions made inside undo together as one step, and what shows them (the Term Helper list) is
        refreshed once when the batch ends, so a whole batch changes the screen as one action (see ``on_batch_done``)."""
        self.batch_depth += 1
        try:
            with self.history.group(label):
                yield
        finally:
            self.batch_depth -= 1
            if not self.batch_depth:
                self.on_batch_done()

    # ------------------------------------------------------------------ #
    # Undo                                                                 #
    # ------------------------------------------------------------------ #

    def undo(self, count: int = 1) -> list[str]:
        """Reverse the last *count* sorting decisions, newest first.

        Returns:
            One plain-language line per step ("Undid: Added ‘teal’ to Color"),
            plus notes for anything that could not be put back; or a single
            "Nothing to undo" line when the history is empty.
        """
        messages: list[str] = []
        for _ in range(max(1, count)):
            entry = self.history.pop()
            if entry is None:
                if not messages:
                    messages.append("Nothing to undo")
                break
            messages.append(f"Undid: {entry.label}")
            messages += entry.undo()
        return messages

    def request_undo(self, count: int = 1) -> None:
        """Undo from the UI or a spoken keyword and report it as an event."""
        messages = self.undo(count)
        undone = messages[0] != "Nothing to undo"
        self._on_event(Event("undone" if undone else "ignored", detail="; ".join(messages)))

    def _record(self, event: Event) -> None:
        """Add a resolved term to the undo history (before its effects are carried out)."""
        info = event.resolved
        key, index, origin = info["key"], info["index"], info["origin"]
        if event.kind == "skipped":
            self.history.push(f"Ignored ‘{info['words']}’", lambda: self._restore(key, index, origin))
            return
        previous = (self.settings.aliases.get(info["column"], {}).get(info["words"])
                    if event.kind == "alias_added" else None)
        self.history.push(event.detail,
                          lambda: self._undo_teach(event, previous))

    def _restore(self, key: TermKey, index: int, origin) -> list[str]:
        self.session.restore_term(key, index, origin)
        return []

    def _undo_teach(self, event: Event, previous: str | None) -> list[str]:
        """Undo an add / same-as: empty back-filled cells, forget the value or synonym."""
        info, notes = event.resolved, []
        column, words = info["column"], info["words"]
        for sheet, row, col, value in event.filled or []:
            try:
                if not self.bridge.clear_value(sheet, row, col, value):
                    notes.append(f"Left {col} on row {row} as it is (it was changed)")
            except BridgeError as exc:
                notes.append(f"Could not empty {col} on row {row}: {exc}")
        if event.kind == "add_values":
            value = info["value"]
            if not info["existed"]:
                self.vocab.remove(column, value)
                try:
                    if not self.bridge.remove_from_list(column, value):
                        notes.append(f"Left ‘{value}’ in the {column} list (couldn't find it)")
                except BridgeError as exc:
                    notes.append(f"Could not remove ‘{value}’ from the list: {exc}")
        else:
            self.vocab.remove_alias(column, words, info["value"])
            self.settings.remove_alias(column, words)
            if previous:
                self.settings.add_alias(column, words, previous)
                self.vocab.add_alias(column, words, previous)
            self.settings.save()
        self.session.restore_term(info["key"], info["index"], info["origin"])
        return notes

    # ------------------------------------------------------------------ #
    # Voice sorting                                                        #
    # ------------------------------------------------------------------ #

    def start_voice_sort(self) -> bool:
        """Route speech to the Needs-sorting list until it is empty or the user says done.

        Returns:
            False (and does nothing) if no term is waiting.
        """
        if not self.session.pending:
            return False
        if self.voice_sorter is None:
            self.voice_sorter = VoiceSorter(self)
            self._on_event(Event("sort_voice_started",
                                 detail="Voice sorting on: say yes, a column name, same as …, ignore, later or done"))
        return True

    def stop_voice_sort(self, detail: str = "Voice sorting off") -> None:
        """Return speech to normal dictation."""
        if self.voice_sorter is not None:
            self.voice_sorter = None
            self._on_event(Event("sort_voice_ended", detail=detail))

    def note_choice(self, key: TermKey, column: str) -> None:
        """Tell the window which column a spoken answer picked, just before the term is resolved (so it can be shown)."""
        self._on_event(Event("choice", detail=column, record={"key": key}))

    def _voice_sort(self, text: str) -> None:
        result = self.voice_sorter.handle(text)
        self._on_event(Event("sorting", detail="; ".join(result.messages), record={"heard": text, "problem": result.problem}))
        if result.finished:
            done = not self.session.pending
            self.stop_voice_sort("All sorted" if done else "Voice sorting off")

    def expire_prompt(self) -> None:
        """Give up waiting for a yes/no answer."""
        for event in self.session.expire_prompt():
            self._on_event(event)

    def follow_sheet(self) -> bool:
        """Look at which sheet is open now and, if it is another, load its field words. True if it changed."""
        before = self._sheet
        self._follow_active_sheet()
        return self._sheet != before

    def _follow_active_sheet(self) -> None:
        """Reload field words if the user switched sheets in Excel."""
        try:
            current = self.bridge.active_sheet_name()
        except BridgeError:
            return
        if current != self._sheet:
            self._apply_layout_for(current)
            self.reload_vocab()
            self._on_event(Event("ignored", detail=f"Now on sheet '{current}'"))

    def _carry_out(self, event: Event) -> None:
        """Do what a Session event asks of the outside world (write the row, save a synonym, search, speak ...)."""
        log.debug("event %s: %s", event.kind, event.detail)
        if event.kind in ("committed", "discarded"):
            self._redo = None                              # the row is over: a deleted line can no longer be redone in it
        if event.resolved is not None:
            self._record(event)
        if event.kind == "committed":
            self._write_row(event)
        elif event.kind == "add_values":
            self._write_values(event)
        elif event.kind == "alias_added":
            self._save_alias(event)
        elif event.kind == "search":
            self._search(event)
        elif event.kind == "clear_search":
            self._clear_search(event)
        elif event.kind == "turn_option":
            done = self._turn_event(event.detail.lower())
            event.kind, event.detail = done.kind, done.detail
        elif event.kind == "teach_link":
            word, column = event.values[0]
            done = self.teach_link(word, column)
            event.kind, event.detail = done.kind, done.detail
        elif event.kind == "undo":
            messages = self.undo()
            event.kind = "undone" if messages[0] != "Nothing to undo" else "ignored"
            event.detail = "; ".join(messages)
        elif event.kind == "sort_terms":
            if self.start_voice_sort():
                event.kind, event.detail = "ignored", "Sorting terms by voice"
            else:
                event.kind, event.detail = "ignored", "Nothing to sort"
        elif event.kind == "confirm" and all(column for column, _ in event.values or []):
            self._say(event.detail, lead_in=self.lead_in_s)             # only spoken when a spoken yes can answer it

    def speak(self, text: str) -> None:
        """Speak *text* with the system voice if the "speak sort prompts" setting is on (the speaker says
        nothing otherwise). This is the only kind of system speech Quill uses for guidance."""
        self._say(text)

    def _say(self, text: str, lead_in: float = 0.0) -> None:
        """Speak *text* if there is a speaker, muting the mic meanwhile."""
        if self.speaker is None or not getattr(self.speaker, "enabled", True):
            return                                     # speech is off (the default): say nothing, and don't mute the microphone
        self._on_speech(True)
        extra = {"lead_in": lead_in} if lead_in else {}
        self.speaker.say(text, on_done=lambda: self._on_speech(False), **extra)

    def _search(self, event: Event) -> None:
        """Turn the spoken criteria into filters on the active sheet."""
        try:
            sheet = self.bridge.active_sheet_name()
            query = parse_search(event.detail, self.vocab, self.bridge.numeric_columns(sheet))
            notes = [*query.assumptions, *query.problems]
            if not query.filters:
                event.kind = "unsure"
                event.detail = ("Nothing to filter on in '" + event.detail + "'. "
                                "Use values from your lists, like 'search for fern under 20'.")
                return
            count = self.bridge.apply_filters(sheet, query.filters)
        except BridgeError as exc:
            event.kind, event.detail = "error", f"Could not search: {exc}"
            return
        shown = ", ".join(f.describe() for f in query.filters)
        tail = f" — {count} row{'s' if count != 1 else ''}" if count is not None else ""
        extras = [f"Unrecognised: {' '.join(query.unmatched)}"] if query.unmatched else []
        event.kind = "searched"
        event.detail = "; ".join([f"{shown}{tail}", *notes, *extras])

    def _clear_search(self, event: Event) -> None:
        try:
            cleared = self.bridge.clear_filters(self.bridge.active_sheet_name())
        except BridgeError as exc:
            event.kind, event.detail = "error", f"Could not clear the search: {exc}"
            return
        event.kind = "cleared" if cleared else "ignored"
        event.detail = ("Search cleared; back where you were" if cleared
                        else "No search is active")

    def _write_row(self, event: Event) -> None:
        try:
            sheet = self.bridge.active_sheet_name()          # always the sheet that is open: Quill never picks another
            if self.turn_mode == "append":
                same = self._append_target[1] if self._append_target and self._append_target[0] == sheet else None
                row = self.bridge.append_to_row(sheet, same, event.record)
                self._append_target = (sheet, row)
                event.detail = f"{self._record_name(row)} (added to)"
            else:
                row = self.bridge.append_row(sheet, event.record)
                event.detail = self._record_name(row)
            self.session.tag_origin(event.terms or [], sheet, row)
            self.bridge.select_record(sheet, row if self.turn_mode == "append" else row + 1)   # append keeps the cursor on the row; otherwise it moves on
        except BridgeLockedError as exc:                    # another program holds the file: the row is kept and saved when it is free
            row = exc.row if exc.row is not None else 0
            event.detail = f"{self._record_name(row)} (waiting: the file is in use)"
            self.session.tag_origin(event.terms or [], sheet, row)
            self._append_target = (sheet, row) if self.turn_mode == "append" else None
            self._on_event(Event("locked", detail=f"{exc}. Quill is holding the rows and saves them the moment it is free."))
        except BridgeError as exc:
            self.session.restore(event.record)             # nothing the user said is lost: the row stays as it was
            hint = " Open the sheet you are filling in, then say next row again." if "has no " in str(exc) else ""
            event.kind, event.detail = "error", f"Could not save the row: {exc}.{hint}"   # and it is reported as a failure,
            event.record = event.terms = None                                       # not as a saved row

    def _unit(self) -> str:
        """"row", or "column" while the headings run down the first column."""
        return "column" if self.vertical else "row"

    def _where(self, number: int) -> str:
        """A row number, or a column letter when the headings run down the first column."""
        if self.vertical and number > 0:
            from openpyxl.utils import get_column_letter
            return get_column_letter(number)
        return str(number)

    def _record_name(self, number: int) -> str:
        """"Row 6", or "Column F" when the records run across the sheet."""
        if getattr(self.bridge, "vertical", False):
            from openpyxl.utils import get_column_letter
            return f"Column {get_column_letter(number)}"
        return f"Row {number}"

    def _write_values(self, event: Event) -> None:
        """Add taught values to the workbook's lists, then back-fill the saved row."""
        added = True
        for column, value in event.values:
            try:
                self.bridge.add_to_list(column, value)
            except BridgeError as exc:
                added = False
                self._on_event(Event("error", detail=f"Could not add '{value}': {exc}"))
        if added:
            self._backfill(event)

    def _save_alias(self, event: Event) -> None:
        """Remember the synonym for future sessions, then back-fill the saved row."""
        for column, phrase, canonical in event.values:
            self.settings.add_alias(column, phrase, canonical)
        self.settings.save()
        self._backfill(event)

    def _backfill(self, event: Event) -> None:
        """Fill the empty cell of the row the term was heard in (never overwrites)."""
        for sheet, row, column, value in event.cells or []:
            try:
                if self.bridge.set_value(sheet, row, column, value):
                    event.detail += f"; filled {column} on row {row}"
                    event.filled = [*(event.filled or []), (sheet, row, column, value)]
            except BridgeError as exc:
                self._on_event(Event("error", detail=f"Could not fill {column} on row {row}: {exc}"))
