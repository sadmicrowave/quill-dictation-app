"""Plays Quill's short feedback sounds through Qt's audio."""

from __future__ import annotations
import os
import pathlib


class SoundPlayer:
    """Plays a WAV file; failures are swallowed (a missing sound must never break dictation).

    Setting the ``QUILL_NO_SOUND`` environment variable silences it (the tests do).
    """

    def __init__(self, volume: float = 0.8) -> None:
        self._volume = volume
        self._effects: dict[str, object] = {}

    def __call__(self, path: pathlib.Path) -> None:
        if os.environ.get("QUILL_NO_SOUND"):
            return
        try:
            effect = self._effects.get(str(path))
            if effect is None:
                from PySide6.QtCore import QUrl
                from PySide6.QtMultimedia import QSoundEffect
                effect = QSoundEffect()
                effect.setSource(QUrl.fromLocalFile(str(path)))
                effect.setVolume(self._volume)
                self._effects[str(path)] = effect
            effect.play()
        except Exception:
            pass
