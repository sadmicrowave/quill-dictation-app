"""The right-hand side panel: it eases in beside the window and shows one of two pages.

* **Files** (the folder icon): the active spreadsheet as a button (its name, or "Open File" while there is none;
  pressing it opens the file window where that file is), the sheet and some quiet facts about the file, where
  the data starts (starting row, headings row, which way the headings run), and a filterable, scrollable list of
  the other spreadsheets that are open in programs on this computer. Picking one moves it up to the top.
* **Turn Options** (the turn icon): whether each turn is written to a new row or added to the same row.

The panel only shows state and reports what the user chose through signals; the window animates it and the
application acts on the choices. Its title and close button are drawn in the title bar on macOS (see
``chrome``); elsewhere they are drawn here (:meth:`set_native_header`).
"""

from __future__ import annotations

import datetime as dt
import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
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

from quill.ui.theme import install_backdrop
from quill.ui.widgets import ElidedLabel

#: Width (px) of the panel when it is open.
PANEL_WIDTH = 236

NEXT_ROW, APPEND_TO = "next_row", "append"
FILE_PAGE, TURN_PAGE = "file", "turn"
NO_FILE_TEXT = "Open File"
NO_OTHERS_TEXT = "No open spreadsheet files have been detected."
NO_MATCH_TEXT = "No files match."
TITLES = {"file": "Files", "turn": "Turn Options"}
AUTOMATIC = "Automatic"
LIST_ROLE = Qt.ItemDataRole.UserRole


def file_facts(path: str) -> list[str]:
    """The quiet lines about a file on disk: size, date modified, date created ([] when it cannot be read)."""
    try:
        info = os.stat(path)
    except OSError:
        return []
    created = getattr(info, "st_birthtime", info.st_ctime)

    def when(stamp: float) -> str:
        return dt.datetime.fromtimestamp(stamp).strftime("%b %d, %Y  %I:%M %p").replace(" 0", " ", 1)

    return [f"Size: {human_size(info.st_size)}", f"Modified: {when(info.st_mtime)}", f"Created: {when(created)}"]


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
    label.setProperty("staticHeading", True)
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

    def __init__(self) -> None:
        super().__init__()
        self._syncing = False                   # set while the pages are being filled in, so no change is reported
        self._vertical = False
        self._has_file = False
        self._colors = ("#1F1E1D", "#7A55C2")
        self.setObjectName("sidePanel")
        self.setProperty("keepMargins", True)
        install_backdrop(self)                  # paints the same (see-through-able) background as the window
        self.setFixedWidth(0)
        self.setVisible(False)
        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        edge = QFrame()                         # the single thin line between the window and the panel
        edge.setProperty("panelEdge", True)
        edge.setFixedWidth(1)
        shell.addWidget(edge)
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
        self.title_label = QLabel(TITLES["file"])
        self.title_label.setProperty("panelTitle", True)
        top.addWidget(self.title_label, 1)
        self.close_button = QToolButton()
        self.close_button.setProperty("chromeIcon", True)       # the flat, rounded-on-hover icon look
        self.close_button.setToolTip("Close")
        self.close_button.setAccessibleName("Close the Side Panel")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.close_requested)
        top.addWidget(self.close_button)
        outer.addWidget(self.header)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.stack.addWidget(self._scrolled(self._build_file_page()))
        self.stack.addWidget(self._scrolled(self._build_turn_page()))

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
        """The title bar draws the panel's title and X, so the ones inside the panel are hidden."""
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

    @staticmethod
    def _number_box(special: str) -> NumberField:
        """A boxed number field like the search and Term Helper fields; empty reads *special* (Automatic)."""
        return NumberField(special)

    def _build_file_page(self) -> QWidget:
        page = QWidget()
        layout = self._page_layout(page)
        layout.addWidget(_heading("Active File"))
        self.file_button = FileButton()
        self.file_button.clicked.connect(self.open_file_requested)
        layout.addWidget(self.file_button)
        self.sheet_label = _note("")
        self.sheet_label.setVisible(False)
        layout.addWidget(self.sheet_label)
        self.path_label = ElidedLabel("")                      # one line, shortened with an ellipsis
        self.path_label.setProperty("panelNote", True)
        self.path_label.setVisible(False)
        layout.addWidget(self.path_label)
        self.facts_label = _note("")                             # type, size, dates
        self.facts_label.setVisible(False)
        layout.addWidget(self.facts_label)
        layout.addSpacing(4)
        layout.addWidget(_rule())
        layout.addSpacing(4)

        self.start_heading = _heading("Starting Row")
        layout.addWidget(self.start_heading)
        self.start_spin = self._number_box(AUTOMATIC)
        self.start_spin.valueChanged.connect(lambda n: None if self._syncing else self.start_row_changed.emit(n))
        layout.addWidget(self.start_spin)
        self.start_note = _note("")
        layout.addWidget(self.start_note)

        layout.addSpacing(2)
        layout.addWidget(_heading("Sheet Layout"))
        self.across_radio = QRadioButton("Columns Across")
        self.down_radio = QRadioButton("Rows Down")
        self._layout_group = QButtonGroup(page)
        for radio, vertical, text in ((self.across_radio, False, "Headings run across the first row."),
                                      (self.down_radio, True,
                                       "Headings run down the first column; each turn fills the next column.")):
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            self._layout_group.addButton(radio)
            layout.addWidget(radio)
            layout.addWidget(_note(text))
            radio.toggled.connect(lambda on, v=vertical: self._layout_toggled(v) if on and not self._syncing else None)
        self.headings_heading = _heading("Headings Row")
        layout.addWidget(self.headings_heading)
        self.headings_spin = self._number_box(AUTOMATIC)
        self.headings_spin.valueChanged.connect(lambda n: None if self._syncing else self.headings_row_changed.emit(n))
        layout.addWidget(self.headings_spin)
        self.headings_note = _note("")
        layout.addWidget(self.headings_note)

        layout.addSpacing(4)
        layout.addWidget(_rule())
        layout.addSpacing(4)
        layout.addWidget(_heading("Files"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter files")
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
        self.across_radio.setChecked(True)
        self._explain()
        return page

    def _build_turn_page(self) -> QWidget:
        page = QWidget()
        layout = self._page_layout(page)
        layout.addWidget(_heading("Each Turn"))
        self.next_row_radio = QRadioButton("Next Row")
        self.append_radio = QRadioButton("Append To")
        self._mode_group = QButtonGroup(page)
        for radio, mode, text in ((self.next_row_radio, NEXT_ROW, "Turn words are written to new rows"),
                                  (self.append_radio, APPEND_TO, "Turn words are added to the same row")):
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            self._mode_group.addButton(radio)
            layout.addWidget(radio)
            layout.addWidget(_note(text))
            radio.toggled.connect(lambda on, m=mode: self.mode_changed.emit(m) if on and not self._syncing else None)
        self.new_row_button = QPushButton("Next")                 # the Next button: the turn's row is over, start a fresh one
        self.new_row_button.setProperty("outline", True)
        self.new_row_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_row_button.setToolTip("Stop adding to the current row: the next turn starts a fresh one")
        self.new_row_button.clicked.connect(self.new_row_requested)
        layout.addWidget(self.new_row_button)
        layout.addStretch(1)
        self.next_row_radio.setChecked(True)
        self.new_row_button.setEnabled(False)
        return page

    # ------------------------------------------------------------------ #
    # What the pages show                                                  #
    # ------------------------------------------------------------------ #

    def show_page(self, page: str) -> None:
        """Show the ``"file"`` or the ``"turn"`` page."""
        self.stack.setCurrentIndex(1 if page == TURN_PAGE else 0)
        self.title_label.setText(TITLES[TURN_PAGE if page == TURN_PAGE else FILE_PAGE])

    @property
    def page(self) -> str:
        """Which page is showing."""
        return TURN_PAGE if self.stack.currentIndex() == 1 else FILE_PAGE

    def set_colors(self, text: str, accent: str = "#7A55C2") -> None:
        """Redraw the icons (the X, the search magnifier, the file and Next buttons) in the theme's colours."""
        from quill.ui.icons import make_icon
        self._colors = (text, accent)
        self.close_button.setIcon(make_icon("close", text, 16))
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
        """Show the active file: its name on the button (the full *path* on hover), the sheet, and quiet facts about it
        (the path on one line, its *kind* of program or format, size and dates)."""
        self._has_file = bool(name)
        self.file_button.text_label.setFullText(name or NO_FILE_TEXT, path or name or "Choose a spreadsheet file")
        self._draw_file_icon()
        self.sheet_label.setText(f"Sheet: {sheet}" if name and sheet else "")
        self.sheet_label.setVisible(bool(name and sheet))
        self.path_label.setFullText(path, path)
        self.path_label.setVisible(bool(name and path))
        facts = []
        if name:
            if kind:
                facts.append(f"Type: {kind}")
            facts += file_facts(path) if path else []
        self.facts_label.setText("\n".join(facts))
        self.facts_label.setVisible(bool(facts))

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

    def _layout_toggled(self, vertical: bool) -> None:
        self._vertical = vertical
        self._explain()
        self.layout_changed.emit(vertical)

    def _explain(self) -> None:
        """Word the starting and headings fields for the layout: a row when headings run across, a column when down."""
        unit = "column" if self._vertical else "row"
        self.start_heading.setText(f"Starting {unit.title()}")
        self.headings_heading.setText(f"Headings {unit.title()}")
        self.start_note.setText(f"'{AUTOMATIC}' determines the first empty {unit} after headings or choose a different starting {unit}.")
        self.headings_note.setText(f"'{AUTOMATIC}' finds the {unit} that holds the headings or choose it yourself.")

    def set_options(self, mode: str, vertical: bool, start_row: int = 0, headings_row: int = 0) -> None:
        """Show the saved options (without reporting them back as changes)."""
        self._syncing = True
        try:
            self._vertical = bool(vertical)
            (self.append_radio if mode == APPEND_TO else self.next_row_radio).setChecked(True)
            (self.down_radio if vertical else self.across_radio).setChecked(True)
            self.start_spin.setValue(start_row)
            self.headings_spin.setValue(headings_row)
        finally:
            self._syncing = False
        self._explain()
        self.new_row_button.setEnabled(mode == APPEND_TO)

    def set_turn(self, mode: str, vertical: bool | None = None, start_row: int | None = None, headings_row: int | None = None) -> None:
        """Show the saved mode (and, when given, the layout, starting row and headings row)."""
        self.set_options(mode, self._vertical if vertical is None else vertical,
                         self.start_spin.value() if start_row is None else start_row,
                         self.headings_spin.value() if headings_row is None else headings_row)
