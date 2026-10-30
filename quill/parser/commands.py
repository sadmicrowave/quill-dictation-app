"""Keyword-to-action matching.

Scans transcripts for command keywords ("start listening", "next row", ...)
and splits speech into alternating command and text segments. Keywords and
their bindings come from the user's settings (or the shipped defaults).

Matching is token-based, so the keyword "cancel" never fires inside another
word, apostrophes and punctuation are ignored, and the longest phrase wins
("stop listening" before a hypothetical "stop").
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto

from quill.parser.tokens import tokenize


class Action(Enum):
    """Things a spoken keyword can make the app do."""

    START_LISTENING = auto()
    STOP_LISTENING  = auto()
    NEXT_ROW        = auto()
    DELETE_ROW      = auto()
    SEARCH_FOR      = auto()
    CLEAR_SEARCH    = auto()
    NONE            = auto()   # no command found in this segment


#: Spoken answers to a yes/no question. They are reserved: a keyword may not
#: use one of these words by itself, or answering a question would fire it.
YES_WORDS = frozenset({"yes", "yeah", "yep", "yup", "sure", "okay", "ok", "add", "please", "correct"})
NO_WORDS = frozenset({"no", "nope", "skip", "cancel", "ignore", "dont", "nah"})

#: Answer words a keyword may not use alone. "cancel" is excluded on purpose: it
#: is a shipped keyword, and while a question is pending the session reads it as "no".
RESERVED_ANSWER_WORDS = YES_WORDS | (NO_WORDS - {"cancel"})

#: Actions that consume the words after the keyword as their argument.
ARGUMENT_ACTIONS = frozenset({Action.SEARCH_FOR})


@dataclass
class CommandEvent:
    """Emitted when a keyword is detected in a transcript."""

    action: Action
    remainder: str = ""
    """Transcript text after the keyword (the argument, for ARGUMENT_ACTIONS)."""


#: One piece of a split transcript: plain text to parse, or a command.
Segment = str | CommandEvent


class CommandMatcher:
    """Matches transcript text against the active keyword map.

    Args:
        keyword_map: Mapping of keyword phrase -> Action. Phrases are
            tokenised, so case, punctuation and apostrophes don't matter;
            phrases with no tokens are ignored.
    """

    def __init__(self, keyword_map: dict[str, Action]) -> None:
        pairs = [(tuple(tokenize(phrase)), action) for phrase, action in keyword_map.items()]
        # Longest phrases first so the most specific keyword wins.
        self._keywords: list[tuple[tuple[str, ...], Action]] = sorted(
            [p for p in pairs if p[0]], key=lambda p: len(p[0]), reverse=True
        )

    def _keyword_at(self, tokens: list[str], i: int) -> tuple[Action, int] | None:
        for words, action in self._keywords:
            n = len(words)
            if tuple(tokens[i:i + n]) == words:
                return action, n
        return None

    def match(self, text: str) -> CommandEvent:
        """Find the first keyword in *text*.

        Returns:
            A CommandEvent with the action and the words after it, or
            ``CommandEvent(Action.NONE, text)`` if no keyword is found.
        """
        tokens = tokenize(text)
        for i in range(len(tokens)):
            hit = self._keyword_at(tokens, i)
            if hit:
                action, n = hit
                return CommandEvent(action=action, remainder=" ".join(tokens[i + n:]))
        return CommandEvent(action=Action.NONE, remainder=" ".join(tokens))

    def split(self, text: str) -> list[Segment]:
        """Split *text* into text segments and command events, in speech order.

        ``"fern small next row bright"`` becomes
        ``["fern small", CommandEvent(NEXT_ROW), "bright"]``. For actions in
        ``ARGUMENT_ACTIONS`` the words up to the next keyword become the
        command's ``remainder`` instead of a text segment.
        """
        tokens = tokenize(text)
        segments: list[Segment] = []
        words: list[str] = []
        i = 0

        def flush() -> None:
            if words:
                segments.append(" ".join(words))
                words.clear()

        while i < len(tokens):
            hit = self._keyword_at(tokens, i)
            if hit is None:
                words.append(tokens[i])
                i += 1
                continue
            flush()
            action, n = hit
            i += n
            remainder: list[str] = []
            if action in ARGUMENT_ACTIONS:
                while i < len(tokens) and self._keyword_at(tokens, i) is None:
                    remainder.append(tokens[i])
                    i += 1
            segments.append(CommandEvent(action, " ".join(remainder)))
        flush()
        return segments

    @classmethod
    def from_defaults(cls) -> "CommandMatcher":
        """Build a matcher from the shipped default keyword map."""
        from quill.config.settings import Settings
        return cls(Settings.defaults().keywords)
