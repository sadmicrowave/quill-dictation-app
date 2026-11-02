"""The right-hand side panel: it eases in beside the window and shows one of two pages.

* **Files** (the folder icon): the active spreadsheet as a button (its name, or "Open File" while there is none;
  pressing it opens the file window where that file is), a table of quiet facts about the file, and a filterable,
  scrollable list of the other spreadsheets that are open in programs on this computer. Picking one moves it up
  to the top. Where the data starts (starting row, headings row, which way the headings run) is in the settings
  overlay that the gear next to "Active File" opens (:class:`FileSettings`).
* **Turn Options** (the turn icon): whether each turn is written to a new row or added to the same row.

Every text that names the axis follows the layout: rows when the headings run across the top, columns when they run
down the side (:meth:`SidePanel.set_options`).

The panel only shows state and reports what the user chose through signals; the window animates it and the
application acts on the choices. Its title and close button are drawn in the title bar on macOS (see
``chrome``); elsewhere they are drawn here (:meth:`set_native_header`).
"""

from __future__ import annotations

import datetime as dt
import os
import string

import shiboken6
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from quill.ui.settings_widgets import FlatCombo
from quill.ui.theme import FLASH_STYLES, install_backdrop
from quill.ui.widgets import ElidedLabel

#: Width (px) of the panel when it is open.
PANEL_WIDTH = 236
#: The least and most (px) the user may drag the panel to; the most is also limited so the content never gets too small.
PANEL_MIN_WIDTH, PANEL_MAX_WIDTH = 200, 520

NEXT_ROW, APPEND_TO = "next_row", "append"
FILE_PAGE, TURN_PAGE = "file", "turn"
NO_FILE_TEXT = "Open File"
NO_OTHERS_TEXT = "No open spreadsheet files detected."
NO_MATCH_TEXT = "No files match."
TITLES = {"file": "Files", "turn": "Turn Options"}
AUTOMATIC = "Automatic"
#: How long (ms) the Open File button's blink stays on.
FLASH_MS = 700
LETTERS = string.ascii_uppercase                  # the columns a custom starting / headings column can be (A to Z)
LIST_ROLE = Qt.ItemDataRole.UserRole


def file_facts(path: str) -> list[tuple[str, str]]:
    """``(label, value)`` facts about a file on disk: size, date modified, date created as MM/DD/YY ([] when unreadable)."""
    try:
        info = os.stat(path)
    except OSError:
        return []
    created = getattr(info, "st_birthtime", info.st_ctime)

    def when(stamp: float) -> str:
        return dt.datetime.fromtimestamp(stamp).strftime("%m/%d/%y")

    return [("Size", human_size(info.st_size)), ("Modified", when(info.st_mtime)), ("Created", when(created))]


def human_size(size: int) -> str:
    """``1536`` -> ``"1.5 KB"``."""
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} bytes" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} bytes"


def _rule() -> QFrame:
    """A muted hairline between two sections."""
    line = QFrame()
    line.setProperty("panelRule", True)
    line.setFixedHeight(1)
    return line


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("panelHeading", True)                 # bold section titles
    label.setIndent(0)                      # flush with the controls below it
    return label


def _note(text: str) -> QLabel:
    """Small muted text, left-aligned with the rest of the panel."""
    label = QLabel(text)
    label.setProperty("panelNote", True)
    label.setWordWrap(True)
    label.setContentsMargins(0, 0, 0, 4)
    return label


class NumberField(QLineEdit):
    """A boxed number field where empty means *special* ("Automatic", shown muted): 0 to 1,048,576.

    ``valueChanged`` is sent when the user finishes typing (Return or leaving the field), or on :meth:`setValue`.
    """

    valueChanged = Signal(int)

    def __init__(self, special: str) -> None:
        super().__init__()
        self.setPlaceholderText(special)
        self.setValidator(QIntValidator(0, 1_048_576, self))
        self._value = 0
        self.editingFinished.connect(self._typed)

    def value(self) -> int:
        return self._value

    def setValue(self, number: int) -> None:                      # noqa: N802 (Qt-style name)
        number = max(0, int(number))
        self.setText(str(number) if number else "")
        if number != self._value:
            self._value = number
            self.valueChanged.emit(number)

    def _typed(self) -> None:
        self.setValue(int(self.text() or 0))

    def display(self) -> str:
        """What the field shows: the number, or the special word while empty."""
        return self.text() or self.placeholderText()


class LetterBox(FlatCombo):
    """A drop-down of Automatic and the columns A to Z (the same drop-down the Settings pages use).

    ``valueChanged`` carries the column number (0 for Automatic), like :class:`NumberField`.
    """

    valueChanged = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.addItem(AUTOMATIC, 0)
        for number, letter in enumerate(LETTERS, start=1):
            self.addItem(letter, number)
        self.setMaxVisibleItems(12)
        self.currentIndexChanged.connect(lambda _: self.valueChanged.emit(self.value()))

    def value(self) -> int:
        return int(self.currentData() or 0)

    def setValue(self, number: int) -> None:                      # noqa: N802 (Qt-style name)
        index = self.findData(max(0, min(26, int(number))))
        self.setCurrentIndex(max(index, 0))

    def display(self) -> str:
        return self.currentText()


def _field_row(row_box: QWidget | None = None) -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    return layout


class FileSettings(QFrame):
    """The overlay the gear next to "Active File" opens: where the data starts and which way the headings run.

    Starting row, sheet layout and headings row. With the headings running down the side these are columns, picked
    from A to Z; otherwise they are row numbers. Each explains itself in the words of the current layout.
    """

    start_changed = Signal(int)                 # 0: automatic
    headings_changed = Signal(int)              # 0: automatic
    layout_changed = Signal(bool)               # True: headings run down the first column

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("fileSettings")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(300)
        self._syncing = False
        self._vertical = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(6)
        self.headings_heading = _heading("Headings Row")
        layout.addWidget(self.headings_heading)
        self.headings_number = NumberField(AUTOMATIC)
        self.headings_letter = LetterBox()
        layout.addWidget(self.headings_number)
        layout.addWidget(self.headings_letter)
        self.headings_note = _note("")
        layout.addWidget(self.headings_note)
        layout.addSpacing(2)
        layout.addWidget(_rule())
        layout.addSpacing(2)
        self.start_heading = _heading("Starting Row")
        layout.addWidget(self.start_heading)
        self.start_number = NumberField(AUTOMATIC)
        self.start_letter = LetterBox()
        layout.addWidget(self.start_number)
        layout.addWidget(self.start_letter)
        self.start_note = _note("")
        layout.addWidget(self.start_note)
        layout.addSpacing(2)
        layout.addWidget(_rule())
        layout.addSpacing(2)
        layout.addWidget(_heading("Sheet Layout"))
        self.across_radio = QRadioButton("By Columns")
        self.down_radio = QRadioButton("By Rows")
        self._group = QButtonGroup(self)
        self.across_note = _note("")
        self.down_note = _note("")
        for radio, note, vertical in ((self.across_radio, self.across_note, False), (self.down_radio, self.down_note, True)):
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(radio)
            layout.addWidget(radio)
            layout.addWidget(note)
            radio.toggled.connect(lambda on, v=vertical: self._layout_toggled(v) if on and not self._syncing else None)
        for box in (self.start_number, self.start_letter):
            box.valueChanged.connect(lambda n: None if self._syncing else self.start_changed.emit(n))
        for box in (self.headings_number, self.headings_letter):
            box.valueChanged.connect(lambda n: None if self._syncing else self.headings_changed.emit(n))
        self._explain()

    @property
    def start_box(self) -> NumberField | LetterBox:
        """The starting field in use for the layout."""
        return self.start_letter if self._vertical else self.start_number

    @property
    def headings_box(self) -> NumberField | LetterBox:
        """The headings field in use for the layout."""
        return self.headings_letter if self._vertical else self.headings_number

    def _layout_toggled(self, vertical: bool) -> None:
        self._vertical = vertical
        self._explain()
        self.layout_changed.emit(vertical)

    def _explain(self) -> None:
        """Word every text for the layout, and show the field that fits it (a row number, or a column letter)."""
        unit = "column" if self._vertical else "row"
        self.start_heading.setText(f"Starting {unit.title()}")
        self.headings_heading.setText(f"Headings {unit.title()}")
        if self._vertical:
            self.start_note.setText("'Automatic' finds the first empty column after headings, or choose a custom column.")
            self.headings_note.setText("'Automatic' finds the column that holds the headings, or choose a custom column.")
        else:
            self.start_note.setText("'Automatic' finds the first empty row after headings, or enter a custom row number.")
            self.headings_note.setText("'Automatic' finds the row that holds the headings, or enter a custom row number.")
        self.across_note.setText("Headings run across the first row - each turn writes to the next row.")
        self.down_note.setText("Headings run down the first column - each turn writes to the next column.")
        self.across_radio.setToolTip(self.across_note.text())
        self.down_radio.setToolTip(self.down_note.text())
        self.start_number.setToolTip(self.start_note.text())
        self.start_letter.setToolTip(self.start_note.text())
        self.headings_number.setToolTip(self.headings_note.text())
        self.headings_letter.setToolTip(self.headings_note.text())
        for number, letter in ((self.start_number, self.start_letter), (self.headings_number, self.headings_letter)):
            number.setVisible(not self._vertical)
            letter.setVisible(self._vertical)

    def set_options(self, vertical: bool, start: int, headings: int) -> None:
        """Show the saved options (without reporting them back as changes)."""
        self._syncing = True
        try:
            self._vertical = bool(vertical)
            (self.down_radio if vertical else self.across_radio).setChecked(True)
            self._explain()
            self.start_box.setValue(start)
            self.headings_box.setValue(headings)
        finally:
            self._syncing = False


class PanelGrip(QWidget):
    """A thin strip over the panel's left edge that is dragged sideways to make the panel wider or narrower.

    ``dragged`` carries how far (px) the pointer moved since the last step: positive is to the right (a narrower panel).
    """

    dragged = Signal(int)
    released = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self.setToolTip("Drag left or right to resize the panel")
        self.setFixedWidth(7)
        self._last: int | None = None

    def mousePressEvent(self, event) -> None:                       # noqa: N802 (Qt name)
        self._last = int(event.globalPosition().x())

    def mouseMoveEvent(self, event) -> None:                        # noqa: N802 (Qt name)
        if self._last is not None:
            x = int(event.globalPosition().x())
            if x != self._last:
                step, self._last = x - self._last, x
                self.dragged.emit(step)

    def mouseReleaseEvent(self, event) -> None:                     # noqa: N802 (Qt name)
        if self._last is not None:
            self._last = None
            self.released.emit()


class FileButton(QPushButton):
    """The active file as a button: a folder icon and the file's name (shortened with an ellipsis), or "Open File"."""

    def __init__(self) -> None:
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("keepMargins", True)
        self.icon_label = QLabel()
        self.text_label = ElidedLabel(NO_FILE_TEXT)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(8)
        row.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.text_label, 1, Qt.AlignmentFlag.AlignVCenter)
        for part in (self.icon_label, self.text_label):
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setMinimumHeight(30)

    def sizeHint(self) -> QSize:                                    # noqa: N802 (Qt name)
        return QSize(100, 30)


class SidePanel(QFrame):
    """The panel itself (see the module notes). It starts closed: zero width and hidden."""

    open_file_requested = Signal()
    file_chosen = Signal(object)                # the data of the picked list entry
    mode_changed = Signal(str)                  # NEXT_ROW or APPEND_TO
    layout_changed = Signal(bool)               # True: headings run down the first column
    new_row_requested = Signal()
    start_row_changed = Signal(int)             # 0: automatic
    headings_row_changed = Signal(int)          # 0: automatic
    close_requested = Signal()
    width_dragged = Signal(int)                 # the edge was dragged: pixels to the right (positive makes the panel narrower)
    width_released = Signal()
    settings_requested = Signal()               # the gear button (the window shows the overlay)
    keywords_requested = Signal()               # the Keywords link on the turn page

    def __init__(self) -> None:
        super().__init__()
        self._syncing = False                   # set while the pages are being filled in, so no change is reported
        self._vertical = False
        self._has_file = False
        self._colors = ("#1F1E1D", "#7A55C2")
        self.setObjectName("sidePanel")
        self.setProperty("keepMargins", True)
        self.setProperty("keepSpacing", True)                  # the edge line touches the page beside it
        install_backdrop(self)                  # paints the same (see-through-able) background as the window
        self.setFixedWidth(0)
        self.setVisible(False)
        self.settings = FileSettings()          # the overlay (a popup window of its own)
        self.settings.start_changed.connect(self.start_row_changed)
        self.settings.headings_changed.connect(self.headings_row_changed)
        self.settings.layout_changed.connect(self._layout_toggled)
        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        edge = QFrame()                         # the single thin line between the window and the panel
        edge.setProperty("panelEdge", True)
        edge.setFixedWidth(1)
        shell.addWidget(edge)
        self.grip = PanelGrip(self)                 # the same edge, wide enough to grab
        self.grip.dragged.connect(self.width_dragged)
        self.grip.released.connect(self.width_released)
        body = QWidget()
        body.setProperty("keepMargins", True)
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        shell.addWidget(body, 1)
        self.header = QWidget()                 # the title and X, unless the title bar draws them
        self.header.setProperty("keepMargins", True)
        top = QHBoxLayout(self.header)
        top.setContentsMargins(14, 8, 8, 0)
        top.setSpacing(2)
        self.title_label = QLabel(TITLES["file"])
        self.title_label.setProperty("panelTitle", True)
        top.addWidget(self.title_label, 1)
        self.close_button = self._chrome_button("Close", "Close the Side Panel")
        self.close_button.clicked.connect(self.close_requested)
        top.addWidget(self.close_button)
        outer.addWidget(self.header)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.stack.addWidget(self._scrolled(self._build_file_page()))
        self.stack.addWidget(self._scrolled(self._build_turn_page()))
        self._explain()

    @staticmethod
    def _chrome_button(tip: str, name: str) -> QToolButton:
        button = QToolButton()
        button.setProperty("chromeIcon", True)       # the flat, rounded-on-hover icon look
        button.setToolTip(tip)
        button.setAccessibleName(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def resizeEvent(self, event) -> None:                           # noqa: N802 (Qt name)
        super().resizeEvent(event)
        self._place_grip()

    def showEvent(self, event) -> None:                             # noqa: N802 (Qt name)
        super().showEvent(event)
        self._place_grip()

    def _place_grip(self) -> None:
        """The grip covers the panel's left edge, top to bottom."""
        self.grip.setGeometry(0, 0, self.grip.width(), self.height())
        self.grip.raise_()

    @staticmethod
    def _scrolled(page: QWidget) -> QScrollArea:
        """A page taller than a small window scrolls."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    def set_native_header(self, native: bool) -> None:
        """The title bar draws the panel's title, "…" and X, so the ones inside the panel are hidden."""
        self.header.setVisible(not native)

    # ------------------------------------------------------------------ #
    # Pages                                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _page_layout(page: QWidget) -> QVBoxLayout:
        page.setProperty("keepMargins", True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(6)
        return layout

    def _build_file_page(self) -> QWidget:
        page = QWidget()
        layout = self._page_layout(page)
        title_row = QHBoxLayout()                               # "Active File" and, at the right, the gear that opens its settings
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addWidget(_heading("Active File"), 1)
        self.settings_button = self._chrome_button("File settings: where the data starts and which way the headings run",
                                                   "File Settings")
        self.settings_button.clicked.connect(self.settings_requested)
        title_row.addWidget(self.settings_button)
        layout.addLayout(title_row)
        self.file_button = FileButton()
        self.file_button.clicked.connect(self.open_file_requested)
        layout.addWidget(self.file_button)
        table = QGridLayout()                                    # facts about the file: labels and values line up, no borders
        table.setContentsMargins(0, 2, 0, 2)
        table.setHorizontalSpacing(14)
        table.setVerticalSpacing(3)
        table.setColumnStretch(1, 1)
        self.fact_rows: dict[str, tuple[QLabel, ElidedLabel]] = {}
        for row, name in enumerate(("Sheet", "Path", "Type", "Size", "Modified", "Created")):
            label = QLabel(name)
            label.setProperty("panelNote", True)                 # the label is muted
            label.setIndent(0)
            value = ElidedLabel("")                              # the value is plain text, on one line
            value.setProperty("panelValue", True)
            value.setMinimumWidth(10)
            table.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            table.addWidget(value, row, 1)
            self.fact_rows[name] = (label, value)
            label.setVisible(False)
            value.setVisible(False)
        layout.addLayout(table)
        layout.addSpacing(4)
        layout.addWidget(_rule())
        layout.addSpacing(4)
        layout.addWidget(_heading("Available Files"))
        layout.addWidget(_note("Spreadsheet files currently open on your computer."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.empty_label = _note(NO_OTHERS_TEXT)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.empty_label)
        self.available = QListWidget()
        self.available.setObjectName("panelList")
        self.available.setFrameShape(QFrame.Shape.NoFrame)
        self.available.setCursor(Qt.CursorShape.PointingHandCursor)
        self.available.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.available.setMinimumHeight(150)
        self.available.itemClicked.connect(lambda item: self.file_chosen.emit(item.data(LIST_ROLE)))
        layout.addWidget(self.available, 1)
        layout.addStretch(0)                    # takes the room (and keeps the message at the top) while the list is hidden
        return page

    def _build_turn_page(self) -> QWidget:
        page = QWidget()
        layout = self._page_layout(page)
        self.turn_intro = QLabel("Settings to control how each speak-write iteration (turn) is handled.<br>"
                                 "Voice activated with <a href=\"keywords\">Keywords</a>.")
        self.turn_intro.setProperty("panelNote", True)
        self.turn_intro.setTextFormat(Qt.TextFormat.RichText)
        self.turn_intro.setWordWrap(True)
        self.turn_intro.setOpenExternalLinks(False)
        self.turn_intro.setProperty("hoverLinkTips", True)          # only the link has hover text, while it is hovered
        self.turn_intro.linkActivated.connect(lambda _: self.keywords_requested.emit())
        self.turn_intro.linkHovered.connect(lambda link: self.turn_intro.setToolTip("Open the Keywords settings" if link else ""))
        layout.addWidget(self.turn_intro)
        layout.addSpacing(4)
        layout.addWidget(_rule())
        layout.addSpacing(4)
        self.next_row_radio = QRadioButton("Next Row")
        self.append_radio = QRadioButton("Append To")
        self.next_row_note, self.append_note = _note(""), _note("")
        self._mode_group = QButtonGroup(page)
        for radio, note, mode in ((self.next_row_radio, self.next_row_note, NEXT_ROW),
                                  (self.append_radio, self.append_note, APPEND_TO)):
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            self._mode_group.addButton(radio)
            layout.addWidget(radio)
            layout.addWidget(note)
            radio.toggled.connect(lambda on, m=mode: self._mode_toggled(m) if on else None)
        self.new_row_button = QPushButton("Next")                 # the Next button: moves the cursor on to the next row
        self.new_row_button.setProperty("outline", True)
        self.new_row_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_row_button.clicked.connect(self.new_row_requested)
        layout.addWidget(self.new_row_button)
        layout.addStretch(1)
        self.next_row_radio.setChecked(True)
        self.new_row_button.setEnabled(False)
        return page

    # ------------------------------------------------------------------ #
    # What the pages show                                                  #
    # ------------------------------------------------------------------ #

    def flash_file_button(self, outcome: str = "accepted") -> None:
        """Blink the Open File button (green by default), the way a Term Helper row blinks when it is satisfied: it points
        at the way out of "no file is connected"."""
        border, tint = FLASH_STYLES.get(outcome, FLASH_STYLES["accepted"])
        button = self.file_button
        button.setStyleSheet(f"QPushButton {{ border: 1px solid {border}; background: {tint}; }}")
        QTimer.singleShot(FLASH_MS, lambda: button.setStyleSheet("") if shiboken6.isValid(button) else None)

    def show_page(self, page: str) -> None:
        """Show the ``"file"`` or the ``"turn"`` page."""
        self.stack.setCurrentIndex(1 if page == TURN_PAGE else 0)
        self.title_label.setText(TITLES[TURN_PAGE if page == TURN_PAGE else FILE_PAGE])

    @property
    def page(self) -> str:
        """Which page is showing."""
        return TURN_PAGE if self.stack.currentIndex() == 1 else FILE_PAGE

    def set_colors(self, text: str, accent: str = "#7A55C2") -> None:
        """Redraw the icons (the "…" and X, the search magnifier, the file and Next buttons) in the theme's colours."""
        from quill.ui.icons import make_icon
        self._colors = (text, accent)
        self.close_button.setIcon(make_icon("close", text, 16))
        self.settings_button.setIcon(make_icon("gear", text, 16))
        if not self.search.actions():
            self.search.addAction(make_icon("search", text, 15), QLineEdit.ActionPosition.LeadingPosition)
        else:
            self.search.actions()[0].setIcon(make_icon("search", text, 15))
        self.new_row_button.setIcon(make_icon("next", accent, 16))
        self._draw_file_icon()

    def _draw_file_icon(self) -> None:
        from quill.ui.icons import make_icon
        text, _ = self._colors
        self.file_button.icon_label.setPixmap(
            make_icon("folder-open" if self._has_file else "folder", text, 16).pixmap(16, 16))

    def set_active(self, name: str, sheet: str = "", path: str = "", kind: str = "") -> None:
        """Show the active file: its name on the button (the full *path* on hover) and a table of quiet facts about it
        (sheet, path on one line, *kind* of program or format, size, dates as MM/DD/YY)."""
        self._has_file = bool(name)
        self.file_button.text_label.setFullText(name or NO_FILE_TEXT, path or name or "Choose a spreadsheet file")
        self.file_button.setToolTip((path or name) + "\nClick to choose another file" if name else "Choose a spreadsheet file")
        self._draw_file_icon()
        facts: dict[str, tuple[str, str]] = {}
        if name:
            if sheet:
                facts["Sheet"] = (sheet, sheet)
            if path:
                facts["Path"] = (path, path)
            if kind:
                facts["Type"] = (kind, kind)
            for label, value in (file_facts(path) if path else []):
                facts[label] = (value, value)
        for label, (name_label, value_label) in self.fact_rows.items():
            text, tip = facts.get(label, ("", ""))
            value_label.setFullText(text, tip)
            name_label.setVisible(bool(text))
            value_label.setVisible(bool(text))
        self._draw_file_icon()

    def fact(self, label: str) -> str:
        """The value shown for *label* in the file table ("" while it is hidden)."""
        name_label, value = self.fact_rows[label]
        return value.full_text if not name_label.isHidden() else ""

    def set_available(self, entries: list[tuple[str, str, object]]) -> None:
        """List the other open spreadsheets as ``(name, hover text, data)`` (the data comes back with ``file_chosen``)."""
        self.available.clear()
        for name, tip, data in entries:
            item = QListWidgetItem(name)
            item.setToolTip(tip)
            item.setData(LIST_ROLE, data)
            self.available.addItem(item)
        self._filter(self.search.text())

    def available_names(self) -> list[str]:
        """The names in the list, top to bottom."""
        return [self.available.item(i).text() for i in range(self.available.count())]

    def _filter(self, text: str) -> None:
        """Show only the files whose name holds *text*."""
        wanted = text.strip().lower()
        shown = 0
        for i in range(self.available.count()):
            item = self.available.item(i)
            hide = bool(wanted) and wanted not in item.text().lower()
            item.setHidden(hide)
            shown += not hide
        total = self.available.count()
        self.available.setVisible(shown > 0)
        self.empty_label.setText(NO_MATCH_TEXT if total and not shown else NO_OTHERS_TEXT)
        self.empty_label.setVisible(shown == 0)

    def _mode_toggled(self, mode: str) -> None:
        """A radio button was checked: Next is only usable (and only looks usable) while Append To is chosen."""
        self.new_row_button.setEnabled(mode == APPEND_TO)
        if not self._syncing:
            self.mode_changed.emit(mode)

    def _layout_toggled(self, vertical: bool) -> None:
        self._vertical = vertical
        self._explain()
        self.layout_changed.emit(vertical)

    def _explain(self) -> None:
        """Word the turn page for the layout: rows when headings run across the top, columns when they run down."""
        unit = "column" if self._vertical else "row"
        self.next_row_radio.setText(f"Next {unit.title()}")
        self.next_row_note.setText(f"Turn words are written to new {unit}s")
        self.append_note.setText(f"Turn words are added to the same {unit}")
        self.new_row_button.setToolTip(f"Move cursor to the next {unit}")
        self.next_row_radio.setToolTip(self.next_row_note.text())
        self.append_radio.setToolTip(self.append_note.text())

    def set_options(self, mode: str, vertical: bool, start_row: int = 0, headings_row: int = 0) -> None:
        """Show the saved options on both pages and the overlay (without reporting them back as changes)."""
        self._syncing = True
        try:
            self._vertical = bool(vertical)
            (self.append_radio if mode == APPEND_TO else self.next_row_radio).setChecked(True)
        finally:
            self._syncing = False
        self.settings.set_options(vertical, start_row, headings_row)
        self._explain()
        self.new_row_button.setEnabled(mode == APPEND_TO)

    def set_turn(self, mode: str, vertical: bool | None = None, start_row: int | None = None, headings_row: int | None = None) -> None:
        """Show the saved mode (and, when given, the layout, starting row and headings row)."""
        self.set_options(mode, self._vertical if vertical is None else vertical,
                         self.settings.start_box.value() if start_row is None else start_row,
                         self.settings.headings_box.value() if headings_row is None else headings_row)

    def show_settings(self, global_point) -> None:
        """Show the file settings overlay with its top-right corner at *global_point*."""
        self.settings.adjustSize()
        self.settings.move(global_point.x() - self.settings.width(), global_point.y())
        self.settings.show()
