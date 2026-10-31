"""User-editable settings: keyword map and general preferences.

Settings persist as TOML in the OS user-config directory (via platformdirs).
Shipped defaults live in ``config/defaults.json`` and are always recoverable
with :meth:`Settings.reset_keywords`.

File format (``keywords.toml``)::

    [keywords]
    "next row" = "NEXT_ROW"

    [preferences]
    theme = "auto"

    [aliases."Size"]
    "extra large" = "XL"

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

from quill.feedback import ECHO_WORDS, MODES, PACKS
from quill.parser.commands import RESERVED_ANSWER_WORDS, Action
from quill.parser.tokens import tokenize

#: Preference defaults. Types here define what is accepted on load.
DEFAULT_PREFERENCES: dict[str, object] = {
    "theme": "auto",          # "auto" | "light" | "dark"
    "speak_prompts": True,    # read questions aloud
    "model_path": "",         # Vosk model folder; empty = search the usual places
    "last_workbook": "",      # re-selected on launch when still open
    "workbook_file": "",      # an .xlsx opened with Open Spreadsheet File (no Excel needed); "" = live Excel
    "prompt_timeout_s": 20,   # seconds to wait for a yes/no answer
    "auto_voice_sort": False,  # start voice sorting as soon as terms need sorting
    "feedback": "sounds",     # "off" | "sounds" | "echo": how Quill confirms what it did
    "sound_pack": "chime",    # one of feedback.PACKS
    "echo_style": "okay",     # one of feedback.ECHO_WORDS
    "history_limit": 100,     # how many sorting answers undo remembers
    "accent": "terracotta",   # one of ACCENTS (ui/theme.py)
    "spacing": "compact",     # "compact" | "comfortable"
    "font_size": 12,          # base text size in points
    "log_collapsed": True,    # the main window's log starts hidden (a click on "Log" opens it)
    "row_collapsed": False,   # the main window's Current row section starts hidden
    "hide_dock_icon": False,  # macOS: keep Quill out of the Dock (it stays in the menu bar)
    "mini_mode": False,       # the main window starts as the small overlay
    "mini_on_top": True,      # the mini view floats above other windows
    "mic_always_on": False,   # keep the microphone open while not listening (so "start listening" works)
    "opacity": 100,           # whole-window opacity in percent (text and controls fade too)
    "blur": 60,               # blur behind the windows, 0 (none) to 100 (most); macOS / Windows 11
}

#: Allowed range for ``opacity`` (percent). At 0 the window would vanish, so 10 is the floor.
OPACITY_RANGE = (10, 100)

#: Allowed range for ``blur`` (percent).
BLUR_RANGE = (0, 100)

#: Allowed range for ``font_size`` (points).
FONT_SIZE_RANGE = (9, 20)

#: Allowed range for ``history_limit``.
HISTORY_LIMIT_RANGE = (5, 500)

THEMES = ("auto", "light", "dark")
ACCENTS = ("terracotta", "ocean", "forest", "violet", "rose")   # same keys as ui/theme.ACCENTS
SPACINGS = ("compact", "comfortable")                          # same keys as ui/theme.DENSITIES


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
        aliases: ``{column: {spoken phrase: existing list value}}`` taught by the
            user in the Needs-sorting window ("extra large" means "XL").
    """

    KEYWORDS_FILE = "keywords.toml"

    def __init__(
        self,
        keywords: dict[str, Action],
        preferences: dict[str, object] | None = None,
        config_dir: pathlib.Path | None = None,
        aliases: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.keywords = keywords          # phrase -> Action
        self.aliases: dict[str, dict[str, str]] = aliases or {}
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
        raw_aliases = data.get("aliases")
        if isinstance(raw_aliases, dict):
            for column, mapping in raw_aliases.items():
                if isinstance(mapping, dict):
                    settings.aliases[column] = {
                        str(k).lower(): str(v) for k, v in mapping.items() if isinstance(v, str)
                    }
        for key, allowed in (("feedback", MODES), ("sound_pack", PACKS), ("echo_style", ECHO_WORDS),
                             ("accent", ACCENTS), ("spacing", SPACINGS)):
            if settings.preferences[key] not in allowed:
                settings.preferences[key] = DEFAULT_PREFERENCES[key]
        low, high = HISTORY_LIMIT_RANGE
        settings.preferences["history_limit"] = max(low, min(high, int(settings.preferences["history_limit"])))
        low, high = OPACITY_RANGE
        settings.preferences["opacity"] = max(low, min(high, int(settings.preferences["opacity"])))
        low, high = BLUR_RANGE
        settings.preferences["blur"] = max(low, min(high, int(settings.preferences["blur"])))
        low, high = FONT_SIZE_RANGE
        settings.preferences["font_size"] = max(low, min(high, int(settings.preferences["font_size"])))
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

    def add_alias(self, column: str, phrase: str, canonical: str) -> None:
        """Remember that spoken *phrase* means *canonical* in *column* (not yet saved)."""
        self.aliases.setdefault(column, {})[phrase.strip().lower()] = canonical

    def remove_alias(self, column: str, phrase: str) -> str | None:
        """Forget a remembered synonym (not yet saved); returns what it used to mean."""
        mapping = self.aliases.get(column, {})
        previous = mapping.pop(phrase.strip().lower(), None)
        if not mapping:
            self.aliases.pop(column, None)
        return previous

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
        for column, mapping in sorted(self.aliases.items()):
            if mapping:
                lines.append(f"\n[aliases.{json.dumps(column)}]\n")
                for phrase, canonical in sorted(mapping.items()):
                    lines.append(f"{json.dumps(phrase)} = {json.dumps(canonical)}\n")
        (self._dir() / self.KEYWORDS_FILE).write_text("".join(lines), encoding="utf-8")
