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

import contextlib
import json
import pathlib

try:
    import tomllib  # stdlib Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # backport for 3.9/3.10
    except ImportError:
        tomllib = None  # type: ignore[assignment]

from quill.feedback import ECHO_WORDS, MODES, PACKS
from quill.licensing import DEFAULT_ACCOUNT, clean_account
from quill.parser.commands import RESERVED_ANSWER_WORDS, Action
from quill.parser.tokens import tokenize

#: Preference defaults. Types here define what is accepted on load.
DEFAULT_PREFERENCES: dict[str, object] = {
    "theme": "auto",          # "auto" | "light" | "dark"
    "speak_sort_prompts": False,  # speak what to do for each Term Helper row (system speech; the only place Quill speaks)
    "model_path": "",         # Vosk model folder; empty = search the usual places
    "last_workbook": "",      # re-selected on launch when still open
    "workbook_file": "",      # an .xlsx opened with Open File (no Excel needed); "" = live Excel
    "open_with": "auto",      # the program a chosen file is opened in: "auto" (the system's), "numbers", "libreoffice", "excel"
    "spreadsheet_app": "auto",  # "auto" finds Excel, Numbers, LibreOffice ... by itself; reserved for a picker
    "prompt_timeout_s": 20,   # seconds to wait for a yes/no answer
    "auto_voice_sort": False,  # start voice sorting as soon as terms need sorting
    "feedback": "sounds",     # "off" | "sounds" | "echo": how Quill confirms what it did
    "sound_pack": "chime",    # one of feedback.PACKS
    "echo_style": "okay",     # one of feedback.ECHO_WORDS
    "history_limit": 100,     # how many sorting answers undo remembers
    "accent": "violet",   # one of ACCENTS (ui/theme.py)
    "spacing": "compact",     # "compact" | "comfortable"
    "font_size": 14,          # base text size in points (14 since preferences version 2; 12 before)
    "model_migrated": False,   # the speech model was once switched to the best one installed
    "prefs_version": 2,       # raised when a default changes that saved settings should follow
    "log_collapsed": True,    # the main window's log starts hidden (a click on "Log" opens it)
    "hide_dock_icon": False,  # macOS: keep Quill out of the Dock (it stays in the menu bar)
    "window_width": 0,        # the full window's size when Quill last closed (0 = not saved yet)
    "window_height": 0,
    "mini_width": 0,          # the mini view's size when it was last used (0 = the compact default)
    "mini_height": 0,
    "settings_page": "",      # the Settings page that was open when the window was last closed
    "settings_width": 0,      # and the window's size then (0 = default)
    "settings_height": 0,
    "panel_width": 236,       # how wide the side panel opens (dragged by the user)
    "log_height": 120,        # how tall the log is while open (dragged by the user)
    "mini_mode": False,       # the main window starts as the small overlay
    "mini_on_top": True,      # the mini view floats above other windows
    "auto_stop": True,        # stop listening by itself when nothing has been said for a while
    "auto_stop_seconds": 10,  # ... for this many seconds of quiet
    "sheet_check_seconds": 30,  # how often Quill asks the spreadsheet program which sheet is open (0: never)
    "mic_always_on": False,   # keep the microphone open while not listening (so "start listening" works)
    "opacity": 100,           # whole-window opacity in percent (text and controls fade too)
    "speech_quality": "standard",   # "standard" | "better" | "best": which speech model listens (Broad and Careful are installs)
    "sorting_sounds": True,   # Term Helper answers (added, ignored, a problem) play their confirmation sound
    "sorting_follows_opacity": False,   # the Term Helper fades like the main window (off: it stays solid and easy to read)
    "turn_mode": "next_row",  # "next_row": each turn is a new row | "append": each turn adds to the same row
    "headings_row": 0,        # the row (column, when headings run down) that holds the headings; 0 = find it
    "start_row": 0,           # first row (first column when headings run down) a turn may write to; 0 = the first empty one
    "sorting_x": -1,          # where the Term Helper window was left (-1 = not yet: it opens at the main window's screen corner)
    "sorting_y": -1,
    "sorting_width": 0,
    "vertical_layout": False,  # headings run down the first column (one record per column) instead of across the first row
    "blur": 60,               # blur behind the windows, 0 (none) to 100 (most); macOS / Windows 11
}

#: Allowed range for ``opacity`` (percent). At 0 the window would vanish, so 10 is the floor.
OPACITY_RANGE = (10, 100)

#: Allowed range for ``blur`` (percent).
BLUR_RANGE = (0, 100)

#: Allowed range for ``font_size`` (points).
FONT_SIZE_RANGE = (9, 20)

#: Allowed range for ``auto_stop_seconds``.
AUTO_STOP_RANGE = (3, 3600)
#: Allowed range for ``sheet_check_seconds`` (0 turns the checking off).
SHEET_CHECK_RANGE = (0, 600)

#: Allowed range for ``history_limit``.
HISTORY_LIMIT_RANGE = (5, 500)

THEMES = ("auto", "light", "dark")
ACCENTS = ("violet", "terracotta", "ocean", "forest", "rose")   # same keys as ui/theme.ACCENTS
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


#: Commands added after the first release: a keyword file saved earlier gets their shipped phrases too.
NEW_ACTIONS = (Action.OPEN_TERM_HELPER, Action.APPEND_ON, Action.APPEND_OFF, Action.ROWS_DOWN_ON, Action.ROWS_DOWN_OFF)
KEYWORDS_VERSION = 3          # raised whenever shipped commands are added


def _parse_keywords(table: dict) -> dict[str, Action]:
    """Convert a ``{phrase: "ACTION_NAME"}`` table, dropping unknown actions."""
    result: dict[str, Action] = {}
    for phrase, action_name in table.items():
        with contextlib.suppress(KeyError, TypeError):      # an unknown action (say, from a newer version) is skipped
            result[phrase.lower()] = Action[action_name]
    return result


def _toml_value(value: object) -> str:
    """Render a bool / int / str preference as a TOML value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return _toml_string(str(value))


def _toml_string(text: str) -> str:
    """*text* as a TOML basic string.

    JSON escapes are valid TOML escapes, but ``ensure_ascii`` would write an emoji as a surrogate pair
    (``\\ud83d\\ude00``), which TOML rejects, so the whole settings file would be thrown away on the next
    launch. Real characters are written as they are instead; control characters stay escaped.
    """
    return json.dumps(text, ensure_ascii=False)


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
        self.account: dict[str, object] = clean_account(None)    # licence / subscription facts (licensing.py)
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
            if int(data.get("keywords_version", 1) or 1) < KEYWORDS_VERSION:         # commands added since the file was saved
                for phrase, action in cls.defaults(config_dir).keywords.items():
                    if action in NEW_ACTIONS and phrase not in settings.keywords:
                        settings.keywords[phrase] = action
        prefs = data.get("preferences")
        if not isinstance(prefs, dict):
            settings.preferences["model_migrated"] = True          # a new user has nothing to move to a better model
        if isinstance(prefs, dict):
            for key, default in DEFAULT_PREFERENCES.items():
                value = prefs.get(key)
                # Keep a value only if it has the same type as the default (bool is not int).
                if value is not None and type(value) is type(default):
                    settings.preferences[key] = value
        if int(prefs.get("prefs_version", 1) if isinstance(prefs, dict) else 1) < 2:      # settings saved before the new default size
            if settings.preferences["font_size"] == 12:
                settings.preferences["font_size"] = int(DEFAULT_PREFERENCES["font_size"])
        settings.preferences["prefs_version"] = int(DEFAULT_PREFERENCES["prefs_version"])
        settings.account = clean_account(data.get("account") if isinstance(data.get("account"), dict) else None)
        raw_aliases = data.get("aliases")
        if isinstance(raw_aliases, dict):
            for column, mapping in raw_aliases.items():
                if isinstance(mapping, dict):
                    settings.aliases[column] = {
                        str(k).lower(): str(v) for k, v in mapping.items() if isinstance(v, str)
                    }
        for key, allowed in (("feedback", MODES), ("open_with", ("auto", "numbers", "libreoffice", "excel")), ("turn_mode", ("next_row", "append")), ("speech_quality", ("standard", "better", "best")), ("sound_pack", PACKS), ("echo_style", ECHO_WORDS),
                             ("accent", ACCENTS), ("spacing", SPACINGS)):
            if settings.preferences[key] not in allowed:
                settings.preferences[key] = DEFAULT_PREFERENCES[key]
        low, high = AUTO_STOP_RANGE
        settings.preferences["auto_stop_seconds"] = max(low, min(high, int(settings.preferences["auto_stop_seconds"])))
        settings.preferences["sheet_check_seconds"] = max(SHEET_CHECK_RANGE[0], min(SHEET_CHECK_RANGE[1], int(settings.preferences["sheet_check_seconds"])))
        low, high = HISTORY_LIMIT_RANGE
        settings.preferences["history_limit"] = max(low, min(high, int(settings.preferences["history_limit"])))
        low, high = OPACITY_RANGE
        settings.preferences["opacity"] = max(low, min(high, int(settings.preferences["opacity"])))
        low, high = BLUR_RANGE
        settings.preferences["blur"] = max(low, min(high, int(settings.preferences["blur"])))
        settings.preferences["panel_width"] = max(200, min(520, int(settings.preferences["panel_width"])))
        settings.preferences["log_height"] = max(60, min(600, int(settings.preferences["log_height"])))
        settings.preferences["headings_row"] = max(0, min(1_048_576, int(settings.preferences["headings_row"])))
        settings.preferences["start_row"] = max(0, min(1_048_576, int(settings.preferences["start_row"])))
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
        lines = [f"keywords_version = {KEYWORDS_VERSION}\n\n[keywords]\n"]
        for phrase, action in sorted(self.keywords.items()):
            lines.append(f"{_toml_string(phrase)} = {_toml_string(action.name)}\n")
        lines.append("\n[preferences]\n")
        for key in DEFAULT_PREFERENCES:
            lines.append(f"{key} = {_toml_value(self.preferences[key])}\n")
        lines.append("\n[account]\n")
        for key in DEFAULT_ACCOUNT:
            lines.append(f"{key} = {_toml_value(self.account[key])}\n")
        for column, mapping in sorted(self.aliases.items()):
            if mapping:
                lines.append(f"\n[aliases.{_toml_string(column)}]\n")
                for phrase, canonical in sorted(mapping.items()):
                    lines.append(f"{_toml_string(phrase)} = {_toml_string(canonical)}\n")
        target = self._dir() / self.KEYWORDS_FILE
        scratch = target.with_suffix(".tmp")
        scratch.write_text("".join(lines), encoding="utf-8")
        scratch.replace(target)          # an atomic swap: a crash while saving never leaves a half-written file
