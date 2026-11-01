"""Audible feedback: a short sound (or a spoken word) for what Quill just did.

Four cues cover everything:

  success .. a row saved cleanly, a term added, a search run
  sort ..... terms need sorting (the app also brings the sorting window forward)
  dismiss .. ignore, undo, delete row
  error .... something went wrong or wasn't understood

Several events can land together (a voice-sort chain answers many terms in one
breath), so cues are *requested* and then *flushed* once: only the most
important one plays. ``error`` beats ``sort`` beats ``dismiss`` beats ``success``.

This module has no Qt or audio code. The app supplies ``play(path)`` and
``say(text)``, which keeps it testable and keeps the microphone muting in one place.
"""

from __future__ import annotations
import pathlib
import wave
from typing import Callable

CUES = ("success", "sort", "dismiss", "error")
PRIORITY = {"success": 0, "dismiss": 1, "sort": 2, "error": 3}

#: Feedback modes: nothing, a sound, or a spoken word.
MODES = ("off", "sounds", "echo")
MODE_LABELS = {"off": "Off", "sounds": "Short sounds", "echo": "Spoken Word"}

#: Sound packs (folder name -> label in Settings).
PACKS = {"chime": "Chime", "marimba": "Marimba", "glass": "Glass",
         "digital": "Digital", "walkie": "Walkie-Talkie"}

#: Word spoken for a success in echo mode (key -> the word).
ECHO_WORDS = {"okay": "Okay", "done": "Done", "got_it": "Got It"}

SOUNDS_DIR = pathlib.Path(__file__).parent / "sounds"

#: Spoken for the other cues in echo mode; dismiss uses the kind of event.
_ECHO_FIXED = {"sort": "Please Sort", "error": "Problem"}
_DISMISS_WORDS = {"skipped": "Ignored", "undone": "Undone", "discarded": "Deleted"}

_SUCCESS_KINDS = {"add_values", "alias_added", "searched", "cleared"}
_DISMISS_KINDS = {"skipped", "undone", "discarded"}
_ERROR_KINDS = {"error", "unsure"}

#: Events that are answers given in the Term Helper (their confirmation sounds can be turned off in Settings).
SORTING_KINDS = frozenset({"add_values", "alias_added", "skipped", "sorting"})


def spoken_words() -> list[str]:
    """Every word Quill can say as a confirmation (so their clips can be made ahead of time)."""
    return sorted({*ECHO_WORDS.values(), *_ECHO_FIXED.values(), *_DISMISS_WORDS.values()})


def cue_for(event) -> tuple[str, str] | None:
    """Decide which cue an event deserves.

    Returns:
        ``(cue, dismiss_word)`` or None for events that stay quiet. A row that
        was saved with terms still to sort is silent here: the ``confirm`` event
        that follows it asks for sorting.
    """
    kind = event.kind
    if kind == "committed":
        return None if event.terms else ("success", "")
    if kind == "confirm":
        return ("sort", "")
    if kind == "sorting" and (event.record or {}).get("problem"):
        return ("error", "")
    if kind in _ERROR_KINDS:
        return ("error", "")
    if kind in _DISMISS_KINDS:
        return ("dismiss", _DISMISS_WORDS[kind])
    if kind in _SUCCESS_KINDS:
        return ("success", "")
    return None


def sound_path(pack: str, cue: str, root: pathlib.Path = SOUNDS_DIR) -> pathlib.Path:
    """File for *cue* in *pack* (an unknown pack falls back to the first)."""
    return root / (pack if pack in PACKS else next(iter(PACKS))) / f"{cue}.wav"


def duration_s(path: pathlib.Path) -> float:
    """Length of a WAV file in seconds (0 if it can't be read)."""
    try:
        with wave.open(str(path), "rb") as f:
            return f.getnframes() / float(f.getframerate())
    except (OSError, EOFError, wave.Error):
        return 0.0


class Feedback:
    """Turns events into one short sound or spoken word.

    Args:
        settings: Anything with a ``preferences`` dict (``feedback``,
            ``sound_pack``, ``echo_style``).
        play: Called with a WAV path to play it.
        say: Called with a word to speak.
        busy: Called with the seconds the speaker/player will be making noise
            so the microphone can be muted that long.
        root: Folder holding the sound packs.
    """

    def __init__(self, settings, play: Callable[[pathlib.Path], None],
                 say: Callable[[str], None], busy: Callable[[float], None] | None = None,
                 root: pathlib.Path = SOUNDS_DIR) -> None:
        self._settings = settings
        self._play = play
        self._say = say
        self._busy = busy or (lambda seconds: None)
        self._root = root
        self._wanted: tuple[str, str] | None = None

    def sound_files(self, all_packs: bool = False) -> list[pathlib.Path]:
        """The sound files this feedback may play: the chosen pack's, or every pack's (to load them ahead of time)."""
        packs = list(PACKS) if all_packs else [str(self._settings.preferences.get("sound_pack", "chime"))]
        return [sound_path(pack, cue, self._root) for pack in packs for cue in CUES]

    @property
    def mode(self) -> str:
        """How Quill confirms what it did: one of :data:`MODES` (sounds, a spoken word or nothing)."""
        mode = self._settings.preferences.get("feedback", "sounds")
        return mode if mode in MODES else "sounds"

    def request(self, event) -> None:
        """Note the cue *event* deserves; the best one is played by :meth:`flush`."""
        hit = cue_for(event)
        if hit is None or self.mode == "off":
            return
        if event.kind in SORTING_KINDS and not self._settings.preferences.get("sorting_sounds", True):
            return                                           # the user turned off the Term Helper's completion sounds
        if self._wanted is None or PRIORITY[hit[0]] > PRIORITY[self._wanted[0]]:
            self._wanted = hit

    def flush(self) -> str | None:
        """Play the most important requested cue; returns its name (None if none)."""
        wanted, self._wanted = self._wanted, None
        if wanted is None:
            return None
        self.cue(*wanted)
        return wanted[0]

    def cue(self, cue: str, dismiss_word: str = "", mode: str | None = None,
            pack: str | None = None, echo: str | None = None) -> None:
        """Play or speak *cue* now (arguments override the settings, for previews)."""
        mode = mode or self.mode
        prefs = self._settings.preferences
        if mode == "sounds":
            path = sound_path(pack or str(prefs.get("sound_pack", "chime")), cue, self._root)
            self._busy(duration_s(path) + 0.15)
            self._play(path)
        elif mode == "echo":
            word = self.word(cue, dismiss_word, echo)
            self._busy(0.2 + 0.09 * len(word))
            self._say(word)

    def word(self, cue: str, dismiss_word: str = "", echo: str | None = None) -> str:
        """The word spoken for *cue* in echo mode."""
        if cue == "success":
            key = echo or str(self._settings.preferences.get("echo_style", "okay"))
            return ECHO_WORDS.get(key, ECHO_WORDS["okay"])
        if cue == "dismiss":
            return dismiss_word or "Ignored"
        return _ECHO_FIXED[cue]

    def lead_in_s(self) -> float:
        """How long the sort cue lasts, so a spoken question can wait for it."""
        if self.mode != "sounds":
            return 0.0
        pack = str(self._settings.preferences.get("sound_pack", "chime"))
        return duration_s(sound_path(pack, "sort", self._root)) + 0.1
