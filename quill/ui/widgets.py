"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
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
        self.ink = QColor("#7A55C2")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        font = self.font()
        font.setBold(True)
        self.setFont(font)

    def set_colors(self, fill: str, ink: str) -> None:
        """Badge background and number colour (``"#RRGGBB"``)."""
        self.fill, self.ink = QColor(fill), QColor(ink)
        self.update()

    def sizeHint(self):                                          # noqa: N802 (Qt name)
        metrics = self.fontMetrics()
        height = metrics.height() + 6
        return super().sizeHint().expandedTo(self._size(max(height, metrics.horizontalAdvance(self.text()) + 18), height))

    def minimumSizeHint(self):                                   # noqa: N802
        return self.sizeHint()                                  # never squeezed below its natural size

    @staticmethod
    def _size(width: int, height: int):
        from PySide6.QtCore import QSize
        return QSize(width, height)

    def changeEvent(self, event) -> None:                        # noqa: N802
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.updateGeometry()                               # a style sheet may change the font after the first hint
        super().changeEvent(event)

    def paintEvent(self, event) -> None:                         # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())                              # the whole widget is the pill, so it can never be clipped
        radius = min(rect.height(), rect.width()) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.fill)
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(self.ink)
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()


class HeadingToggle(QLabel):
    """A clickable heading ("Log  v"): plain text that starts exactly at the content's left edge.

    A QToolButton centres its text inside extra margins, which pushed these headings about 8 px in
    from the edge everything else lines up with; a label has none.
    """

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("headingToggle", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMargin(0)
        self.setContentsMargins(0, 0, 0, 0)

    def click(self) -> None:
        """Act as if the heading had been clicked (also used by tests)."""
        self.clicked.emit()

    def mousePressEvent(self, event) -> None:                    # noqa: N802 (Qt name)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def wrap_tip(text: str, width: int = 52) -> str:
    """*text* with its lines wrapped at *width* characters, so a tooltip stays a readable block, not a long strip."""
    import textwrap
    return "\n".join(textwrap.fill(line, width) if line else "" for line in text.splitlines())
