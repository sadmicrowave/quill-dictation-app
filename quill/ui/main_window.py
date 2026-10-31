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
from typing import Callable

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QLayout, QMainWindow, QPlainTextEdit, QSizePolicy,
    QPushButton, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from quill.ui.chrome import set_always_on_top
from quill.ui.icons import make_icon
from quill.ui.theme import apply_spacing
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
        on_workbook: Called with a workbook name picked in the combo box.
        on_download_model: Called when the user asks to download the speech model.
        on_sorting: Called when the user opens the Needs-sorting list.
        on_undo: Called when the user presses Undo (takes back the last sorting answer).
        on_log_toggled: Called with True/False when the user collapses/expands the log.
        on_row_toggled: Same, for the Current row section.
        on_mini_toggled: Called with True/False when the user enters/leaves the mini view.
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
        on_row_toggled: Callable[[bool], None] | None = None,
        row_collapsed: bool = False,
        on_mini_toggled: Callable[[bool], None] | None = None,
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
        self._on_row_toggled = on_row_toggled or (lambda collapsed: None)
        self._row_collapsed = row_collapsed
        self._on_mini_toggled = on_mini_toggled or (lambda mini: None)
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
        self._text_color = "#1F1E1D"
        self._accent = "#C9623F"
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
        self.mini_button = QToolButton()                # just an icon (no box), like the Log heading
        self.mini_button.setProperty("flatIcon", True)
        self.mini_button.setAutoRaise(True)
        self.mini_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mini_button.clicked.connect(lambda: self.set_mini(not self._mini, notify=True))
        row = QHBoxLayout()
        for widget in (self.dot, self.state_label):
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(self.toggle_button)
        row.addWidget(self.settings_button)
        row.addWidget(self.mini_button)
        layout.addLayout(row)
        self._layout, self._status_row = layout, row

        # --- workbook row
        self.workbook_combo = QComboBox()
        self.workbook_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.workbook_combo.activated.connect(
            lambda index: self._on_workbook(self.workbook_combo.itemText(index))
        )
        self.sheet_label = QLabel("Sheet: –")
        self.workbook_row = QWidget()                   # one widget so the mini view can hide the row whole
        row = QHBoxLayout(self.workbook_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.workbook_combo, 1)
        layout.addWidget(self.workbook_row)
        layout.addWidget(self.sheet_label)

        # --- current row
        self.row_toggle = self._section_toggle("row", "Show or hide the row being built")
        layout.addWidget(self.row_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.row_table = QTableWidget(0, 2)
        self.row_table.horizontalHeader().setVisible(False)
        self.row_table.verticalHeader().setVisible(False)
        self.row_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.row_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.row_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.row_table.setMaximumHeight(150)
        self._row_height = self.row_table.verticalHeader().defaultSectionSize()
        layout.addWidget(self.row_table)
        self.last_label = ElidedLabel("Last Saved: –")      # one line however much was saved
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
        title = QLabel("Needs Sorting")
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
        self.undo_button = QPushButton("↶ Undo")
        self.undo_button.setToolTip("Take back the last sorting answer; press again to keep stepping back")
        self.undo_button.clicked.connect(lambda: self._on_undo())
        self.undo_button.setVisible(False)
        layout.addWidget(self.undo_button)

        # --- log
        self.log_toggle = self._section_toggle("log", "Show or hide the log")
        layout.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(MAX_LOG_LINES)
        layout.addWidget(self.log, 1)

        # --- footer
        self.footer = QLabel()
        self.footer.setWordWrap(True)
        self.footer.setVisible(False)
        self.download_button = QPushButton("Download Speech Model")
        self.download_button.clicked.connect(lambda: self._on_download_model())
        self.download_button.setVisible(False)
        layout.addWidget(self.footer)
        layout.addWidget(self.download_button)

        window.setCentralWidget(central)
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)   # lets opacity < 100 show through
        self._window = window
        self.refresh_icons()
        self._set_collapsed("row", self._row_collapsed)
        self._set_collapsed("log", self._log_collapsed)
        if self._mini:
            self.set_mini(True)
        else:
            self._refresh_visibility()
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
        self._set_collapsed("log", collapsed, notify)

    @property
    def row_collapsed(self) -> bool:
        return self._row_collapsed

    def set_row_collapsed(self, collapsed: bool, notify: bool = False) -> None:
        """Hide or show the Current row table, like the log."""
        self._set_collapsed("row", collapsed, notify)

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
        self.toggle_button.setText("" if mini else ("Stop" if self._listening else "Start"))
        self._place_sorting_button(mini)
        self._set_margins(mini)
        self._refresh_visibility()
        self.refresh_icons(self._text_color, self._on_accent, self._accent)

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

    def _set_margins(self, mini: bool) -> None:
        if mini:
            self._layout.setContentsMargins(10, 8, 10, 8)
            self._layout.setSpacing(6)
        else:
            apply_spacing(self._window)

    def _place_sorting_button(self, mini: bool) -> None:
        """In the mini view the Needs-sorting count sits in the status row; otherwise on its own row."""
        in_row = self._status_row.indexOf(self.sorting_button) >= 0
        if mini and not in_row:
            self._layout.removeWidget(self.sorting_button)
            self._status_row.insertWidget(self._status_row.indexOf(self.toggle_button), self.sorting_button)
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
        self.mini_button.setVisible(not self._native_mini_button)           # the title bar has its own
        for widget in (self.settings_button, self.workbook_row, self.sheet_label,
                       self.row_toggle, self.last_label, self.log_toggle):
            widget.setVisible(full)
        self.undo_button.setVisible(full and self._undo_count > 0)
        self.log.setVisible(full and not self._log_collapsed)
        self.row_table.setVisible(self._view_mini or not self._row_collapsed)    # the mini view always shows the row
        self.footer.setVisible(full and bool(self._footer_text))
        self.download_button.setVisible(full and self._offer_download)
        self.sorting_button.setVisible(self._sorting_count > 0)
        self.sorting_title.setVisible(full)                               # just the count pill when mini
        self.row_table.setMaximumHeight(66 if self._view_mini else 150)
        self.row_table.setMinimumHeight(48 if self._view_mini else 0)
        self.row_table.verticalHeader().setDefaultSectionSize(22 if self._view_mini else self._row_height)
        self.sorting_button.setMinimumHeight(self.toggle_button.sizeHint().height() if self._view_mini
                                             else (self.sorting_button.fontMetrics().height() * 2 + 4))
        self.sorting_button.setToolTip("Needs Sorting" if self._view_mini else "")

    def _section_toggle(self, name: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setProperty("heading", True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tip)
        button.clicked.connect(lambda: self._set_collapsed(name, not self._collapsed(name), notify=True))
        return button

    def _collapsed(self, name: str) -> bool:
        return self._log_collapsed if name == "log" else self._row_collapsed

    def _set_collapsed(self, name: str, collapsed: bool, notify: bool = False) -> None:
        """Collapse or expand a section, and resize the window so no blank gap is left.

        The window gives back the height the section used when it collapses and
        takes the same height again when it reopens.
        """
        body, toggle, title = ((self.log, self.log_toggle, "Log") if name == "log"
                               else (self.row_table, self.row_toggle, "Current Row"))
        was = self._applied.get(name, False)      # what is on screen now (not the saved preference)
        window = self._window
        shown = window is not None and window.isVisible()
        height = self._height_now() if window is not None else 0
        spacing = window.centralWidget().layout().spacing() if window is not None else 0
        used = body.height() + max(spacing, 0)
        if name == "log":
            self._log_collapsed = collapsed
        else:
            self._row_collapsed = collapsed
        self._applied[name] = collapsed
        self._refresh_visibility()
        if window is not None and not self._view_mini:   # (the mini view hides sections whatever their state)
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
            (self._on_log_toggled if name == "log" else self._on_row_toggled)(collapsed)

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
        self.last_label.setFullText("Last Saved: " + " · ".join(p for p in parts if p), tip)

    def append_log(self, text: str) -> None:
        """Add a timestamped line to the log."""
        self.log.appendPlainText(f"{dt.datetime.now():%H:%M:%S}  {text}")

    def set_listening_indicator(self, active: bool) -> None:
        """Update the active light, label and button."""
        self._listening = active
        self.dot.setStyleSheet(f"color: {COLOR_ACTIVE if active else COLOR_IDLE}; font-size: 18px;")
        self.state_label.setText("Listening" if active else "Not Listening")
        self.toggle_button.setText("" if self._view_mini else ("Stop" if active else "Start"))
        self.toggle_button.setToolTip("Stop Listening" if active else "Start Listening")
        self.toggle_button.setAccessibleName("Stop Listening" if active else "Start Listening")
        self.toggle_button.setIcon(self._icon("stop" if active else "play", self._on_accent))

    def _icon(self, name: str, color: str):
        return make_icon(name, color)

    def refresh_icons(self, text_color: str = "#1F1E1D", on_accent: str = "#FFFFFF",
                      accent: str = "#C9623F") -> None:
        """Redraw the button icons and the count pill for the current theme colours."""
        self._on_accent, self._text_color, self._accent = on_accent, text_color, accent
        if self._window is None:
            return                      # not built yet; setup() draws them
        self.mini_button.setIcon(make_icon("maximize" if self._view_mini else "minimize", text_color, 16))
        self.mini_button.setToolTip("Back to the Full Window" if self._view_mini else "Mini View")
        self.mini_button.setAccessibleName("Back to the Full Window" if self._view_mini else "Mini View")
        self.badge_label.set_colors(on_accent, accent)
        self.settings_button.setIcon(make_icon("settings", text_color, 18))
        self.toggle_button.setIcon(make_icon("stop" if self._listening else "play", on_accent, 16))

    def set_undo_count(self, count: int) -> None:
        """Show "Undo (n)" while there is a sorting answer to take back."""
        self._undo_count = count
        self._refresh_visibility()
        self.undo_button.setText(f"↶ Undo ({count})")

    def set_sorting_count(self, count: int) -> None:
        """Show the accent-coloured "Needs sorting" button, with *count* as a pill, while terms wait."""
        self._sorting_count = count
        self._refresh_visibility()
        self.badge_label.setText(str(count))
        self.sorting_button.setAccessibleName(f"Needs Sorting ({count})")

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
