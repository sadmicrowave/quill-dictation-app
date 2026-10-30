"""Microphone listener using Vosk offline speech recognition.

Captures audio from the default microphone via sounddevice, feeds it to
a Vosk KaldiRecogniser, and emits transcript segments as strings via a
callback.

Full implementation in Phase 5. This stub exposes the public interface.
"""

from __future__ import annotations
import pathlib
import threading
from typing import Callable


TranscriptCallback = Callable[[str], None]
"""Type alias: called with each final transcript segment."""


class Listener:
    """Wraps Vosk + sounddevice for cross-platform offline transcription.

    Args:
        model_path: Directory containing the Vosk model files.
        on_transcript: Callback called with each final recognised segment.
        sample_rate: Audio sample rate (Vosk small-en models use 16000).
    """

    SAMPLE_RATE = 16_000

    def __init__(
        self,
        model_path: pathlib.Path,
        on_transcript: TranscriptCallback,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self._model_path = model_path
        self._on_transcript = on_transcript
        self._sample_rate = sample_rate
        self._running = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Begin capturing and recognising audio in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the capture thread to stop."""
        self._running = False

    def drain(self) -> None:
        """Drain the audio buffer after the speaker talks.

        Recreates the Vosk recogniser so stale audio from the speaker
        is not transcribed as user input.
        """
        # TODO (Phase 5): flush sounddevice queue; recreate KaldiRecogniser
        pass

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _run(self) -> None:
        """Background thread: open microphone, feed Vosk, emit segments."""
        # TODO (Phase 5): implement with sounddevice.RawInputStream + vosk
        pass
