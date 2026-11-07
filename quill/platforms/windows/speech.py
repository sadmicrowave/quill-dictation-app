"""The system voice on Windows (SAPI through pyttsx3)."""

from __future__ import annotations

import logging
import pathlib

log = logging.getLogger("quill.speaker")


def speak(text: str) -> None:
    try:
        import pyttsx3
        engine = pyttsx3.init()   # one engine per utterance: SAPI engines are thread-bound
        engine.say(text)
        engine.runAndWait()
    except Exception as exc:
        log.debug("speech failed: %s", exc)


def render_clip(text: str, destination: pathlib.Path) -> bool:
    """Write *text* spoken by the system voice to a WAV file."""
    import pyttsx3
    engine = pyttsx3.init()
    engine.save_to_file(text, str(destination))
    engine.runAndWait()
    return destination.is_file()
