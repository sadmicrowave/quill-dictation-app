"""Small widgets the main window is built from.

Kept apart from :mod:`quill.ui.main_window` so that file holds the window's behaviour only:

* :class:`ChipPlacer`: lays the "File stream not connected" chip over the file picker.
* :class:`WorkbookCombo`: the file picker, a drop-down only when there is a choice to make.
* :class:`StreamBox`: the Voice Stream (what is being heard).
* :class:`RowTable`: the grid showing the row being built.
* :class:`ResizeWatcher`: tells the window when it is being resized.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QComboBox, QLabel, QSizePolicy, QStyle, QTableWidget, QTextEdit, QWidget

#: Height (px) of the "File stream not connected" chip.
CHIP_HEIGHT = 22

#: Height (px) of the row grid when empty (the Voice Stream box is as tall), and of the stream's growth limit.
ROW_EMPTY_HEIGHT = 42
STREAM_MIN_HEIGHT = ROW_EMPTY_HEIGHT
STREAM_MAX_LINES = 5        # the Voice Stream box grows to this many lines, then scrolls


class ChipPlacer(QObject):
    """Keeps a chip laid over the left of a combo box (in the space its text would use) as the box moves or resizes.

    The chip is a sibling of the box, not a child: a label inside a combo box is not given the style sheet.
    """

    def __init__(self, combo: QComboBox, chip: QLabel) -> None:
        super().__init__(combo)
        self._combo, self._chip = combo, chip
        combo.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
            self.place()
        return False

    def place(self) -> None:
        gap = 8
        room = max(self._combo.width() - 2 * gap - 22, 40)          # leave the drop-down arrow clear
        width = min(self._chip.sizeHint().width(), room)
        box = self._combo.geometry()                                  # in the shared parent's coordinates
        self._chip.setGeometry(box.x() + gap, box.y() + (box.height() - CHIP_HEIGHT) // 2, width, CHIP_HEIGHT)
        self._chip.raise_()


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
        self.setPlaceholderText("Words you say appear here as they are heard")
        font = self.font()
        font.setItalic(True)
        self.setFont(font)
        self.setFixedHeight(STREAM_MIN_HEIGHT)

    def fit(self) -> None:
        """Make the box as tall as its text needs (between one line and :data:`STREAM_MAX_LINES`)."""
        doc = self.document()
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


class WorkbookCombo(QComboBox):
    """The workbook picker: a drop-down only while there is more than one workbook to choose from.

    With none (the "not connected" notice) or one, the arrow is hidden and it does not open, so it
    does not promise a choice that is not there.
    """

    def sync(self) -> None:
        single = self.count() <= 1
        if self.property("single") != single:
            self.setProperty("single", single)
            self.style().unpolish(self)
            self.style().polish(self)
        self.setCursor(Qt.CursorShape.ArrowCursor if single else Qt.CursorShape.PointingHandCursor)

    def showPopup(self) -> None:                                   # noqa: N802 (Qt name)
        if self.count() > 1:
            super().showPopup()


class RowTable(QTableWidget):
    """The Current Row box: it asks for just its minimum height, so it grows only when given room.

    It only displays: the cells can't be selected, focused or edited (that would suggest an action
    that isn't there), and the grid line at the far right edge is pushed out of view.
    """

    def __init__(self, rows: int, columns: int) -> None:
        super().__init__(rows, columns)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)                  # drawn in paintEvent, so there is no line at the far right

    def paintEvent(self, event) -> None:                             # noqa: N802 (Qt name)
        super().paintEvent(event)
        if self.columnCount() < 2 or not self.rowCount():
            return
        color = QColor.fromRgba(self.style().styleHint(QStyle.StyleHint.SH_Table_GridLineColor, None, self) & 0xFFFFFFFF)
        painter = QPainter(self.viewport())
        painter.setPen(color)
        bottom = self.rowViewportPosition(self.rowCount() - 1) + self.rowHeight(self.rowCount() - 1)
        divider = self.columnViewportPosition(0) + self.columnWidth(0) - 1
        painter.drawLine(divider, 0, divider, bottom - 1)            # between the two columns
        for row in range(self.rowCount()):
            y = self.rowViewportPosition(row) + self.rowHeight(row) - 1
            painter.drawLine(0, y, self.viewport().width() - 1, y)
        painter.end()


    def sizeHint(self) -> QSize:                                    # noqa: N802 (Qt name)
        return QSize(super().sizeHint().width(), self.minimumHeight())

    def minimumSizeHint(self) -> QSize:                             # noqa: N802
        return QSize(super().minimumSizeHint().width(), self.minimumHeight())
