"""Building blocks for the Settings window: rows, a toggle switch, a segmented control."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QSlider, QSpinBox,
    QToolButton, QVBoxLayout, QWidget,
)

from quill.ui.icons import make_icon


#: Width and height of every value control on a settings row (drop-down, number box, slider), so the
#: descriptions wrap alike on every row and every control lines up whatever the spacing mode.
CONTROL_WIDTH = 190
CONTROL_HEIGHT = 34


class SettingRow(QWidget):
    """One setting: a title and a muted description on the left, the control on the right.

    A hairline divider under it separates it from the next row. ``search_text``
    is what the Settings search matches against.

    Args:
        title: The setting's name.
        description: One line of help (may be empty).
        control: The widget that edits it.
        keywords: Extra words the search should match.
    """

    def __init__(self, title: str, description: str, control: QWidget, keywords: str = "") -> None:
        super().__init__()
        self.title = title
        self.setProperty("keepMargins", True)       # its inner layout is set explicitly; spacing must not move it
        self.search_text = f"{title} {description} {keywords}".lower()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        line = QHBoxLayout()
        line.setContentsMargins(0, 12, 0, 12)
        line.setSpacing(24)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.title_label = QLabel(title)
        text.addWidget(self.title_label)
        self.description_label = QLabel(description)
        self.description_label.setWordWrap(True)
        self.description_label.setProperty("muted", True)
        if not description:
            self.description_label.hide()           # (never setVisible(True): on a wrapped label it forces a layout pass, ~20 ms a row)
        text.addWidget(self.description_label)
        line.addLayout(text, 1)
        if isinstance(control, (QComboBox, QSpinBox)) or control.property("valueControl"):
            control.setFixedWidth(CONTROL_WIDTH)
            control.setMinimumHeight(CONTROL_HEIGHT)
        line.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(line)
        divider = QFrame()
        divider.setObjectName("settingsDivider")
        divider.setFixedHeight(1)
        outer.addWidget(divider)
        self.control = control

    def matches(self, query: str) -> bool:
        """True if every word of *query* appears in this row's text."""
        return all(word in self.search_text for word in query.lower().split())


class _WheelGuard:
    """Mixin: a control changes with the mouse wheel only once it has been clicked into.

    Without this, scrolling a settings page with a trackpad changes whichever
    drop-down, number box or slider happens to be under the pointer (which once
    turned a saved keyword into the wrong action).
    """

    def wheelEvent(self, event) -> None:                         # noqa: N802 (Qt name)
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()                                       # let the page scroll instead


class GuardedCombo(_WheelGuard, QComboBox):
    """A QComboBox that ignores the wheel until focused, with a pointing-hand cursor."""

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def showPopup(self) -> None:                                 # noqa: N802 (Qt name)
        """Open the list wide enough for its longest item, lined up with the control's right edge.

        The list is a window of its own; without this its width (and so the text) depended on the control.
        """
        super().showPopup()
        container = self.view().window()
        metrics = self.view().fontMetrics()
        text = max((metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        icon = self.iconSize().width() + 8 if any(not self.itemIcon(i).isNull() for i in range(self.count())) else 0
        wanted = text + icon + 2 * 10 + 2 * 4 + 2 * 2 + 12       # item padding, list padding, frame, a little air
        width = max(self.width(), wanted)
        x = self.mapToGlobal(QPoint(self.width() - width, 0)).x() if self.property("flat") else container.x()
        container.setGeometry(x, container.y(), width, container.height())


class GuardedSpinBox(_WheelGuard, QSpinBox):
    """A QSpinBox that ignores the wheel until focused."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("flat", True)                           # drawn like the flat drop-downs (see theme.py)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


class GuardedSlider(_WheelGuard, QSlider):
    """A QSlider that ignores the wheel until focused, with a pointing-hand cursor."""

    def __init__(self, orientation=Qt.Orientation.Horizontal) -> None:
        super().__init__(orientation)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class FlatCombo(GuardedCombo):
    """A drop-down drawn as plain text with a chevron (no box), like the settings rows of Claude."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("flat", True)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.setMinimumContentsLength(8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class ToggleSwitch(QCheckBox):
    """An on/off switch (a rounded track with a sliding knob). A QCheckBox underneath."""

    TRACK_W, TRACK_H = 40, 22

    def __init__(self) -> None:
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:                                 # noqa: N802 (Qt name)
        return QSize(self.TRACK_W + 2, self.TRACK_H + 2)

    def hitButton(self, pos) -> bool:                            # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:                         # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        on = self.isChecked()
        track = palette.highlight().color() if on else palette.placeholderText().color()
        if not self.isEnabled():
            track.setAlphaF(0.4)
        track_rect = QRectF(1, 1, self.TRACK_W, self.TRACK_H)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(track_rect, self.TRACK_H / 2, self.TRACK_H / 2)
        knob = self.TRACK_H - 6
        x = track_rect.right() - knob - 3 if on else track_rect.left() + 3
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QRectF(x, track_rect.top() + 3, knob, knob))
        painter.end()


class SegmentedControl(QWidget):
    """A row of icon buttons of which exactly one is selected (Auto / Light / Dark).

    Offers the parts of the QComboBox API the settings code uses
    (``currentIndex``, ``currentData``, ``setCurrentIndex``, ``count``).
    """

    currentIndexChanged = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("segmented")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QToolButton] = []
        self._data: list[object] = []
        self._group.idClicked.connect(self._clicked)

    def addItem(self, icon_name: str, label: str, data: object) -> None:      # noqa: N802
        button = QToolButton()
        button.setCheckable(True)
        button.setProperty("segment", True)
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setIconSize(QSize(18, 18))
        color = self.palette().windowText().color().name()
        button.setIcon(make_icon(icon_name, color, 18))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        index = len(self._buttons)
        self._group.addButton(button, index)
        self._layout.addWidget(button)
        self._buttons.append(button)
        self._data.append(data)
        if index == 0:
            button.setChecked(True)

    def count(self) -> int:
        return len(self._buttons)

    def currentIndex(self) -> int:                                            # noqa: N802
        return max(self._group.checkedId(), 0)

    def currentData(self) -> object:                                          # noqa: N802
        return self._data[self.currentIndex()] if self._data else None

    def setCurrentIndex(self, index: int) -> None:                            # noqa: N802
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    def findData(self, data: object) -> int:                                  # noqa: N802
        return self._data.index(data) if data in self._data else -1

    def _clicked(self, index: int) -> None:
        self.currentIndexChanged.emit(index)
