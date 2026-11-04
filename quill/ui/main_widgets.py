"""Small widgets the main window is built from.

Kept apart from :mod:`quill.ui.main_window` so that file holds the window's behaviour only:

* :class:`ChipPlacer`: lays the "File not connected" chip over the file picker.
* :class:`WorkbookCombo`: the file picker, a drop-down only when there is a choice to make.
* :class:`StreamBox`: the Voice Stream (what is being heard).
* :class:`RowTable`: the grid showing the row being built.
* :class:`ResizeWatcher`: tells the window when it is being resized.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from quill.ui.widgets import CHIP_HEIGHT

#: Where the hint text of an empty Voice Stream box and an empty row grid starts: (left, top, right, bottom) inside the box.
PLACEHOLDER_MARGINS = (6, 4, 4, 0)

#: Height (px) of the row grid when empty (the Voice Stream box is as tall), and of the stream's growth limit.
ROW_EMPTY_HEIGHT = 42
STREAM_MIN_HEIGHT = ROW_EMPTY_HEIGHT
STREAM_MAX_LINES = 5        # the Voice Stream box grows to this many lines, then scrolls


class StreamBox(QTextEdit):
    """The Voice Stream: what is being heard, as italic text that grows to a few lines before it scrolls.

    Words Quill recognises are drawn as pills in the theme colour. It is display only.
    """

    def __init__(self, on_height=None) -> None:
        super().__init__()
        self._on_height = on_height or (lambda old, new: None)
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # The hint is a label, exactly like the row grid's, so both are drawn by the same code and match.
        self.hint = QLabel("Words you say appear here as they are heard.", self.viewport())
        self.hint.setProperty("placeholder", True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.viewport().setProperty("keepMargins", True)      # the spacing setting must not resize this layout's margins
        holder = QVBoxLayout(self.viewport())
        holder.setContentsMargins(*PLACEHOLDER_MARGINS)
        holder.addWidget(self.hint)
        font = self.font()
        font.setItalic(True)
        self.setFont(font)
        self.setFixedHeight(STREAM_MIN_HEIGHT)

    def fit(self) -> None:
        """Make the box as tall as its text needs (between one line and :data:`STREAM_MAX_LINES`)."""
        doc = self.document()
        self.hint.setVisible(doc.isEmpty())
        doc.setTextWidth(max(self.viewport().width(), 40))
        line = self.fontMetrics().lineSpacing()
        extra = 2 * self.frameWidth() + 14                         # border and the style sheet's padding
        wanted = int(doc.size().height()) + extra
        height = max(STREAM_MIN_HEIGHT, min(wanted, STREAM_MAX_LINES * line + extra))
        if doc.isEmpty():
            height = STREAM_MIN_HEIGHT                           # the placeholder is as tall as the row grid's
        if height != self.height():
            old = self.height()
            self.setFixedHeight(height)
            self._on_height(old, height)

    def resizeEvent(self, event) -> None:                           # noqa: N802 (Qt name)
        super().resizeEvent(event)
        QTimer.singleShot(0, self.fit)                              # the wrapping changed with the width
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


class ResizeWatcher(QObject):
    """Restarts a timer every time the window is resized, so the size is reported once it has settled."""

    def __init__(self, window: QWidget, timer: QTimer, on_resize=None) -> None:
        super().__init__(window)
        self._timer = timer
        self._on_resize = on_resize

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            self._timer.start()
            if self._on_resize is not None:
                self._on_resize()
        return False


class RowTable(QTableWidget):
    """The row being built: a column and its value per line, which the user can delete.

    It asks for just its minimum height, so it grows only when given room. The cells can't be selected,
    focused or edited (that would suggest an action that isn't there); the one thing that can be done is to
    remove a line Quill got wrong: hovering a line shows a round "x" at its right end, and clicking it
    emits :attr:`row_remove_requested` with the line's column name. The grid line at the far right edge
    is not drawn.
    """

    #: Emitted with the column name when the user clicks a line's delete button.
    row_remove_requested = Signal(str)
    #: Emitted with the column name and the global point under the pointer when the user clicks the column name of a
    #: line whose value could go in another column (see :meth:`set_changeable`).
    row_change_requested = Signal(str, QPoint)

    DELETE_SIZE = 16          # px, the round delete button
    DELETE_MARGIN = 9         # px from the right edge (the button sits in the right-most cell)
    DELETE_HOT_FILL = "#E5484D"   # the button turns red while the pointer is over it: it removes something
    DELETE_TIP = "Remove this line from the row.\nQuill will not write it."
    CHANGE_TIP = "Change which column this value goes in."

    def __init__(self, rows: int, columns: int) -> None:
        super().__init__(rows, columns)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)                  # drawn in paintEvent, so there is no line at the far right
        self.setMouseTracking(True)
        self._hovered_row = -1
        self._button_hot = False                 # the pointer is over the delete button itself
        self._changeable: set[str] = set()       # columns whose line can be changed to another column
        self._over_name = False                  # the pointer is over the column name of such a line
        self._button_fill = QColor("#7A55C2")    # the theme colour; set with :meth:`set_delete_colors`
        self._button_glyph = QColor("#FFFFFF")

    def set_delete_colors(self, fill: str, glyph: str) -> None:
        """Colour the delete button: a filled circle in *fill* with an "x" in *glyph* (the theme's accent colours)."""
        self._button_fill, self._button_glyph = QColor(fill), QColor(glyph)
        self.viewport().update()

    def set_changeable(self, columns: set[str]) -> None:
        """The columns whose line can be changed to another column: their name shows a small arrow and can be clicked."""
        self._changeable = set(columns)
        self.viewport().update()

    def _name_hit(self, row: int, point: QPoint) -> bool:
        """Is *point* on the column-name cell of a line that can be changed?"""
        item = self.item(row, 0) if row >= 0 else None
        return (item is not None and item.text() in self._changeable and point.x() < self.columnWidth(0)
                and not self.delete_button_rect(row).contains(point))

    # -- the delete button -------------------------------------------------

    def delete_button_rect(self, row: int) -> QRect:
        """Where the delete button of *row* is, in viewport coordinates."""
        top = self.rowViewportPosition(row)
        size = self.DELETE_SIZE
        return QRect(self.viewport().width() - self.DELETE_MARGIN - size, top + (self.rowHeight(row) - size) // 2,
                     size, size)

    def _row_at(self, point: QPoint) -> int:
        row = self.rowAt(point.y())
        return row if 0 <= row < self.rowCount() and self.item(row, 0) is not None else -1

    def _over_button(self, point: QPoint) -> bool:
        return self._hovered_row >= 0 and self.delete_button_rect(self._hovered_row).contains(point)

    def mouseMoveEvent(self, event) -> None:                         # noqa: N802 (Qt name)
        super().mouseMoveEvent(event)
        point = event.position().toPoint()
        row = self._row_at(point)
        if row != self._hovered_row:
            self._hovered_row = row
            self.viewport().update()
        hot = self._over_button(point)
        if hot != self._button_hot:
            self._button_hot = hot
            self.viewport().update()
        name = not hot and self._name_hit(row, point)
        if name != self._over_name:
            self._over_name = name
            self.viewport().update()
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if hot or name else Qt.CursorShape.ArrowCursor)
        self.viewport().setToolTip(self.DELETE_TIP if hot else self.CHANGE_TIP if name else "")

    def leaveEvent(self, event) -> None:                             # noqa: N802
        super().leaveEvent(event)
        if self._hovered_row != -1:
            self._hovered_row, self._button_hot, self._over_name = -1, False, False
            self.viewport().setToolTip("")
            self.viewport().update()

    def mousePressEvent(self, event) -> None:                        # noqa: N802
        point = event.position().toPoint()
        row = self._row_at(point)
        if (event.button() == Qt.MouseButton.LeftButton and row >= 0
                and self.delete_button_rect(row).contains(point)):
            self._hovered_row, self._button_hot = -1, False
            self.viewport().setToolTip("")
            self.row_remove_requested.emit(self.item(row, 0).text())
            return
        if event.button() == Qt.MouseButton.LeftButton and self._name_hit(row, point):
            self.row_change_requested.emit(self.item(row, 0).text(), event.globalPosition().toPoint())
            return
        super().mousePressEvent(event)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:                             # noqa: N802 (Qt name)
        super().paintEvent(event)
        if not self.rowCount():
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.columnCount() >= 2:
            color = QColor.fromRgba(self.style().styleHint(QStyle.StyleHint.SH_Table_GridLineColor, None, self) & 0xFFFFFFFF)
            painter.setPen(color)
            bottom = self.rowViewportPosition(self.rowCount() - 1) + self.rowHeight(self.rowCount() - 1)
            divider = self.columnViewportPosition(0) + self.columnWidth(0) - 1
            painter.drawLine(divider, 0, divider, bottom - 1)        # between the two columns
            for row in range(self.rowCount() - 1):     # no line under the last row
                y = self.rowViewportPosition(row) + self.rowHeight(row) - 1
                painter.drawLine(0, y, self.viewport().width() - 1, y)
        if self._hovered_row >= 0 and self.item(self._hovered_row, 0) is not None \
                and self.item(self._hovered_row, 0).text() in self._changeable:          # a small arrow after the name: it opens a menu
            row = self._hovered_row
            name_width = self.fontMetrics().horizontalAdvance(self.item(row, 0).text())
            x = min(self.columnWidth(0) - 14, 8 + name_width + 10)
            y = self.rowViewportPosition(row) + self.rowHeight(row) / 2
            painter.setPen(QPen(self.palette().placeholderText().color(), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x - 3.5, y - 1.5), QPointF(x, y + 2))
            painter.drawLine(QPointF(x, y + 2), QPointF(x + 3.5, y - 1.5))
        if self._hovered_row >= 0:
            box = QRectF(self.delete_button_rect(self._hovered_row))
            centre = box.center()                      # the exact middle, so the "x" is centred in the circle
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.DELETE_HOT_FILL) if self._button_hot else self._button_fill)
            painter.drawEllipse(box)
            painter.setPen(QPen(self._button_glyph, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            reach = self.DELETE_SIZE * 0.2          # half the length of each stroke of the "x"
            painter.drawLine(QPointF(centre.x() - reach, centre.y() - reach), QPointF(centre.x() + reach, centre.y() + reach))
            painter.drawLine(QPointF(centre.x() + reach, centre.y() - reach), QPointF(centre.x() - reach, centre.y() + reach))
        painter.end()

    def sizeHint(self) -> QSize:                                    # noqa: N802 (Qt name)
        return QSize(super().sizeHint().width(), self.minimumHeight())

    def minimumSizeHint(self) -> QSize:                             # noqa: N802
        return QSize(super().minimumSizeHint().width(), self.minimumHeight())
