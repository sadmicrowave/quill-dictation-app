"""Controller: carries out Session events against the workbook and speaker.

The glue between the pure pieces (Session, Vocabulary) and the outside world
(WorkbookBridge, Speaker). It has no Qt or audio code, so S4 ("unknown terms
are asked about, added to the workbook on yes") is testable end to end with a
file-based bridge.
"""

from __future__ import annotations
import datetime as dt
from typing import Callable

from quill.bridge.base import BridgeError, WorkbookBridge
from quill.config.settings import Settings
from quill.parser.commands import Action, CommandMatcher
from quill.parser.vocab import Vocabulary
from quill.search import parse_search
from quill.session import Decision, Event, Session, TermKey

EventCallback = Callable[[Event], None]

#: Shown and spoken whenever Quill is asked to listen with no spreadsheet to listen to.
NO_WORKBOOK_HELP = (
    "I can't find an open spreadsheet. Open one in Excel and I'll attach to it "
    "automatically, then say start listening."
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
        self._on_event = on_event or (lambda event: None)
        self._on_speech = on_speech or (lambda speaking: None)
        self.vocab = Vocabulary()
        self.session = Session(self.vocab, CommandMatcher(settings.keywords), today=today)
        self._sheet = ""
        self.connected = False
        """True while attached to a workbook."""

    # ------------------------------------------------------------------ #
    # Workbook connection                                                  #
    # ------------------------------------------------------------------ #

    def connect(self, workbook: str | None = None) -> None:
        """Connect the bridge and load the vocabulary from the workbook.

        Raises:
            BridgeError: if the workbook cannot be reached.
        """
        self.connected = False
        self.bridge.connect(workbook)
        self.reload_vocab()
        self.connected = True

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
        try:
            self.bridge.disconnect()
        except BridgeError:
            pass
        if self.session.listening:
            for event in self.session.apply(Action.STOP_LISTENING):
                self._on_event(event)

    def reload_vocab(self) -> None:
        """Re-read lists and headers (after a refresh or a sheet change)."""
        self.vocab.load(self.bridge.get_lists(), self.bridge.get_headers())
        self.vocab.numeric_columns = self.bridge.numeric_columns()
        self._apply_aliases()
        self._sheet = self.bridge.active_sheet_name()

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

    # ------------------------------------------------------------------ #
    # Dictation                                                            #
    # ------------------------------------------------------------------ #

    def handle_transcript(self, text: str) -> None:
        """Process one recognised phrase end to end."""
        if not self.connected:
            self.try_connect()   # a workbook may have been opened since we last looked
        else:
            self._follow_active_sheet()
        for event in self._refuse_without_workbook(self.session.feed(text)):
            self._carry_out(event)
            self._on_event(event)

    def _refuse_without_workbook(self, events: list[Event]) -> list[Event]:
        """With nothing to write to, swap "started" for guidance and keep the gate shut."""
        if self.connected or not any(e.kind == "started" for e in events):
            return events
        self.session.listening = False
        self.session.record.clear()
        return [Event("error", detail=NO_WORKBOOK_HELP) if e.kind == "started" else e
                for e in events]

    def set_listening(self, active: bool) -> None:
        """Open or close the listening gate without speech (tray / button)."""
        action = Action.START_LISTENING if active else Action.STOP_LISTENING
        if active and not self.connected and not self.try_connect():
            self._carry_out(Event("error", detail=NO_WORKBOOK_HELP))
            self._on_event(Event("error", detail=NO_WORKBOOK_HELP))
            return
        for event in self.session.apply(action):
            self._carry_out(event)
            self._on_event(event)

    def pending_terms(self) -> list[TermKey]:
        """Terms waiting to be sorted: ``(suggested column or None, words)``."""
        return list(self.session.pending or [])

    def resolve_term(self, key: TermKey, decision: Decision, term: str | None = None) -> None:
        """Apply the user's decision about one unrecognised term."""
        for event in self.session.resolve(key, decision, term):
            self._carry_out(event)
            self._on_event(event)

    def expire_prompt(self) -> None:
        """Give up waiting for a yes/no answer."""
        for event in self.session.expire_prompt():
            self._on_event(event)

    def _follow_active_sheet(self) -> None:
        """Reload field words if the user switched sheets in Excel."""
        try:
            current = self.bridge.active_sheet_name()
        except BridgeError:
            return
        if current != self._sheet:
            self.reload_vocab()
            self._on_event(Event("ignored", detail=f"Now on sheet '{current}'"))

    def _carry_out(self, event: Event) -> None:
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
        elif event.kind == "error" and event.detail == NO_WORKBOOK_HELP:
            self._say(event.detail)
        elif event.kind == "confirm":
            self._say(event.detail)

    def _say(self, text: str) -> None:
        """Speak *text* if there is a speaker, muting the mic meanwhile."""
        if self.speaker is None:
            return
        self._on_speech(True)
        self.speaker.say(text, on_done=lambda: self._on_speech(False))

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
            sheet = self.bridge.active_sheet_name()
            row = self.bridge.append_row(sheet, event.record)
            event.detail = f"Row {row}"
            self.session.tag_origin(event.terms or [], sheet, row)
        except BridgeError as exc:
            self.session.restore(event.record)
            self._on_event(Event("error", detail=f"Could not save the row: {exc}"))

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
            except BridgeError as exc:
                self._on_event(Event("error", detail=f"Could not fill {column} on row {row}: {exc}"))
