"""A stand-in for the macOS title bars, so a test can look at what each window's title bar holds *afterwards*, as it does on screen.

The real thing (``quill/platforms/macos/chrome.py``) adds a set of icons to a window's title bar every time it is asked, and the old
set stays: asking twice shows two sets (this is how the main window once got a second row of icons drawn over its title). The system may also
replace a window's native window (a Term Helper that is closed and shown again), which empties its title bar; Quill is then told
and must put the icons back. This stand-in models exactly that, per window, and nothing else.
"""
from __future__ import annotations

from unittest import mock


class _Button:
    """The icon row Quill is given back: it accepts every call the app makes (set_enabled, set_mini, set_extra_image ...) and is
    already level with the title (``align`` answers 0)."""

    def align(self) -> float:
        return 0.0

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class FakeNativeWindows:
    def __init__(self) -> None:
        self.icons: dict[int, list[tuple[str, str]]] = {}      # window id -> (side, what) of every icon set on its title bar, in the order added
        self.widgets: dict[int, object] = {}
        self.on_rebuilt: dict[int, object] = {}               # window id -> what Quill asked to be called when the window is rebuilt

    # -- what Quill calls ------------------------------------------------------------------------------
    def add_titlebar_button(self, widget, callback, platform=None, **options):
        key = id(widget)
        self.widgets[key] = widget
        self.icons.setdefault(key, []).append((options.get("side", "right"), options.get("symbol") or "resize"))
        return _Button()

    def watch_native_window(self, widget, on_rebuilt):
        self.widgets[id(widget)] = widget
        self.on_rebuilt[id(widget)] = on_rebuilt
        return None

    # -- what the system does --------------------------------------------------------------------------
    def rebuild(self, widget) -> None:
        """The system replaced the window's native window: its title bar is empty again, and Quill is told."""
        self.icons[id(widget)] = []
        callback = self.on_rebuilt.get(id(widget))
        if callback is not None:
            callback()

    def patches(self):
        return [mock.patch("quill.app.add_titlebar_button", self.add_titlebar_button),
                mock.patch("quill.ui.sorting_window.add_titlebar_button", self.add_titlebar_button),
                mock.patch("quill.app.watch_native_window", self.watch_native_window)]
