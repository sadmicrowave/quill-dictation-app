"""Microphone listener using Vosk offline speech recognition.

Captures audio from the default microphone via sounddevice, feeds it to a
Vosk ``KaldiRecognizer``, and reports each *final* phrase through a callback.
Everything stays on the machine; nothing is sent to the cloud.

The callback runs on the listener's background thread. UI code must hand the
text to the GUI thread (see :class:`quill.app.TranscriptRelay`).

Vosk and sounddevice are imported lazily, and both the recogniser and the
audio stream can be injected, so the loop is testable without a microphone
or a speech model.
"""

from __future__ import annotations
import json
import pathlib
import queue
import threading
from typing import Callable, ContextManager

TranscriptCallback = Callable[[str], None]
"""Type alias: called with each final transcript segment."""

ErrorCallback = Callable[[str], None]
"""Type alias: called with a human-readable message when listening fails."""

#: ``(sample_rate, audio_callback) -> context manager`` that streams audio.
StreamFactory = Callable[[int, Callable[[bytes], None]], ContextManager]

#: ``(model, sample_rate) -> recogniser`` with AcceptWaveform/Result.
RecognizerFactory = Callable[[object, int], object]


def _default_model_loader(path: pathlib.Path):
    from vosk import Model
    return Model(str(path))


def _default_recognizer(model, sample_rate: int):
    from vosk import KaldiRecognizer
    return KaldiRecognizer(model, sample_rate)


def _default_stream(sample_rate: int, push: Callable[[bytes], None]):
    import sounddevice

    def on_audio(indata, frames, time_info, status) -> None:
        push(bytes(indata))

    return sounddevice.RawInputStream(
        samplerate=sample_rate, blocksize=8000, dtype="int16", channels=1, callback=on_audio
    )


class Listener:
    """Wraps Vosk + sounddevice for cross-platform offline transcription.

    Args:
        model_path: Directory containing the Vosk model files.
        on_transcript: Callback called with each final recognised segment.
        sample_rate: Audio sample rate (Vosk small-en models use 16000).
        on_error: Called if the microphone or model cannot be opened.
        model_loader: Test seam: ``path -> model``.
        recognizer_factory: Test seam: ``(model, rate) -> recogniser``.
        stream_factory: Test seam: ``(rate, push) -> context manager``.
    """

    SAMPLE_RATE = 16_000

    def __init__(
        self,
        model_path: pathlib.Path,
        on_transcript: TranscriptCallback,
        sample_rate: int = SAMPLE_RATE,
        on_error: ErrorCallback | None = None,
        model_loader: Callable[[pathlib.Path], object] = _default_model_loader,
        recognizer_factory: RecognizerFactory = _default_recognizer,
        stream_factory: StreamFactory = _default_stream,
    ) -> None:
        self._model_path = model_path
        self._on_transcript = on_transcript
        self._sample_rate = sample_rate
        self._on_error = on_error or (lambda message: None)
        self._model_loader = model_loader
        self._recognizer_factory = recognizer_factory
        self._stream_factory = stream_factory

        self._model = None                       # loaded once; loading takes seconds
        self._audio: "queue.Queue[bytes]" = queue.Queue()
        self._drain = threading.Event()
        self._muted = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def running(self) -> bool:
        """True while the capture thread is active."""
        return self._running

    def start(self) -> None:
        """Begin capturing and recognising audio in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="quill-listener", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the capture thread to stop and wait briefly for it."""
        self._running = False
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def drain(self) -> None:
        """Discard buffered audio and restart the recogniser.

        Call this after Quill speaks so its own voice is not transcribed as
        user input. Takes effect on the capture thread's next loop.
        """
        self._drain.set()

    def mute(self) -> None:
        """Drop incoming audio until :meth:`unmute` (used while Quill speaks)."""
        self._muted.set()

    def unmute(self) -> None:
        """Resume recognition, discarding anything heard while muted."""
        self._drain.set()
        self._muted.clear()

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _clear_queue(self) -> None:
        while True:
            try:
                self._audio.get_nowait()
            except queue.Empty:
                return

    def _run(self) -> None:
        """Background thread: open microphone, feed Vosk, emit segments."""
        try:
            if self._model is None:
                self._model = self._model_loader(self._model_path)
            recognizer = self._recognizer_factory(self._model, self._sample_rate)
            with self._stream_factory(self._sample_rate, self._audio.put):
                while self._running:
                    if self._drain.is_set():
                        self._drain.clear()
                        self._clear_queue()
                        recognizer = self._recognizer_factory(self._model, self._sample_rate)
                        continue
                    try:
                        chunk = self._audio.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if self._muted.is_set():
                        continue
                    if recognizer.AcceptWaveform(chunk):
                        self._emit(recognizer.Result())
        except Exception as exc:   # model missing, no microphone, permission denied, ...
            self._running = False
            self._on_error(f"Listening stopped: {exc}")
        finally:
            self._clear_queue()

    def _emit(self, result_json: str) -> None:
        try:
            text = json.loads(result_json).get("text", "").strip()
        except (ValueError, AttributeError):
            return
        if text:
            self._on_transcript(text)
