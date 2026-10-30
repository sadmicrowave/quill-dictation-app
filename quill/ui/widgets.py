"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
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


class Pill(QLabel):
    """A count drawn as a fully rounded badge, inline with the text around it.

    Painted by hand (not with a style sheet) so the rounding is identical on
    every platform and theme.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.fill = QColor("#FFFFFF")
        self.ink = QColor("#C9623F")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.font()
        font.setBold(True)
        self.setFont(font)

    def set_colors(self, fill: str, ink: str) -> None:
        """Badge background and number colour (``"#RRGGBB"``)."""
        self.fill, self.ink = QColor(fill), QColor(ink)
        self.update()

    def sizeHint(self):                                          # noqa: N802 (Qt name)
        metrics = self.fontMetrics()
        height = metrics.height() + 4
        return super().sizeHint().expandedTo(self._size(max(height, metrics.horizontalAdvance(self.text()) + 18), height))

    @staticmethod
    def _size(width: int, height: int):
        from PySide6.QtCore import QSize
        return QSize(width, height)

    def paintEvent(self, event) -> None:                         # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        height = self.fontMetrics().height() + 4
        rect = QRectF(0, (self.height() - height) / 2, self.width(), height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.fill)
        painter.drawRoundedRect(rect, height / 2, height / 2)
        painter.setPen(self.ink)
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()
