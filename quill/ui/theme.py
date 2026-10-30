"""Apply the user's light/dark/auto preference to the whole application."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_SCHEMES = {
    "auto": Qt.ColorScheme.Unknown,   # follow the operating system
    "light": Qt.ColorScheme.Light,
    "dark": Qt.ColorScheme.Dark,
}


def apply_theme(app: QApplication, mode: str) -> None:
    """Set the colour scheme.

    Args:
        app: The running application.
        mode: ``"auto"`` (follow the OS), ``"light"`` or ``"dark"``. Anything
            else is treated as ``"auto"``.

    Qt draws native widgets in the chosen scheme, so window chrome, controls
    and menus all follow it without a custom stylesheet.
    """
    app.styleHints().setColorScheme(_SCHEMES.get(mode, Qt.ColorScheme.Unknown))
