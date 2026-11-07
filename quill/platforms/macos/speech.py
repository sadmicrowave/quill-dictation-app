"""The system voice on a Mac (the built-in ``say`` tool, and ``afconvert`` to make a WAV clip)."""

from __future__ import annotations

import logging
import pathlib
import subprocess
import tempfile

log = logging.getLogger("quill.speaker")


def speak(text: str) -> None:
    try:
        # "--" ends the options, so spoken text that starts with "-" is never read as a ``say`` option.
        subprocess.run(["say", "--", text], check=False, timeout=30)    # noqa: S603, S607 (built-in macOS tool)
    except Exception as exc:
        log.debug("speech failed: %s", exc)   # TTS is a nicety; the prompt is also logged


def render_clip(text: str, destination: pathlib.Path) -> bool:
    """Write *text* spoken by the system voice to a 22 kHz mono WAV file."""
    with tempfile.TemporaryDirectory() as tmp:
        raw = pathlib.Path(tmp) / "clip.aiff"
        subprocess.run(["say", "-o", str(raw), "--", text], check=True, timeout=30)       # noqa: S603, S607
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@22050", str(raw), str(destination)],
                       check=True, timeout=30)                                             # noqa: S603, S607
    return destination.is_file()
