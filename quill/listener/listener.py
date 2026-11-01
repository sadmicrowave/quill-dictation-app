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
import logging
import math
import pathlib
import queue
import threading
from array import array
from typing import Callable, ContextManager

log = logging.getLogger("quill.listener")

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
        samplerate=sample_rate, blocksize=1600, dtype="int16", channels=1, callback=on_audio
    )


class Listener:
    """Wraps Vosk + sounddevice for cross-platform offline transcription.

    Args:
        model_path: Directory containing the Vosk model files.
        on_transcript: Callback called with each final recognised segment.
        sample_rate: Audio sample rate (Vosk small-en models use 16000).
        on_error: Called if the microphone or model cannot be opened.
        on_partial: Called with the words of the phrase still being spoken, as they are recognised
            (changes only; an empty string once the phrase is final).
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
        on_partial: TranscriptCallback | None = None,
    ) -> None:
        self._model_path = model_path
        self._on_transcript = on_transcript
        self._sample_rate = sample_rate
        self._on_error = on_error or (lambda message: None)
        self._on_partial = on_partial
        self._last_partial = ""
        self._on_level: Callable[[float], None] | None = None
        self._model_loader = model_loader
        self._recognizer_factory = recognizer_factory
        self._stream_factory = stream_factory

        self._model = None                       # loaded once; loading takes seconds
        self._audio: "queue.Queue[bytes]" = queue.Queue()
        self._drain = threading.Event()
        self._muted = threading.Event()
        self._running = False
        self._loading = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def running(self) -> bool:
        """True while the capture thread is active."""
        return self._running

    def preload(self) -> None:
        """Load the speech model in the background *without* opening the microphone.

        Loading takes a few seconds; doing it ahead of time makes :meth:`start`
        (which is what opens the microphone) quick.
        """
        if self._model is not None or self._loading:
            return
        self._loading = True

        def load() -> None:
            try:
                if self._model is None:
                    self._model = self._model_loader(self._model_path)
            except Exception as exc:
                self._on_error(f"Could not load the speech model: {exc}")
            finally:
                self._loading = False

        threading.Thread(target=load, name="quill-model-loader", daemon=True).start()

    def set_level_callback(self, callback: Callable[[float], None] | None) -> None:
        """Be told how loud the user's voice is (0 to 1) for every chunk of audio (on the listener's thread)."""
        self._on_level = callback

    @staticmethod
    def loudness(chunk: bytes) -> float:
        """A 0 to 1 loudness for a chunk of 16-bit audio (quiet room near 0, a normal voice around 0.5 to 1)."""
        samples = array("h")
        samples.frombytes(chunk[: len(chunk) // 2 * 2])
        if not samples:
            return 0.0
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        return min(1.0, (rms / 3500.0) ** 0.6)

    def set_partial_callback(self, callback: TranscriptCallback | None) -> None:
        """Receive the words of the phrase being spoken as they are recognised (see ``on_partial``)."""
        self._on_partial = callback

    def start(self) -> None:
        """Open the microphone and begin recognising audio in a background thread."""
        if self._running:
            return
        log.debug("opening the microphone")
        self._running = True
        self._thread = threading.Thread(target=self._run, name="quill-listener", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Close the microphone: signal the capture thread to stop and wait briefly for it."""
        log.debug("closing the microphone")
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
                    if self._on_level is not None:
                        self._on_level(self.loudness(chunk))
                    if recognizer.AcceptWaveform(chunk):
                        self._emit(recognizer.Result())
                        self._partial("")
                    elif self._on_partial is not None:
                        self._partial(self._read_partial(recognizer))
        except Exception as exc:   # model missing, no microphone, permission denied, ...
            log.exception("listening stopped")
            self._running = False
            self._on_error(f"Listening stopped: {exc}")
        finally:
            self._clear_queue()

    @staticmethod
    def _read_partial(recognizer) -> str:
        try:
            return json.loads(recognizer.PartialResult()).get("partial", "").strip()
        except (AttributeError, ValueError):
            return ""

    def _partial(self, text: str) -> None:
        """Report the unfinished phrase when it has changed."""
        if self._on_partial is not None and text != self._last_partial:
            self._last_partial = text
            self._on_partial(text)

    def _emit(self, result_json: str) -> None:
        try:
            text = json.loads(result_json).get("text", "").strip()
        except (ValueError, AttributeError):
            return
        if text:
            log.debug("heard: %s", text)
            self._on_transcript(text)
