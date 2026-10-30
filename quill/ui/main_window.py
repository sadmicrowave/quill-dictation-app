"""Main Quill window — compact, OS-native, dark-mode-aware.

Layout (~340 px wide):
  status row:  [● Listening]  [Start/Stop]  [Settings…]
  workbook row: [workbook picker] [Refresh]     Sheet: <name>
  Current row (the fields being built, one line per column)
  Last saved row
  Scrolling action log
  Footer message (model / connection status)

The window only displays state and reports user intent through the callbacks
passed to the constructor; it holds no dictation logic.
"""
from __future__ import annotations
import datetime as dt
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from quill.ui.icons import make_icon
from quill.ui.widgets import ElidedLabel, Pill, tooltip_lines

#: Active-light colours (the same hues are used by the tray icon).
COLOR_ACTIVE = "#34c759"
COLOR_IDLE = "#8e8e93"

#: Lines kept in the log before the oldest are dropped.
MAX_LOG_LINES = 500


class MainWindow:
    """The compact status window.

    Args:
        on_toggle: Called when the user presses Start/Stop; receives the
            *desired* listening state.
        on_settings: Called when the user opens Settings.
        on_refresh: Called when the user presses Refresh.
        on_workbook: Called with a workbook name picked in the combo box.
        on_download_model: Called when the user asks to download the speech model.
        on_sorting: Called when the user opens the Needs-sorting list.
        on_undo: Called when the user presses Undo (takes back the last sorting answer).
        on_log_toggled: Called with True/False when the user collapses/expands the log.
        log_collapsed: Start with the log collapsed.
    """

    def __init__(
        self,
        on_toggle: Callable[[bool], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_refresh: Callable[[], None] | None = None,
        on_workbook: Callable[[str], None] | None = None,
        on_download_model: Callable[[], None] | None = None,
        on_sorting: Callable[[], None] | None = None,
        on_undo: Callable[[], None] | None = None,
        on_log_toggled: Callable[[bool], None] | None = None,
        log_collapsed: bool = False,
    ) -> None:
        self._on_toggle = on_toggle or (lambda active: None)
        self._on_settings = on_settings or (lambda: None)
        self._on_refresh = on_refresh or (lambda: None)
        self._on_workbook = on_workbook or (lambda name: None)
        self._on_download_model = on_download_model or (lambda: None)
        self._on_sorting = on_sorting or (lambda: None)
        self._on_undo = on_undo or (lambda: None)
        self._on_log_toggled = on_log_toggled or (lambda collapsed: None)
        self._log_collapsed = log_collapsed
        self._window: QMainWindow | None = None
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
        layout = QVBoxLayout(central)

        # --- status row
        self.dot = QLabel("●")
        self.state_label = QLabel()
        self.toggle_button = QPushButton()
        self.toggle_button.setProperty("accent", True)
        self.toggle_button.clicked.connect(lambda: self._on_toggle(not self._listening))
        self.settings_button = QPushButton()            # icon only; refresh_icons() draws it
        self.settings_button.setProperty("iconOnly", True)
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(lambda: self._on_settings())
        row = QHBoxLayout()
        for widget in (self.dot, self.state_label):
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(self.toggle_button)
        row.addWidget(self.settings_button)
        layout.addLayout(row)

        # --- workbook row
        self.workbook_combo = QComboBox()
        self.workbook_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.workbook_combo.activated.connect(
            lambda index: self._on_workbook(self.workbook_combo.itemText(index))
        )
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-read the workbook's lists and columns")
        refresh.clicked.connect(lambda: self._on_refresh())
        self.sheet_label = QLabel("Sheet: –")
        row = QHBoxLayout()
        row.addWidget(self.workbook_combo, 1)
        row.addWidget(refresh)
        layout.addLayout(row)
        layout.addWidget(self.sheet_label)

        # --- current row
        layout.addWidget(self._heading("Current row"))
        self.row_table = QTableWidget(0, 2)
        self.row_table.horizontalHeader().setVisible(False)
        self.row_table.verticalHeader().setVisible(False)
        self.row_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.row_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.row_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.row_table.setMaximumHeight(150)
        layout.addWidget(self.row_table)
        self.last_label = ElidedLabel("Last saved: –")      # one line however much was saved
        self.last_label.setProperty("note", True)          # smaller italic supporting text
        layout.addWidget(self.last_label)

        # "Needs sorting (3)": filled in the accent colour, the count as an inline pill.
        self.sorting_button = QPushButton()
        self.sorting_button.setProperty("accent", True)
        self.sorting_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sorting_button.setMinimumHeight(self.sorting_button.fontMetrics().height() * 2 + 4)
        inner = QHBoxLayout(self.sorting_button)
        inner.setContentsMargins(12, 0, 12, 0)
        inner.addStretch(1)
        title = QLabel("Needs sorting")
        self.badge_label = Pill("0")
        for part in (title, self.badge_label):
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)   # clicks reach the button
            inner.addWidget(part, 0, Qt.AlignmentFlag.AlignVCenter)   # the pill hugs its text
        inner.addStretch(1)
        self.sorting_button.clicked.connect(lambda: self._on_sorting())
        self.sorting_button.setVisible(False)
        layout.addWidget(self.sorting_button)
        self.undo_button = QPushButton("↶ Undo")
        self.undo_button.setToolTip("Take back the last sorting answer; press again to keep stepping back")
        self.undo_button.clicked.connect(lambda: self._on_undo())
        self.undo_button.setVisible(False)
        layout.addWidget(self.undo_button)

        # --- log
        self.log_toggle = QToolButton()
        self.log_toggle.setProperty("heading", True)
        self.log_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_toggle.setToolTip("Show or hide the log")
        self.log_toggle.clicked.connect(lambda: self.set_log_collapsed(not self._log_collapsed, notify=True))
        layout.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(MAX_LOG_LINES)
        layout.addWidget(self.log, 1)

        # --- footer
        self.footer = QLabel()
        self.footer.setWordWrap(True)
        self.download_button = QPushButton("Download speech model")
        self.download_button.clicked.connect(lambda: self._on_download_model())
        self.download_button.setVisible(False)
        layout.addWidget(self.footer)
        layout.addWidget(self.download_button)

        window.setCentralWidget(central)
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)   # lets opacity < 100 show through
        self._window = window
        self.refresh_icons()
        self.set_log_collapsed(self._log_collapsed)
        self.set_listening_indicator(False)

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
        self._log_collapsed = collapsed
        self.log.setVisible(not collapsed)
        self.log_toggle.setText(f"Log  {'▾' if collapsed else '▴'}")
        self.log_toggle.setToolTip("Show the log" if collapsed else "Hide the log")
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

    def update_workbooks(self, names: list[str], current: str = "") -> None:
        """Replace the picker's choices; select *current* if given."""
        self.workbook_combo.blockSignals(True)
        self.workbook_combo.clear()
        self.workbook_combo.addItems(names)
        if current:
            self.update_workbook(current)
        self.workbook_combo.blockSignals(False)

    def update_sheet(self, name: str) -> None:
        self.sheet_label.setText(f"Sheet: {name}")

    def update_current_row(self, fields: dict[str, object]) -> None:
        """Show the record being built, one column per line."""
        self.row_table.setRowCount(len(fields))
        for r, (column, value) in enumerate(fields.items()):
            text = value.isoformat() if isinstance(value, dt.date) else str(value)
            for c, content in enumerate((column, text)):
                item = QTableWidgetItem(content)
                if c == 0:
                    item.setForeground(self.row_table.palette().placeholderText())
                self.row_table.setItem(r, c, item)

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
        self.last_label.setFullText("Last saved: " + " · ".join(p for p in parts if p), tip)

    def append_log(self, text: str) -> None:
        """Add a timestamped line to the log."""
        self.log.appendPlainText(f"{dt.datetime.now():%H:%M:%S}  {text}")

    def set_listening_indicator(self, active: bool) -> None:
        """Update the active light, label and button."""
        self._listening = active
        self.dot.setStyleSheet(f"color: {COLOR_ACTIVE if active else COLOR_IDLE}; font-size: 18px;")
        self.state_label.setText("Listening" if active else "Not listening")
        self.toggle_button.setText("Stop" if active else "Start")
        self.toggle_button.setIcon(self._icon("stop" if active else "play", self._on_accent))

    def _icon(self, name: str, color: str):
        return make_icon(name, color)

    def refresh_icons(self, text_color: str = "#1F1E1D", on_accent: str = "#FFFFFF",
                      accent: str = "#C9623F") -> None:
        """Redraw the button icons and the count pill for the current theme colours."""
        self._on_accent = on_accent
        if self._window is None:
            return                      # not built yet; setup() draws them
        self.badge_label.set_colors(on_accent, accent)
        self.settings_button.setIcon(make_icon("settings", text_color, 18))
        self.toggle_button.setIcon(make_icon("stop" if self._listening else "play", on_accent, 16))

    def set_undo_count(self, count: int) -> None:
        """Show "Undo (n)" while there is a sorting answer to take back."""
        self.undo_button.setVisible(count > 0)
        self.undo_button.setText(f"↶ Undo ({count})")

    def set_sorting_count(self, count: int) -> None:
        """Show the accent-coloured "Needs sorting" button, with *count* as a pill, while terms wait."""
        self.sorting_button.setVisible(count > 0)
        self.badge_label.setText(str(count))
        self.sorting_button.setAccessibleName(f"Needs sorting ({count})")

    def set_footer(self, text: str, offer_download: bool = False) -> None:
        """Show a status message; optionally reveal the model-download button."""
        self.footer.setText(text)
        self.download_button.setVisible(offer_download)
        self.download_button.setEnabled(True)

    @property
    def listening(self) -> bool:
        """Last state passed to :meth:`set_listening_indicator`."""
        return self._listening
