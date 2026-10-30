"""System tray / menu bar icon via PySide6 QSystemTrayIcon.

Menu items:
  Needs sorting (n)…    (only while terms wait; also a count badge on the icon)
  Editing: <workbook>   (these two lines appear only while listening;
  <folder it lives in>   click either to bring the workbook to the front)
  Start Listening / Stop Listening  (label flips with state)
  Open Quill
  Quit

Active light: a green dot while listening, a grey ring when stopped.
A click on the icon opens this menu (a left click pops it up on Windows too);
listening is only ever started or stopped from the menu item or the window.
"""
from __future__ import annotations
import pathlib
import sys
from typing import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from quill.ui.main_window import COLOR_ACTIVE, COLOR_IDLE

ICON_SIZE = 64

#: Longest workbook name / folder path shown in the menu before eliding.
MAX_TITLE_CHARS = 44
MAX_FOLDER_CHARS = 52


def elide_end(text: str, width: int) -> str:
    """Shorten *text* to *width* characters, ending with an ellipsis."""
    return text if len(text) <= width else text[: width - 1] + "…"


def elide_middle(text: str, width: int) -> str:
    """Shorten *text* keeping both ends: ``~/Docs/…/Plants/2026``."""
    if len(text) <= width:
        return text
    keep = width - 1
    head = keep // 3
    return text[:head] + "…" + text[len(text) - (keep - head):]


def folder_for_display(path: str) -> str:
    """The containing folder of *path*, with the home folder shown as ``~``."""
    folder = str(pathlib.Path(path).parent)
    home = str(pathlib.Path.home())
    return "~" + folder[len(home):] if folder.startswith(home) else folder


def make_icon(listening: bool, badge: int = 0, badge_color: str = "#C9623F") -> QIcon:
    """Draw the tray icon: a filled green dot when listening, else a grey ring.

    With *badge* > 0 a coloured circle holding the count sits at the top right
    ("9+" past nine), like the unread count on other menu bar apps.
    """
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
    if badge > 0:
        text = str(badge) if badge < 10 else "9+"
        radius = 19
        center = QPoint(ICON_SIZE - radius - 1, radius + 1)
        painter.setBrush(QColor(badge_color))
        painter.setPen(QPen(QColor("white"), 3))
        painter.drawEllipse(center, radius, radius)
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(26 if len(text) == 1 else 22)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius,
                         Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


class TrayIcon:
    """The tray icon and its menu.

    Args:
        app: The QApplication (used for Quit).
        main_window: Window to raise on "Open Quill".
        on_start: Called when the user asks to start listening.
        on_stop: Called when the user asks to stop listening.
        on_open_workbook: Called when the user clicks the workbook line.
    """

    def __init__(self, app, main_window, on_start: Callable, on_stop: Callable,
                 on_open_workbook: Callable | None = None,
                 on_open_sorting: Callable | None = None) -> None:
        self._app = app
        self._main_window = main_window
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_open_workbook = on_open_workbook or (lambda: None)
        self._on_open_sorting = on_open_sorting or (lambda: None)
        self._sorting_action: QAction | None = None
        self._workbook_name = ""
        self._workbook_path = ""
        self._title_action: QAction | None = None
        self._folder_action: QAction | None = None
        self._tray: QSystemTrayIcon | None = None
        self._toggle_action: QAction | None = None
        self._menu: QMenu | None = None
        self._listening = False
        self._badge = 0
        self._badge_color = "#C9623F"

    @property
    def badge(self) -> int:
        """The count shown on the icon (0 = none)."""
        return self._badge

    def set_badge(self, count: int, color: str | None = None) -> None:
        """Show *count* terms needing sorting as a badge on the icon (0 removes it)."""
        self._badge = max(0, count)
        if color:
            self._badge_color = color
        self._redraw()
        if self._sorting_action is not None:
            self._sorting_action.setVisible(self._badge > 0)
            self._sorting_action.setText(f"Needs sorting ({self._badge})…")

    def _redraw(self) -> None:
        if self._tray is not None:
            self._tray.setIcon(make_icon(self._listening, self._badge, self._badge_color))

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
            the window only). The menu object is still built.
        """
        self._menu = QMenu()
        self._title_action = self._menu.addAction("", lambda: self._on_open_workbook())
        self._folder_action = self._menu.addAction("", lambda: self._on_open_workbook())
        self._menu.addSeparator()
        self._toggle_action = self._menu.addAction("Start Listening", self.toggle)
        self._menu.addAction("Open Quill", self._main_window.show)
        self._sorting_action = self._menu.addAction("", lambda: self._on_open_sorting())
        self._sorting_action.setVisible(False)
        self._menu.addSeparator()
        self._menu.addAction("Quit", self._app.quit)
        self._refresh_workbook_items()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        self._tray = QSystemTrayIcon(make_icon(self._listening, self._badge, self._badge_color))
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.setToolTip("Quill — not listening")
        self._tray.show()
        return True

    @property
    def workbook_items(self) -> tuple[QAction | None, QAction | None]:
        """The (title, folder) menu entries (exposed for tests)."""
        return self._title_action, self._folder_action

    def set_workbook(self, name: str, path: str = "") -> None:
        """Set the workbook shown in the menu ('' clears it)."""
        self._workbook_name, self._workbook_path = name, path
        self._refresh_workbook_items()

    def _refresh_workbook_items(self) -> None:
        """Show the workbook lines only while listening on a known workbook."""
        if self._title_action is None:
            return
        show = self._listening and bool(self._workbook_name)
        self._title_action.setVisible(show)
        self._folder_action.setVisible(show and bool(self._workbook_path))
        if not show:
            return
        self._title_action.setText("Editing: " + elide_end(self._workbook_name, MAX_TITLE_CHARS))
        self._title_action.setToolTip(self._workbook_path or self._workbook_name)
        if self._workbook_path:
            folder = folder_for_display(self._workbook_path)
            self._folder_action.setText(elide_middle(folder, MAX_FOLDER_CHARS))
            self._folder_action.setToolTip(self._workbook_path)

    def notify(self, message: str, title: str = "Quill") -> None:
        """Pop a system notification from the tray icon (no-op without a tray)."""
        if self._tray is not None:
            self._tray.showMessage(title, message)

    def toggle(self) -> None:
        """Flip listening by asking the app to start or stop."""
        (self._on_stop if self._listening else self._on_start)()

    def set_listening(self, active: bool) -> None:
        """Swap icon colour and flip the Start/Stop label."""
        self._listening = active
        self._refresh_workbook_items()
        if self._toggle_action is not None:
            self._toggle_action.setText("Stop Listening" if active else "Start Listening")
        if self._tray is not None:
            self._redraw()
            self._tray.setToolTip("Quill — listening" if active else "Quill — not listening")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """A click on the icon only ever *opens the menu*; it never starts or stops listening.

        macOS shows the attached menu by itself. Windows shows it only on a
        right click, so a left click pops it up there too.
        """
        if reason == QSystemTrayIcon.ActivationReason.Trigger and sys.platform == "win32":
            self._menu.popup(QCursor.pos())
