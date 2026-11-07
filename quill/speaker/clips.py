"""Spoken confirmation words as ready-made sound clips, so they play the instant they are needed.

Asking the system voice to say a word takes one to three seconds (starting the speech process, loading the
voice, synthesising), which makes a voice app feel slow. The few words Quill can say ("Okay", "Done",
"Ignored" ...) are therefore rendered to small WAV files **once**, on a background thread, and kept in the
user's cache folder; afterwards they are played like any other sound. A word with no clip yet is spoken the
old way (and its clip is made for next time). Everything stays on the computer.

The renderer is injectable, so the logic is tested without any speech engine.
"""

from __future__ import annotations
import logging
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
from typing import Callable
from quill import platforms

log = logging.getLogger("quill.clips")

Renderer = Callable[[str, pathlib.Path], bool]
"""``(text, destination.wav) -> success``: make a WAV of the system voice saying *text*."""


def clips_dir() -> pathlib.Path:
    """The per-user cache folder for rendered clips (created if needed)."""
    try:
        from platformdirs import user_cache_dir
        folder = pathlib.Path(user_cache_dir("Quill", appauthor=False)) / "clips"
    except ImportError:
        folder = pathlib.Path.home() / ".quill" / "clips"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def render_with_system_voice(text: str, destination: pathlib.Path) -> bool:
    """Render *text* with the operating system's voice to a 22 kHz mono WAV; False if that is not possible."""
    if os.environ.get("QUILL_NO_SOUND"):
        return False
    try:
        render = platforms.offered(sys.platform, "render_clip")
        if render is not None:
            return bool(render(text, destination))
    except Exception as exc:                                 # no voice, no tool, no permission: fall back to live speech
        log.debug("could not render %r: %s", text, exc)
    return False


class SpokenClips:
    """A cache of short spoken words as WAV files.

    Args:
        folder: Where the clips live (default: the per-user cache folder).
        render: Makes a clip (default: the system voice).
    """

    def __init__(self, folder: pathlib.Path | None = None, render: Renderer | None = None) -> None:
        self._folder = folder
        self._render = render or render_with_system_voice
        self._lock = threading.Lock()
        self._working: set[str] = set()

    @property
    def folder(self) -> pathlib.Path:
        if self._folder is None:
            self._folder = clips_dir()
        self._folder.mkdir(parents=True, exist_ok=True)
        return self._folder

    def path(self, word: str) -> pathlib.Path:
        """Where the clip for *word* is (or will be) stored."""
        slug = re.sub(r"[^a-z0-9]+", "_", word.lower()).strip("_") or "word"
        return self.folder / f"{slug}.wav"

    def ready(self, word: str) -> bool:
        """True if the clip for *word* exists and has some content (never in silent mode, i.e. the tests)."""
        if os.environ.get("QUILL_NO_SOUND"):
            return False
        clip = self.path(word)
        return clip.is_file() and clip.stat().st_size > 44            # (a bare WAV header has no sound in it)

    def make(self, word: str) -> bool:
        """Render *word* now (blocks, so call it off the GUI thread); True when its clip is ready."""
        if self.ready(word):
            return True
        with self._lock:
            if word in self._working:
                return False
            self._working.add(word)
        try:
            target = self.path(word)
            partial = target.with_suffix(".part.wav")                 # written aside, so a half clip is never played
            if self._render(word, partial) and partial.is_file():
                partial.replace(target)
                return True
            partial.unlink(missing_ok=True)
            return False
        finally:
            with self._lock:
                self._working.discard(word)

    def make_in_background(self, words, done: Callable[[list[pathlib.Path]], None] | None = None) -> threading.Thread:
        """Render every word in *words* that has no clip, on a helper thread; *done* gets the clips made."""
        def work() -> None:
            made = [self.path(w) for w in words if not self.ready(w) and self.make(w)]
            if done is not None and made:
                done(made)

        thread = threading.Thread(target=work, name="quill-clips", daemon=True)
        thread.start()
        return thread
