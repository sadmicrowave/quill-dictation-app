"""System tray / menu bar icon via PySide6 QSystemTrayIcon.

Menu items:
  Start Listening / Stop Listening  (label flips with state)
  Open Quill
  Quit

Active-light: icon changes colour when listening is on.
Full implementation in Phase 8.
"""
from __future__ import annotations
from typing import Callable, TYPE_CHECKING
if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication
    from quill.ui.main_window import MainWindow

class TrayIcon:
    def __init__(self, app, main_window, on_start: Callable, on_stop: Callable) -> None:
        self._app = app
        self._main_window = main_window
        self._on_start = on_start
        self._on_stop = on_stop
        self._tray = None
        self._listening = False

    def setup(self) -> None:
        """Create QSystemTrayIcon and context menu."""
        pass  # TODO Phase 8

    def set_listening(self, active: bool) -> None:
        """Swap icon colour and flip Start/Stop label."""
        self._listening = active
        # TODO Phase 8
