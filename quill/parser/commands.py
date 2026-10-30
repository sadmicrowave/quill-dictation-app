"""Keyword-to-action state machine.

Watches incoming transcript segments for command keywords and routes
them to the appropriate action. Keywords and their bindings are loaded
from the user's config (or the shipped defaults).

Full implementation in Phase 6.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto


class Action(Enum):
    START_LISTENING = auto()
    STOP_LISTENING  = auto()
    NEXT_ROW        = auto()
    DELETE_ROW      = auto()
    SEARCH_FOR      = auto()
    NONE            = auto()   # no command found in this segment


@dataclass
class CommandEvent:
    """Emitted when a keyword is detected in a transcript segment."""
    action: Action
    remainder: str = ""   # transcript text after the keyword, if any


class CommandMatcher:
    """Matches transcript text against the active keyword map.

    Args:
        keyword_map: Mapping of lowercase keyword phrase -> Action.
                     Built from config/defaults.json + user overrides.
    """

    def __init__(self, keyword_map: dict[str, Action]) -> None:
        # Sort longest phrases first so "stop listening" matches before "stop"
        self._keywords: list[tuple[str, Action]] = sorted(
            keyword_map.items(), key=lambda kv: len(kv[0]), reverse=True
        )

    def match(self, text: str) -> CommandEvent:
        """Scan *text* for the first keyword match.

        Returns:
            CommandEvent with the matched action and any trailing text,
            or CommandEvent(Action.NONE) if no keyword is found.
        """
        lower = text.lower().strip()
        for phrase, action in self._keywords:
            if phrase in lower:
                idx = lower.index(phrase) + len(phrase)
                return CommandEvent(action=action, remainder=text[idx:].strip())
        return CommandEvent(action=Action.NONE, remainder=text)

    @classmethod
    def from_defaults(cls) -> "CommandMatcher":
        """Load the shipped default keyword map."""
        import json, pathlib
        defaults_path = pathlib.Path(__file__).parent.parent / "config" / "defaults.json"
        data = json.loads(defaults_path.read_text())
        mapping = {
            phrase: Action[action_name]
            for phrase, action_name in data["keywords"].items()
        }
        return cls(mapping)
