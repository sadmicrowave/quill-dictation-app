"""Main Quill window — compact, OS-native, dark-mode-aware.

Layout (~340 px wide):
  status row:  [● Listening]  [Start/Stop]  [Settings…]
  workbook row: [workbook picker]               Sheet: <name>
  Current row (the fields being built, one line per column)
  Last saved row
  Scrolling action log
  Footer message (model / connection status)

The window only displays state and reports user intent through the callbacks
passed to the constructor; it holds no dictation logic.
"""
from __future__ import annotations
import datetime as dt
import logging
from typing import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QSize, Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QLayout, QMainWindow, QPlainTextEdit, QSizePolicy,
    QPushButton, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from quill.ui.chrome import set_always_on_top
from quill.ui.icons import make_icon
from quill.ui.theme import apply_spacing
from quill.ui.widgets import ElidedLabel, HeadingToggle, Pill, connection_tip, tooltip_lines

#: Active-light colours (the same hues are used by the tray icon).
COLOR_ACTIVE = "#34c759"
COLOR_IDLE = "#8e8e93"

#: The help page the window's ? icon opens.
HELP_TOPIC = "welcome"

#: The chip that replaces the sheet name while no spreadsheet is connected, and its tooltip.
NOT_CONNECTED_TEXT = "File stream not connected"
NOT_CONNECTED_HINT = (
    "No spreadsheet is connected, so there is nothing to read lists from or write rows to.\n"
    "Quill works through a workbook open in Excel (it attaches automatically within a few seconds of "
    "the workbook opening) or through an .xlsx file chosen with File > Open Spreadsheet File.\n"
    "Open a workbook or choose a file; listening can start once the connection is made."
)
CHIP_HEIGHT = 22

#: Heights (px) of the Current Row box: when empty, and the most it grows to before it scrolls inside itself.
ROW_EMPTY_HEIGHT = 42
ROW_MAX_FULL = 150
ROW_MAX_MINI = 66

#: Space left below the "Log" heading when the log is minimized, in pixels.
LOG_BOTTOM_MARGIN = 7

#: Lines kept in the log before the oldest are dropped.
MAX_LOG_LINES = 500


class _ChipPlacer(QObject):
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


class _WorkbookCombo(QComboBox):
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


class _RowTable(QTableWidget):
    """The Current Row box: it asks for just its minimum height, so it grows only when given room."""

    def sizeHint(self) -> QSize:                                    # noqa: N802 (Qt name)
        return QSize(super().sizeHint().width(), self.minimumHeight())

    def minimumSizeHint(self) -> QSize:                             # noqa: N802
        return QSize(super().minimumSizeHint().width(), self.minimumHeight())


class MainWindow:
    """The compact status window.

    Args:
        on_toggle: Called when the user presses Start/Stop; receives the
            *desired* listening state.
        on_settings: Called when the user opens Settings.
        on_workbook: Called with a workbook name picked in the combo box.
        on_download_model: Called when the user asks to download the speech model.
        on_sorting: Called when the user opens the Needs-sorting list.
        on_undo: Called when the user presses Undo (takes back the last sorting answer).
        on_log_toggled: Called with True/False when the user collapses/expands the log.
        on_mini_toggled: Called with True/False when the user enters/leaves the mini view.
        on_open_file: Called when the user chooses Open Spreadsheet File (button or File menu).
        on_use_excel: Called when the user chooses to go back to the open Excel workbook.
        on_help: Called with a help topic when the user presses the ? icon.
        mini: Start in the mini view. mini_on_top: keep the mini view above other windows.
        log_collapsed: Start with the log collapsed.
    """

    def __init__(
        self,
        on_toggle: Callable[[bool], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_workbook: Callable[[str], None] | None = None,
        on_download_model: Callable[[], None] | None = None,
        on_sorting: Callable[[], None] | None = None,
        on_undo: Callable[[], None] | None = None,
        on_log_toggled: Callable[[bool], None] | None = None,
        log_collapsed: bool = False,
        on_mini_toggled: Callable[[bool], None] | None = None,
        on_open_file: Callable[[], None] | None = None,
        on_use_excel: Callable[[], None] | None = None,
        on_help: Callable[[str], None] | None = None,
        mini: bool = False,
        mini_on_top: bool = True,
    ) -> None:
        self._on_toggle = on_toggle or (lambda active: None)
        self._on_settings = on_settings or (lambda: None)
        self._on_workbook = on_workbook or (lambda name: None)
        self._on_download_model = on_download_model or (lambda: None)
        self._on_sorting = on_sorting or (lambda: None)
        self._on_undo = on_undo or (lambda: None)
        self._on_log_toggled = on_log_toggled or (lambda collapsed: None)
        self._log_collapsed = log_collapsed
        self._on_mini_toggled = on_mini_toggled or (lambda mini: None)
        self._on_open_file = on_open_file or (lambda: None)
        self._on_use_excel = on_use_excel or (lambda: None)
        self._on_help = on_help or (lambda topic: None)
        self._native_help_button = False
        self._mini = mini                          # the state asked for (may still be animating there)
        self._view_mini = False                    # what is actually on screen (set by _apply_view)
        self._native_mini_button = False           # True once the title bar has its own resize icon
        self.native_window_recreated = False       # set if a window flag had to be changed the old way
        self._mini_on_top = mini_on_top
        self._full_size = QSize(360, 520)        # the size to return to when leaving the mini view
        self._undo_count = 0
        self._sorting_count = 0
        self._footer_text = ""
        self._offer_download = False
        self._not_connected = False
        self._native_settings_button = False
        self._native_undo_button = False
        self._text_color = "#1F1E1D"
        self._accent = "#7A55C2"
        self._applied: dict[str, bool] = {}     # which sections are collapsed on screen
        self._freed: dict[str, int] = {}     # window height each collapsed section gave back
        self._window: QMainWindow | None = None
        self.root: QWidget | None = None       # the widget that paints the background (set in setup)
        self._listening = False
        self._on_accent = "#FFFFFF"

    # ------------------------------------------------------------------ #
    # Construction                                                         #
    # ------------------------------------------------------------------ #

    def setup(self) -> None:
        """Build the widgets. Call once, after the QApplication exists."""
        window = QMainWindow()
        window.setWindowTitle("Quill")
        window.resize(360, 520)
        central = QWidget()
        central.setObjectName("mainRoot")                       # paints the background; opacity applies to it
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.root = central
        layout = QVBoxLayout(central)
        # The window may be smaller than its content while it animates between sizes, so the layout
        # must not force the window's minimum size (it is set once an animation has finished).
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        central.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        # --- status row
        # One button is the whole control: the light, the state and the play / stop glyph. Pressing it
        # starts or stops listening; it fills with the accent colour while listening.
        self.dot = QLabel("●")
        self.state_label = QLabel()
        self.toggle_icon = QLabel()
        self.toggle_button = QPushButton()
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setProperty("keepMargins", True)
        self.toggle_button.setProperty("outline", True)           # outlined in the accent colour until listening fills it
        inner = QHBoxLayout(self.toggle_button)
        inner.setContentsMargins(14, 0, 14, 0)
        inner.setSpacing(8)
        for part, stretch in ((self.toggle_icon, 0), (None, 1), (self.dot, 0), (self.state_label, 0)):
            if part is None:
                inner.addStretch(stretch)
                continue
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)   # clicks reach the button
            inner.addWidget(part, 0, Qt.AlignmentFlag.AlignVCenter)
        self.toggle_button.clicked.connect(lambda: self._on_toggle(not self._listening))
        self.settings_button = QPushButton()            # icon only; refresh_icons() draws it
        self.settings_button.setProperty("iconOnly", True)
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(lambda: self._on_settings())
        self.mini_button = QToolButton()                # just an icon (no box), like the Log heading
        self.mini_button.setProperty("flatIcon", True)
        self.mini_button.setAutoRaise(True)
        self.mini_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mini_button.clicked.connect(lambda: self.set_mini(not self._mini, notify=True))
        row = QHBoxLayout()
        # Undo: just an icon (greyed out when there is nothing to take back); the title bar has its own on macOS
        self.undo_button = QPushButton()
        self.undo_button.setProperty("iconOnly", True)
        self.undo_button.setToolTip("Undo the Last Answer")
        self.undo_button.setAccessibleName("Undo")
        self.undo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(lambda: self._on_undo())
        self.help_button = QPushButton()                  # the title bar has its own on macOS
        self.help_button.setProperty("iconOnly", True)
        self.help_button.setToolTip("Help")
        self.help_button.setAccessibleName("Help")
        self.help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.help_button.clicked.connect(lambda: self._on_help(HELP_TOPIC))
        row.addWidget(self.toggle_button, 1)
        row.addWidget(self.help_button)
        row.addWidget(self.undo_button)
        row.addWidget(self.settings_button)
        row.addWidget(self.mini_button)
        layout.addLayout(row)
        self._layout, self._status_row = layout, row

        # --- workbook row
        self.workbook_combo = _WorkbookCombo()
        self.workbook_combo.sync()
        self.workbook_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.workbook_combo.activated.connect(
            lambda index: self._on_workbook(self.workbook_combo.itemText(index))
        )
        self.sheet_label = QLabel("Sheet: –")
        # Shown instead of the sheet name while no spreadsheet is connected: a technical warning chip.
        # (It sits inside the empty workbook picker; the mini view, which has no picker, has its own.)
        self.workbook_row = QWidget()                   # one widget so the mini view can hide the row whole
        self.connection_chip = self._make_chip(self.workbook_row)
        self._chip_placer = _ChipPlacer(self.workbook_combo, self.connection_chip)
        self.mini_chip = self._make_chip(None)
        self.open_file_button = QPushButton()                   # just a folder icon; refresh_icons() draws it
        self.open_file_button.setProperty("iconOnly", True)
        self.open_file_button.setToolTip("Open Spreadsheet File\nWork on an .xlsx file directly (no Excel needed)")
        self.open_file_button.setAccessibleName("Open Spreadsheet File")
        self.open_file_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_file_button.clicked.connect(lambda: self._on_open_file())
        self.workbook_row.setProperty("keepMargins", True)    # flush with the content above and below
        row = QHBoxLayout(self.workbook_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.workbook_combo, 1)
        row.addWidget(self.open_file_button)
        layout.addWidget(self.workbook_row)
        layout.addWidget(self.sheet_label)
        layout.addWidget(self.mini_chip, 0, Qt.AlignmentFlag.AlignLeft)

        # --- current row
        # (Not collapsible: the row being built is the point of every spoken turn, so it is always in view.)
        self.row_heading = QLabel("Current Row")
        self.row_heading.setProperty("staticHeading", True)
        layout.addWidget(self.row_heading, 0, Qt.AlignmentFlag.AlignLeft)
        self.row_table = _RowTable(0, 2)
        self.row_table.horizontalHeader().setVisible(False)
        self.row_table.verticalHeader().setVisible(False)
        self.row_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.row_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.row_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._row_height = self.row_table.verticalHeader().defaultSectionSize()
        self.row_table.setMinimumHeight(ROW_EMPTY_HEIGHT)           # starts small; grows with the fields heard
        self._row_target = ROW_EMPTY_HEIGHT
        # a hint shown while no fields have been heard yet
        self.row_placeholder = QLabel("Fields appear here as they are heard", self.row_table.viewport())
        self.row_placeholder.setProperty("note", True)
        self.row_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.row_placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        holder = QVBoxLayout(self.row_table.viewport())
        holder.setContentsMargins(4, 0, 4, 0)
        holder.addWidget(self.row_placeholder)
        layout.addWidget(self.row_table, 1)        # takes the height when the window is resized: it is what is being watched
        self._has_last_saved = False                       # the line shows only once a row has been saved
        self.last_label = ElidedLabel("")                  # one line however much was saved
        self.last_label.setProperty("note", True)          # smaller italic supporting text
        layout.addWidget(self.last_label)

        # "Needs sorting (3)": filled in the accent colour, the count as an inline pill.
        self.sorting_button = QPushButton()
        self.sorting_button.setProperty("accent", True)
        self.sorting_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sorting_button.setMinimumHeight(self.sorting_button.fontMetrics().height() * 2 + 4)
        self.sorting_button.setProperty("keepMargins", True)
        inner = QHBoxLayout(self.sorting_button)
        inner.setContentsMargins(12, 0, 12, 0)
        inner.addStretch(1)
        title = QLabel("Term Helper")
        self.sorting_title = title
        self.badge_label = Pill("0")
        for part in (title, self.badge_label):
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)   # clicks reach the button
            inner.addWidget(part, 0, Qt.AlignmentFlag.AlignVCenter)   # the pill hugs its text
        inner.addStretch(1)
        self.sorting_button.clicked.connect(lambda: self._on_sorting())
        self._sorting_index = -1
        self.sorting_button.setVisible(False)
        layout.addWidget(self.sorting_button)
        self._sorting_index = layout.indexOf(self.sorting_button)

        # --- status messages (the model download, and so on) sit above the log, so that
        # nothing is ever below "Log" when it is minimized
        self.footer = QLabel()
        self.footer.setWordWrap(True)
        self.footer.setVisible(False)
        self.download_button = QPushButton("Download Speech Model")
        self.download_button.clicked.connect(lambda: self._on_download_model())
        self.download_button.setVisible(False)
        layout.addWidget(self.footer)
        layout.addWidget(self.download_button)

        # --- log (last). The Current Row box takes extra height when the window grows (and shares it with
        # the log while that is open), so no gaps open between sections and "Log" stays at the bottom.
        self.log_toggle = self._section_toggle("Show or hide the log")
        layout.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(MAX_LOG_LINES)
        layout.addWidget(self.log, 1)

        # File menu (the global menu bar on macOS): Open Spreadsheet File, and back to live Excel.
        file_menu = window.menuBar().addMenu("File")
        self.open_file_action = file_menu.addAction("Open Spreadsheet File…", lambda: self._on_open_file())
        self.open_file_action.setShortcut("Ctrl+O")
        self.use_excel_action = file_menu.addAction("Use Open Excel Workbook", lambda: self._on_use_excel())
        self.use_excel_action.setEnabled(False)
        window.setCentralWidget(central)
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)   # lets opacity < 100 show through
        self._window = window
        self.refresh_icons()
        self._set_collapsed("log", self._log_collapsed)
        if self._mini:
            self.set_mini(True)
        else:
            self._refresh_visibility()
        self.set_listening_indicator(False)

    @staticmethod
    def _make_chip(parent: QWidget | None) -> QLabel:
        """The "File stream not connected" warning chip: a fixed-height pill that never stretches."""
        chip = QLabel(NOT_CONNECTED_TEXT, parent)
        chip.setProperty("chip", "warn")
        chip.setToolTip(connection_tip())
        chip.setFixedHeight(CHIP_HEIGHT)
        chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        chip.setVisible(False)
        return chip

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("heading", True)      # bold via the style sheet, so it follows the font size
        return label

    # ------------------------------------------------------------------ #
    # Collapsible log                                                      #
    # ------------------------------------------------------------------ #

    @property
    def log_collapsed(self) -> bool:
        return self._log_collapsed

    def set_log_collapsed(self, collapsed: bool, notify: bool = False) -> None:
        """Hide or show the log; the heading's arrow points down when collapsed, up when open."""
        self._set_collapsed("log", collapsed, notify)

    # ------------------------------------------------------------------ #
    # Mini view                                                            #
    # ------------------------------------------------------------------ #

    #: Width of the mini view, and how long a resize animation takes (ms; 0 = jump straight there).
    MINI_WIDTH = 340
    animation_ms = 240

    @property
    def mini(self) -> bool:
        return self._mini

    def set_mini(self, mini: bool, notify: bool = False) -> None:
        """Switch between the full window and a small always-handy overlay.

        The mini view keeps only a status row (light, state text, the Needs-sorting
        count, Start / Stop and a way back) and the row being built; the log, the
        saved-row line, the workbook details, Undo and Settings are hidden. It floats
        above other windows (unless turned off) so it can sit over a spreadsheet.

        When the window is on screen the *size* eases between the two layouts and the
        contents change at the end (entering) or the start (leaving) of the move, so
        the window visibly shrinks or grows instead of snapping to the new look.
        """
        window = self._window
        self._finish_animation()                     # settle a previous switch that is still running
        self._mini = mini
        if window is None:
            self._view_mini = mini
            return
        showing = self._view_mini
        if mini != showing:
            if mini and window.isVisible():
                self._full_size = QSize(window.width(), window.height())     # to come back to
            self._apply_stay_on_top()
            animate = window.isVisible() and self.animation_ms > 0
            if not animate:
                self._apply_view(mini)
                target = QSize(self.MINI_WIDTH, self._fit_height()) if mini else self._full_size
                self._resize_to(target.width(), target.height())
            elif mini:
                self._apply_view(True)                                      # measure the mini layout ...
                target = QSize(self.MINI_WIDTH, self._fit_height())
                self._apply_view(False)                                     # ... but keep showing the full one
                self._resize_to(target.width(), target.height(), then=lambda: self._apply_view(True))
            else:
                self._resize_to(self._full_size.width(), self._full_size.height(),
                                then=lambda: self._apply_view(False))
        else:
            self._apply_view(mini)
        if notify:
            self._on_mini_toggled(mini)

    def _finish_animation(self) -> None:
        """If a resize is still running, jump to its end and apply the contents it was heading for."""
        animation = getattr(self, "_animation", None)
        if animation is not None and animation.state() == QPropertyAnimation.State.Running:
            animation.stop()
            self._window.resize(animation.endValue())
            self._apply_view(self._mini)
            self._settle_minimum()

    def _apply_view(self, mini: bool) -> None:
        """Put the contents of the full window or the mini view on screen (the size is separate)."""
        self._view_mini = mini
        self._place_sorting_button(mini)
        self._set_margins(mini)
        self._refresh_visibility()
        self.refresh_icons(self._text_color, self._on_accent, self._accent)

    def set_not_connected(self, not_connected: bool, hint: str | None = None) -> None:
        """Show the "File stream not connected." chip (instead of the sheet name) while there is no spreadsheet."""
        self._not_connected = not_connected
        if hint:
            for chip in (self.connection_chip, self.mini_chip):
                chip.setToolTip(connection_tip(hint))
        self._refresh_visibility()

    def set_native_settings_button(self, native: bool) -> None:
        """The title bar now has its own Settings icon, so the one inside the window is hidden."""
        self._native_settings_button = native
        self._refresh_visibility()

    def set_native_help_button(self, native: bool) -> None:
        """The title bar now has its own Help icon, so the one inside the window is hidden."""
        self._native_help_button = native
        self._refresh_visibility()

    def set_native_undo_button(self, native: bool) -> None:
        """The title bar now has its own Undo icon, so the one inside the window is hidden."""
        self._native_undo_button = native
        self._refresh_visibility()

    def set_native_mini_button(self, native: bool) -> None:
        """The title bar now has its own resize icon, so the one inside the window is hidden."""
        self._native_mini_button = native
        self._refresh_visibility()

    def apply_density(self, spacing: str | None = None) -> None:
        """Apply the spacing setting to this window (the mini view keeps its own tight margins)."""
        if self._window is None:
            return
        apply_spacing(self._window, spacing)
        if self._view_mini:
            self._set_margins(True)
        else:
            self._log_bottom_margin()

    def _set_margins(self, mini: bool) -> None:
        if mini:
            self._layout.setContentsMargins(10, 8, 10, 8)
            self._layout.setSpacing(6)
        else:
            apply_spacing(self._window)
            self._log_bottom_margin()

    def _log_bottom_margin(self) -> None:
        """With the log minimized "Log" is the last thing in the window: only a small margin may follow it."""
        if self._log_collapsed and not self._view_mini and self._window is not None:
            m = self._layout.contentsMargins()
            self._layout.setContentsMargins(m.left(), m.top(), m.right(), LOG_BOTTOM_MARGIN)

    def _place_sorting_button(self, mini: bool) -> None:
        """In the mini view the Needs-sorting count sits in the status row; otherwise on its own row."""
        in_row = self._status_row.indexOf(self.sorting_button) >= 0
        if mini and not in_row:
            self._layout.removeWidget(self.sorting_button)
            self._status_row.insertWidget(self._status_row.indexOf(self.toggle_button) + 1, self.sorting_button)
        elif not mini and in_row:
            self._status_row.removeWidget(self.sorting_button)
            self._layout.insertWidget(self._sorting_index, self.sorting_button)

    # -- animated resizing ------------------------------------------------

    def _height_now(self) -> int:
        """The height the window has, or is heading for if an animation is running."""
        animation = getattr(self, "_animation", None)
        if animation is not None and animation.state() == QPropertyAnimation.State.Running:
            return animation.endValue().height()
        return self._window.height()

    def _resize_to(self, width: int, height: int, then=None) -> None:
        """Resize the window, easing to the new size unless animation is off or it is not on screen.

        *then* (optional) runs once the new size has been reached.
        """
        window = self._window
        previous = getattr(self, "_animation", None)
        if previous is not None:
            previous.stop()
        window.setMinimumSize(0, 0)                  # so it can shrink (or start small) while animating
        if self.animation_ms <= 0 or not window.isVisible():
            window.resize(width, height)
            self._settle_minimum()
            if then is not None:
                then()
            return
        animation = QPropertyAnimation(window, b"size", window)
        animation.setDuration(self.animation_ms)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.setStartValue(window.size())
        animation.setEndValue(QSize(width, height))
        self._animation = animation
        def done() -> None:
            if then is not None:
                then()
            self._settle_minimum()
        animation.finished.connect(done)
        animation.start()

    def _fit_height(self) -> int:
        """The height the window needs right now (the layout is recomputed first, as Qt only does that lazily)."""
        layout = self._window.centralWidget().layout()
        layout.invalidate()
        layout.activate()
        return layout.sizeHint().height()

    def _keep_minimum(self) -> None:
        """Re-apply the content's minimum size when widgets appear or disappear (not while a resize is animating).

        Without this the window could stay smaller than its content after, say, the Term Helper
        button appears, and the sections would draw on top of each other.
        """
        animation = getattr(self, "_animation", None)
        if (self._window is None or not self._window.isVisible()
                or (animation is not None and animation.state() == QPropertyAnimation.State.Running)):
            return
        layout = self._window.centralWidget().layout()
        layout.invalidate()
        layout.activate()
        self._settle_minimum()

    def _settle_minimum(self) -> None:
        """Stop the user dragging the window smaller than its content (applied once a resize is done)."""
        self._window.setMinimumSize(self._window.centralWidget().layout().minimumSize())

    def set_mini_on_top(self, on_top: bool) -> None:
        """Choose whether the mini view floats above other windows."""
        self._mini_on_top = on_top
        self._apply_stay_on_top()

    def _apply_stay_on_top(self) -> None:
        window = self._window
        if window is None:
            return
        want = self._mini and self._mini_on_top
        if set_always_on_top(window, want):
            return                                    # done by the OS, in place
        if bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != want:
            was_visible = window.isVisible()
            window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, want)   # recreates the native window
            self.native_window_recreated = True       # the caller must restyle it
            if was_visible:
                window.show()

    def _refresh_visibility(self) -> None:
        """Show each widget only if both the view (full / mini) and its own state call for it."""
        if self._window is None:
            return
        full = not self._view_mini
        self.state_label.setVisible(True)                                   # "Listening" / "Not Listening" shows in both views
        self.sheet_label.setVisible(full and not self._not_connected)
        self.connection_chip.setVisible(full and self._not_connected)       # inside the workbook picker ...
        self.mini_chip.setVisible(self._view_mini and self._not_connected)  # ... or alone in the mini view
        side = self.workbook_combo.sizeHint().height()
        self.open_file_button.setFixedSize(side, side)                       # a square the height of the picker
        self._chip_placer.place()
        tall = self.sorting_button.fontMetrics().height() * 2 + 4
        self.toggle_button.setMinimumHeight(0 if self._view_mini else tall)
        self.mini_button.setVisible(not self._native_mini_button)           # the title bar has its own
        self.settings_button.setVisible(full and not self._native_settings_button)
        for widget in (self.workbook_row, self.row_heading, self.log_toggle):
            widget.setVisible(full)
        self.last_label.setVisible(full and self._has_last_saved)
        self.help_button.setVisible(full and not self._native_help_button)
        self.undo_button.setVisible(full and not self._native_undo_button)
        self.undo_button.setEnabled(self._undo_count > 0)
        self.log.setVisible(full and not self._log_collapsed)
        self.footer.setVisible(full and bool(self._footer_text))
        self.download_button.setVisible(full and self._offer_download)
        self.sorting_button.setVisible(self._sorting_count > 0)
        self.sorting_title.setVisible(full)                               # just the count pill when mini
        self.row_table.verticalHeader().setDefaultSectionSize(22 if self._view_mini else self._row_height)
        self._fit_row_table(animate=False)
        self.sorting_button.setMinimumHeight(self.toggle_button.sizeHint().height() if self._view_mini else tall)
        log_open = full and not self._log_collapsed
        self._layout.setStretchFactor(self.row_table, 2 if log_open else 1)     # with the log open they share extra height
        self._layout.setStretchFactor(self.log, 1)
        self._keep_minimum()
        self.sorting_button.setToolTip("Term Helper: terms that were heard but not placed yet")

    def _section_toggle(self, tip: str) -> HeadingToggle:
        button = HeadingToggle()
        button.setToolTip(tip)
        button.clicked.connect(lambda: self._set_collapsed("log", not self._log_collapsed, notify=True))
        return button

    def _set_collapsed(self, name: str, collapsed: bool, notify: bool = False) -> None:
        """Collapse or expand the log, and resize the window so no blank gap is left.

        The window gives back the height the log used when it collapses and
        takes the same height again when it reopens.
        """
        body, toggle, title = self.log, self.log_toggle, "Log"
        was = self._applied.get(name, False)      # what is on screen now (not the saved preference)
        window = self._window
        shown = window is not None and window.isVisible()
        height = self._height_now() if window is not None else 0
        spacing = window.centralWidget().layout().spacing() if window is not None else 0
        used = body.height() + max(spacing, 0)
        self._log_collapsed = collapsed
        self._applied[name] = collapsed
        self._refresh_visibility()
        if window is not None and not self._view_mini:
            self._set_margins(False)           # a minimized log leaves only a small margin beneath it
            window.centralWidget().layout().activate()
            if collapsed and not was:
                target = max(self._fit_height(), height - used) if shown else self._fit_height()
                self._resize_to(window.width(), target)
                self._freed[name] = max(height - target, 0) if shown else 0   # what it gave back
            elif was and not collapsed:
                self._resize_to(window.width(), max(height + self._freed.pop(name, 0), self._fit_height()))
        toggle.setText(f"{title}  {'▾' if collapsed else '▴'}")
        toggle.setToolTip(f"Show the {title.lower()}" if collapsed else f"Hide the {title.lower()}")
        if notify:
            self._on_log_toggled(collapsed)

    # ------------------------------------------------------------------ #
    # Window                                                               #
    # ------------------------------------------------------------------ #

    @property
    def widget(self) -> QMainWindow | None:
        """The underlying QMainWindow (None before :meth:`setup`)."""
        return self._window

    def show(self) -> None:
        if self._window is not None:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    # ------------------------------------------------------------------ #
    # State                                                                #
    # ------------------------------------------------------------------ #

    def update_workbook(self, name: str) -> None:
        """Show *name* as the selected workbook (adding it if absent)."""
        index = self.workbook_combo.findText(name)
        if index < 0:
            self.workbook_combo.addItem(name)
            index = self.workbook_combo.count() - 1
        self.workbook_combo.setCurrentIndex(index)
        self.workbook_combo.sync()

    def set_file_mode(self, file_mode: bool) -> None:
        """Say whether Quill is working on a file (not live Excel): enables the way back to Excel."""
        self.use_excel_action.setEnabled(file_mode)

    def update_workbooks(self, names: list[str], current: str = "") -> None:
        """Replace the picker's choices; select *current* if given."""
        self.workbook_combo.blockSignals(True)
        self.workbook_combo.clear()
        self.workbook_combo.addItems(names)
        if current:
            self.update_workbook(current)
        self.workbook_combo.blockSignals(False)
        self.workbook_combo.sync()

    def update_sheet(self, name: str) -> None:
        self.sheet_label.setText(f"Sheet: {name}")

    def _row_table_height(self) -> int:
        """How tall the Current Row box should be: small when empty, growing with its rows up to a cap."""
        rows = self.row_table.rowCount()
        if rows == 0:
            return ROW_EMPTY_HEIGHT
        cap = ROW_MAX_MINI if self._view_mini else ROW_MAX_FULL
        cell = self.row_table.verticalHeader().defaultSectionSize()
        return max(ROW_EMPTY_HEIGHT, min(cap, rows * cell + 2 * self.row_table.frameWidth() + 6))

    def _fit_row_table(self, animate: bool = True) -> None:
        """Give the Current Row box room for its content and, on screen, let the window grow to match.

        That is its *minimum* height: a taller window gives it more. Past the cap it stops asking for
        more and scrolls inside itself.
        """
        new = self._row_table_height()
        old, self._row_target = self._row_target, new
        shortfall = new - self.row_table.height()          # before the minimum is set: that resizes the box at once
        self.row_table.setMinimumHeight(new)
        window = self._window
        if (animate and window is not None and window.isVisible() and new > old and shortfall > 0
                and self.row_table.isVisibleTo(window)):
            self._resize_to(window.width(), self._height_now() + shortfall)

    def update_current_row(self, fields: dict[str, object]) -> None:
        """Show the record being built, one column per line (the box grows with the fields, then scrolls)."""
        self.row_table.setRowCount(len(fields))
        self.row_placeholder.setVisible(not fields)
        for r, (column, value) in enumerate(fields.items()):
            text = value.isoformat() if isinstance(value, dt.date) else str(value)
            for c, content in enumerate((column, text)):
                item = QTableWidgetItem(content)
                if c == 0:
                    item.setForeground(self.row_table.palette().placeholderText())
                self.row_table.setItem(r, c, item)
        self._fit_row_table()

    def set_last_saved(self, row: str, record: dict[str, object] | None = None) -> None:
        """Show the last saved row as one line: ``Row 6 · 12 fields · Type: T-Shirt, …``.

        However much was saved the line stays one line (it is shortened to fit);
        the tooltip lists every field, capped at a screenful.
        """
        parts = [row]
        tip = row
        if record:
            items = [(k, v.isoformat() if isinstance(v, dt.date) else str(v)) for k, v in record.items()]
            count = len(items)
            parts.append(f"{count} field{'s' if count != 1 else ''}")
            parts.append(", ".join(f"{k}: {v}" for k, v in items))
            tip = f"{row}\n{tooltip_lines(items)}"
        self.last_label.setFullText("Last Saved: " + " · ".join(p for p in parts if p), tip)
        self._has_last_saved = True
        self._refresh_visibility()

    def append_log(self, text: str) -> None:
        """Add a timestamped line to the log (and to the log file, for troubleshooting)."""
        logging.getLogger("quill").info(text)
        self.log.appendPlainText(f"{dt.datetime.now():%H:%M:%S}  {text}")

    def set_listening_indicator(self, active: bool) -> None:
        """Update the active light, label and button."""
        self._listening = active
        self.dot.setStyleSheet(f"color: {COLOR_ACTIVE if active else COLOR_IDLE}; font-size: 18px;")
        self.state_label.setText("Listening" if active else "Not Listening")
        self.toggle_button.setToolTip("Stop Listening" if active else "Start Listening")
        self.toggle_button.setAccessibleName("Stop Listening" if active else "Start Listening")
        self.toggle_button.setProperty("accent", active)          # filled with the accent while listening,
        self.toggle_button.setProperty("outline", not active)     # outlined in it while idle (so it reads as clickable)
        style = self.toggle_button.style()
        style.unpolish(self.toggle_button)
        style.polish(self.toggle_button)
        self._draw_toggle_icon()

    def _icon(self, name: str, color: str):
        return make_icon(name, color)

    def _draw_toggle_icon(self) -> None:
        """The play / stop glyph at the right of the Start / Stop button, in the colour that suits its fill."""
        if self._window is None:
            return
        color = self._on_accent if self._listening else self._text_color
        self.toggle_icon.setPixmap(make_icon("stop" if self._listening else "play", color, 16).pixmap(16, 16))

    def refresh_icons(self, text_color: str = "#1F1E1D", on_accent: str = "#FFFFFF",
                      accent: str = "#7A55C2") -> None:
        """Redraw the button icons and the count pill for the current theme colours."""
        self._on_accent, self._text_color, self._accent = on_accent, text_color, accent
        if self._window is None:
            return                      # not built yet; setup() draws them
        self.mini_button.setIcon(make_icon("maximize" if self._view_mini else "minimize", text_color, 16))
        self.mini_button.setToolTip("Back to the Full Window" if self._view_mini else "Mini View")
        self.mini_button.setAccessibleName("Back to the Full Window" if self._view_mini else "Mini View")
        self.badge_label.set_colors(on_accent, accent)
        self.undo_button.setIcon(make_icon("undo", text_color, 18))
        self.help_button.setIcon(make_icon("question", text_color, 18))
        self.settings_button.setIcon(make_icon("settings", text_color, 18))
        self.open_file_button.setIcon(make_icon("folder", text_color, 18))
        self._draw_toggle_icon()

    def set_undo_count(self, count: int) -> None:
        """Show "Undo (n)" while there is a sorting answer to take back."""
        self._undo_count = count
        self._refresh_visibility()

    def set_sorting_count(self, count: int) -> None:
        """Show the accent-coloured "Needs sorting" button, with *count* as a pill, while terms wait."""
        self._sorting_count = count
        self._refresh_visibility()
        self.badge_label.setText(str(count))
        self.sorting_button.setAccessibleName(f"Term Helper ({count})")

    def set_footer(self, text: str, offer_download: bool = False) -> None:
        """Show a status message; optionally reveal the model-download button."""
        self.footer.setText(text)
        self._footer_text, self._offer_download = text, offer_download
        self._refresh_visibility()              # an empty footer would leave a blank strip
        self.download_button.setEnabled(True)

    @property
    def listening(self) -> bool:
        """Last state passed to :meth:`set_listening_indicator`."""
        return self._listening
