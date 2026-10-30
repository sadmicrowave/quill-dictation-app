"""User-editable settings: keyword map and general preferences.

Settings persist as TOML in the OS user-config directory (via platformdirs).
Shipped defaults live in ``config/defaults.json`` and are always recoverable
with :meth:`Settings.reset_keywords`.

File format (``keywords.toml``)::

    [keywords]
    "next row" = "NEXT_ROW"

    [preferences]
    theme = "auto"

If the file has a ``[keywords]`` table it *replaces* the defaults, so keywords
the user deleted stay deleted. Without one, the defaults apply.

Usage:
    settings = Settings.load()
    settings.set_keywords([("next row", Action.NEXT_ROW), ...])
    settings.save()
"""

from __future__ import annotations
import json
import pathlib

try:
    import tomllib          # stdlib Python 3.11+
except ImportError:
    try:
        import tomli as tomllib   # backport for 3.9/3.10
    except ImportError:
        tomllib = None  # type: ignore[assignment]

from quill.parser.commands import RESERVED_ANSWER_WORDS, Action
from quill.parser.tokens import tokenize

#: Preference defaults. Types here define what is accepted on load.
DEFAULT_PREFERENCES: dict[str, object] = {
    "theme": "auto",          # "auto" | "light" | "dark"
    "speak_prompts": True,    # read questions aloud
    "model_path": "",         # Vosk model folder; empty = search the usual places
    "last_workbook": "",      # re-selected on launch when still open
    "prompt_timeout_s": 20,   # seconds to wait for a yes/no answer
}

THEMES = ("auto", "light", "dark")


def _config_dir() -> pathlib.Path:
    """Return the OS user-config directory for Quill, creating it if needed."""
    try:
        from platformdirs import user_config_dir
        base = pathlib.Path(user_config_dir("Quill", appauthor=False))
    except ImportError:
        base = pathlib.Path.home() / ".quill"   # fallback without platformdirs
    base.mkdir(parents=True, exist_ok=True)
    return base


def _defaults_path() -> pathlib.Path:
    return pathlib.Path(__file__).parent / "defaults.json"


def _parse_keywords(table: dict) -> dict[str, Action]:
    """Convert a ``{phrase: "ACTION_NAME"}`` table, dropping unknown actions."""
    result: dict[str, Action] = {}
    for phrase, action_name in table.items():
        try:
            result[phrase.lower()] = Action[action_name]
        except (KeyError, TypeError):
            pass  # unknown action (e.g. from a newer version) — skip
    return result


def _toml_value(value: object) -> str:
    """Render a bool / int / str preference as a TOML value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value))   # JSON string escapes are valid TOML basic strings


class Settings:
    """Holds the active keyword map and user preferences.

    Args:
        keywords: phrase -> Action.
        preferences: Overrides for ``DEFAULT_PREFERENCES``.
        config_dir: Where ``keywords.toml`` lives (default: the OS config dir).
    """

    KEYWORDS_FILE = "keywords.toml"

    def __init__(
        self,
        keywords: dict[str, Action],
        preferences: dict[str, object] | None = None,
        config_dir: pathlib.Path | None = None,
    ) -> None:
        self.keywords = keywords          # phrase -> Action
        self.preferences: dict[str, object] = {**DEFAULT_PREFERENCES, **(preferences or {})}
        self._config_dir = config_dir

    # ------------------------------------------------------------------ #
    # Load                                                                 #
    # ------------------------------------------------------------------ #

    @classmethod
    def defaults(cls, config_dir: pathlib.Path | None = None) -> "Settings":
        """Settings with only the shipped defaults (nothing read from disk)."""
        data = json.loads(_defaults_path().read_text(encoding="utf-8"))
        return cls(_parse_keywords(data["keywords"]), config_dir=config_dir)

    @classmethod
    def load(cls, config_dir: pathlib.Path | None = None) -> "Settings":
        """Load settings: the shipped defaults, replaced by the user's file if present.

        A missing or unreadable file silently yields the defaults.

        Args:
            config_dir: Override the config directory (tests use a temp dir).
        """
        settings = cls.defaults(config_dir)
        data = cls._read_user_file(settings._dir())
        keywords = data.get("keywords")
        if isinstance(keywords, dict):
            settings.keywords = _parse_keywords(keywords)
        prefs = data.get("preferences")
        if isinstance(prefs, dict):
            for key, default in DEFAULT_PREFERENCES.items():
                value = prefs.get(key)
                # Keep a value only if it has the same type as the default (bool is not int).
                if value is not None and type(value) is type(default):
                    settings.preferences[key] = value
        if settings.preferences["theme"] not in THEMES:
            settings.preferences["theme"] = DEFAULT_PREFERENCES["theme"]
        return settings

    @classmethod
    def _read_user_file(cls, directory: pathlib.Path) -> dict:
        path = directory / cls.KEYWORDS_FILE
        if tomllib is None or not path.exists():
            return {}
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception:   # corrupt file: fall back to defaults rather than crash at launch
            return {}

    def _dir(self) -> pathlib.Path:
        if self._config_dir is not None:
            self._config_dir.mkdir(parents=True, exist_ok=True)
            return self._config_dir
        return _config_dir()

    # ------------------------------------------------------------------ #
    # Edit                                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def validate_keywords(rows: list[tuple[str, Action]]) -> list[str]:
        """Check a proposed keyword table and return human-readable problems.

        Rules: phrases must contain a word; no duplicates (ignoring case and
        punctuation); no phrase may be just a reserved yes/no answer word;
        and START_LISTENING / STOP_LISTENING must each keep a phrase so the
        user cannot lock themselves out.

        Args:
            rows: ``(phrase, action)`` pairs in table order.

        Returns:
            A list of error messages; empty when the table is valid.
        """
        errors: list[str] = []
        seen: dict[tuple[str, ...], str] = {}
        for phrase, _ in rows:
            key = tuple(tokenize(phrase))
            if not key:
                errors.append("Every keyword needs at least one word.")
                continue
            if key in seen:
                errors.append(f"Duplicate keyword: '{phrase.strip()}'.")
            seen.setdefault(key, phrase)
            if len(key) == 1 and key[0] in RESERVED_ANSWER_WORDS:
                errors.append(
                    f"'{phrase.strip()}' is reserved for answering questions "
                    "(yes/no); pick a different word."
                )
        actions = {action for _, action in rows}
        for required in (Action.START_LISTENING, Action.STOP_LISTENING):
            if required not in actions:
                errors.append(f"Keep at least one keyword for {required.name.replace('_', ' ').title()}.")
        return errors

    def set_keywords(self, rows: list[tuple[str, Action]]) -> None:
        """Replace the keyword map after validating it.

        Raises:
            ValueError: with the validation messages, if the table is invalid.
        """
        errors = self.validate_keywords(rows)
        if errors:
            raise ValueError("\n".join(errors))
        self.keywords = {phrase.strip().lower(): action for phrase, action in rows}

    def reset_keywords(self) -> None:
        """Restore the shipped default keywords (preferences are untouched)."""
        self.keywords = self.defaults().keywords

    # ------------------------------------------------------------------ #
    # Save                                                                 #
    # ------------------------------------------------------------------ #

    def save(self) -> None:
        """Write keywords and preferences to TOML in the config dir."""
        lines = ["[keywords]\n"]
        for phrase, action in sorted(self.keywords.items()):
            lines.append(f"{json.dumps(phrase)} = {json.dumps(action.name)}\n")
        lines.append("\n[preferences]\n")
        for key in DEFAULT_PREFERENCES:
            lines.append(f"{key} = {_toml_value(self.preferences[key])}\n")
        (self._dir() / self.KEYWORDS_FILE).write_text("".join(lines), encoding="utf-8")
