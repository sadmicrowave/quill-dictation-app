"""Window chrome, system-neutral: what the app asks of the operating system's window frame.

"Chrome" is the frame around a window: the title bar, its buttons and the border. Quill keeps the operating system's own frame
and only tints it. Everything that differs between systems lives in a provider (:mod:`quill.platforms`): the macOS provider
draws the transparent title bar, vibrancy blur and native title-bar icons; the Windows provider paints the title bar and
acrylic blur. This module only forwards each call to the provider of the system it runs on, and does the plain thing (usually
nothing) where there is none, so the rest of Quill never checks which system it is on.
"""

from __future__ import annotations

import sys
from typing import Callable

from quill import platforms

#: SF Symbol names for the title-bar icons (the macOS provider draws them; other systems ignore them).
SYMBOL_MINI = "arrow.down.right.and.arrow.up.left"
SYMBOL_FULL = "arrow.up.left.and.arrow.down.right"
SYMBOL_SETTINGS = "slider.horizontal.3"
SYMBOL_UNDO = "arrow.uturn.backward"
SYMBOL_HELP = "questionmark.circle"
SYMBOL_FOLDER = "folder"
SYMBOL_TURN = "bubble.left.and.bubble.right"


def _chrome(platform: str | None = None):
    """The provider's chrome module for *platform* (default: this system), or None."""
    module = platforms.provider(platform or sys.platform)
    return getattr(module, "chrome", None) if module is not None else None


def _call(name: str, default, *args, platform: str | None = None, **kwargs):
    module = _chrome(platform)
    function = getattr(module, name, None) if module is not None else None
    return default if function is None else function(*args, **kwargs)


def apply_chrome(widget, dark: bool, colors: dict[str, str], platform: str | None = None,
                 opacity: int = 100, blur: int = 0) -> str | None:
    """Tint *widget*'s native title bar to match the theme (*opacity* in percent, *blur* 0 to 100).

    Returns:
        The name of the provider that applied something (``"macos"``, ``"windows"``), else None.
    """
    return _call("apply_chrome", None, widget, dark, colors, platform=platform, opacity=opacity, blur=blur)


def no_window_shadow(widget, platform: str | None = None) -> bool:
    """Take the operating system's shadow off a window, so a rounded, transparent one has no square edge."""
    return _call("no_window_shadow", False, widget, platform=platform)


def set_always_on_top(widget, on: bool, platform: str | None = None, **native) -> bool:
    """Float *widget* above other windows (or stop) with the OS's own call; False if the caller must use Qt's window flag."""
    return _call("set_always_on_top", False, widget, on, platform=platform, **native)


def set_dock_icon_visible(visible: bool, platform: str | None = None, **native) -> bool:
    """Show or hide the app's Dock icon (macOS only); False where that does not exist."""
    return _call("set_dock_icon_visible", False, visible, platform=platform, **native)


def bring_app_forward(widget, platform: str | None = None, **native) -> None:
    """Make Quill the frontmost application with *widget* in front."""
    module = _chrome(platform)
    if module is not None and hasattr(module, "bring_app_forward"):
        module.bring_app_forward(widget, platform=platform, **native)
        return
    try:
        widget.raise_()
        widget.activateWindow()
    except Exception:
        pass


def add_titlebar_button(widget, callback: Callable[[], None], platform: str | None = None, **options):
    """Add icons to the native title bar where the system has such a place (macOS); None where the window draws its own."""
    return _call("add_titlebar_button", None, widget, callback, platform=platform, **options)


def set_title_inset(widget, points: float, platform: str | None = None) -> bool:
    """Make room (in points) at the right of the title bar for the side panel."""
    return _call("set_title_inset", False, widget, points, platform=platform)


def refresh_chrome(widget) -> None:
    """Re-place what the title bar holds after the system rebuilt it."""
    _call("refresh_chrome", None, widget)


def refresh_chrome_soon(widget) -> None:
    """:func:`refresh_chrome` now and again a moment later."""
    _call("refresh_chrome_soon", None, widget)


def native_window_rebuilt(widget) -> bool:
    """True if the native window was replaced since the chrome was applied (its styling and icons are gone)."""
    return bool(_call("native_window_rebuilt", False, widget))


def watch_native_window(widget, on_rebuilt: Callable[[], None]):
    """Call *on_rebuilt* whenever the native window of *widget* is replaced; returns the watcher (None where not needed)."""
    return _call("watch_native_window", None, widget, on_rebuilt)


class FileDialogWarmer:
    """Makes the system's file window appear at once the first time it is asked for (macOS; elsewhere it does nothing)."""

    def __init__(self) -> None:
        module = _chrome()
        self._inner = module.FileDialogWarmer() if module is not None and hasattr(module, "FileDialogWarmer") else None
        self.done = False

    def start(self, platform: str | None = None) -> bool:
        if self._inner is None:
            return False
        started = self._inner.start(platform)
        self.done = self._inner.done
        return started

    def cancel(self) -> None:
        if self._inner is not None:
            self._inner.cancel()
