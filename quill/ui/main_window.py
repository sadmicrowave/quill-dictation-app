"""Main Quill window — compact, OS-native, dark-mode-aware.

Layout (~340 px wide):
  status row:  [● Listening]  [Start/Stop]  [Settings…]
  workbook row: [workbook picker]
  Current row (the fields being built, one line per column)
  Last saved row
  Scrolling action log
  Footer message (model / connection status)

The window only displays state and reports user intent through the callbacks
passed to the constructor; it holds no dictation logic.
"""
from __future__ import annotations

import datetime as dt
import html
import logging
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFontMetrics, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from quill.stream import WordMatch
from quill.ui.chrome import set_always_on_top
from quill.ui.icons import make_icon
from quill.ui.main_widgets import (
    CHIP_HEIGHT,
    PLACEHOLDER_MARGINS,
    ROW_EMPTY_HEIGHT,
    STREAM_MIN_HEIGHT,
    ResizeWatcher,
    RowTable,
    StreamBox,
)
from quill.ui.theme import install_backdrop, apply_spacing
from quill.ui.widgets import (
    ElidedLabel,
    HeadingToggle,
    ListenButton,
    Pill,
    connection_tip,
    tooltip_lines,
)

#: Active-light colours (the same hues are used by the tray icon).
COLOR_ACTIVE = "#34c759"

#: The help page the window's ? icon opens.
HELP_TOPIC = "welcome"

#: The chip that replaces the sheet name while no spreadsheet is connected, and its tooltip.
NOT_CONNECTED_TEXT = "File stream not connected"
NOT_CONNECTED_HINT = (
    "No spreadsheet is connected, so there is nothing to read lists from or write rows to.\n"
    "Quill works through a workbook open in your spreadsheet program (it attaches automatically within a few seconds of "
    "the workbook opening) or through an .xlsx or .csv file chosen with File > Open Spreadsheet File.\n"
    "Open a workbook or choose a file; listening can start once the connection is made."
)

#: Most the Current Row box grows to before it scrolls inside itself (full view, mini view).
ROW_MAX_FULL = 150
ROW_MAX_MINI = 66

#: Space left below the "Log" heading when the log is minimized, in pixels.
LOG_BOTTOM_MARGIN = 7
SIZE_SETTLE_MS = 400        # how long the window must stay still before its size is reported
MIN_REMEMBERED = (300, 300)  # a remembered size below this is ignored
MIN_WINDOW = (453, 383)      # the full window never gets smaller than this, and opens at it the first time
LOG_OPEN_HEIGHT = 120       # height of the log while it is open

#: Lines kept in the log before the oldest are dropped.
MAX_LOG_LINES = 500
LOG_TIME_GAP = 12           # px between the time and the message in the log

#: How each kind of log message is shown: a label after the time (none for plain information) and a colour.
LOG_LEVELS = {"info": (None, None), "warning": ("Warning", "#D98E04"), "error": ("Error", "#E5484D")}


class MainWindow:
    """The compact status window.

    Args:
        on_toggle: Called when the user presses Start/Stop; receives the
            *desired* listening state.
        on_settings: Called when the user opens Settings.
        on_sorting: Called when the user opens the Needs-sorting list.
        on_next_row: Called when the user presses the next-row arrow (the same as saying "next row").
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
        on_sorting: Callable[[], None] | None = None,
        on_undo: Callable[[], None] | None = None,
        on_next_row: Callable[[], None] | None = None,
        on_log_toggled: Callable[[bool], None] | None = None,
        log_collapsed: bool = False,
        on_mini_toggled: Callable[[bool], None] | None = None,
        on_open_file: Callable[[], None] | None = None,
        on_use_excel: Callable[[], None] | None = None,
        on_help: Callable[[str], None] | None = None,
        on_resized: Callable[[int, int], None] | None = None,
        on_mini_resized: Callable[[int, int], None] | None = None,
        on_field_removed: Callable[[str], None] | None = None,
        on_file_state: Callable[[bool, str, str], None] | None = None,
        mini: bool = False,
        mini_on_top: bool = True,
    ) -> None:
        self._on_toggle = on_toggle or (lambda active: None)
        self._on_settings = on_settings or (lambda: None)
        self._on_file_state = on_file_state or (lambda has, name, sheet: None)
        self._on_sorting = on_sorting or (lambda: None)
        self._on_undo = on_undo or (lambda: None)
        self._on_next_row = on_next_row or (lambda: None)
        self._on_log_toggled = on_log_toggled or (lambda collapsed: None)
        self._log_collapsed = log_collapsed
        self._on_mini_toggled = on_mini_toggled or (lambda mini: None)
        self._on_open_file = on_open_file or (lambda: None)
        self._on_use_excel = on_use_excel or (lambda: None)
        self._on_help = on_help or (lambda topic: None)
        self._on_resized = on_resized or (lambda width, height: None)
        self._native_help_button = False
        self._mini = mini                          # the state asked for (may still be animating there)
        self._view_mini = False                    # what is actually on screen (set by _apply_view)
        self._native_mini_button = False           # True once the title bar has its own resize icon
        self.native_window_recreated = False       # set if a window flag had to be changed the old way
        self._mini_on_top = mini_on_top
        self._full_size = QSize(*MIN_WINDOW)     # the size to return to when leaving the mini view
        self._undo_count = 0
        self._sorting_count = 0
        self._not_connected = False
        self._native_settings_button = False
        self._native_file_button = False
        self._workbook_name = ""
        self._sheet_name = ""
        self._native_undo_button = False
        self._text_color = "#1F1E1D"
        self._accent = "#7A55C2"
        self._applied: dict[str, bool] = {}     # which sections are collapsed on screen
        self._log_grew = 0                   # window height added to make room for the open log (given back on close)
        self._log_animation: QVariantAnimation | None = None
        self._log_busy = False               # the log is sliding open or shut
        self._density = ""                   # the spacing mode last given to apply_density ("" = the application's)
        self._mini_detail = False            # the mini view is tall enough to show the stream and the row
        self._mini_base = 0                  # the mini view's own (compact) height
        self._mini_size: QSize | None = None  # the size the user left the mini view at
        self._on_mini_resized = on_mini_resized or (lambda width, height: None)
        self._on_field_removed = on_field_removed or (lambda column: None)
        self._row_fields: dict[str, object] = {}   # what the row grid shows now
        self._stream_words: list[tuple[str, WordMatch]] = []     # what was heard (final), with what Quill made of each word
        self._stream_partial: list[tuple[str, WordMatch]] = []   # the phrase still being spoken
        self._stream_done = False            # the row ended: the next words start a fresh stream
        self._classify_words = lambda words: [WordMatch(False) for _ in words]
        self._sorting_animation: QVariantAnimation | None = None
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
        # Per-pixel transparency (opacity below 100, blur) needs this *before* anything creates the native
        # window; set later it is ignored and the window stays solid.
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        window.setWindowTitle("Quill")
        window.resize(*MIN_WINDOW)
        self._size_timer = QTimer(window)                       # tells the app the window's size once resizing stops
        self._size_timer.setSingleShot(True)
        self._size_timer.setInterval(SIZE_SETTLE_MS)
        self._size_timer.timeout.connect(self.report_size)
        window.installEventFilter(ResizeWatcher(window, self._size_timer, self._sync_mini_detail))
        central = QWidget()
        central.setObjectName("mainRoot")

        install_backdrop(central)                              # paints its own (see-through-able) background
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.root = central
        layout = QVBoxLayout(central)
        # The window may be smaller than its content while it animates between sizes, so the layout
        # must not force the window's minimum size (it is set once an animation has finished).
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        central.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        # --- status row
        # One button is the whole control (see ListenButton). Pressing it starts or stops listening; it fills with
        # the accent colour while listening.
        self.toggle_button = ListenButton()           # play / stop icon, centred text, countdown, sound lines
        self.toggle_icon = self.toggle_button.icon_label
        self.countdown_label = self.toggle_button.countdown_label       # "Stops in 7s" (hidden when not running)
        self.wave = self.toggle_button.wave
        self._countdown_seconds: int | None = None
        self.toggle_button.clicked.connect(lambda: self._on_toggle(not self._listening))
        self.settings_button = QPushButton()            # icon only; refresh_icons() draws it
        self.settings_button.setProperty("iconOnly", True)
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(lambda: self._on_settings())
        self.error_button = QToolButton()               # the mini view's red "!": an error happened (the log is hidden there)
        self.error_button.setProperty("errorMark", True)
        self.error_button.setText("!")
        self.error_button.setAccessibleName("Show the Error")
        self.error_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.error_button.setVisible(False)
        self.error_button.clicked.connect(lambda: self.set_mini(False, notify=True))
        self._mini_error = ""
        self.mini_button = QToolButton()                # just an icon (no box), like the Log heading
        self.mini_button.setProperty("flatIcon", True)
        self.mini_button.setAutoRaise(True)
        self.mini_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mini_button.clicked.connect(lambda: self.set_mini(not self._mini, notify=True))
        row = status_row = QHBoxLayout()
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
        self.next_button = QPushButton()                 # small next arrow beside Start: save this row and start the next
        self.next_button.setProperty("iconOnly", True)
        self.next_button.setToolTip("Next Row")
        self.next_button.setAccessibleName("Next Row")
        self.next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_button.setVisible(False)
        self.next_button.clicked.connect(lambda: self._on_next_row())
        row.addWidget(self.toggle_button, 1)
        row.addWidget(self.next_button)
        row.addWidget(self.help_button)
        row.addWidget(self.undo_button)
        row.addWidget(self.settings_button)
        row.addWidget(self.error_button)
        row.addWidget(self.mini_button)
        layout.addLayout(row)
        self._layout, self._status_row = layout, row

        # --- file
        # No file picker in the window: the folder icon (title bar on macOS, status row elsewhere) opens one.
        # While no spreadsheet is connected a technical warning chip says so (the mini view has its own).
        self.connection_chip = self._make_chip(None)          # sits inside the Start button, right of the play icon
        self.mini_chip = self.connection_chip                 # (the same one in both views)
        self.toggle_button.set_chip(self.connection_chip)
        self.open_file_button = QPushButton()                   # just a folder icon; refresh_icons() draws it
        self.open_file_button.setProperty("iconOnly", True)
        self.open_file_button.setAccessibleName("Open Spreadsheet File")
        self.open_file_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_file_button.clicked.connect(lambda: self._on_open_file())
        status_row.insertWidget(status_row.indexOf(self.settings_button), self.open_file_button)

        # --- current row
        # (Not collapsible: the row being built is the point of every spoken turn, so it is always in view.)
        # (No title: each box says what it is for in its own hint text.)
        self.stream = StreamBox(self._stream_height_changed)
        layout.addWidget(self.stream)
        self.row_table = RowTable(0, 2)
        self.row_table.horizontalHeader().setVisible(False)
        self.row_table.verticalHeader().setVisible(False)
        self.row_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.row_table.row_remove_requested.connect(self._remove_row_requested)
        self._row_height = self.row_table.verticalHeader().defaultSectionSize()
        self.row_table.setMinimumHeight(ROW_EMPTY_HEIGHT)           # starts small; grows with the fields heard
        self._row_target = ROW_EMPTY_HEIGHT
        # a hint shown while no fields have been heard yet
        self.row_placeholder = QLabel("Words you say that match to columns in the selected file appear here as they are heard", self.row_table.viewport())
        self.row_placeholder.setProperty("placeholder", True)        # same look as the Voice Stream box's placeholder
        self.row_placeholder.setWordWrap(True)
        self.row_placeholder.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.row_placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.row_table.viewport().setProperty("keepMargins", True)     # the spacing setting must not resize this layout's margins
        holder = QVBoxLayout(self.row_table.viewport())
        holder.setContentsMargins(*PLACEHOLDER_MARGINS)   # the same place the Voice Stream box's hint starts
        holder.addWidget(self.row_placeholder)
        layout.addWidget(self.row_table, 1)        # takes the height when the window is resized: it is what is being watched
        self._has_last_saved = False                       # the line shows only once a row has been saved
        self.last_label = ElidedLabel("")                  # one line however much was saved
        self.last_label.setProperty("note", True)          # smaller italic supporting text
        self.last_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

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

        # --- log (last). The Current Row box takes extra height when the window grows (and shares it with
        # the log while that is open), so no gaps open between sections and "Log" stays at the bottom.
        self.log_toggle = self._section_toggle("Show or hide the log")
        footer_row = QHBoxLayout()                          # "Log" on the left, the last saved row on the right
        footer_row.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        footer_row.addWidget(self.last_label, 1)
        layout.addLayout(footer_row)
        self.log = QTextEdit()                # (not the plain-text kind: it can hang a long line's wrap under the message)
        self.log.setReadOnly(True)
        self.log.document().setUndoRedoEnabled(False)
        layout.addWidget(self.log)
        layout.addStretch(0)         # soaks up spare height in the compact mini view (and while it grows back), so nothing drifts down
        self._spacer_index = layout.count() - 1

        # File menu (the global menu bar on macOS): Open Spreadsheet File, and back to live Excel.
        file_menu = window.menuBar().addMenu("File")
        self.open_file_action = file_menu.addAction("Open Spreadsheet File…", lambda: self._on_open_file())
        self.open_file_action.setShortcut("Ctrl+O")
        self.use_excel_action = file_menu.addAction("Use the Open Workbook", lambda: self._on_use_excel())
        self.use_excel_action.setEnabled(False)
        window.setCentralWidget(central)
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
        """True while the log is hidden."""
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
        """True when the mini view is wanted (it may still be animating there)."""
        return self._mini

    def set_mini(self, mini: bool, notify: bool = False) -> None:
        """Switch between the full window and a small always-handy overlay.

        The mini view keeps only a status row (light, sound lines, the Needs-sorting
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
                if mini:
                    target = self._mini_target()
                    self._apply_view(True)
                else:
                    self._apply_view(False)
                    target = self._full_size
                self._resize_to(target.width(), target.height())
            elif mini:
                target = self._mini_target()                                # measures the compact mini layout
                self._apply_view(False)                                     # ... but keep showing the full one
                self._resize_to(target.width(), target.height(), then=lambda: self._apply_view(True))
            else:
                self._resize_to(self._full_size.width(), self._full_size.height(),
                                then=lambda: self._apply_view(False))
        else:
            self._apply_view(mini)
        if notify:
            self._on_mini_toggled(mini)

    def _mini_detail_need(self) -> int:
        """The mini view's height from which there is room for the stream and the row."""
        gap = max(self._layout.spacing(), 0)
        return self._mini_base + STREAM_MIN_HEIGHT + ROW_EMPTY_HEIGHT + 2 * gap

    def _mini_target(self) -> QSize:
        """The size to take on entering the mini view: where the user left it, else the compact default.

        Also measures the compact height (``_mini_base``) and decides whether the target shows the details.
        """
        self._view_mini, self._mini_detail = True, False
        self._place_sorting_button(True)
        self._set_margins(True)
        self._refresh_visibility()
        self._mini_base = self._fit_height()
        remembered = self._mini_size
        target = QSize(max(remembered.width(), 200), max(remembered.height(), self._mini_base)) \
            if remembered is not None else QSize(self.MINI_WIDTH, self._mini_base)
        self._mini_detail = target.height() >= self._mini_detail_need()
        self._view_mini = False                                           # the caller applies the view
        return target

    def _sync_mini_detail(self) -> None:
        """While the mini view is on screen, show the stream and row only when the window is tall enough."""
        window = self._window
        animation = getattr(self, "_animation", None)
        if (window is None or not self._view_mini or not self._mini_base
                or (animation is not None and animation.state() == QPropertyAnimation.State.Running)):
            return
        want = window.height() >= self._mini_detail_need()
        if want != self._mini_detail:
            self._mini_detail = want
            self._refresh_visibility()

    def restore_mini_size(self, width: int, height: int) -> None:
        """Use a remembered size for the mini view the next time it is entered."""
        if width >= 200 and height >= 60:
            self._mini_size = QSize(width, height)
            if self._window is not None and self._mini and self._view_mini:
                self._window.resize(width, height)

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
        if not mini:
            self._mini_error = ""                       # back in the full window the Log is open and shows it
        self._place_sorting_button(mini)
        self._set_margins(mini)
        self._refresh_visibility()
        self.refresh_icons(self._text_color, self._on_accent, self._accent)

    def set_not_connected(self, not_connected: bool, hint: str | None = None) -> None:
        """Show the "File stream not connected." chip (instead of the sheet name) while there is no spreadsheet."""
        self._not_connected = not_connected
        if hint:
            self.connection_chip.setToolTip(connection_tip(hint))
        self._refresh_visibility()

    def set_native_file_button(self, native: bool) -> None:
        """The title bar now has its own folder icon, so the one inside the window is hidden."""
        self._native_file_button = native
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
        self._density = spacing or ""
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
        if (self._window is None or not self._window.isVisible() or self._log_busy
                or (animation is not None and animation.state() == QPropertyAnimation.State.Running)):
            return
        layout = self._window.centralWidget().layout()
        layout.invalidate()
        layout.activate()
        self._settle_minimum()

    def _settle_minimum(self) -> None:
        """Stop the user dragging the window smaller than its content (applied once a resize is done)."""
        if self._log_busy:                             # the log is still sliding; its final size is not known yet
            return
        if self._view_mini and self._mini_base:        # the mini view may shrink back to its compact size
            self._window.setMinimumSize(self._window.centralWidget().layout().minimumSize().width(), self._mini_base)
            return
        content = self._window.centralWidget().layout().minimumSize()
        self._window.setMinimumSize(max(content.width(), MIN_WINDOW[0]), max(content.height(), MIN_WINDOW[1]))

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
        self._render_countdown()
        self.connection_chip.setVisible(self._not_connected)
        self.toggle_button.set_notice(self._not_connected, self.connection_chip.toolTip())
        self.open_file_button.setVisible(full and not self._native_file_button)
        self.next_button.setVisible(self._listening)                          # only while a turn is going on
        self.error_button.setVisible(self._view_mini and bool(self._mini_error))
        tall = self.sorting_button.fontMetrics().height() * 2 + 4
        self.toggle_button.setMinimumHeight(0 if self._view_mini else tall)
        self.toggle_button.set_compact(self._view_mini)
        self.mini_button.setVisible(not self._native_mini_button)           # the title bar has its own
        self.settings_button.setVisible(full and not self._native_settings_button)
        self.log_toggle.setVisible(full)
        detail = full or self._mini_detail                                   # the mini view shows them only when tall
        self.stream.setVisible(detail)
        self.row_table.setVisible(detail)
        self.last_label.setVisible(full and self._has_last_saved)
        self.help_button.setVisible(full and not self._native_help_button)
        self.undo_button.setVisible(full and not self._native_undo_button)
        self.undo_button.setEnabled(self._undo_count > 0)
        self.log.setVisible(full and (not self._log_collapsed or self._log_closing()))
        if self.log.isVisibleTo(self._window) and not self._log_busy:
            self.log.setFixedHeight(LOG_OPEN_HEIGHT)
        self.sorting_button.setVisible(self._sorting_count > 0)
        self.sorting_title.setVisible(full)                               # just the count pill when mini
        self.row_table.verticalHeader().setDefaultSectionSize(22 if self._view_mini else self._row_height)
        self._fit_row_table(animate=False)
        self.sorting_button.setMinimumHeight(self.toggle_button.sizeHint().height() if self._view_mini else tall)
        self._layout.setStretch(self._spacer_index, 1 if (self._view_mini and not detail) else 0)
        self._layout.setStretchFactor(self.row_table, 1)       # extra height always goes to the Current Row box;
        self._layout.setStretchFactor(self.log, 0)             # the log keeps its own height
        self._keep_minimum()
        self.sorting_button.setToolTip("Term Helper: terms that were heard but not placed yet")

    def _section_toggle(self, tip: str) -> HeadingToggle:
        button = HeadingToggle()
        button.setToolTip(tip)
        button.clicked.connect(lambda: self._set_collapsed("log", not self._log_collapsed, notify=True))
        return button

    # ------------------------------------------------------------------ #
    # Remembering the size                                                 #
    # ------------------------------------------------------------------ #

    def restore_size(self, width: int, height: int) -> bool:
        """Use a remembered size for the full window (kept on screen; ignored if it is implausibly small).

        Returns:
            True if the size was used.
        """
        if self._window is None or width < MIN_REMEMBERED[0] or height < MIN_REMEMBERED[1]:
            return False
        screen = self._window.screen()
        if screen is not None:
            room = screen.availableGeometry()
            width, height = min(width, room.width()), min(height, room.height())
        width, height = max(width, MIN_WINDOW[0]), max(height, MIN_WINDOW[1])
        self._full_size = QSize(width, height)
        if not self._mini:
            self._window.resize(width, height)
        return True

    def report_size(self) -> None:
        """Tell the app the full window's size (not while it is the mini view or in the middle of a resize)."""
        window = self._window
        animation = getattr(self, "_animation", None)
        if (window is None or self._log_busy or self._mini != self._view_mini
                or (animation is not None and animation.state() == QPropertyAnimation.State.Running)):
            return
        if self._view_mini:                                    # the mini view keeps its own size
            self._mini_size = QSize(window.width(), window.height())
            self._on_mini_resized(window.width(), window.height())
            return
        self._full_size = QSize(window.width(), window.height())
        self._on_resized(window.width(), window.height())

    def _log_opening(self) -> bool:
        return self._log_animation is not None and self._log_animation.property("opening") is True \
            and self._log_animation.state() == QVariantAnimation.State.Running

    def _log_closing(self) -> bool:
        return self._log_animation is not None and self._log_animation.property("opening") is False \
            and self._log_animation.state() == QVariantAnimation.State.Running

    def _finish_log_animation(self) -> None:
        """If the log is still sliding open or shut, jump to the end of it."""
        animation = self._log_animation
        if animation is not None and animation.state() == QVariantAnimation.State.Running:
            animation.setCurrentTime(animation.duration())
            animation.stop()
            animation.finished.emit()

    def _set_collapsed(self, name: str, collapsed: bool, notify: bool = False) -> None:
        """Show or hide the log.

        Opening takes the room from the Current Row box (the log slides up from the bottom and the
        window keeps its size). Only when that box has no height to spare does the window grow, by
        just the shortfall; closing gives the same height back (the box grows again, or the window
        shrinks again if it had grown).
        """
        was = self._applied.get(name, False)      # what is on screen now (not the saved preference)
        window = self._window
        self._finish_log_animation()
        self._log_busy = False
        shown = window is not None and window.isVisible() and not self._view_mini
        self._log_collapsed = collapsed
        self._applied[name] = collapsed
        if window is None or self._view_mini or collapsed == was:
            self._refresh_visibility()
        elif not shown:                                     # not on screen: just fit the window to the content
            self._refresh_visibility()
            self._set_margins(False)
            window.centralWidget().layout().activate()
            self._resize_to(window.width(), self._fit_height())
        elif collapsed:
            self._close_log(window)
        else:
            self._open_log(window)
        self.log_toggle.setText(f"Log  {'▾' if collapsed else '▴'}")
        self.log_toggle.setToolTip("Show the log" if collapsed else "Hide the log")
        if notify:
            self._on_log_toggled(collapsed)

    def _slide_log(self, start: int, end: int, opening: bool, then) -> None:
        """Move the log's height from *start* to *end* (instantly when animation is off)."""
        if self.animation_ms <= 0:
            self.log.setFixedHeight(end)
            then()
            return
        animation = QVariantAnimation(self._window)
        animation.setDuration(self.animation_ms)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setProperty("opening", opening)
        animation.valueChanged.connect(lambda value: self.log.setFixedHeight(int(value)))
        animation.finished.connect(then)
        self._log_animation = animation
        self.log.setFixedHeight(start)
        animation.start()

    def _open_log(self, window) -> None:
        layout = window.centralWidget().layout()
        spacing = max(layout.spacing(), 0)
        self._log_busy = True
        slack = max(self.row_table.height() - self.row_table.minimumHeight(), 0)    # what the box can give up
        grow = max(LOG_OPEN_HEIGHT + spacing - slack, 0)
        self._log_grew = grow
        height, width = self._height_now(), window.width()
        self.log.setFixedHeight(0)
        self._set_margins(False)
        self._refresh_visibility()
        self.log.setVisible(True)
        if grow:
            self._resize_to(width, height + grow)
        self._slide_log(0, LOG_OPEN_HEIGHT, True, self._log_settled)

    def _close_log(self, window) -> None:
        grew, height, width = self._log_grew, self._height_now(), window.width()
        self._log_busy = True
        self._log_grew = 0
        self._set_margins(False)                       # the small margin that follows a minimized log
        if grew:
            self.log.setVisible(False)
            floor = self._fit_height()
            self.log.setVisible(True)
            self._resize_to(width, max(floor, height - grew))
        self._slide_log(self.log.height(), 0, False, self._log_hidden)

    def _log_settled(self) -> None:
        self._log_busy = False
        self._refresh_visibility()
        self._keep_minimum()

    def _log_hidden(self) -> None:
        self._log_busy = False
        self._refresh_visibility()
        self._set_margins(False)           # a minimized log leaves only a small margin beneath it
        self._keep_minimum()

    # ------------------------------------------------------------------ #
    # Window                                                               #
    # ------------------------------------------------------------------ #

    @property
    def widget(self) -> QMainWindow | None:
        """The underlying QMainWindow (None before :meth:`setup`)."""
        return self._window

    def show(self) -> None:
        """Show the window."""
        if self._window is not None:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()
            self._keep_minimum()                      # from the first moment the window cannot be dragged smaller

    # ------------------------------------------------------------------ #
    # State                                                                #
    # ------------------------------------------------------------------ #

    @property
    def workbook_name(self) -> str:
        """The name of the file being filled in ('' while none is connected)."""
        return self._workbook_name

    @property
    def sheet_name(self) -> str:
        """The open sheet's name ('' if unknown)."""
        return self._sheet_name

    def set_active_sheet(self, name: str) -> None:
        """Note which sheet is open: the folder icon's hover text names it."""
        if name != self._sheet_name:
            self._sheet_name = name
            self._show_file_state()

    def update_workbook(self, name: str) -> None:
        """Note *name* as the file in use: the folder icon turns solid and its tooltip names the file."""
        self._workbook_name = name
        self._show_file_state()

    def set_file_mode(self, file_mode: bool) -> None:
        """Say whether Quill is working on a file (not the open workbook): enables the way back to it."""
        self.use_excel_action.setEnabled(file_mode)

    def update_workbooks(self, names: list[str], current: str = "") -> None:
        """The workbooks that can be targeted changed; *current* (if given) is the one in use."""
        self._workbook_name = current
        if not current:
            self._sheet_name = ""
        self._show_file_state()

    def _show_file_state(self) -> None:
        """Draw the folder icon: muted and closed with no file, solid and open with one."""
        if self._window is None:
            return
        has = bool(self._workbook_name)
        sheet = f"\nSheet: {self._sheet_name}" if has and self._sheet_name else ""
        tip = (f"{self._workbook_name}{sheet}" if has
               else "Open Spreadsheet File\nWork on an .xlsx or .csv file directly (no spreadsheet program needed)")
        self.open_file_button.setToolTip(tip)
        color = self._text_color
        if not has:
            muted = QColor(color)
            muted.setAlpha(110)
            color = muted.name(QColor.NameFormat.HexArgb)
        self.open_file_button.setIcon(make_icon("folder-open" if has else "folder", color, 18))
        self._on_file_state(has, self._workbook_name, self._sheet_name)

    def _row_table_height(self) -> int:
        """How tall the Current Row box should be: small when empty, growing with its rows up to a cap."""
        rows = self.row_table.rowCount()
        if rows == 0:
            return ROW_EMPTY_HEIGHT
        cap = ROW_MAX_MINI if self._view_mini else ROW_MAX_FULL
        self._size_rows()
        total = sum(self.row_table.rowHeight(r) for r in range(rows))
        return max(ROW_EMPTY_HEIGHT, min(cap, total + 2 * self.row_table.frameWidth() + 6))

    def _size_rows(self) -> None:
        """A line is as tall as the values in its cell: a column given several values shows one per line."""
        table = self.row_table
        cell = table.verticalHeader().defaultSectionSize()
        for r in range(table.rowCount()):
            item = table.item(r, 1)
            lines = item.text().count("\n") + 1 if item is not None else 1
            height = cell + (lines - 1) * max(cell - 8, 14)
            if table.rowHeight(r) != height:
                table.setRowHeight(r, height)

    def _switching_view(self) -> bool:
        """True while the window is easing between the full and mini views: nothing else may resize it then
        (it would cut the animation short, and the switch would never finish)."""
        return self._mini != self._view_mini

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
                and self.row_table.isVisibleTo(window) and not self._switching_view()):
            self._resize_to(window.width(), self._height_now() + shortfall)

    def update_current_row(self, fields: dict[str, object]) -> None:
        """Show the record being built, one column per line (the box grows with the fields, then scrolls)."""
        self._row_fields = dict(fields)
        self.row_table.setRowCount(len(fields))
        self.row_placeholder.setVisible(not fields)
        for r, (column, value) in enumerate(fields.items()):
            text = value.isoformat() if isinstance(value, dt.date) else str(value)
            for c, content in enumerate((column, text)):
                item = QTableWidgetItem(content)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)            # not selectable
                if c == 0:
                    item.setForeground(self.row_table.palette().placeholderText())
                self.row_table.setItem(r, c, item)
        self._size_rows()
        self._fit_row_table()

    def _remove_row_requested(self, column: str) -> None:
        """The user clicked a line's delete button: take it out of the grid, un-colour its words, tell the app."""
        self._row_fields.pop(column, None)
        self.update_current_row(self._row_fields)
        self.unmatch_stream_column(column)
        self._on_field_removed(column)

    # ------------------------------------------------------------------ #
    # Voice Stream                                                         #
    # ------------------------------------------------------------------ #

    def set_stream_classifier(self, classify) -> None:
        """Tell the stream how to judge heard words: ``classify(words) -> [WordMatch, ...]`` (see :mod:`quill.stream`)."""
        self._classify_words = classify

    def add_stream_text(self, text: str) -> None:
        """A phrase was finished: keep it in the stream (the words in the phrase still being spoken are replaced)."""
        content = self._content_words(text.split())
        self._stream_partial = []
        if content:                                    # a phrase that was only a command leaves the stream as it was
            self._begin_stream()
            self._stream_words += content
        self._render_stream()

    def set_stream_partial(self, text: str) -> None:
        """The words of the phrase still being spoken, as far as they are recognised."""
        content = self._content_words(text.split())
        if content:
            self._begin_stream()
        self._stream_partial = content
        self._render_stream()

    def _content_words(self, words: list[str]) -> list[tuple[str, WordMatch]]:
        """The words with what Quill made of each, leaving out spoken commands ("next row" is not content)."""
        return [(word, match) for word, match in zip(words, self._classify_words(words)) if not match.command]

    def unmatch_stream_column(self, column: str) -> None:
        """The user removed the row for *column*: the words that filled it lose their pill (and are muted again)."""
        self._stream_words = [(word, WordMatch(False) if match.column == column else match)
                              for word, match in self._stream_words]
        self._render_stream()

    def end_stream(self) -> None:
        """The row ended (saved, discarded or listening stopped): the next words start a new stream."""
        self._stream_done = True

    def sorting_finished(self) -> None:
        """The Term Helper closed with everything answered: bring this window back and, if the row it was
        about is over, clear the heard words so the next row starts clean."""
        if self._stream_done:
            self.clear_stream()
        self.show()

    def clear_stream(self) -> None:
        """Empty the Voice Stream."""
        self._stream_words, self._stream_partial, self._stream_done = [], [], False
        self._render_stream()

    def stream_text(self) -> str:
        """Everything in the stream, as plain text."""
        return " ".join(word for word, _ in self._stream_words + self._stream_partial)

    def _begin_stream(self) -> None:
        if self._stream_done:
            self._stream_words, self._stream_partial, self._stream_done = [], [], False

    def _render_stream(self) -> None:
        """Draw the stream in italics.

        Understood words are pills in the theme colour. Words still being spoken start in the normal text
        colour; once a phrase is final, the words that were not understood are muted.
        """
        pill = f"background-color:{self._accent}; color:{self._on_accent}"
        muted = self.stream.palette().placeholderText().color().name()

        def draw(items, unknown_color: str) -> str:
            return " ".join(
                f'<span style="{pill}">&nbsp;{html.escape(word)}&nbsp;</span>' if match.known
                else f'<span style="color:{unknown_color}">{html.escape(word)}</span>'
                for word, match in items)

        parts = [p for p in (draw(self._stream_words, muted), draw(self._stream_partial, self._text_color)) if p]
        self.stream.setHtml(f'<div style="font-style:italic">{" ".join(parts)}</div>' if parts else "")
        self.stream.fit()
        bar = self.stream.verticalScrollBar()
        bar.setValue(bar.maximum())                    # keep the newest words in view once it scrolls

    def _stream_height_changed(self, old: int, new: int) -> None:
        """The stream grew or shrank: take the room from the Current Row box, growing the window only if it has none."""
        window = self._window
        if window is None or new <= old or not window.isVisible() or self._view_mini or self._switching_view():
            self._keep_minimum()
            return
        slack = max(self.row_table.height() - self.row_table.minimumHeight(), 0)
        grow = max(new - old - slack, 0)
        if grow:
            self._resize_to(window.width(), self._height_now() + grow)
        else:
            self._keep_minimum()

    def set_last_saved(self, row: str, record: dict[str, object] | None = None) -> None:
        """Show the last saved row as one line: ``Row 6 · 12 fields · Type: T-Shirt, …``.

        However much was saved the line stays one line (it is shortened to fit);
        the tooltip lists every field, capped at a screenful.
        """
        parts = [row] if row and row != "Row saved" else []        # (the label already says "Last Saved")
        tip = row
        if record:
            items = [(k, (v.isoformat() if isinstance(v, dt.date) else str(v)).replace("\n", ", ")) for k, v in record.items()]
            count = len(items)
            parts.append(f"{count} field{'s' if count != 1 else ''}")
            parts.append(", ".join(f"{k}: {v}" for k, v in items))
            tip = f"{row}\n{tooltip_lines(items)}"
        self.last_label.setFullText("Last Saved: " + " · ".join(p for p in parts if p), tip)
        self._has_last_saved = True
        self._refresh_visibility()

    def append_log(self, text: str, level: str = "info") -> None:
        """Add a timestamped line to the log (and to the log file, for troubleshooting).

        *level* is ``"info"``, ``"warning"`` or ``"error"``. Warnings and errors say so after the time and are
        coloured (every error the same red); an error also opens the log if it is collapsed, so it is seen.
        """
        label, color = LOG_LEVELS.get(level, LOG_LEVELS["info"])
        logging.getLogger("quill").log({"error": logging.ERROR, "warning": logging.WARNING}.get(level, logging.INFO), text)
        stamp = f"{dt.datetime.now():%H:%M:%S}"
        line = f"{stamp}\t{label + '  ' if label else ''}{text}"
        fmt = QTextCharFormat()                                   # a plain format: the colour never carries to the next line
        if color:
            fmt.setForeground(QColor(color))
        # Two columns without borders: the time, then the message. A long message wraps back to where the
        # message starts (a hanging indent), never under the time.
        column = QFontMetrics(self.log.font()).horizontalAdvance("00:00:00") + LOG_TIME_GAP
        block = QTextBlockFormat()
        block.setLeftMargin(column)
        block.setTextIndent(-column)
        block.setTabPositions([QTextOption.Tab(column, QTextOption.TabType.LeftTab)])
        cursor = QTextCursor(self.log.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.log.document().isEmpty():
            cursor.setBlockFormat(block)
        else:
            cursor.insertBlock(block, QTextCharFormat())
        cursor.insertText(line, fmt)
        while self.log.document().blockCount() > MAX_LOG_LINES:      # keep the newest lines only
            oldest = QTextCursor(self.log.document().begin())
            oldest.select(QTextCursor.SelectionType.BlockUnderCursor)
            oldest.removeSelectedText()
            oldest.deleteChar()
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        if level == "error":
            self._mini_error = text                                 # the mini view shows a red "!" until it is seen
            self.error_button.setToolTip(f"{text}\nClick to go back to the full window and the Log")
            self._refresh_visibility()
            if self._log_collapsed:
                self._set_collapsed("log", False)

    def clear_mini_error(self) -> None:
        """The error has been seen (or a row saved since): take the mini view's red "!" away."""
        if self._mini_error:
            self._mini_error = ""
            self._refresh_visibility()

    def set_listening_indicator(self, active: bool) -> None:
        """Update the button (icon, text, colours, sound lines)."""
        self._listening = active
        self.toggle_button.set_active(active)
        self._refresh_visibility()

    def set_quiet_countdown(self, seconds: int | None) -> None:
        """Show how many seconds are left before Quill stops listening because it is quiet (None hides it)."""
        self._countdown_seconds = seconds
        self._render_countdown()

    def _render_countdown(self) -> None:
        seconds = self._countdown_seconds
        self.toggle_button.set_countdown(seconds)

    def add_demo_menu(self, scenarios) -> None:
        """Add a **Demo** menu with one entry per ``(label, action)`` (only in demo mode; see :mod:`quill.demo`)."""
        menu = self._window.menuBar().addMenu("Demo")
        for label, action in scenarios:
            menu.addAction(label, action)

    def _icon(self, name: str, color: str):
        return make_icon(name, color)

    def refresh_icons(self, text_color: str = "#1F1E1D", on_accent: str = "#FFFFFF",
                      accent: str = "#7A55C2") -> None:
        """Redraw the button icons and the count pill for the current theme colours."""
        self._on_accent, self._text_color, self._accent = on_accent, text_color, accent
        if self._window is None:
            return                      # not built yet; setup() draws them
        self._render_stream()
        self.mini_button.setIcon(make_icon("maximize" if self._view_mini else "minimize", text_color, 16))
        self.mini_button.setToolTip("Back to the Full Window" if self._view_mini else "Mini View")
        self.mini_button.setAccessibleName("Back to the Full Window" if self._view_mini else "Mini View")
        self.badge_label.set_colors(on_accent, accent)
        self.row_table.set_delete_colors(accent, on_accent)
        self.update_current_row(self._row_fields)         # the grid's first column takes its colour from the theme
        self.undo_button.setIcon(make_icon("undo", text_color, 18))
        self.help_button.setIcon(make_icon("question", text_color, 18))
        self.next_button.setIcon(make_icon("next", text_color, 18))
        self.settings_button.setIcon(make_icon("settings", text_color, 18))
        self._show_file_state()
        self.toggle_button.set_colors(text_color, on_accent, accent)

    def set_undo_count(self, count: int) -> None:
        """Show "Undo (n)" while there is a sorting answer to take back."""
        self._undo_count = count
        self._refresh_visibility()

    def set_sorting_count(self, count: int) -> None:
        """Show the accent-coloured "Needs sorting" button, with *count* as a pill, while terms wait."""
        appearing = count > 0 and self._sorting_count == 0
        self._sorting_count = count
        slide = (appearing and self._view_mini and self._window is not None and self._window.isVisible()
                 and self.animation_ms > 0)
        if slide:
            self.sorting_button.setMaximumWidth(0)       # starts squeezed shut, so Start gives it the room
        self._refresh_visibility()
        self.badge_label.setText(str(count))
        if slide:
            self._slide_sorting_in()
        self.sorting_button.setAccessibleName(f"Term Helper ({count})")

    def _slide_sorting_in(self) -> None:
        """Mini view: the Start button eases narrower while the Term Helper button grows in on its right."""
        button = self.sorting_button
        target = max(button.sizeHint().width(), 44)
        effect = QGraphicsOpacityEffect(button)
        button.setGraphicsEffect(effect)
        animation = QVariantAnimation(button)
        animation.setDuration(260)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)

        def step(value) -> None:
            button.setMaximumWidth(max(int(target * float(value)), 1))
            effect.setOpacity(float(value))

        def done() -> None:
            button.setMaximumWidth(16777215)
            button.setGraphicsEffect(None)

        animation.valueChanged.connect(step)
        animation.finished.connect(done)
        self._sorting_animation = animation
        animation.start()

    @property
    def listening(self) -> bool:
        """Last state passed to :meth:`set_listening_indicator`."""
        return self._listening
