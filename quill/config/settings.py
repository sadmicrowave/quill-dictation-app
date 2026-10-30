"""User-editable settings: keyword map and general preferences.

Settings are persisted as TOML in the OS-appropriate user config directory
(via platformdirs). Shipped defaults live in config/defaults.json.

Usage:
    settings = Settings.load()
    settings.keywords["next row"] = Action.NEXT_ROW
    settings.save()
"""

from __future__ import annotations
import json
import pathlib
import sys

try:
    import tomllib          # stdlib Python 3.11+
except ImportError:
    try:
        import tomli as tomllib   # backport for 3.9/3.10
    except ImportError:
        tomllib = None  # type: ignore[assignment]

from quill.parser.commands import Action


def _config_dir() -> pathlib.Path:
    """Return the OS user-config directory for Quill, creating it if needed."""
    try:
        from platformdirs import user_config_dir
        base = pathlib.Path(user_config_dir("Quill", appauthor=False))
    except ImportError:
        # Fallback: ~/.quill
        base = pathlib.Path.home() / ".quill"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _defaults_path() -> pathlib.Path:
    return pathlib.Path(__file__).parent / "defaults.json"


class Settings:
    """Holds the active keyword map and any other user preferences."""

    KEYWORDS_FILE = "keywords.toml"

    def __init__(self, keywords: dict[str, Action]) -> None:
        self.keywords = keywords          # phrase -> Action

    # ------------------------------------------------------------------ #
    # Load                                                                 #
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls) -> "Settings":
        """Load settings: defaults first, then user overrides on top."""
        defaults = cls._load_defaults()
        overrides = cls._load_overrides()
        merged = {**defaults, **overrides}
        return cls(keywords=merged)

    @classmethod
    def _load_defaults(cls) -> dict[str, Action]:
        data = json.loads(_defaults_path().read_text())
        result: dict[str, Action] = {}
        for phrase, action_name in data["keywords"].items():
            try:
                result[phrase.lower()] = Action[action_name]
            except KeyError:
                pass  # unknown action in defaults — skip silently
        return result

    @classmethod
    def _load_overrides(cls) -> dict[str, Action]:
        if tomllib is None:
            return {}
        override_path = _config_dir() / cls.KEYWORDS_FILE
        if not override_path.exists():
            return {}
        try:
            data = tomllib.loads(override_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        result: dict[str, Action] = {}
        for phrase, action_name in data.get("keywords", {}).items():
            try:
                result[phrase.lower()] = Action[action_name]
            except KeyError:
                pass
        return result

    # ------------------------------------------------------------------ #
    # Save                                                                 #
    # ------------------------------------------------------------------ #

    def save(self) -> None:
        """Write user keyword overrides to TOML in the config dir."""
        lines = ["[keywords]\n"]
        for phrase, action in sorted(self.keywords.items()):
            safe = phrase.replace('"', '\\"')
            lines.append(f'"{safe}" = "{action.name}"\n')
        override_path = _config_dir() / self.KEYWORDS_FILE
        override_path.write_text("".join(lines), encoding="utf-8")
