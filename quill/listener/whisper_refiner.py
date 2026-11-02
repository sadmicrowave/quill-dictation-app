"""Optional second pass: a Whisper-class model re-reads each finished phrase.

The live recogniser (Vosk) keeps showing words as they are spoken and decides where a phrase ends. When a
phrase ends, the audio of it goes to a Whisper model, which is far better at ordinary speech but cannot work
word by word. Its text replaces Vosk's for that phrase; if it fails or hears nothing, Vosk's text is used, so
this can only help. Everything runs on the computer.

The engine is ``faster-whisper`` (CTranslate2). It is imported only when first needed, so Quill starts and works
without it. The model folder is the CTranslate2 conversion of Whisper ``base.en``.
"""

from __future__ import annotations
import logging
import re
import threading
from typing import Callable

log = logging.getLogger("quill.whisper")

SAMPLE_RATE = 16_000
_PUNCTUATION = re.compile(r"[,;:!?\"“”()\[\]]")


def engine_available() -> bool:
    """True if the faster-whisper package can be imported."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def normalize(text: str) -> str:
    """Whisper writes sentences ("I bought it, in the 1990s."): make it the plain lowercase words the parser reads."""
    text = _PUNCTUATION.sub(" ", text).replace("…", " ")
    text = re.sub(r"(?<!\d)\.(?!\d)", " ", text)                    # full stops, but not the one in 3.5
    return " ".join(text.lower().split())


class WhisperRefiner:
    """Turns a phrase's audio into text with a Whisper model.

    Args:
        model_dir: Folder of the CTranslate2 model.
        hint: ``() -> str``, words the speaker is likely to say (the sheet's own list values), given to the model as
            a prompt so it spells them the way the sheet does.
        loader: Test seam: ``model_dir -> model`` where ``model.transcribe(audio, **options)`` yields segments.
    """

    def __init__(self, model_dir, hint: Callable[[], str] | None = None, loader: Callable | None = None) -> None:
        self._dir = model_dir
        self._hint = hint or (lambda: "")
        self._loader = loader or self._default_loader
        self._model = None
        self._lock = threading.Lock()

    @staticmethod
    def _default_loader(model_dir):
        from faster_whisper import WhisperModel
        return WhisperModel(str(model_dir), device="cpu", compute_type="int8", cpu_threads=4)

    def preload(self) -> None:
        """Load the model now (it takes a second or so), so the first phrase is not delayed."""
        self._ensure()

    def _ensure(self):
        with self._lock:
            if self._model is None:
                self._model = self._loader(self._dir)
            return self._model

    def refine(self, pcm: bytes) -> str | None:
        """The text of 16-bit mono 16 kHz audio, normalised; None when it could not be read or nothing was heard."""
        try:
            import numpy as np
            audio = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
            if audio.size < SAMPLE_RATE // 4:                       # under a quarter of a second: nothing to read
                return None
            model = self._ensure()
            segments, _ = model.transcribe(
                audio, language="en", beam_size=1, without_timestamps=True, condition_on_previous_text=False,
                initial_prompt=self._hint() or None, vad_filter=False)
            text = normalize(" ".join(segment.text for segment in segments))
            return text or None
        except Exception:                                           # never let a failed second look lose the phrase
            log.exception("whisper could not read the phrase")
            return None
