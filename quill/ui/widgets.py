"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy

#: Lines of the full text shown in a tooltip before "…and n more".
TOOLTIP_LINES = 40


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with an ellipsis to fit its width.

    However much text it is given it stays one line high; the full text is kept
    in :attr:`full_text` and the tooltip.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        self.setText(text)

    def setText(self, text: str) -> None:                       # noqa: N802 (Qt name)
        self.full_text = text
        self._elide()

    def setFullText(self, text: str, tooltip: str | None = None) -> None:   # noqa: N802
        """Show *text* shortened to fit; *tooltip* (default: the text) has all of it."""
        self.setToolTip(tooltip if tooltip is not None else text)
        self.setText(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self.full_text, Qt.TextElideMode.ElideRight,
                                           max(self.width(), 40)))


def tooltip_lines(items: list[tuple[str, str]], limit: int = TOOLTIP_LINES) -> str:
    """``"Column: value"`` lines for a tooltip, capped with a count of what was left out."""
    lines = [f"{key}: {value}" for key, value in items[:limit]]
    if len(items) > limit:
        lines.append(f"…and {len(items) - limit} more")
    return "\n".join(lines)
