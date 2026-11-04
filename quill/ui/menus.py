"""Quill's menu bar: every major operation, reachable from the OS menu bar (macOS) or the window's own menu bar (Windows, Linux).

One table (:data:`LAYOUT`) says which menus exist and what is in them; :class:`QuillMenus` builds them, calls the handlers it
was given, and keeps their state in step with the app (the Start / Stop wording, Mini View / Full Window, check marks, what is
greyed out). The window's own menu bar is always filled. On macOS a second, window-less menu bar is filled the same way, so the
same menus show while the Settings, Term Helper or Help window is in front (macOS shows the menu bar of the window in front).

The menu bar never holds logic: each entry calls a handler by name (see :data:`HANDLERS`), so the app decides what happens and a
test can press every entry without any window.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar

#: The Settings pages the View menu can open directly (the titles of the pages in the Settings window).
SETTINGS_PAGES = ("General", "Appearance", "Sounds", "Keywords", "Speech Model", "Learned Words")

#: Everything the menus can ask the app to do. A missing handler makes its entry do nothing.
HANDLERS = (
    "open_file", "use_excel", "refresh_files", "settings", "quit",
    "toggle_listening", "next_row", "undo", "term_helper", "new_row", "mode_next_row", "mode_append",
    "mini", "files_panel", "turn_panel", "log", "minimize", "bring_front",
    "help", "open_logs", "about",
)


@dataclass(frozen=True)
class Entry:
    """One menu entry: its id (also the handler it calls), text, shortcut and kind."""

    key: str
    text: str
    shortcut: str = ""
    kind: str = "action"          # "action" | "check" | "radio:<group>" | "submenu"
    role: str = ""                # a macOS role: "preferences" | "quit" | "about"


SEP = Entry("-", "")

#: The menus, in order. The text of an entry may change with the app's state (see :meth:`QuillMenus.update`).
LAYOUT: tuple[tuple[str, tuple[Entry, ...]], ...] = (
    ("File", (
        Entry("open_file", "Open File…", "Ctrl+O"),
        Entry("use_excel", "Use the Open Workbook"),
        Entry("refresh_files", "Check for Open Files Now", "Ctrl+R"),
        SEP,
        Entry("settings", "Settings…", "Ctrl+,", role="preferences"),
        SEP,
        Entry("quit", "Quit Quill", "Ctrl+Q", role="quit"),
    )),
    ("Listening", (
        Entry("toggle_listening", "Start Listening", "Ctrl+L"),
        Entry("next_row", "Next Row", "Ctrl+Return"),
        Entry("new_row", "Start a New Row"),
        SEP,
        Entry("undo", "Undo", "Ctrl+Z"),
        Entry("term_helper", "Term Helper…", "Ctrl+Shift+T"),
        SEP,
        Entry("mode_next_row", "Each Turn Is a New Row", kind="radio:turn"),
        Entry("mode_append", "Each Turn Adds to the Same Row", kind="radio:turn"),
    )),
    ("View", (
        Entry("mini", "Switch to Mini View", "Ctrl+Shift+M"),
        Entry("files_panel", "Files Panel", "Ctrl+Shift+F", kind="check"),
        Entry("turn_panel", "Turn Options Panel", "Ctrl+Shift+O", kind="check"),
        Entry("log", "Log", "Ctrl+Alt+L", kind="check"),
        SEP,
        Entry("pages", "Settings Page", kind="submenu"),
    )),
    ("Window", (
        Entry("minimize", "Minimize", "Ctrl+M"),
        Entry("bring_front", "Bring Quill to the Front"),
    )),
    ("Help", (
        Entry("help", "Quill Help", "F1"),
        Entry("open_logs", "Open the Log Folder"),
        SEP,
        Entry("about", "About Quill", role="about"),
    )),
)

_ROLES = {
    "preferences": QAction.MenuRole.PreferencesRole,
    "quit": QAction.MenuRole.QuitRole,
    "about": QAction.MenuRole.AboutRole,
}


@dataclass
class MenuState:
    """What the menus need to know about the app (everything defaults to a window with no file and nothing happening)."""

    listening: bool = False
    has_file: bool = False
    can_use_excel: bool = False            # "Use the Open Workbook" applies: a file is open instead of live Excel
    mini: bool = False
    panel_page: str = ""                   # "" (closed), "file" or "turn" (the pages of the side panel)
    log_open: bool = False
    can_undo: bool = False
    sorting_count: int = 0
    turn_mode: str = "next_row"            # "next_row" | "append"
    file_page: str = "file"
    turn_page: str = "turn"


@dataclass
class _Built:
    """The actions of one filled menu bar."""

    bar: QMenuBar
    actions: dict[str, QAction] = field(default_factory=dict)
    menus: dict[str, QMenu] = field(default_factory=dict)


class QuillMenus:
    """Builds and drives Quill's menus.

    Args:
        handlers: ``{name: callable}`` for the names in :data:`HANDLERS`; ``settings_page`` is called with a page title.
        platform: Override ``sys.platform`` (tests).
    """

    def __init__(self, handlers: dict[str, Callable], platform: str | None = None) -> None:
        self._handlers = handlers
        self._platform = platform or sys.platform
        self._built: list[_Built] = []
        self.state = MenuState()
        self._group: dict[str, QActionGroup] = {}

    # ------------------------------------------------------------------ #

    def install(self, bar: QMenuBar, reuse: dict[str, QAction] | None = None) -> dict[str, QAction]:
        """Fill *bar* with the menus. *reuse* gives actions that already exist (the window's Open File and Use the Open
        Workbook), which are kept instead of making new ones. Returns the actions by id."""
        built = _Built(bar)
        reuse = reuse or {}
        existing = {a.text(): a.menu() for a in bar.actions() if a.menu() is not None}
        for title, entries in LAYOUT:
            menu = existing.get(title) or bar.addMenu(title)             # (the window already has a File menu: it is filled in)
            built.menus[title] = menu
            for entry in entries:
                if entry is SEP or entry.key == "-":
                    menu.addSeparator()
                elif entry.kind == "submenu":
                    sub = menu.addMenu(entry.text)
                    built.menus[entry.key] = sub
                    for page in SETTINGS_PAGES:
                        sub.addAction(page, lambda p=page: self._call("settings_page", p))
                else:
                    action = reuse.get(entry.key) or self._make(menu, entry)
                    if entry.key in reuse and action not in menu.actions():
                        menu.addAction(action)
                    built.actions[entry.key] = action
        self._built.append(built)
        self._apply(built)
        return built.actions

    def install_default_bar(self) -> QMenuBar | None:
        """macOS only: a menu bar that belongs to no window, shown while a window without its own menu bar (Settings, the Term
        Helper, Help) is in front. None elsewhere."""
        if self._platform != "darwin":
            return None
        bar = QMenuBar()
        self.install(bar)
        return bar

    def _make(self, menu: QMenu, entry: Entry) -> QAction:
        text = entry.text
        if entry.key == "quit" and self._platform == "win32":
            text = "Exit"
        action = menu.addAction(text)
        if entry.shortcut:
            action.setShortcut(QKeySequence(entry.shortcut))
        if entry.role:
            action.setMenuRole(_ROLES[entry.role])
        if entry.kind == "check":
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, k=entry.key: self._call(k))
        elif entry.kind.startswith("radio:"):
            action.setCheckable(True)
            group = self._group.setdefault(entry.kind, QActionGroup(menu))
            group.setExclusive(True)
            group.addAction(action)
            action.triggered.connect(lambda _=False, k=entry.key: self._call(k))
        else:
            action.triggered.connect(lambda _=False, k=entry.key: self._call(k))
        return action

    def _call(self, name: str, *args) -> None:
        handler = self._handlers.get(name)
        if handler is not None:
            handler(*args)

    # ------------------------------------------------------------------ #

    def update(self, **changes) -> None:
        """Change what the menus show (any :class:`MenuState` field), in every menu bar."""
        for key, value in changes.items():
            if not hasattr(self.state, key):
                raise AttributeError(key)
            setattr(self.state, key, value)
        for built in self._built:
            self._apply(built)

    def actions(self, bar: QMenuBar | None = None) -> dict[str, QAction]:
        """The actions of one menu bar (the first filled one by default), by id."""
        for built in self._built:
            if bar is None or built.bar is bar:
                return built.actions
        return {}

    def _apply(self, built: _Built) -> None:
        s, a = self.state, built.actions

        def put(key: str, **props) -> None:
            action = a.get(key)
            if action is None:
                return
            if "text" in props:
                action.setText(props["text"])
            if "enabled" in props:
                action.setEnabled(props["enabled"])
            if "checked" in props:
                blocked = action.blockSignals(True)           # (showing a state must never run the handler)
                action.setChecked(props["checked"])
                action.blockSignals(blocked)

        put("toggle_listening", text="Stop Listening" if s.listening else "Start Listening")
        put("next_row", enabled=s.listening)
        put("new_row", enabled=s.listening)
        put("undo", enabled=s.can_undo)
        put("term_helper", text=f"Term Helper ({s.sorting_count})…" if s.sorting_count else "Term Helper…",
            enabled=s.sorting_count > 0)
        put("use_excel", enabled=s.can_use_excel)
        put("mini", text="Switch to the Full Window" if s.mini else "Switch to Mini View")
        put("files_panel", checked=s.panel_page == s.file_page)
        put("turn_panel", checked=s.panel_page == s.turn_page)
        put("log", checked=s.log_open)
        put("mode_next_row", checked=s.turn_mode != "append")
        put("mode_append", checked=s.turn_mode == "append")
