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
from quill.session import Event, Session

EventCallback = Callable[[Event], None]


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

    # ------------------------------------------------------------------ #
    # Workbook connection                                                  #
    # ------------------------------------------------------------------ #

    def connect(self, workbook: str | None = None) -> None:
        """Connect the bridge and load the vocabulary from the workbook.

        Raises:
            BridgeError: if the workbook cannot be reached.
        """
        self.bridge.connect(workbook)
        self.reload_vocab()

    def reload_vocab(self) -> None:
        """Re-read lists and headers (after a refresh or a sheet change)."""
        self.vocab.load(self.bridge.get_lists(), self.bridge.get_headers())
        self._sheet = self.bridge.active_sheet_name()

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
        self._follow_active_sheet()
        for event in self.session.feed(text):
            self._carry_out(event)
            self._on_event(event)

    def set_listening(self, active: bool) -> None:
        """Open or close the listening gate without speech (tray / button)."""
        action = Action.START_LISTENING if active else Action.STOP_LISTENING
        for event in self.session.apply(action):
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
        elif event.kind == "confirm" and self.speaker is not None:
            self._on_speech(True)
            self.speaker.say(event.detail, on_done=lambda: self._on_speech(False))

    def _write_row(self, event: Event) -> None:
        try:
            row = self.bridge.append_row(self.bridge.active_sheet_name(), event.record)
            event.detail = f"Row {row}"
        except BridgeError as exc:
            self.session.restore(event.record)
            self._on_event(Event("error", detail=f"Could not save the row: {exc}"))

    def _write_values(self, event: Event) -> None:
        for column, value in event.values:
            try:
                self.bridge.add_to_list(column, value)
            except BridgeError as exc:
                self._on_event(Event("error", detail=f"Could not add '{value}': {exc}"))
