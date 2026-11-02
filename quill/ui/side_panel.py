"""The right-hand side panel: it eases in beside the window and shows one of two pages.

* **File** (the folder icon): the active spreadsheet (its name, with the full path on hover, and the sheet), a
  button for the standard file chooser, and a scrollable list of the other spreadsheets that are open in
  programs on this computer. Picking one moves it up into the active section.
* **Turn** (the turn icon): how the words of one turn are written (to the next row, or appended to the same
  row) and which way the sheet is laid out (headings across the top, or down the side).

The panel only shows state and reports what the user chose through signals; the window animates it and the
application acts on the choices.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from quill.ui.theme import install_backdrop
from quill.ui.widgets import ElidedLabel

#: Width (px) of the panel when it is open.
PANEL_WIDTH = 236

NEXT_ROW, APPEND_TO = "next_row", "append"
FILE_PAGE, TURN_PAGE = "file", "turn"
NO_FILE_TEXT = "No file connected"
NO_OTHERS_TEXT = "No other spreadsheets are open on this computer."
LIST_ROLE = Qt.ItemDataRole.UserRole


def _rule() -> QFrame:
    """A muted hairline between two sections."""
    line = QFrame()
    line.setProperty("panelRule", True)
    line.setFixedHeight(1)
    return line


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("staticHeading", True)
    return label


def _note(text: str, indent: int = 0) -> QLabel:
    label = QLabel(text)
    label.setProperty("note", True)
    label.setWordWrap(True)
    label.setContentsMargins(indent, 0, 0, 4)
    return label


class SidePanel(QFrame):
    """The panel itself (see the module notes). It starts closed: zero width and hidden."""

    open_file_requested = Signal()
    file_chosen = Signal(object)                # the data of the picked list entry
    mode_changed = Signal(str)                  # NEXT_ROW or APPEND_TO
    layout_changed = Signal(bool)               # True: headings run down the first column
    new_row_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._syncing = False                   # set while the pages are being filled in, so no change is reported
        self.setObjectName("sidePanel")
        self.setProperty("keepMargins", True)
        install_backdrop(self)                  # paints the same (see-through-able) background as the window
        self.setFixedWidth(0)
        self.setVisible(False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.stack.addWidget(self._build_file_page())
        scroll = QScrollArea()                   # the turn page is taller than a small window
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._build_turn_page())
        self.stack.addWidget(scroll)

    # ------------------------------------------------------------------ #
    # Pages                                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _page_layout(page: QWidget) -> QVBoxLayout:
        page.setProperty("keepMargins", True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        return layout

    def _build_file_page(self) -> QWidget:
        page = QWidget()
        layout = self._page_layout(page)
        layout.addWidget(_heading("Active File"))
        self.name_label = ElidedLabel(NO_FILE_TEXT)
        self.name_label.setProperty("panelName", True)
        layout.addWidget(self.name_label)
        self.sheet_label = QLabel("")
        self.sheet_label.setProperty("note", True)
        self.sheet_label.setVisible(False)
        layout.addWidget(self.sheet_label)
        self.open_button = QPushButton("Open File…")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.setToolTip("Choose a spreadsheet file with the standard file window")
        self.open_button.clicked.connect(self.open_file_requested)
        layout.addWidget(self.open_button)
        layout.addSpacing(4)
        layout.addWidget(_rule())
        layout.addSpacing(4)
        layout.addWidget(_heading("Available Spreadsheets"))
        self.available = QListWidget()
        self.available.setObjectName("panelList")
        self.available.setFrameShape(QFrame.Shape.NoFrame)
        self.available.setCursor(Qt.CursorShape.PointingHandCursor)
        self.available.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.available.setMinimumHeight(60)
        self.available.itemClicked.connect(lambda item: self.file_chosen.emit(item.data(LIST_ROLE)))
        layout.addWidget(self.available, 1)
        self.empty_label = _note(NO_OTHERS_TEXT)
        layout.addWidget(self.empty_label)
        return page

    def _build_turn_page(self) -> QWidget:
        page = QWidget()
        layout = self._page_layout(page)
        layout.addWidget(_heading("Each Turn"))
        self.next_row_radio = QRadioButton("Next Row")
        self.append_radio = QRadioButton("Append To")
        self._mode_group = QButtonGroup(page)
        for radio, mode, text in ((self.next_row_radio, NEXT_ROW, "Every turn is written to a new row."),
                                  (self.append_radio, APPEND_TO,
                                   "Every turn adds to the same row. A cell that already has a value gets the new "
                                   "one after a comma.")):
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            self._mode_group.addButton(radio)
            layout.addWidget(radio)
            layout.addWidget(_note(text, 22))
            radio.toggled.connect(lambda on, m=mode: self.mode_changed.emit(m) if on and not self._syncing else None)
        self.new_row_button = QPushButton("Start a New Row")
        self.new_row_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_row_button.setToolTip("Stop adding to the current row: the next turn starts a fresh one")
        self.new_row_button.clicked.connect(self.new_row_requested)
        layout.addWidget(self.new_row_button)
        layout.addSpacing(4)
        layout.addWidget(_rule())
        layout.addSpacing(4)
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
            layout.addWidget(_note(text, 22))
            radio.toggled.connect(lambda on, v=vertical: self.layout_changed.emit(v) if on and not self._syncing else None)
        layout.addStretch(1)
        self.set_turn(NEXT_ROW, False)
        return page

    # ------------------------------------------------------------------ #
    # What the pages show                                                  #
    # ------------------------------------------------------------------ #

    def show_page(self, page: str) -> None:
        """Show the ``"file"`` or the ``"turn"`` page."""
        self.stack.setCurrentIndex(1 if page == TURN_PAGE else 0)

    @property
    def page(self) -> str:
        """Which page is showing."""
        return TURN_PAGE if self.stack.currentIndex() == 1 else FILE_PAGE

    def set_active(self, name: str, sheet: str = "", path: str = "") -> None:
        """Show the active file: its name (the full *path* on hover) and, when it has several, its sheet."""
        if name:
            self.name_label.setFullText(name, path or name)
        else:
            self.name_label.setFullText(NO_FILE_TEXT, NO_FILE_TEXT)
        self.name_label.setProperty("muted", not name)
        self.name_label.style().unpolish(self.name_label)
        self.name_label.style().polish(self.name_label)
        self.sheet_label.setText(f"Sheet: {sheet}" if name and sheet else "")
        self.sheet_label.setVisible(bool(name and sheet))

    def set_available(self, entries: list[tuple[str, str, object]]) -> None:
        """List the other open spreadsheets as ``(name, hover text, data)`` (the data comes back with ``file_chosen``)."""
        self.available.clear()
        for name, tip, data in entries:
            item = QListWidgetItem(name)
            item.setToolTip(tip)
            item.setData(LIST_ROLE, data)
            self.available.addItem(item)
        self.empty_label.setVisible(not entries)

    def available_names(self) -> list[str]:
        """The names in the list, top to bottom."""
        return [self.available.item(i).text() for i in range(self.available.count())]

    def set_turn(self, mode: str, vertical: bool) -> None:
        """Show the turn settings (without reporting them back as a change)."""
        self._syncing = True
        try:
            (self.append_radio if mode == APPEND_TO else self.next_row_radio).setChecked(True)
            (self.down_radio if vertical else self.across_radio).setChecked(True)
        finally:
            self._syncing = False
        self.new_row_button.setEnabled(mode == APPEND_TO)
