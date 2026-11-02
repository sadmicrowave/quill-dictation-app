"""Building blocks for the Settings window: rows, a toggle switch, a segmented control."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QSizePolicy, QSlider, QSpinBox, QStyle,
    QStyleOptionSlider, QToolButton, QVBoxLayout, QWidget,
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
        if not control.toolTip():
            control.setToolTip(description or title)       # hovering the control says what the setting does
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
        self.line = line                            # (the model rows put their radio button at its left)
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


class ModelRow(SettingRow):
    """One speech model on the Speech Model page: a radio button (only one can be chosen), the model's name in bold with
    its download size beside it, a description of what it does for the quality, and on the right either an
    "Installed" pill (no fill, in the accent colour) or a Download button.
    """

    chosen = Signal(str)                       # the model's key, when its radio button is checked
    download_requested = Signal(str)

    def __init__(self, key: str, name: str, size: str, description: str) -> None:
        self.key = key
        self.installed_pill = QLabel("Installed")
        self.installed_pill.setProperty("installedPill", True)           # drawn by the theme: accent border, no fill
        self.installed_pill.setToolTip(f"The {name} model is installed on this computer")
        self.download_button = QPushButton("Download")
        self.download_button.setToolTip(f"Download the {name} model ({size}); it is downloaded once")
        self.download_button.clicked.connect(lambda: self.download_requested.emit(self.key))
        holder = QWidget()
        holder.setProperty("keepMargins", True)
        side = QHBoxLayout(holder)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(8)
        side.addWidget(self.installed_pill)
        side.addWidget(self.download_button)
        super().__init__(name, description, holder, f"{name} {size} speech model download install quality")
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        self.title_label.setText(f"<b>{name}</b>&nbsp;&nbsp;{size}")        # the name bold, the size not
        self.radio = QRadioButton()
        self.radio.setCursor(Qt.CursorShape.PointingHandCursor)
        self.radio.setToolTip(f"Use the {name} model")
        self.radio.toggled.connect(lambda on: self.chosen.emit(self.key) if on else None)
        self.line.insertWidget(0, self.radio, 0, Qt.AlignmentFlag.AlignTop)
        self.title_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title_label.mousePressEvent = lambda event: self.radio.click()       # the name is a label for the radio

    def set_installed(self, installed: bool, busy: bool = False) -> None:
        """Show the Installed pill for a model that is on this computer, the Download button for one that is not."""
        self.installed_pill.setVisible(installed and not busy)
        self.download_button.setVisible(not installed)
        self.download_button.setEnabled(not busy)


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
        self.lineEdit().setTextMargins(11, 0, 6, 0)              # the text starts where a drop-down's does (theme.TEXT_INSET)


class GuardedSlider(_WheelGuard, QSlider):
    """A QSlider that ignores the wheel until focused, with a pointing-hand cursor.

    A press anywhere along (and around) the slider moves the handle there at once and can then be dragged, so
    it does not take a precise click on the thin groove.
    """

    HEIGHT = 30                                                  # a tall target; the groove itself stays thin

    def __init__(self, orientation=Qt.Orientation.Horizontal) -> None:
        super().__init__(orientation)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(self.HEIGHT)

    def _value_at(self, position: QPoint) -> int:
        """The value under a mouse position (along the slider's length)."""
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self)
        if self.orientation() == Qt.Orientation.Horizontal:
            span, offset = groove.width() - handle.width(), position.x() - groove.x() - handle.width() // 2
        else:
            span, offset = groove.height() - handle.height(), position.y() - groove.y() - handle.height() // 2
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), offset, max(span, 1),
                                              option.upsideDown)

    def mousePressEvent(self, event) -> None:                    # noqa: N802 (Qt name)
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setSliderDown(True)
        self.setSliderPosition(self._value_at(event.position().toPoint()))
        self.setFocus()
        event.accept()

    def mouseMoveEvent(self, event) -> None:                     # noqa: N802 (Qt name)
        if self.isSliderDown():
            self.setSliderPosition(self._value_at(event.position().toPoint()))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:                  # noqa: N802 (Qt name)
        if self.isSliderDown() and event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(False)                            # emits the final value
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class FlatCombo(GuardedCombo):
    """A drop-down drawn as plain text with a chevron (no box), like the settings rows of Claude."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("flat", True)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.setMinimumContentsLength(8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class PillField(QWidget):
    """An editable spoken phrase drawn as the pill every spoken word or phrase wears in Quill (the same colours as
    ``widgets.pill``), left-aligned in its cell and as wide as its text.

    ``field`` is the line edit; ``text()`` and ``setText()`` pass through.
    """

    focused = Signal()

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setProperty("keepMargins", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        self.field = QLineEdit(text)
        self.field.setProperty("pillField", True)
        self.field.setPlaceholderText("phrase")
        self.field.setToolTip("The words you say. Click to change them")
        self.field.textChanged.connect(self._fit)
        self.field.installEventFilter(self)
        row.addWidget(self.field, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        self._fit()

    def _fit(self, *_args) -> None:
        """As wide as the words (never narrower than a short word)."""
        text = self.field.text() or self.field.placeholderText()
        self.field.setFixedWidth(max(80, self.field.fontMetrics().horizontalAdvance(text) + 16))

    def eventFilter(self, obj, event) -> bool:                      # noqa: N802 (Qt name)
        if obj is self.field and event.type() == QEvent.Type.FocusIn:
            self.focused.emit()
        return False

    def text(self) -> str:
        return self.field.text()

    def setText(self, text: str) -> None:                          # noqa: N802 (Qt name)
        self.field.setText(text)


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
        self._icon_names: list[str] = []
        self._group.idClicked.connect(self._clicked)

    def addItem(self, icon_name: str, label: str, data: object) -> None:      # noqa: N802
        button = QToolButton()
        button.setCheckable(True)
        button.setProperty("segment", True)
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setIconSize(QSize(18, 18))
        self._icon_names.append(icon_name)
        button.setIcon(make_icon(icon_name, self.palette().windowText().color().name(), 18))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        index = len(self._buttons)
        self._group.addButton(button, index)
        self._layout.addWidget(button)
        self._buttons.append(button)
        self._data.append(data)
        if index == 0:
            button.setChecked(True)

    def refresh_icons(self, color: str | None = None) -> None:
        """Redraw the icons in *color* (default: the current text colour), e.g. after the theme changed."""
        color = color or self.palette().windowText().color().name()
        for button, name in zip(self._buttons, self._icon_names, strict=True):
            button.setIcon(make_icon(name, color, 18))

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
