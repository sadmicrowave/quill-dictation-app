"""System tray / menu bar icon via PySide6 QSystemTrayIcon.

Menu items:
  Start Listening / Stop Listening  (label flips with state)
  Open Quill
  Quit

Active light: a green dot while listening, a grey ring when stopped.
On Windows a left click toggles listening. On macOS a click opens the menu
(a Qt/AppKit convention when a menu is attached), so use the menu item.
"""
from __future__ import annotations
from typing import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from quill.ui.main_window import COLOR_ACTIVE, COLOR_IDLE

ICON_SIZE = 64


def make_icon(listening: bool) -> QIcon:
    """Draw the tray icon: a filled green dot when listening, else a grey ring."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if listening:
        painter.setBrush(QColor(COLOR_ACTIVE))
        painter.setPen(Qt.PenStyle.NoPen)
    else:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(COLOR_IDLE), 8))
    painter.drawEllipse(QPoint(ICON_SIZE // 2, ICON_SIZE // 2), 22, 22)
    painter.end()
    return QIcon(pixmap)


class TrayIcon:
    """The tray icon and its menu.

    Args:
        app: The QApplication (used for Quit).
        main_window: Window to raise on "Open Quill".
        on_start: Called when the user asks to start listening.
        on_stop: Called when the user asks to stop listening.
    """

    def __init__(self, app, main_window, on_start: Callable, on_stop: Callable) -> None:
        self._app = app
        self._main_window = main_window
        self._on_start = on_start
        self._on_stop = on_stop
        self._tray: QSystemTrayIcon | None = None
        self._toggle_action: QAction | None = None
        self._menu: QMenu | None = None
        self._listening = False

    @property
    def listening(self) -> bool:
        return self._listening

    @property
    def toggle_action(self) -> QAction | None:
        """The Start/Stop menu entry (exposed for tests)."""
        return self._toggle_action

    def setup(self) -> bool:
        """Create the QSystemTrayIcon and its menu.

        Returns:
            False if the platform has no system tray (the app then runs with
            the window only).
        """
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        self._tray = QSystemTrayIcon(make_icon(False))
        self._menu = QMenu()
        self._toggle_action = self._menu.addAction("Start Listening", self.toggle)
        self._menu.addAction("Open Quill", self._main_window.show)
        self._menu.addSeparator()
        self._menu.addAction("Quit", self._app.quit)
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.setToolTip("Quill — not listening")
        self._tray.show()
        return True

    def toggle(self) -> None:
        """Flip listening by asking the app to start or stop."""
        (self._on_stop if self._listening else self._on_start)()

    def set_listening(self, active: bool) -> None:
        """Swap icon colour and flip the Start/Stop label."""
        self._listening = active
        if self._toggle_action is not None:
            self._toggle_action.setText("Stop Listening" if active else "Start Listening")
        if self._tray is not None:
            self._tray.setIcon(make_icon(active))
            self._tray.setToolTip("Quill — listening" if active else "Quill — not listening")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle()
