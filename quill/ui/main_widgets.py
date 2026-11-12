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
    QVariantAnimation,
    QEasingCurve,
    Signal,
)
import textwrap

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QLabel,
    QStyleOptionViewItem,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)


#: Where the hint text of an empty Voice Stream box and an empty row grid starts: (left, top, right, bottom) inside the box.
PLACEHOLDER_MARGINS = (6, 4, 4, 0)

#: Height (px) of the row grid when empty (the Voice Stream box is as tall), and of the stream's growth limit.
ROW_EMPTY_HEIGHT = 42
STREAM_MIN_HEIGHT = ROW_EMPTY_HEIGHT
ROW_HINT = "Words you say that match to columns in the selected file appear here as they are heard."
#: The grid's hint when the connected sheet has no columns Quill can find; both links open the file settings (where those options are).
NO_COLUMNS_HINT = ('This sheet has no column headings that Quill can find. Check <a href="file-settings">Headings Row</a> or '
                   '<a href="file-settings">Sheet Layout</a> in the file settings.')
SHUFFLE_MS = 240            # a heard column slides to the top of the row grid in this time
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


class _ValuePills(QStyledItemDelegate):
    """Draws each value of the row grid as a pill: the same square-cornered, accent-coloured wrapper the words in the Voice Stream
    wear, because they are what the user said."""

    PAD_X, PAD_Y, MARGIN = 7, 3, 6

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.fill, self.ink = QColor("#7A55C2"), QColor("#FFFFFF")
        self.auto_fill, self.auto_ink = QColor("#B8B8C0"), QColor("#222222")      # (a value Quill filled in itself: grey, never the colour of spoken words)

    def paint(self, painter, option, index) -> None:
        text = str(index.data() or "")
        if not text:
            return
        table = self.parent()
        if table.row_opacity(index.row()) <= 0.01:
            return
        reach = option.rect.width() - self.MARGIN - table.DELETE_SIZE - table.DELETE_MARGIN - 6          # (clear of the delete button)
        metrics = option.fontMetrics
        shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(reach - 2 * self.PAD_X, 20))
        width = metrics.horizontalAdvance(shown) + 2 * self.PAD_X
        height = min(metrics.height() + 2 * self.PAD_Y, option.rect.height() - 4)
        box = QRect(option.rect.left() + self.MARGIN, option.rect.top() + (option.rect.height() - height) // 2 + round(table.row_offset(index.row())),
                    width, height)                                            # (a line that is moving is drawn part-way between its places)
        painter.save()
        painter.setOpacity(table.row_opacity(index.row()))
        auto = table.is_auto(index.row())
        painter.fillRect(box, self.auto_fill if auto else self.fill)
        painter.setPen(self.auto_ink if auto else self.ink)
        painter.setFont(option.font)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, shown)
        painter.restore()


class _ColumnNames(QStyledItemDelegate):
    """Draws the column names of the row grid. While the columns ease in, each name fades up and slides a few pixels from the left."""

    SLIDE = 10          # px a name travels while it fades in

    def paint(self, painter, option, index) -> None:
        table = self.parent()
        opacity = table.row_opacity(index.row())
        if opacity <= 0.01:
            return
        painter.save()
        painter.setOpacity(opacity)
        painter.translate(-self.SLIDE * (1.0 - opacity), table.row_offset(index.row()))
        if table.has_tip(index.row()):                                       # (a long name stops short of the information icon)
            option = QStyleOptionViewItem(option)
            option.rect.setRight(option.rect.right() - table.ICON_RESERVE)
        super().paint(painter, option, index)
        painter.restore()


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
    ICON_SIZE = 13            # px, the round "i" after a column name that has help
    ICON_RESERVE = 22         # px at the right end of the name cell kept for it
    TIP_WIDTH = 46            # characters a help text is wrapped at

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
        self._pills = _ValuePills(self)
        self._active: set[str] = set()           # columns that have a value in the row: only their lines can be removed
        self._auto: set[str] = set()             # columns whose value Quill filled in itself (their pill is grey)
        self._tips: dict[str, str] = {}          # column -> its help, shown from an "i" after the name
        self._over_icon = False                  # the pointer is over such an icon
        self._revealed: float | None = None      # rows shown so far while the columns ease in (None: all of them, no animation)
        self._reveal = QVariantAnimation(self)
        self._reveal.setEasingCurve(QEasingCurve.Type.Linear)
        self._reveal.valueChanged.connect(self._reveal_step)
        self._reveal.finished.connect(self._reveal_done)
        self._offsets: dict[int, float] = {}     # px each line is still short of its new place while the grid reshuffles
        self._shuffle = QVariantAnimation(self)
        self._shuffle.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._shuffle.setStartValue(0.0)
        self._shuffle.setEndValue(1.0)
        self._shuffle.setDuration(SHUFFLE_MS)
        self._shuffle_progress = 1.0
        self._shuffle.valueChanged.connect(self._shuffle_step)
        self._shuffle.finished.connect(self._shuffle_done)
        self._names = _ColumnNames(self)
        if columns >= 2:
            self.setItemDelegateForColumn(0, self._names)
            self.setItemDelegateForColumn(1, self._pills)          # the values, in pills

    def set_pill_colors(self, fill: str, ink: str) -> None:
        """Colour the pills the values are drawn in (the theme's accent and the colour on it, as in the Voice Stream)."""
        self._pills.fill, self._pills.ink = QColor(fill), QColor(ink)
        self.viewport().update()

    def set_delete_colors(self, fill: str, glyph: str) -> None:
        """Colour the delete button: a filled circle in *fill* with an "x" in *glyph* (the theme's accent colours)."""
        self._button_fill, self._button_glyph = QColor(fill), QColor(glyph)
        self.viewport().update()

    def set_auto_colors(self, fill: str, ink: str) -> None:
        """Colour the pill of a value Quill filled in itself (the muted grey of a word waiting in the Term Helper)."""
        self._pills.auto_fill, self._pills.auto_ink = QColor(fill), QColor(ink)
        self.viewport().update()

    def set_auto(self, columns: set[str]) -> None:
        """The columns whose value in the row Quill filled in itself (a counter's next number): their pills are grey, not the spoken colour."""
        self._auto = set(columns)
        self.viewport().update()

    def is_auto(self, row: int) -> bool:
        item = self.item(row, 0) if 0 <= row < self.rowCount() else None
        return item is not None and item.text() in self._auto

    def set_tips(self, tips: dict[str, str]) -> None:
        """Help for some columns: each shows a small "i" after its name that says it when the pointer rests on it."""
        self._tips = dict(tips)
        self.viewport().update()

    def has_tip(self, row: int) -> bool:
        item = self.item(row, 0) if 0 <= row < self.rowCount() else None
        return item is not None and item.text() in self._tips

    def icon_rect(self, row: int) -> QRect:
        """Where the information icon of *row* is, in viewport coordinates."""
        size = self.ICON_SIZE
        return QRect(self.columnWidth(0) - size - 8, self.rowViewportPosition(row) + (self.rowHeight(row) - size) // 2, size, size)

    def _icon_hit(self, row: int, point: QPoint) -> bool:
        return self.has_tip(row) and self.icon_rect(row).adjusted(-3, -3, 3, 3).contains(point)

    def tip_for(self, row: int) -> str:
        """The help text of *row*'s column, wrapped for a tool tip."""
        item = self.item(row, 0) if 0 <= row < self.rowCount() else None
        return textwrap.fill(self._tips.get(item.text(), ""), self.TIP_WIDTH) if item is not None else ""

    def set_active(self, columns: set[str]) -> None:
        """The columns that have a value in the row now (only their lines show the delete button)."""
        self._active = set(columns)
        self.viewport().update()

    def row_opacity(self, row: int) -> float:
        """How visible *row* is: 1 once shown, rising from 0 as the columns ease in from the top, one after the other."""
        if self._revealed is None:
            return 1.0
        return max(0.0, min(1.0, self._revealed - row))

    def row_offset(self, row: int) -> float:
        """How far (px, vertically) *row* is from the place it is moving to: 0 when it is not moving."""
        return self._offsets.get(row, 0.0) * (1.0 - self._shuffle_progress)

    def line_positions(self) -> dict[str, int]:
        """Where each line is now (its top, in viewport pixels), by column name: taken before a refill, for :meth:`slide_from`."""
        return {item.text(): self.rowViewportPosition(r) for r in range(self.rowCount()) if (item := self.item(r, 0)) is not None}

    def slide_from(self, before: dict[str, int], animate: bool = True) -> None:
        """The lines were just refilled in a new order: slide each one from where it was (*before*, see :meth:`line_positions`) to
        where it is now. A line that was not there before does not move. Runs about a quarter of a second, then stops by itself."""
        self._shuffle.stop()
        self._offsets = {}
        self._shuffle_progress = 1.0
        if animate and self._revealed is None:                    # (while the columns ease in, they are not moving)
            for r in range(self.rowCount()):
                item = self.item(r, 0)
                if item is not None and item.text() in before:
                    gap = before[item.text()] - self.rowViewportPosition(r)
                    if gap:
                        self._offsets[r] = float(gap)
        if self._offsets:
            self._shuffle_progress = 0.0
            self._shuffle.start()
        self.viewport().update()

    def _shuffle_step(self, value) -> None:
        self._shuffle_progress = float(value)
        self.viewport().update()

    def _shuffle_done(self) -> None:
        self._offsets, self._shuffle_progress = {}, 1.0
        self.viewport().update()

    def ease_in_rows(self, animate: bool = True) -> None:
        """Show the rows one after the other from the top, each fading and sliding in (about a second at most, then it stops by itself)."""
        self._reveal.stop()
        rows = self.rowCount()
        if not animate or rows == 0:
            self._revealed = None
            self.viewport().update()
            return
        stagger = 45                                         # ms between one row starting and the next
        fade = 260                                           # ms one row takes to appear
        total = min(fade + stagger * (rows - 1), 1100)
        self._revealed = 0.0
        self._reveal.setDuration(total)
        self._reveal.setStartValue(0.0)
        self._reveal.setEndValue(float(rows) + fade / stagger)        # (the last row has its whole fade left to run)
        self._reveal.start()
        self.viewport().update()

    def _reveal_step(self, value) -> None:
        self._revealed = float(value)                        # rows revealed, with a fractional part for the one fading in
        self.viewport().update()

    def _reveal_done(self) -> None:
        self._revealed = None
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

    def _removable(self, row: int) -> bool:
        """Can the line at *row* be removed? Only a line that has a value in the row."""
        item = self.item(row, 0) if row >= 0 else None
        return item is not None and item.text() in self._active

    def _over_button(self, point: QPoint) -> bool:
        return self._removable(self._hovered_row) and self.delete_button_rect(self._hovered_row).contains(point)

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
        icon = not hot and not name and self._icon_hit(row, point)
        if icon != self._over_icon:
            self._over_icon = icon
            self.viewport().update()
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if hot or name else Qt.CursorShape.ArrowCursor)
        tip = self.DELETE_TIP if hot else self.CHANGE_TIP if name else self.tip_for(row) if icon else ""
        if tip != self.viewport().toolTip():
            QToolTip.hideText()                           # (a tip window shown again with other text keeps the old one's size: make a new one)
            self.viewport().setToolTip(tip)

    def leaveEvent(self, event) -> None:                             # noqa: N802
        super().leaveEvent(event)
        if self._hovered_row != -1:
            self._hovered_row, self._button_hot, self._over_name, self._over_icon = -1, False, False, False
            self.viewport().setToolTip("")
            self.viewport().update()

    def mousePressEvent(self, event) -> None:                        # noqa: N802
        point = event.position().toPoint()
        row = self._row_at(point)
        if (event.button() == Qt.MouseButton.LeftButton and self._removable(row)
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

    def divider_x(self) -> float:
        """Where the line between the name and the value columns is, in this widget's own coordinates (the columns start inside the
        frame, so it is not the middle of the widget). The resize handle under the grid puts its middle dot here."""
        if self.columnCount() < 2:
            return self.width() / 2
        return self.viewport().x() + self.columnViewportPosition(0) + self.columnWidth(0) - 1

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
            divider = self.columnViewportPosition(0) + self.columnWidth(0) - 1        # (see divider_x)
            painter.drawLine(divider, 0, divider, bottom - 1)        # between the two columns
            for row in range(self.rowCount() - 1):     # no line under the last row
                y = self.rowViewportPosition(row) + self.rowHeight(row) - 1
                painter.setOpacity(self.row_opacity(row) * (self._shuffle_progress if self._offsets else 1.0))      # (the lines fade back after a shuffle)
                painter.drawLine(0, y, self.viewport().width() - 1, y)
            painter.setOpacity(1.0)
        for row in range(self.rowCount()):                                          # the "i" after a column name that has help
            if self.has_tip(row) and self.row_opacity(row) > 0.01:
                heard = self.item(row, 0).text() in self._active          # (a name in the normal colour: its column has a value)
                box = QRectF(self.icon_rect(row)).translated(0, self.row_offset(row))
                colour = self.palette().text().color() if heard else self.palette().placeholderText().color()
                if row == self._hovered_row and self._over_icon:
                    colour = self.palette().text().color()
                painter.setOpacity(self.row_opacity(row))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(colour)
                painter.drawEllipse(box)
                painter.setPen(QPen(self.palette().base().color(), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))        # (the "i" is cut out of the disc)
                x, top = box.center().x(), box.top()
                painter.drawPoint(QPointF(x, top + box.height() * 0.30))
                painter.drawLine(QPointF(x, top + box.height() * 0.46), QPointF(x, top + box.height() * 0.74))
                painter.setOpacity(1.0)
        if self._hovered_row >= 0 and self.item(self._hovered_row, 0) is not None \
                and self.item(self._hovered_row, 0).text() in self._changeable:          # a small arrow after the name: it opens a menu
            row = self._hovered_row
            name_width = self.fontMetrics().horizontalAdvance(self.item(row, 0).text())
            x = min(self.columnWidth(0) - 14, 8 + name_width + 10)
            y = self.rowViewportPosition(row) + self.rowHeight(row) / 2
            painter.setPen(QPen(self.palette().placeholderText().color(), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x - 3.5, y - 1.5), QPointF(x, y + 2))
            painter.drawLine(QPointF(x, y + 2), QPointF(x + 3.5, y - 1.5))
        if self._removable(self._hovered_row):
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
