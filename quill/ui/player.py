"""Plays Quill's short feedback sounds through Qt's audio."""

from __future__ import annotations
import contextlib
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
        with contextlib.suppress(Exception):          # a sound that will not play must never break dictation
            self._effect(path).play()

    def preload(self, paths) -> None:
        """Load these sound files now, so the first time each plays it starts at once instead of after loading it."""
        if os.environ.get("QUILL_NO_SOUND"):
            return
        for path in paths:
            try:
                if pathlib.Path(path).is_file():
                    self._effect(path)
            except Exception:
                pass

    def _effect(self, path: pathlib.Path):
        """The (cached) sound effect for *path*; creating it starts loading the file."""
        effect = self._effects.get(str(path))
        if effect is None:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(str(path)))
            effect.setVolume(self._volume)
            self._effects[str(path)] = effect
        return effect
