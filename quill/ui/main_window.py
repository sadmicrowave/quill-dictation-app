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

import dataclasses
import datetime as dt
import html
import logging
import pathlib
from typing import Callable

import shiboken6
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFontMetrics, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QMenu,
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

from quill import diagnostics
from quill.parser.tokens import tokenize
from quill.parser.vocab import NO_COLUMNS_START_HELP
from quill.stream import WordMatch
from quill.ui.chrome import set_always_on_top
from quill.ui.hints import fill_missing_tips
from quill.ui.icons import make_icon
from quill.ui.main_widgets import (
    NO_COLUMNS_HINT,
    PLACEHOLDER_MARGINS,
    ROW_EMPTY_HEIGHT,
    ROW_HINT,
    STREAM_MIN_HEIGHT,
    ResizeWatcher,
    RowTable,
    StreamBox,
)
from quill.ui.theme import apply_spacing, grey_pill, install_backdrop
from quill.ui.side_panel import FILE_PAGE, PANEL_MAX_WIDTH, PANEL_MIN_WIDTH, PANEL_WIDTH, SidePanel, TURN_PAGE
from quill.ui.listen_button import NO_COLUMNS_SHORT, NO_COLUMNS_TEXT, ListenButton
from quill.ui.widgets import (
    ElidedLabel,
    FooterButton,
    Pill,
    ResizeGrip,
    connection_tip,
    tooltip_lines,
)

#: Active-light colours (the same hues are used by the tray icon).
COLOR_ACTIVE = "#34c759"

#: The help page the window's ? icon opens.
HELP_TOPIC = "welcome"

#: The chip that replaces the sheet name while no spreadsheet is connected, and its tooltip.
NOT_CONNECTED_HINT = (
    "No spreadsheet is connected, so there is nothing to read lists from or write rows to.\n"
    "Quill works through a workbook open in your spreadsheet program (it attaches automatically within a few seconds of "
    "the workbook opening) or through an .xlsx or .csv file chosen with File > Open File.\n"
    "Open a workbook or choose a file; listening can start once the connection is made."
)

#: Most the Current Row box grows to before it scrolls inside itself (full view, mini view).
ROW_MAX_FULL = 150
ROW_MAX_MINI = 66

#: Space left below the "Log" heading when the log is minimized, in pixels.
LOG_BOTTOM_MARGIN = 3

#: The room the layout keeps at the bottom for the footer: its height (22), the gap above it and the margin below it.
FOOTER_ROOM = 22 + 3 + LOG_BOTTOM_MARGIN

#: Pixels the grip of the heard-words box sits below that box's bottom edge: over the middle of the gap to the box under it.
ROW_GRIP_DROP = 5
SIZE_SETTLE_MS = 400        # how long the window must stay still before its size is reported
MIN_REMEMBERED = (300, 300)  # a remembered size below this is ignored
MIN_WINDOW = (453, 340)      # the full window never gets smaller than this, and opens at it the first time
LOG_OPEN_HEIGHT = 120       # height of the log while it is open (until the user drags it to another)
LOG_MIN_HEIGHT, LOG_MAX_HEIGHT = 60, 600     # how short and tall the user may drag the log
#: Gap (px) between the log box and the footer under it.
LOG_FOOTER_GAP = 3
MIN_CONTENT_WIDTH = 405     # the content (everything but the side panel) is never dragged narrower than this

#: Lines kept in the log before the oldest are dropped.
MAX_LOG_LINES = 500


def sentence(text: str) -> str:
    """*text* as a finished sentence: a full stop is added unless it already ends in one (or in other closing punctuation;
    a closing quote counts as the end when what is inside it is already punctuated)."""
    text = text.rstrip()
    if not text:
        return text
    core = text.rstrip("’”\"')")
    last = core[-1] if core else text[-1]
    return text if last in ".!?…:;" else text + "."


LOG_TIME_GAP = 12           # px between the time and the message in the log

#: How each kind of log message is shown: a label after the time (none for plain information) and a colour.
LOG_LEVELS = {"info": (None, None), "warning": ("Warning", "#D98E04"), "error": ("Error", "#E5484D")}


#: How long the "Remember ...?" line stays before it goes by itself (nothing is learned then).
LEARN_OFFER_MS = 12_000

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
        on_open_file: Called when the user chooses Open File (button or File menu).
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
        on_field_options: Callable[[str], list[str]] | None = None,
        on_field_changed: Callable[[str, str], None] | None = None,
        on_learn_answer: Callable[[bool | None], None] | None = None,
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
        self._not_connected_tip = connection_tip()                   # what hovering the "File not connected" button says
        self._native_settings_button = False
        self._native_file_button = False
        self._native_turn_button = False
        self._panel_width = PANEL_WIDTH      # how wide it opens (the user drags the edge to change it)
        self._on_panel_size: Callable[[int], None] = lambda width: None
        self._panel_open = False             # the side panel is open (or sliding open)
        self._panel_page = FILE_PAGE
        self._panel_animation: QVariantAnimation | None = None
        self._pending_panel = ""             # a page to open once the full window is back (the panel is not in the mini view)
        self._on_panel_width: Callable[[int], None] = lambda width: None
        self._on_panel_toggled: Callable[[str], None] = lambda page: None   # told the open page, or "" when it closes
        self._workbook_name = ""
        self._workbook_path = ""
        self._workbook_kind = ""
        self._sheet_name = ""
        self._native_undo_button = False
        self._text_color = "#1F1E1D"
        self._update_alert = False                              # the Settings icon wears a red dot (a newer version is out)
        self._file_alert = ""                                   # why the folder icon wears a red dot (see raise_file_alert)
        self._accent = "#7A55C2"
        self._applied: dict[str, bool] = {}     # which sections are collapsed on screen
        self._log_height = LOG_OPEN_HEIGHT   # the log's height while open (the user can drag it)
        self._on_log_height: Callable[[int], None] = lambda height: None
        self._log_grew = 0                   # window height added to make room for the open log (given back on close)
        self._log_animation: QVariantAnimation | None = None
        self._log_busy = False               # the log is sliding open or shut
        self._density = ""                   # the spacing mode last given to apply_density ("" = the application's)
        self._mini_detail = False            # the mini view is tall enough to show the stream and the row
        self._mini_base = 0                  # the mini view's own (compact) height
        self._mini_size: QSize | None = None  # the size the user left the mini view at
        self._on_mini_resized = on_mini_resized or (lambda width, height: None)
        self._on_field_removed = on_field_removed or (lambda column: None)
        self._on_field_options = on_field_options or (lambda column: [])      # the other columns a line's value could go in
        self._on_field_changed = on_field_changed or (lambda column, to: None)
        self._on_learn_answer = on_learn_answer or (lambda answer: None)      # True: yes, False: no, None: no answer in time
        self._row_fields: dict[str, object] = {}   # the values of the row being built (what the grid shows beside their names)
        self._sheet_columns: list[str] = []        # the active sheet's columns, in sheet order (the grid lists them all, muted, from the start)
        self._grid_shown: tuple = ()               # what the grid was last filled with (it is only refilled when this changes)
        self._stream_words: list[tuple[str, WordMatch]] = []     # what was heard (final), with what Quill made of each word
        self._stream_partial: list[tuple[str, WordMatch]] = []   # the phrase still being spoken
        self._stream_done = False            # the row ended: the next words start a fresh stream
        self._no_columns = False                   # connected, but the sheet's headings were not found
        self._pending_span = 0                       # (the next number for a term waiting in the Term Helper: its words share one pill)
        self._answered_span = 10_000                 # (spans given to words that were just answered and are read again)
        self._live_fields: dict[str, object] = {}  # what the words still being spoken would put in the row (shown as they are heard)
        self._live_stale = False                   # a phrase just ended: its live values stay until the row's own values arrive
        self._preview_values = lambda words: {}
        self._classify_words = lambda words: [WordMatch(False) for _ in words]
        self._sorting_animation: QVariantAnimation | None = None
        self._countdown_share: float | None = None
        self._next_animation: QVariantAnimation | None = None             # the Next Row button easing in or out beside Start
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
        self._reshow_size: QSize | None = None               # the size the window had when it was hidden (see _SizeKeeper)
        self._reshow_pos = None                              # ... and where it was
        self._reshowing = False
        window.installEventFilter(_SizeKeeper(window, self))
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
        # The content and the side panel sit side by side; the panel is closed (zero width) until a title bar icon opens it.
        self._shell = QWidget()
        shell = QHBoxLayout(self._shell)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self._shell.setProperty("keepMargins", True)
        self._shell.setProperty("keepSpacing", True)         # the content and the panel touch: no gap between them
        shell.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._shell.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.panel = SidePanel()
        self.panel.close_requested.connect(self.close_panel)
        self.panel.width_dragged.connect(self._panel_dragged)
        self.panel.width_released.connect(lambda: self._on_panel_size(self._panel_width))
        self.panel.settings_requested.connect(self.show_file_settings)
        shell.addWidget(central, 1)
        shell.addWidget(self.panel)

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
        self.error_button.setToolTip("Something went wrong: back to the full window to read it.")
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
        self.next_button.setProperty("outline", True)             # purple border, like the Start button
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
        self.open_file_button = QPushButton()                   # just a folder icon; refresh_icons() draws it
        self.open_file_button.setProperty("iconOnly", True)
        self.open_file_button.setAccessibleName("Open File")
        self.open_file_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_file_button.clicked.connect(lambda: self.toggle_panel(FILE_PAGE))
        status_row.insertWidget(status_row.indexOf(self.settings_button), self.open_file_button)
        self.turn_button = QPushButton()                        # the turn icon: opens the side panel's turn page
        self.turn_button.setProperty("iconOnly", True)
        self.turn_button.setToolTip("Turn Settings")
        self.turn_button.setAccessibleName("Turn Settings")
        self.turn_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.turn_button.clicked.connect(lambda: self.toggle_panel(TURN_PAGE))
        status_row.insertWidget(status_row.indexOf(self.settings_button), self.turn_button)

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
        self.row_table.row_change_requested.connect(self._change_row_requested)
        self._row_height = self.row_table.verticalHeader().defaultSectionSize()
        self.row_table.setMinimumHeight(ROW_EMPTY_HEIGHT)           # starts small; grows with the fields heard
        self._row_target = ROW_EMPTY_HEIGHT
        # a hint shown while no fields have been heard yet
        self.row_placeholder = QLabel(ROW_HINT, self.row_table.viewport())
        self.row_placeholder.setProperty("placeholder", True)        # same look as the Voice Stream box's placeholder
        self.row_placeholder.setWordWrap(True)
        self.row_placeholder.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.row_placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)     # (until it holds links: see _refresh_grid)
        self.row_placeholder.setOpenExternalLinks(False)
        self.row_placeholder.linkActivated.connect(lambda _href: self.open_file_settings())
        self.row_table.viewport().setProperty("keepMargins", True)     # the spacing setting must not resize this layout's margins
        holder = QVBoxLayout(self.row_table.viewport())
        holder.setContentsMargins(*PLACEHOLDER_MARGINS)   # the same place the Voice Stream box's hint starts
        holder.addWidget(self.row_placeholder)
        self.row_grip = ResizeGrip(central)         # drag the bottom edge of the matched words box: it trades height with the log
        self.row_grip.dragged.connect(self._grip_dragged)
        self.row_grip.released.connect(lambda: self._on_log_height(self._log_height))
        self.row_table.installEventFilter(_GripPlacer(self.row_table, self.row_grip, ROW_GRIP_DROP))
        self.row_grip.centre_provider = self.row_table.divider_x        # (the middle dot sits on the line between the grid's two columns)
        layout.addWidget(self.row_table, 1)        # takes the height when the window is resized: it is what is being watched
        self.learn_bar = QWidget()                 # "Remember that 'spotted' means Observation Date?  Yes  No": quiet, goes by itself
        learn = QHBoxLayout(self.learn_bar)
        learn.setContentsMargins(0, 0, 0, 0)
        learn.setSpacing(6)
        self.learn_label = QLabel("")                # wraps: a long column name must still be read in full
        self.learn_label.setWordWrap(True)
        self.learn_label.setProperty("note", True)
        learn.addWidget(self.learn_label, 1)
        self.learn_yes, self.learn_no = QPushButton("Yes"), QPushButton("No")
        for button, answer in ((self.learn_yes, True), (self.learn_no, False)):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, a=answer: self._learn_answered(a))
            learn.addWidget(button)
        self.learn_bar.setVisible(False)
        self._learn_timer = QTimer(self._window)
        self._learn_timer.setSingleShot(True)
        self._learn_timer.setInterval(LEARN_OFFER_MS)
        self._learn_timer.timeout.connect(lambda: self._learn_answered(None))
        layout.addWidget(self.learn_bar)
        self._has_last_saved = False                       # the line shows only once a row has been saved
        self.last_label = ElidedLabel("")                  # one line however much was saved
        self.last_label.setProperty("note", True)          # smaller italic supporting text
        self.last_label.setObjectName("lastSaved")         # (and muted further: see the theme)
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
        # The window's footer sits below everything, log included: icon buttons of one size on the left (the bug opens and closes
        # the log; others can join it), the last saved row on the right.
        self.log_toggle = FooterButton("bug", "Show the log", idle_opacity=0.45)
        self.log_toggle.toggled.connect(self._log_button_toggled)        # (toggled, not clicked: an accessibility "press" only toggles)
        self.export_log_button = FooterButton("export", "Export the log to a text file.", checkable=False)
        self.export_log_button.setVisible(False)                          # shown only while the log is open
        self.export_log_button.clicked.connect(self.export_log)
        self.footer = QFrame(central)                       # (placed by hand at the bottom: the layout only reserves its room)
        self.footer.setObjectName("windowFooter")
        self.footer.setProperty("keepMargins", True)
        footer_row = QHBoxLayout(self.footer)
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(6)
        footer_row.setProperty("keepSpacing", True)
        footer_row.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        footer_row.addWidget(self.export_log_button, 0, Qt.AlignmentFlag.AlignLeft)
        footer_row.addSpacing(4)
        footer_row.addWidget(self.last_label, 1)
        footer_row.addStretch(0)                           # (takes the room when Last Saved is hidden: the buttons stay at the left)
        self.log = QTextEdit()                # (not the plain-text kind: it can hang a long line's wrap under the message)
        self.log.setReadOnly(True)
        self.log.document().setUndoRedoEnabled(False)
        log_block = QVBoxLayout()                           # the heading sits close to its box, in either spacing
        log_block.setContentsMargins(0, 0, 0, 0)
        log_block.setSpacing(0)
        log_block.setProperty("keepSpacing", True)
        log_block.addWidget(self.log)
        layout.addLayout(log_block)
        central.installEventFilter(_FooterPlacer(central, self.footer, self))
        layout.addStretch(0)         # soaks up spare height in the compact mini view (and while it grows back), so nothing drifts down
        self._spacer_index = layout.count() - 1

        # File menu (the global menu bar on macOS): Open File, and back to live Excel.
        file_menu = window.menuBar().addMenu("File")
        self.open_file_action = file_menu.addAction("Open File…", lambda: self._on_open_file())
        self.open_file_action.setShortcut("Ctrl+O")
        self.use_excel_action = file_menu.addAction("Use the Open Workbook", lambda: self._on_use_excel())
        self.use_excel_action.setEnabled(False)
        window.setCentralWidget(self._shell)
        self._window = window
        self.refresh_icons()
        self._set_collapsed("log", self._log_collapsed)
        if self._mini:
            self.set_mini(True)
        else:
            self._refresh_visibility()
            self._set_margins(False)                           # (the footer is the last thing: a small margin follows it)
        self.set_listening_indicator(False)
        fill_missing_tips(window)
        fill_missing_tips(self.panel.settings)
        self._refresh_grid()                                   # (columns read before the window was built)

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
    MINI_WIDTH = 470
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
                self._full_size = QSize(window.width() - self._panel_extra(), window.height())   # to come back to
            if mini:
                self._collapse_panel()                                      # the panel is not part of the mini view
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

    def _collapse_panel(self) -> None:
        """Close the panel at once, without moving the window (entering the mini view, which sets its own size)."""
        if self._panel_animation is not None:
            self._panel_animation.stop()
        if self._panel_open:
            self._panel_open = False
            self._on_panel_toggled("")
        self.panel.setFixedWidth(0)
        self.panel.setVisible(False)
        self._on_panel_width(0)

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
            width = max(width, self.MINI_WIDTH)             # (a size remembered before the title bar grew would crowd its icons)
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
        if not mini and self._pending_panel:                # the icon was pressed in the mini view: now open the panel
            page, self._pending_panel = self._pending_panel, ""
            QTimer.singleShot(0, lambda: self.open_panel(page))

    def set_not_connected(self, not_connected: bool, hint: str | None = None) -> None:
        """Say "File not connected" in the Start button (and explain it on hover) while there is no spreadsheet."""
        self._not_connected = not_connected
        self._not_connected_tip = connection_tip(hint) if hint else self._not_connected_tip
        self._refresh_visibility()

    def set_native_file_button(self, native: bool) -> None:
        """The title bar now has its own folder icon, so the one inside the window is hidden."""
        self._native_file_button = native
        self._refresh_visibility()

    def set_native_turn_button(self, native: bool) -> None:
        """The title bar now has its own turn icon, so the one inside the window is hidden."""
        self._native_turn_button = native
        self._refresh_visibility()

    # -- the side panel -----------------------------------------------------

    @property
    def panel_open(self) -> bool:
        """True while the side panel is open (or sliding open)."""
        return self._panel_open

    @property
    def panel_page(self) -> str:
        """The page the open panel shows (``"file"`` or ``"turn"``); "" while it is closed."""
        return self._panel_page if self._panel_open else ""

    def set_panel_listener(self, callback: Callable[[str], None], on_width: Callable[[int], None] | None = None) -> None:
        """Call *callback* with the page that opened, or "" when the panel closed; *on_width* with the panel's
        width at every step of its slide (the title bar icons and line follow it)."""
        self._on_panel_toggled = callback
        self._on_panel_width = on_width or (lambda width: None)

    def toggle_panel(self, page: str) -> None:
        """The folder / turn icon: open the panel on *page*, switch to it, or close the panel if it already shows it."""
        if self._panel_open and self._panel_page == page:
            self.close_panel()
        else:
            self.open_panel(page)

    def open_panel(self, page: str) -> None:
        """Ease the panel open on *page* (the window grows by the panel's width). In the mini view the full window comes back first."""
        if self._window is None:
            return
        if self._mini or self._view_mini:
            self._pending_panel = page
            if self._mini:
                self.set_mini(False, notify=True)
            return
        self._panel_page = page
        self.panel.show_page(page)
        if page == FILE_PAGE:
            self.clear_file_alert()                       # (looking at the file section is what the red dot asks for)
        self._on_panel_toggled(page)
        if not self._panel_open:
            self._panel_open = True
            self._slide_panel(self._panel_width)

    def set_panel_size_listener(self, callback: Callable[[int], None]) -> None:
        """Call *callback* with the panel's width whenever the user finishes dragging it to a new one."""
        self._on_panel_size = callback

    def restore_panel_width(self, width: int) -> None:
        """Use the panel width the user left it at (kept within the limits)."""
        self._panel_width = max(PANEL_MIN_WIDTH, min(PANEL_MAX_WIDTH, int(width or PANEL_WIDTH)))

    @property
    def panel_width(self) -> int:
        """The width the panel opens at."""
        return self._panel_width

    def _panel_room(self) -> int:
        """The most the panel can be right now: what is left of the window once the content has its own minimum."""
        content = max(self._layout.minimumSize().width(), MIN_CONTENT_WIDTH)
        return max(PANEL_MIN_WIDTH, min(PANEL_MAX_WIDTH, self._window.width() - content))

    def _panel_dragged(self, dx: int) -> None:
        """The panel's edge was dragged *dx* px to the right: the panel narrows and the content widens, or the reverse. The
        window keeps its size, and the content never gets narrower than it can work at."""
        if self._window is None or not self._panel_open or self._panel_animation_running():
            return
        width = max(PANEL_MIN_WIDTH, min(self._panel_room(), self.panel.width() - dx))
        if width != self.panel.width():
            self._panel_width = width
            self.panel.setFixedWidth(width)
            self._on_panel_width(width)                       # the title bar's line, title and icons follow
            self._settle_minimum()

    def _panel_animation_running(self) -> bool:
        return self._panel_animation is not None and self._panel_animation.state() == QVariantAnimation.State.Running

    def open_file_settings(self) -> None:
        """Open the Files panel (if it is not open) and show the file settings overlay under its gear: where the headings row and
        the sheet layout are chosen. The overlay waits for the panel to finish sliding, since it hangs from the gear."""
        if self._window is None or not self._workbook_name:
            return
        slow = self._mini or self._view_mini                          # (the full window has to come back first)
        if self._panel_open and self._panel_page == FILE_PAGE and not slow:
            self.show_file_settings()
            return
        self.open_panel(FILE_PAGE)
        QTimer.singleShot(self.animation_ms * (3 if slow else 1) + 150, self._show_file_settings_later)

    def _show_file_settings_later(self) -> None:
        if self._panel_open and self._panel_page == FILE_PAGE:
            self.show_file_settings()

    def show_file_settings(self) -> None:
        """Open the file settings overlay under the gear button of the Files page."""
        if self._window is None or not self._panel_open or self._panel_page != FILE_PAGE:
            return
        button = self.panel.settings_button                      # the overlay hangs from the gear, right edges level
        self.panel.show_settings(button.mapToGlobal(button.rect().bottomRight()) + QPoint(0, 4))

    def close_panel(self) -> None:
        """Ease the panel shut (the window gives its width back)."""
        if self._window is None or not self._panel_open:
            return
        self._panel_open = False
        self._on_panel_toggled("")
        self._slide_panel(0)

    def _panel_extra(self) -> int:
        """Width the panel currently adds to the window."""
        return self.panel.width() if self.panel.isVisibleTo(self._window) else 0

    def _slide_panel(self, width: int) -> None:
        """Move the panel to *width* and the window with it, both easing together, so the content never gets squeezed."""
        window, panel = self._window, self.panel
        if self._panel_animation is not None:
            self._panel_animation.stop()
        start = panel.width()
        panel.setVisible(True)
        target = window.width() + (width - start)
        if width:
            screen = window.screen()
            if screen is not None:
                target = min(target, max(screen.availableGeometry().width(), window.width()))
        else:
            target = max(target, MIN_WINDOW[0])
        animate = window.isVisible() and self.animation_ms > 0

        def done() -> None:
            panel.setFixedWidth(width)
            panel.setVisible(width > 0)
            self._on_panel_width(width)
            self._keep_minimum()
            QTimer.singleShot(60, self._window, self._keep_minimum)             # (again once the panel has been laid out: its page decides the height)

        if not animate:
            panel.setFixedWidth(width)
            self._on_panel_width(width)
            self._resize_to(target, window.height(), then=done)
            return
        animation = QVariantAnimation(window)
        animation.setDuration(self.animation_ms)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.setStartValue(start)
        animation.setEndValue(width)
        animation.valueChanged.connect(lambda value: (panel.setFixedWidth(int(value)), self._on_panel_width(int(value))))
        self._panel_animation = animation
        window.setMinimumSize(0, 0)
        animation.start()
        self._resize_to(target, window.height(), then=done)

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
        """The footer is the last thing in the window: only a small margin may follow it."""
        if not self._view_mini and self._window is not None:
            m = self._layout.contentsMargins()
            # The footer is not in the flow: the layout keeps its room at the bottom (its height, the gap above it, the margin
            # below it), so the gap above it is the same small one whether the log is open or shut.
            self._layout.setContentsMargins(m.left(), m.top(), m.right(), FOOTER_ROOM)
            self.place_footer()

    def place_footer(self) -> None:
        """Put the footer at the bottom of the window, under whatever the layout ends with."""
        if self._window is None or self._view_mini:
            return
        root, m = self.root, self._layout.contentsMargins()
        height = self.footer.sizeHint().height()
        self.footer.setGeometry(m.left(), root.height() - LOG_BOTTOM_MARGIN - height, root.width() - m.left() - m.right(), height)
        self.footer.raise_()

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

    def set_log_height_listener(self, callback: Callable[[int], None]) -> None:
        """Call *callback* with the log's height whenever the user finishes dragging it to a new one."""
        self._on_log_height = callback

    def restore_log_height(self, height: int) -> None:
        """Use the log height the user left it at (kept within bounds)."""
        self._log_height = max(LOG_MIN_HEIGHT, min(LOG_MAX_HEIGHT, int(height or LOG_OPEN_HEIGHT)))
        if self._window is not None and self.log.isVisibleTo(self._window) and not self._log_busy:
            self.log.setFixedHeight(self._log_height)

    @property
    def log_height(self) -> int:
        """The height the log has while it is open."""
        return self._log_height

    def _grip_dragged(self, dy: int) -> None:
        """The bottom edge of the matched words box was dragged *dy* px (down is positive).

        With the log open the two boxes trade height (the window stays the size it is); with the log hidden the whole
        window is resized, and the box takes the difference. Never horizontally: the window's width is the user's own.
        """
        window = self._window
        if window is None or self._view_mini or self._log_busy:
            return
        if self.log.isVisibleTo(window) and not self._log_collapsed:
            room = max(self.row_table.height() - self.row_table.minimumHeight(), 0)         # what the matched words box can give up
            wanted = self._log_height - dy                                                  # down makes the log shorter
            wanted = max(LOG_MIN_HEIGHT, min(LOG_MAX_HEIGHT, wanted, self._log_height + room))
            if wanted != self._log_height:
                self._log_height = wanted
                self.log.setFixedHeight(wanted)
            return
        floor = max(self._layout.minimumSize().height(), MIN_WINDOW[1])
        window.resize(window.width(), max(floor, window.height() + dy))

    def _fit_height(self) -> int:
        """The height the window needs right now (the layout is recomputed first, as Qt only does that lazily)."""
        layout = self._layout
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
        layout = self._layout
        layout.invalidate()
        layout.activate()
        self._settle_minimum()

    def _settle_minimum(self) -> None:
        """Stop the user dragging the window smaller than its content (applied once a resize is done)."""
        if self._log_busy:                             # the log is still sliding; its final size is not known yet
            return
        if self._view_mini and self._mini_base:        # the mini view may shrink back to its compact size
            self._window.setMinimumSize(self._layout.minimumSize().width(), self._mini_base)
            return
        content = self._layout.minimumSize()
        panel_least = PANEL_MIN_WIDTH if self._panel_extra() else 0     # the panel gives way first; the content keeps its own minimum
        panel_height = 0
        if self._panel_extra() and self.panel.height() > 0:             # the panel's page shows whole, never cut off below
            panel_height = self.panel.needed_height() + self._window.height() - self.panel.height()
        self._window.setMinimumSize(max(max(content.width(), MIN_CONTENT_WIDTH) + panel_least, MIN_WINDOW[0]),
                                    max(content.height(), MIN_WINDOW[1], panel_height))

    def fit_panel(self) -> None:
        """Keep the content (everything but the side panel) at least :data:`MIN_CONTENT_WIDTH` wide as the window narrows: the
        panel gives up width instead, and takes it back (up to the width the user chose) as the window widens."""
        if (self._window is None or not self._panel_open or self._panel_animation_running() or self._log_busy
                or not self.panel.isVisibleTo(self._window)):
            return
        content = max(self._layout.minimumSize().width(), MIN_CONTENT_WIDTH)
        width = max(PANEL_MIN_WIDTH, min(self._panel_width, self._window.width() - content))
        if width != self.panel.width():
            self.panel.setFixedWidth(width)
            self._on_panel_width(width)

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
        if self._no_columns and not self._listening:            # a sheet with nothing to match: Start is off, and the button says why
            self.toggle_button.set_notice(True, NO_COLUMNS_START_HELP, NO_COLUMNS_TEXT, blocked=True, short=NO_COLUMNS_SHORT)
        else:
            self.toggle_button.set_notice(self._not_connected, self._not_connected_tip)
        self.open_file_button.setVisible(full and not self._native_file_button)
        self.turn_button.setVisible(full and not self._native_turn_button)
        sliding = self._next_animation is not None
        if not sliding:
            self.next_button.setVisible(self._listening)                      # only while a turn is going on
        self.error_button.setVisible(self._view_mini and bool(self._mini_error))
        self.toggle_button.set_compact(self._view_mini)                      # (first: the Next Row button below is as tall as it)
        tall = self.sorting_button.fontMetrics().height() * 2 + 4
        self.toggle_button.setMinimumHeight(0 if self._view_mini else tall)
        beside = max(tall if full else 0, self.toggle_button.sizeHint().height())
        if sliding:
            self.next_button.setFixedHeight(beside)                           # (its width is being eased)
        else:
            self.next_button.setFixedSize(beside + 14, beside)                # as tall as the Start button
        self.mini_button.setVisible(not self._native_mini_button)           # the title bar has its own
        self.settings_button.setVisible(full and not self._native_settings_button)
        self.footer.setVisible(full)
        detail = full or self._mini_detail                                   # the mini view shows them only when tall
        self.stream.setVisible(detail)
        self.row_table.setVisible(detail)
        if self._view_mini:
            self.learn_bar.setVisible(False)
        self.row_grip.allowed = full                                         # (only the full window is resized this way)
        self.row_grip.setVisible(full and detail)
        self.last_label.setVisible(full and self._has_last_saved)
        self.help_button.setVisible(full and not self._native_help_button)
        self.undo_button.setVisible(full and not self._native_undo_button)
        self.undo_button.setEnabled(self._undo_count > 0)
        self.log.setVisible(full and (not self._log_collapsed or self._log_closing()))
        if self.log.isVisibleTo(self._window) and not self._log_busy:
            self.log.setFixedHeight(self._log_height)
        self.sorting_button.setVisible(self._sorting_count > 0)
        self.sorting_title.setVisible(full)                               # just the count pill when mini
        self.row_table.verticalHeader().setDefaultSectionSize(22 if self._view_mini else self._row_height)
        self._fit_row_table(animate=False)
        self.sorting_button.setMinimumHeight(self.toggle_button.sizeHint().height() if self._view_mini else tall)
        self._layout.setStretch(self._spacer_index, 1 if (self._view_mini and not detail) else 0)
        self._layout.setStretchFactor(self.row_table, 1)       # extra height always goes to the Current Row box;
        self._layout.setStretchFactor(self.log, 0)             # the log keeps its own height
        self._keep_minimum()
        self.sorting_button.setToolTip("Term Helper: terms that were heard but not placed yet.")

    @staticmethod
    def log_file_name(now: dt.datetime | None = None) -> str:
        """The name offered for an exported log: ``quill-system-log-<date and time>.txt``."""
        return f"quill-system-log-{(now or dt.datetime.now()):%Y-%m-%d_%H-%M-%S}.txt"

    def export_log(self) -> str | None:
        """Ask where to save the log (the file chooser starts in the user's home folder, with the suggested name) and write it as plain text.

        Returns:
            The path written, or None if the chooser was cancelled or the file could not be written.
        """
        start = str(pathlib.Path.home() / self.log_file_name())
        chosen, _ = QFileDialog.getSaveFileName(self._window, "Export the Log", start, "Text files (*.txt)")
        if not chosen:
            return None
        try:
            pathlib.Path(chosen).write_text(self.log.toPlainText() + "\n", encoding="utf-8")
        except OSError as exc:
            self.append_log(f"The log could not be saved: {exc.strerror or 'the file could not be written'}.", "error",
                            safe="The log could not be exported")
            return None
        return chosen

    def _log_button_toggled(self, selected: bool) -> None:
        """The footer's bug button was switched (a click, or an accessibility press): open or close the log to match. A switch the
        window made itself (it already agrees) changes nothing."""
        if selected != (not self._log_collapsed):
            self._set_collapsed("log", not selected, notify=True)

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

    def remember_for_reshow(self) -> None:
        """The window is being hidden (closed to the menu bar): note its size, to give it back when it is shown again."""
        window = self._window
        animation = getattr(self, "_animation", None)
        if (window is None or self._log_busy or self._mini != self._view_mini or self._reshowing
                or (animation is not None and animation.state() == QPropertyAnimation.State.Running)):
            return
        self._reshow_size = QSize(window.width(), window.height())
        self._reshow_pos = window.pos()

    def restore_after_reshow(self) -> None:
        """The window was shown again: macOS builds a new native window with a different title bar, and the window comes back
        taller or shorter than it was (it grew a little each time it was closed and reopened, taking the room from the
        matched words box). Give it the size it had, and keep the size from being reported while it settles."""
        if self._reshow_size is None or self._window is None:
            return
        self._reshowing = True
        saved, spot = QSize(self._reshow_size), self._reshow_pos
        steps = (0, 150, 400, 900)
        for index, delay in enumerate(steps):
            QTimer.singleShot(delay, lambda last=index == len(steps) - 1: self._apply_reshow(saved, spot, last))

    def _apply_reshow(self, saved: QSize, spot, last: bool) -> None:
        window = self._window
        if window is not None and shiboken6.isValid(window) and window.isVisible() and self._reshow_size is not None:
            if window.width() != saved.width() or window.height() != saved.height():
                window.resize(saved)
            if spot is not None and window.pos() != spot:
                window.move(spot)                                    # (it also came back lower by the title bar's difference)
        if last:
            self._reshowing = False
            self._reshow_size = None
            self.report_size()

    def report_size(self) -> None:
        """Tell the app the full window's size (not while it is the mini view or in the middle of a resize)."""
        window = self._window
        animation = getattr(self, "_animation", None)
        if (window is None or self._log_busy or self._mini != self._view_mini or self._reshowing
                or (animation is not None and animation.state() == QPropertyAnimation.State.Running)):
            return
        if self._view_mini:                                    # the mini view keeps its own size
            self._mini_size = QSize(window.width(), window.height())
            self._on_mini_resized(window.width(), window.height())
            return
        width = window.width() - self._panel_extra()          # the panel is not part of the size to remember
        self._full_size = QSize(width, window.height())
        self._on_resized(width, window.height())

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
            self._layout.activate()
            self._resize_to(window.width(), self._fit_height())
        elif collapsed:
            self._close_log(window)
        else:
            self._open_log(window)
        self.log_toggle.setChecked(not collapsed)                 # selected while the log is open
        self.log_toggle.setToolTip("Show the log" if collapsed else "Hide the log")
        self.log_toggle.setAccessibleName("Show the log" if collapsed else "Hide the log")
        self.export_log_button.setVisible(not collapsed)           # the export button joins the bug while the log is open
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
        layout = self._layout
        spacing = max(layout.spacing(), 0)
        self._log_busy = True
        slack = max(self.row_table.height() - self.row_table.minimumHeight(), 0)    # what the box can give up
        grow = max(self._log_height + spacing - slack, 0)
        self._log_grew = grow
        height, width = self._height_now(), window.width()
        self.log.setFixedHeight(0)
        self._set_margins(False)
        self._refresh_visibility()
        self.log.setVisible(True)
        if grow:
            self._resize_to(width, height + grow)
        self._slide_log(0, self._log_height, True, self._log_settled)

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
            self._workbook_path = ""
        self._show_file_state()

    def set_workbook_path(self, path: str, kind: str = "") -> None:
        """Note the full path of the file in use and what it is open in (the side panel shows both)."""
        self._workbook_path, self._workbook_kind = path, kind
        self._show_file_state()

    def set_native_panel_header(self, native: bool) -> None:
        """The title bar draws the panel's title and close button, so the panel's own are hidden."""
        self.panel.set_native_header(native)

    def _show_file_state(self) -> None:
        """Draw the folder icon: muted and closed with no file, solid and open with one."""
        if self._window is None:
            return
        has = bool(self._workbook_name)
        sheet = f"\nSheet: {self._sheet_name}" if has and self._sheet_name else ""
        tip = (f"{self._workbook_name}{sheet}" if has
               else "Open File\nChoose an .xlsx or .csv file for Quill to fill in.")
        self.open_file_button.setToolTip(tip)
        color = self._text_color
        if not has:
            muted = QColor(color)
            muted.setAlpha(110)
            color = muted.name(QColor.NameFormat.HexArgb)
        self.open_file_button.setIcon(make_icon("folder-open" if has else "folder", color, 18, badge=bool(self._file_alert)))
        if self._file_alert:
            self.open_file_button.setToolTip(f"{self._file_alert}\n{tip}")
        self.panel.set_active(self._workbook_name, self._sheet_name, self._workbook_path, self._workbook_kind)
        self._on_file_state(has, self._workbook_name, self._sheet_name)

    # -- the folder icon's alert dot ------------------------------------------

    @property
    def file_alert(self) -> str:
        """Why the folder icon wears its red dot ("" when it does not): what changed in the file section."""
        return self._file_alert

    def raise_file_alert(self, text: str) -> None:
        """Put the red dot on the folder icon (in the title bar and in the window) with *text* as its hover line. Opening the
        side panel puts it away again."""
        if text != self._file_alert:
            self._file_alert = text
            self._show_file_state()

    def set_update_alert(self, on: bool) -> None:
        """The red dot on the in-window Settings icon (the title bar's is the app's: see ``_sync_titlebar_settings``)."""
        if on != self._update_alert:
            self._update_alert = on
            self.settings_button.setIcon(make_icon("settings", self._text_color, 18, badge=on))
            self.settings_button.setToolTip("A newer version of Quill is available.\nSettings" if on else "Settings")

    def clear_file_alert(self) -> None:
        if self._file_alert:
            self._file_alert = ""
            self._show_file_state()

    def _row_table_height(self) -> int:
        """How tall the Current Row box should be: small when empty, growing with its rows up to a cap."""
        rows = sum(1 for line in self._grid_shown[0] if line[2]) if self._grid_shown else 0       # (the lines that were heard)
        if rows == 0:
            return ROW_EMPTY_HEIGHT                    # (the muted columns below the heard ones scroll, they never ask for room)
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
        """Show the record being built: the values of the columns heard so far (the box grows with them, then scrolls)."""
        self._row_fields = dict(fields)
        self._live_fields, self._live_stale = {}, False          # (the row now has what was heard)
        self.row_table.set_changeable({c for c in fields if self._on_field_options(c)})
        self._refresh_grid()

    def set_no_columns(self, on: bool) -> None:
        """A file is connected but its sheet has no columns Quill could find: the empty grid says so (instead of its usual hint)."""
        if on != self._no_columns:
            self._no_columns = on
            if self._window is not None:
                self._grid_shown = ()
                self._refresh_grid()
                self._refresh_visibility()                       # (Start is off while the sheet has no columns)

    def set_columns(self, columns: list[str]) -> None:
        """The active sheet's columns (empty: no file is connected).

        The grid lists all of them, in the sheet's order and muted, so the user can see Quill is connected to the right sheet; they
        ease in from the top when the list is new. Heard columns then come to the top (see :meth:`_refresh_grid`).
        """
        columns = list(columns)
        if columns == self._sheet_columns:
            return                                               # the same sheet, read again: nothing to show
        self._sheet_columns = columns
        if self._window is None:
            return                                               # (not built yet: setup shows them)
        self._refresh_grid()
        window = self._window
        self.row_table.ease_in_rows(animate=bool(columns) and self.animation_ms > 0 and window is not None and window.isVisible())

    def _heard_columns(self) -> list[str]:
        """The columns the words in the Voice Stream filled, in the order they were first heard (live: partial words count)."""
        found: list[str] = []
        if self._stream_done:
            return found                                         # the row is over: what is left in the box belongs to it, not to the next turn
        for _, match in self._stream_words + self._stream_partial:
            if match.column and match.column not in found:
                found.append(match.column)
        return found

    def _grid_lines(self) -> list[tuple[str, str, bool]]:
        """What the grid shows, top to bottom: ``(column, value text, heard)``.

        The columns heard in this turn come first, in the order they were said (a column's value shows once it is understood, at the
        end of the phrase); then every other column of the sheet, muted, in the sheet's order.
        """
        heard = self._heard_columns()
        fields = self._fields_now()
        for column in fields:                                    # (a value set another way, e.g. by changing a line's column)
            if column not in heard:
                heard.append(column)
        lines = []
        for column in heard:
            value = fields.get(column)
            lines.append((column, "" if value is None else (value.isoformat() if isinstance(value, dt.date) else str(value)), True))
        lines += [(column, "", False) for column in self._sheet_columns if column not in heard]
        return lines

    def _fields_now(self) -> dict[str, object]:
        """The row's values with those the words still being spoken would add (understood as they are heard, not at the end of the phrase)."""
        return {**self._row_fields, **self._live_fields}

    def heard_lines(self) -> list[tuple[str, str]]:
        """The grid's lines in the normal colour (the columns heard in this turn): ``(column, value text)``, top to bottom."""
        return [(column, text) for column, text, heard in (self._grid_shown[0] if self._grid_shown else ()) if heard]

    def _refresh_grid(self) -> None:
        """Fill the grid from :meth:`_grid_lines`: heard columns in the normal colour at the top, the rest muted below them."""
        if self._window is None:
            return                                               # not built yet
        lines = self._grid_lines()
        table = self.row_table
        table.set_active(set(self._fields_now()))
        shown = (tuple(lines), self._text_color)
        if shown == self._grid_shown:
            return
        window = self._window
        slide = self.animation_ms > 0 and window is not None and window.isVisible() and bool(self._grid_shown and self._grid_shown[0])
        before = table.line_positions() if slide else {}
        self._grid_shown = shown
        table.setRowCount(len(lines))
        self.row_placeholder.setTextFormat(Qt.TextFormat.RichText if self._no_columns else Qt.TextFormat.PlainText)
        self.row_placeholder.setText(NO_COLUMNS_HINT if self._no_columns else ROW_HINT)
        self.row_placeholder.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse if self._no_columns
                                                     else Qt.TextInteractionFlag.NoTextInteraction)
        self.row_placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not self._no_columns)
        self.row_placeholder.setVisible(not lines)
        palette = table.palette()
        for r, (column, text, heard) in enumerate(lines):
            for c, content in enumerate((column, text)):
                item = QTableWidgetItem(content)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)            # not selectable
                if c == 0:
                    item.setForeground(palette.text() if heard else palette.placeholderText())
                table.setItem(r, c, item)
        table.scrollToTop()
        self._size_rows()
        self._fit_row_table()
        table.slide_from(before, animate=slide)                 # a column heard now slides up to the top

    def _change_row_requested(self, column: str, where) -> None:
        """The user clicked a line's column name: offer the other columns its value could go in."""
        options = self._on_field_options(column)
        if not options:
            return
        menu = QMenu(self._window)
        header = menu.addAction("Change this to")
        header.setEnabled(False)
        menu.addSeparator()
        for option in options:
            menu.addAction(option).triggered.connect(lambda _=False, o=option: self._field_changed(column, o))
        menu.exec(where)

    def _field_changed(self, column: str, to_column: str) -> None:
        self._on_field_changed(column, to_column)

    def show_learn_offer(self, text: str) -> None:
        """Ask "Remember ...?" in a quiet line under the row; it goes by itself after a few seconds (nothing is learned then)."""
        self.learn_label.setText(text)
        self.learn_bar.setVisible(self._learn_allowed())
        self._learn_timer.start()
        self._keep_minimum()

    def hide_learn_offer(self) -> None:
        self._learn_timer.stop()
        self.learn_bar.setVisible(False)
        self._keep_minimum()

    def _learn_allowed(self) -> bool:
        return not self._view_mini

    def _learn_answered(self, answer: bool | None) -> None:
        self.hide_learn_offer()
        self._on_learn_answer(answer)

    def _remove_row_requested(self, column: str) -> None:
        """The user clicked a line's delete button: take it out of the grid, un-colour its words, tell the app."""
        self._row_fields.pop(column, None)
        self._live_fields.pop(column, None)                      # (a line still being heard can be removed too)
        self._stream_partial = [(word, WordMatch(False) if match.column == column else match) for word, match in self._stream_partial]
        self.update_current_row(self._row_fields)
        self.unmatch_stream_column(column)
        self._on_field_removed(column)

    # ------------------------------------------------------------------ #
    # Voice Stream                                                         #
    # ------------------------------------------------------------------ #

    def revalidate_stream(self, valid_columns: set[str]) -> None:
        """The sheet (or its lists) changed: a word heard for a column the sheet no longer has stops counting as understood, so the grid
        never lists a column that was heard on another sheet."""
        def fix(items):
            return [(word, WordMatch(False) if match.column and match.column not in valid_columns else match) for word, match in items]
        self._stream_words, self._stream_partial = fix(self._stream_words), fix(self._stream_partial)
        self._live_fields = {c: v for c, v in self._live_fields.items() if c in valid_columns}
        self._render_stream()

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
            self._live_stale = bool(self._live_fields)
            if self._live_stale:
                QTimer.singleShot(400, self._drop_live)        # (normally the row's own values replace them at once)
        self._render_stream()

    def set_stream_partial(self, text: str) -> None:
        """The words of the phrase still being spoken, as far as they are recognised."""
        content = self._content_words(text.split())
        if content:
            self._begin_stream()
        self._stream_partial = content
        self._live_fields, self._live_stale = (self._preview_values([w for w, _ in content]) if content else {}), False
        self._render_stream()

    def _drop_live(self) -> None:
        """The values heard a moment ago were not confirmed by the row: take them back out of the grid."""
        if self._live_stale:
            self._live_fields, self._live_stale = {}, False
            self._refresh_grid()

    def set_stream_previewer(self, preview) -> None:
        """Tell the grid how to read words still being spoken: ``preview(words) -> {column: value}`` (what they would put in the row)."""
        self._preview_values = preview

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
        self._live_fields, self._live_stale = {}, False
        self._refresh_grid()                           # (the words stay in the box, but the grid starts over)

    def sorting_finished(self) -> None:
        """The Term Helper closed with everything answered: bring this window back and, if the row it was
        about is over, clear the heard words so the next row starts clean. A row that was stopped with values still in it
        is not over (nothing was saved): its heard words and its grid stay together until it is saved or discarded."""
        if self._stream_done and not self._row_fields:
            self.clear_stream()
        self.show()

    def clear_stream(self) -> None:
        """Empty the Voice Stream."""
        self._stream_words, self._stream_partial, self._stream_done = [], [], False
        self._live_fields, self._live_stale = {}, False
        self._render_stream()

    def stream_text(self) -> str:
        """Everything in the stream, as plain text."""
        return " ".join(word for word, _ in self._stream_words + self._stream_partial)

    def _begin_stream(self) -> None:
        """New words arrive after the row ended. If the row is over (saved or discarded) they start a new stream; a row that was only
        stopped, with values in it, goes on: its heard words stay beside its grid."""
        if self._stream_done:
            if self._row_fields:
                self._stream_done = False
                return
            self._stream_words, self._stream_partial, self._stream_done = [], [], False
            self._live_fields, self._live_stale = {}, False

    def set_pending_words(self, terms: list[str]) -> None:
        """The terms waiting in the Term Helper now (the words as heard): the words in the stream that tripped it wear a grey pill.

        A word that was waiting and is not any more has been answered: it is read again, so a word that was added (or matched to a
        known one) turns into an ordinary purple pill and a word that was ignored (or whose row was discarded) is plain text again.
        """
        waiting = [tokens for tokens in (tokenize(term) for term in terms) if tokens]
        flat: list[tuple[str, int]] = []                  # every token of the finished words, and the word it came from
        for index, (word, match) in enumerate(self._stream_words):
            flat += [(token, index) for token in tokenize(word)] if not match.command else []
        marked: dict[int, int] = {}                       # word index -> the span of the term it belongs to
        for tokens in waiting:
            size = len(tokens)
            for start in range(len(flat) - size + 1):
                if [t for t, _ in flat[start:start + size]] == tokens:
                    self._pending_span -= 1
                    for _, index in flat[start:start + size]:
                        marked.setdefault(index, self._pending_span)
        old = self._stream_words
        words: list[tuple[str, WordMatch]] = []
        released: list[int] = []                          # words that were waiting and are not
        for index, (word, match) in enumerate(old):
            if index in marked:
                words.append((word, WordMatch(False, pending=True, span=marked[index])))
            elif match.pending:
                words.append((word, match))
                released.append(index)
            else:
                words.append((word, match))
        for run in _runs(released, old):                  # (one term's words are read together, as when they were heard)
            heard = self._classify_words([old[i][0] for i in run])
            self._answered_span += 100
            for index, now in zip(run, heard):
                words[index] = (old[index][0], dataclasses.replace(now, pending=False, span=None if now.span is None else self._answered_span + now.span))
        if words != old:
            self._stream_words = words
            self._render_stream()

    def _render_stream(self) -> None:
        """Draw the stream in italics.

        Understood words are pills in the theme colour; words that tripped the Term Helper (still waiting there) are muted grey pills.
        Words still being spoken start in the normal text colour; once a phrase is final, the other words that were not understood are
        muted text.
        """
        pill = f"background-color:{self._accent}; color:{self._on_accent}"
        grey_fill, grey_ink = grey_pill(self._text_color)
        waiting = f"background-color:{grey_fill}; color:{grey_ink}"
        muted = self.stream.palette().placeholderText().color().name()

        def draw(items, unknown_color: str) -> str:
            pieces: list[str] = []
            run: list[str] = []                         # the words of the value being gathered: one pill for all of them
            run_key = None
            run_style = pill

            def close() -> None:
                nonlocal run, run_key
                if run:
                    pieces.append(f'<span style="{run_style}">&nbsp;{" ".join(run)}&nbsp;</span>')
                run, run_key = [], None

            for word, match in items:
                if (match.known or match.pending) and match.span is not None:
                    key = (match.span, match.pending)
                    if run and key != run_key:
                        close()
                    run.append(html.escape(word))
                    run_key, run_style = key, waiting if match.pending else pill
                    continue
                close()
                if match.known or match.pending:
                    pieces.append(f'<span style="{waiting if match.pending else pill}">&nbsp;{html.escape(word)}&nbsp;</span>')
                else:
                    pieces.append(f'<span style="color:{unknown_color}">{html.escape(word)}</span>')
            close()
            return " ".join(pieces)

        parts = [p for p in (draw(self._stream_words, muted), draw(self._stream_partial, self._text_color)) if p]
        self.stream.setHtml(f'<div style="font-style:italic">{" ".join(parts)}</div>' if parts else "")
        self.stream.fit()
        bar = self.stream.verticalScrollBar()
        bar.setValue(bar.maximum())                    # keep the newest words in view once it scrolls
        self._refresh_grid()                           # a column just heard comes to the top of the grid, as the word is heard

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
        """Show the last saved row as a short, muted summary at the right of the footer: ``Last Saved: Row 7 · 4 Fields``.

        Only the count is shown; the tooltip lists every field (capped at a screenful).
        """
        parts = [row] if row and row != "Row saved" else []
        tip = row
        if record:
            items = [(k, (v.isoformat() if isinstance(v, dt.date) else str(v)).replace("\n", ", ")) for k, v in record.items()]
            count = len(items)
            parts.append(f"{count} Field{'s' if count != 1 else ''}")
            tip = f"{row}\n{tooltip_lines(items)}"
        self.last_label.setFullText("Last Saved: " + " · ".join(p for p in parts if p), tip)
        self._has_last_saved = True
        self._refresh_visibility()

    def append_log(self, text: str, level: str = "info", reveal: bool = True, safe: str | tuple | None = None) -> None:
        """Add a timestamped line to the log (and to the log file, for troubleshooting).

        *safe* is the same event as it may be told in a support report: a fixed string, or ``(format, *args)`` whose
        arguments are numbers, names from a fixed list or an error's class name (see ``diagnostics.syslog``). It goes
        to the log file as a ``SYS`` line beside the full text, which is ``USR`` and stays on this computer. Leave it
        out when the event has no safe wording: nothing is then ever reported.

        *level* is ``"info"``, ``"warning"`` or ``"error"``. Warnings and errors say so after the time and are
        coloured (every error the same red); an error also opens the log if it is collapsed, so it is seen (unless *reveal* is
        False: the user is already being shown the way out, by the interface itself).
        """
        label, color = LOG_LEVELS.get(level, LOG_LEVELS["info"])
        text = sentence(text)
        python_level = {"error": logging.ERROR, "warning": logging.WARNING}.get(level, logging.INFO)
        logging.getLogger("quill").log(python_level, text)
        if safe is not None:
            fmt, *args = (safe,) if isinstance(safe, str) else safe
            diagnostics.syslog().log(python_level, fmt, *args)
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
            self.error_button.setToolTip(f"{text}\nClick to go back to the full window and the Log.")
            self._refresh_visibility()
            if self._log_collapsed and reveal:
                self._set_collapsed("log", False)

    def clear_mini_error(self) -> None:
        """The error has been seen (or a row saved since): take the mini view's red "!" away."""
        if self._mini_error:
            self._mini_error = ""
            self._refresh_visibility()

    def set_listening_indicator(self, active: bool) -> None:
        """Update the button (icon, text, colours, sound lines)."""
        changed = active != self._listening
        self._listening = active
        self.toggle_button.set_active(active)
        slide = (changed and self._window is not None and self._window.isVisible() and self.animation_ms > 0
                 and not self._view_mini)
        if slide:
            self._begin_next_slide(active)
        self._refresh_visibility()
        if slide:
            self._run_next_slide(active)

    def _begin_next_slide(self, appearing: bool) -> None:
        """Before the layout is refreshed: stop an earlier slide and, when the button is coming, start it squeezed shut."""
        if self._next_animation is not None:
            self._next_animation.stop()
        self._next_animation = QVariantAnimation(self.next_button)
        if appearing:
            self.next_button.setVisible(True)
            self.next_button.setFixedWidth(0)

    def _run_next_slide(self, appearing: bool) -> None:
        """The Next Row button eases in beside Start (which gives it the room, getting narrower) or eases out again (Start
        grows back); the width changes smoothly instead of jumping."""
        button = self.next_button
        full = button.height() + 14
        animation = self._next_animation
        effect = QGraphicsOpacityEffect(button)
        button.setGraphicsEffect(effect)
        animation.setDuration(max(self.animation_ms, 1))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(0.0 if appearing else 1.0)
        animation.setEndValue(1.0 if appearing else 0.0)

        def step(value) -> None:
            button.setFixedWidth(max(int(full * float(value)), 0))
            effect.setOpacity(float(value))

        def done() -> None:
            if self._next_animation is animation:
                self._next_animation = None
                button.setGraphicsEffect(None)
                button.setVisible(self._listening)
                button.setFixedSize(full, button.height())

        animation.valueChanged.connect(step)
        animation.finished.connect(done)
        step(animation.startValue())
        animation.start()

    def set_quiet_countdown(self, seconds: int | None, share: float | None = None) -> None:
        """Show how many seconds are left before Quill stops listening because it is quiet (None hides it); *share* is the exact
        part of the quiet time left (0 to 1), which the ring empties by smoothly."""
        self._countdown_seconds = seconds
        self._countdown_share = share
        self._render_countdown()

    def _render_countdown(self) -> None:
        seconds = self._countdown_seconds
        self.toggle_button.set_countdown(seconds, self._countdown_share)

    def add_demo_menu(self, scenarios) -> None:
        """Add a **Demo** menu with one entry per ``(label, action)`` (only in demo mode; see :mod:`quill.demo`)."""
        menu = self._window.menuBar().addMenu("Demo")
        for label, action in scenarios:
            menu.addAction(label, action)

    def refresh_icons(self, text_color: str = "#1F1E1D", on_accent: str = "#FFFFFF",
                      accent: str = "#7A55C2") -> None:
        """Redraw the button icons and the count pill for the current theme colours."""
        self._on_accent, self._text_color, self._accent = on_accent, text_color, accent
        if self._window is None:
            return                      # not built yet; setup() draws them
        self.panel.set_colors(text_color, accent)
        self.row_grip.set_color(text_color)
        self.log_toggle.set_colors(text_color, text_color)
        self.export_log_button.set_colors(text_color, text_color)
        self._render_stream()
        self.mini_button.setIcon(make_icon("maximize" if self._view_mini else "minimize", text_color, 16))
        self.mini_button.setToolTip("Back to the Full Window" if self._view_mini else "Mini View")
        self.mini_button.setAccessibleName("Back to the Full Window" if self._view_mini else "Mini View")
        self.badge_label.set_colors(on_accent, accent)
        self.row_table.set_delete_colors(accent, on_accent)
        self.row_table.set_pill_colors(accent, on_accent)
        self.update_current_row(self._row_fields)         # the grid's first column takes its colour from the theme
        self.undo_button.setIcon(make_icon("undo", text_color, 18))
        self.help_button.setIcon(make_icon("question", text_color, 18))
        self.turn_button.setIcon(make_icon("turn", text_color, 18))
        self.next_button.setIcon(make_icon("next", accent, 18))
        self.settings_button.setIcon(make_icon("settings", text_color, 18, badge=self._update_alert))
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


class _SizeKeeper(QObject):
    """Remembers the main window's size when it is hidden and has it given back when it is shown (see
    :meth:`MainWindow.restore_after_reshow`)."""

    def __init__(self, window: QWidget, owner: "MainWindow") -> None:
        super().__init__(window)
        self._window, self._owner = window, owner

    def eventFilter(self, obj, event) -> bool:                       # noqa: N802 (Qt name)
        if obj is self._window:
            if event.type() == QEvent.Type.Hide and not self._window.isMinimized():
                self._owner.remember_for_reshow()
            elif event.type() == QEvent.Type.Show and not event.spontaneous():
                self._owner.restore_after_reshow()
            elif event.type() == QEvent.Type.Resize:
                self._owner.fit_panel()
        return False


class _FooterPlacer(QObject):
    """Keeps the footer at the bottom of the window as it is resized."""

    def __init__(self, root: QWidget, footer: QWidget, owner: "MainWindow") -> None:
        super().__init__(root)
        self._owner = owner

    def eventFilter(self, obj, event) -> bool:                      # noqa: N802 (Qt name)
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
            self._owner.place_footer()
        return False


class _GripPlacer(QObject):
    """Keeps a resize grip on the bottom edge of the box it belongs to."""

    def __init__(self, box: QWidget, grip: ResizeGrip, drop: int = 0) -> None:
        super().__init__(box)
        self._box, self._grip, self._drop = box, grip, drop          # (*drop*: px the grip sits below the box's bottom edge)

    def eventFilter(self, obj, event) -> bool:                      # noqa: N802 (Qt name)
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.Hide):
            box, grip = self._box, self._grip
            grip.setVisible(box.isVisible() and getattr(grip, "allowed", True))
            grip.setGeometry(box.x(), box.y() + box.height() - grip.height() + self._drop, box.width(), grip.height())
            grip.raise_()
            QTimer.singleShot(0, grip.update)                       # (the columns settle after this event: draw the dot where the line ended up)
        return False


def _runs(indices: list[int], words: list[tuple[str, WordMatch]]) -> list[list[int]]:
    """*indices* (ascending) split into runs of neighbours that waited as one term (the same span)."""
    runs: list[list[int]] = []
    for index in indices:
        if runs and index == runs[-1][-1] + 1 and words[index][1].span == words[runs[-1][-1]][1].span:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs
