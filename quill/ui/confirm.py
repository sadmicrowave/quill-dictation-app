"""A styled confirmation box for actions that destroy several things at once.

Quill's windows are dressed by its own theme, so a plain system message box looks out of place and says little. This
one names what will be lost, offers the safe choice first (Cancel is the default and Escape), and colours the button
that does the damage red. Use :func:`confirm` before any single click that can remove many items.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class ConfirmDialog(QDialog):
    """Title, explanation and two buttons; ``exec()`` is ``Accepted`` only when the action button was pressed.

    Args:
        parent: The window it belongs to (it opens centred over it).
        title: What is about to happen, as a short sentence ("Forget 42 learned words?").
        message: What it means and that it cannot be undone.
        action: The button that carries it out ("Forget 42 Words"); named for what it does, never "OK".
        cancel: The button that backs out.
        danger: Colour the action button red (the default: these are deletions).
    """

    def __init__(self, parent: QWidget | None, title: str, message: str, action: str, cancel: str | None = "Cancel",
                 danger: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("confirmDialog")
        self.setModal(True)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("confirmTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        body = QLabel(message)
        body.setWordWrap(True)
        body.setProperty("muted", True)
        layout.addWidget(body)
        layout.addSpacing(8)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.cancel_button = QPushButton(cancel or "")
        self.action_button = QPushButton(action)
        self.action_button.setProperty("danger", danger)
        self.action_button.setProperty("accent", not danger)
        for button in ((self.cancel_button,) if cancel else ()) + (self.action_button,):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoDefault(False)
            buttons.addWidget(button)
        (self.cancel_button if cancel else self.action_button).setDefault(True)   # Return and Escape back out: the safe choice
        self.cancel_button.clicked.connect(self.reject)
        self.action_button.clicked.connect(self.accept)
        layout.addLayout(buttons)


def confirm(parent: QWidget | None, title: str, message: str, action: str, cancel: str = "Cancel",
            danger: bool = True) -> bool:
    """Ask, and return True only if the user pressed the action button."""
    dialog = ConfirmDialog(parent, title, message, action, cancel, danger)
    try:
        return dialog.exec() == QDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()


def info(parent: QWidget | None, title: str, message: str, button: str = "OK") -> None:
    """Tell the user something (one button), in the same style as :func:`confirm`."""
    dialog = ConfirmDialog(parent, title, message, button, cancel=None, danger=False)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
