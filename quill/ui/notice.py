"""A small notice box: green for something that worked, red for something that went wrong.

One widget for every such message, so success and failure always look the same wherever they appear (the amber note in
the Files panel is its own older widget). It is hidden until given text, takes the room it needs and never moves its
neighbours when hidden. Colours come from the theme (``ok`` and ``error`` tokens, see :mod:`quill.ui.theme`).
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


class Notice(QFrame):
    """A rounded, tinted box with one wrapped line of text; :attr:`kind` is ``"ok"``, ``"error"`` or ``""`` (hidden)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("notice")
        self.setProperty("notice", "")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setProperty("noticeText", True)
        layout.addWidget(self.label)
        self.setVisible(False)

    @property
    def kind(self) -> str:
        return str(self.property("notice") or "")

    def show_ok(self, text: str) -> None:
        """Show *text* as a success notice (green)."""
        self._show("ok", text)

    def show_error(self, text: str) -> None:
        """Show *text* as an error notice (red)."""
        self._show("error", text)

    def clear(self) -> None:
        """Hide the notice."""
        self.label.setText("")
        self.setProperty("notice", "")
        self.setVisible(False)

    def _show(self, kind: str, text: str) -> None:
        self.label.setText(text)
        self.setProperty("notice", kind)
        self.style().unpolish(self)                      # the style sheet picks the colour from the property
        self.style().polish(self)
        self.setVisible(True)
