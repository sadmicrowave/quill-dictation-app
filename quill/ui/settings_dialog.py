"""The Settings window: a sidebar of groups with a search box, and rows of settings.

Layout (like Claude's own settings):

    [ Search            ]  | Appearance
    Preferences            |   Theme .............. [ auto | light | dark ]
      General              |   Accent colour ...... Terracotta  v
      Appearance           |   ...
      Sounds               |
    Voice and commands     |
      Keywords             |                              [Cancel] [OK]

Each setting is a :class:`SettingRow` (name, muted help text, control). The
search box filters the rows of every group and hides groups with no match.
Nothing is saved until the user confirms with OK, and a keyword table that
fails validation keeps the window open with the reasons shown.
"""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from quill.config.settings import (
    AUTO_STOP_RANGE,
    BLUR_RANGE,
    FONT_SIZE_RANGE,
    HISTORY_LIMIT_RANGE,
    OPACITY_RANGE,
    SPACINGS,
    THEMES,
)
from quill.feedback import ECHO_WORDS, MODE_LABELS, MODES, PACKS
from quill.licensing import LicenseService
from quill.parser.commands import Action
from quill.ui.chrome import apply_chrome
from quill.ui.settings_widgets import (
    FlatCombo,
    GuardedCombo,
    GuardedSlider,
    GuardedSpinBox,
    SegmentedControl,
    SettingRow,
    ToggleSwitch,
)
from quill.ui.theme import install_backdrop, ACCENTS, DENSITIES, apply_opacity

if TYPE_CHECKING:
    from quill.config.settings import Settings

#: Actions a user can bind a phrase to (NONE is internal).
BINDABLE_ACTIONS = [a for a in Action if a is not Action.NONE]

#: Sidebar groups: (caption, [page titles]).
GROUPS = [("Preferences", ["General", "Appearance", "Sounds"]),
          ("Voice and Commands", ["Keywords"])]

THEME_ICONS = {"auto": "monitor", "light": "sun", "dark": "moon"}


def action_label(action: Action) -> str:
    """Human-readable action name: ``NEXT_ROW`` -> ``Next Row``."""
    return action.name.replace("_", " ").title()


def _swatch(color: str) -> QIcon:
    """A small round colour chip for the accent picker."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("transparent"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QColor("transparent"))
    painter.drawEllipse(1, 1, 14, 14)
    painter.end()
    return QIcon(pixmap)


def _slider(low: int, high: int, value: int, tip: str) -> tuple[QSlider, QLabel, QWidget]:
    """A horizontal slider with a live "NN%" label; returns (slider, label, container)."""
    slider = GuardedSlider(Qt.Orientation.Horizontal)
    slider.setRange(low, high)
    slider.setValue(value)
    slider.setToolTip(tip)
    label = QLabel(f"{value}%")
    label.setFixedWidth(44)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v: label.setText(f"{v}%"))
    box = QWidget()
    box.setProperty("valueControl", True)               # the settings row gives it the standard control width
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(slider, 1)
    row.addWidget(label)
    return slider, label, box


#: The preferences the controls edit (Cancel puts back just these).
EDITED_PREFERENCES = (
    "theme", "speak_sort_prompts", "auto_voice_sort", "mic_always_on", "auto_stop", "auto_stop_seconds",
    "mini_on_top", "hide_dock_icon", "accent", "spacing", "font_size", "opacity", "sorting_follows_opacity",
    "blur", "history_limit", "feedback", "sound_pack", "echo_style",
)


class SettingsDialog:
    """Modal editor for keywords and preferences.

    Args:
        settings: The Settings object to edit (mutated and saved on OK).
        parent: Optional parent QWidget.
        on_preview: Called with ``(mode, sound_pack, echo_word)`` to play one sample.
        on_change: Called after every control change, once the new values are in
            ``settings.preferences``, so the app can show them live. Cancel puts the
            original values back and calls it again; only OK saves.
    """

    #: The Account page is built but kept out of the window until subscriptions launch.
    SHOW_ACCOUNT = False

    @property
    def _groups(self) -> list:
        return GROUPS + ([("Account", ["Account"])] if self.SHOW_ACCOUNT else [])

    def __init__(self, settings: "Settings", parent=None, on_preview=None, on_change=None,
                 on_open_logs=None, on_help=None, on_download_model=None, model_installed=None) -> None:
        self._on_download_model = on_download_model or (lambda: None)
        self._model_installed = model_installed or (lambda: True)
        self._on_help = on_help
        self._on_done = None                      # called when the non-modal window closes (see open)
        self._on_open_logs = on_open_logs or self._open_log_folder
        self._on_preview = on_preview or (lambda mode, pack, echo: None)
        self._on_change = on_change or (lambda: None)
        self._original: dict = {}
        self._settings = settings
        self._parent = parent
        self._dialog: QDialog | None = None
        self.root: QWidget | None = None
        self.table: QTableWidget | None = None
        self.search: QLineEdit | None = None
        self.nav: QListWidget | None = None
        self.pages: QStackedWidget | None = None
        self.rows: list[SettingRow] = []
        self._page_rows: dict[str, list[SettingRow]] = {}
        self._page_index: dict[str, int] = {}
        self._nav_items: dict[str, QListWidgetItem] = {}
        self.theme_combo: SegmentedControl | None = None
        self.accent_combo: QComboBox | None = None
        self.spacing_combo: QComboBox | None = None
        self.font_spin: QSpinBox | None = None
        self.opacity_slider: QSlider | None = None
        self.blur_slider: QSlider | None = None
        self.feedback_combo: QComboBox | None = None
        self.pack_combo: QComboBox | None = None
        self.echo_combo: QComboBox | None = None
        self.history_spin: QSpinBox | None = None
        self.speak_check: ToggleSwitch | None = None
        self.auto_sort_check: ToggleSwitch | None = None
        self.mic_check: ToggleSwitch | None = None
        self.auto_stop_check: ToggleSwitch | None = None
        self.auto_stop_spin: QSpinBox | None = None
        self.mini_top_check: ToggleSwitch | None = None
        self.dock_check: ToggleSwitch | None = None
        self.sorting_opacity_check: ToggleSwitch | None = None
        self.model_button: QPushButton | None = None
        self.model_row: SettingRow | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    #: The Settings window fades with the window-opacity setting but never below this, so it stays readable.
    MIN_DIALOG_OPACITY = 70

    def exec(self) -> bool:
        """Show modally and wait. Returns True if the user saved changes. (The app itself uses :meth:`open`.)"""
        self._prepare()
        try:
            return self._dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._remember_position()

    def open(self, on_done=None) -> None:
        """Show the window without blocking, so the rest of the application (and quitting it) stays available.

        Args:
            on_done: Called with True (saved) or False (cancelled) once the window closes.
        """
        self._prepare()
        self._on_done = on_done
        self._dialog.finished.connect(self._finished)
        self._dialog.setModal(False)
        self._dialog.show()

    def _prepare(self) -> None:
        """Build and dress the window (the pointer is held steady while that happens)."""
        QGuiApplication.setOverrideCursor(Qt.CursorShape.ArrowCursor)
        try:
            self.build(lazy=True)
            self._restore_position()
            self._apply_dialog_look()
            self._install_help_icon()
        finally:
            QGuiApplication.restoreOverrideCursor()

    def _finished(self, result: int) -> None:
        self._remember_position()
        if self._on_done is not None:
            self._on_done(result == QDialog.DialogCode.Accepted)

    def bring_forward(self) -> None:
        """Raise this window (it is already open)."""
        if self._dialog is not None:
            self._dialog.raise_()
            self._dialog.activateWindow()

    def close_now(self) -> None:
        """Close the window without saving (used when the whole app is quitting)."""
        if self._dialog is not None:
            self._dialog.reject()

    def _restore_position(self) -> None:
        """Open on the page that was open last time, at the size it had."""
        prefs = self._settings.preferences
        page = str(prefs.get("settings_page", ""))
        if page in self._nav_items:
            self.nav.setCurrentRow(self._nav_row(page))
        width, height = int(prefs.get("settings_width", 0)), int(prefs.get("settings_height", 0))
        if width >= 720 and height >= 520:
            self._dialog.resize(width, height)

    def _remember_position(self) -> None:
        """Keep the open page and the window size for next time (saved even if the changes were cancelled)."""
        current = self.nav.currentItem() if self.nav is not None else None
        title = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        if title and self._dialog is not None:
            prefs = self._settings.preferences
            prefs["settings_page"] = title
            prefs["settings_width"], prefs["settings_height"] = self._dialog.width(), self._dialog.height()
            self._settings.save()

    def _install_help_icon(self) -> None:
        """Put a "?" in the title bar (macOS) that opens the Settings help page."""
        from quill.ui.chrome import SYMBOL_HELP, add_titlebar_button
        self._help_icon = add_titlebar_button(self._dialog, lambda: self.open_help(), symbol=SYMBOL_HELP,
                                              tip="Help", side="left")

    def open_help(self, topic: str = "settings") -> None:
        """Show the help window on the Settings page. It belongs to this dialog, which is modal, so it stays usable."""
        if self._on_help is not None:
            self._on_help(topic)
            return
        from PySide6.QtWidgets import QApplication

        from quill.ui.help_window import HelpWindow
        if getattr(self, "_help", None) is None:
            self._help = HelpWindow(parent=self._dialog)
            self._help.setup()
            self._help.restyle(self._settings.preferences, QApplication.instance())
        self._help.show(topic)

    def _apply_dialog_look(self) -> None:
        """Give this window the OS title-bar styling, blur and (floored) opacity."""
        from PySide6.QtWidgets import QApplication

        from quill.ui.theme import colors_for, is_dark
        app = QApplication.instance()
        if app is None or self._dialog is None:
            return
        prefs = self._settings.preferences
        dark = is_dark(app)
        opacity = max(int(prefs["opacity"]), self.MIN_DIALOG_OPACITY)
        colors = colors_for(dark, str(prefs["accent"]))
        apply_opacity(self.root, opacity, int(prefs["blur"]))        # first: Qt marks a fully opaque window opaque
        apply_chrome(self._dialog, dark, colors, opacity=opacity, blur=int(prefs["blur"]))
        self.theme_combo.refresh_icons(colors["text"])               # the Theme icons follow the light / dark colours

    def build(self, lazy: bool = False) -> QDialog:
        """Construct the dialog widgets (separate from exec for testing).

        Args:
            lazy: Leave the Keywords page (a table with a drop-down on every row, the slowest part by far)
                empty until it is first opened or searched, so the window appears at once.
        """
        self._lazy_keywords = lazy
        dialog = QDialog(self._parent)
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)    # paint the themed background
        dialog.setWindowTitle("Quill Settings")
        dialog.resize(920, 740)
        dialog.setMinimumSize(720, 520)
        shell = QVBoxLayout(dialog)
        shell.setContentsMargins(0, 0, 0, 0)
        root = QWidget()
        root.setObjectName("settingsRoot")

        install_backdrop(root)                              # paints its own (see-through-able) background
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell.addWidget(root)
        self.root = root
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        self._build_pages()
        self._fill_nav()

        footer = QWidget()
        footer.setObjectName("settingsFooter")
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(24, 12, 24, 14)
        foot.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(lambda: self.try_accept(dialog))
        box.rejected.connect(dialog.reject)
        foot.addWidget(box)
        outer.addWidget(footer)

        self._dialog = dialog
        self.nav.setCurrentRow(self._nav_row("General"))
        self._finish_build(dialog)
        return dialog

    def _finish_build(self, dialog: QDialog) -> None:
        """Pointer cursors on clickable things, and hook every control up for live updates."""
        for button in dialog.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nav.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self._original = copy.deepcopy(self._settings.preferences)
        for control in (self.speak_check, self.auto_sort_check, self.mic_check, self.mini_top_check,
                        self.dock_check, self.auto_stop_check, self.sorting_opacity_check):
            control.toggled.connect(self._live)
        self.auto_stop_check.toggled.connect(self.auto_stop_spin.setEnabled)
        for control in (self.theme_combo, self.accent_combo, self.spacing_combo, self.feedback_combo,
                        self.pack_combo, self.echo_combo):
            control.currentIndexChanged.connect(self._live)
        for control in (self.font_spin, self.history_spin, self.opacity_slider, self.blur_slider, self.auto_stop_spin):
            control.valueChanged.connect(self._live)
        dialog.rejected.connect(self.revert)

    def _live(self, *_args) -> None:
        """A control changed: put the new values in the settings (unsaved) and let the app show them."""
        self._store_preferences()
        self._on_change()                # the app applies the new theme first ...
        self._apply_dialog_look()        # ... so this window is dressed in the new colours, not the old

    def revert(self) -> None:
        """Cancel: put the settings back exactly as they were when the window opened."""
        prefs = self._settings.preferences
        for key in EDITED_PREFERENCES:           # only what this window edits: the window may have changed size or view meanwhile
            if key in self._original:
                prefs[key] = copy.deepcopy(self._original[key])
        self._on_change()

    def _store_preferences(self) -> None:
        """Copy every control's value into ``settings.preferences`` (not saved to disk)."""
        prefs = self._settings.preferences
        prefs["theme"] = THEMES[self.theme_combo.currentIndex()]
        prefs["speak_sort_prompts"] = self.speak_check.isChecked()
        prefs["auto_voice_sort"] = self.auto_sort_check.isChecked()
        prefs["mic_always_on"] = self.mic_check.isChecked()
        prefs["auto_stop"] = self.auto_stop_check.isChecked()
        prefs["auto_stop_seconds"] = self.auto_stop_spin.value()
        prefs["mini_on_top"] = self.mini_top_check.isChecked()
        prefs["hide_dock_icon"] = self.dock_check.isChecked()
        prefs["accent"] = self.accent_combo.currentData()
        prefs["spacing"] = self.spacing_combo.currentData()
        prefs["font_size"] = self.font_spin.value()
        prefs["opacity"] = self.opacity_slider.value()
        prefs["sorting_follows_opacity"] = self.sorting_opacity_check.isChecked()
        prefs["blur"] = self.blur_slider.value()
        prefs["history_limit"] = self.history_spin.value()
        prefs["feedback"] = self.feedback_combo.currentData()
        prefs["sound_pack"] = self.pack_combo.currentData()
        prefs["echo_style"] = self.echo_combo.currentData()

    # ------------------------------------------------------------------ #
    # Sidebar and search                                                   #
    # ------------------------------------------------------------------ #

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("settingsSidebar")
        side.setFixedWidth(236)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(14, 16, 14, 12)
        layout.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        layout.addWidget(self.search)
        self.empty_label = QLabel("No settings match your search.")
        self.empty_label.setProperty("muted", True)
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.currentRowChanged.connect(self._show_page)
        layout.addWidget(self.nav, 1)
        return side

    def _fill_nav(self) -> None:
        for caption, titles in self._groups:
            head = QListWidgetItem(caption)
            head.setFlags(Qt.ItemFlag.NoItemFlags)           # a caption, not selectable
            head.setData(Qt.ItemDataRole.UserRole, None)
            head.setData(Qt.ItemDataRole.AccessibleDescriptionRole, "caption")
            self.nav.addItem(head)
            for title in titles:
                item = QListWidgetItem(title)
                item.setData(Qt.ItemDataRole.UserRole, title)
                self.nav.addItem(item)
                self._nav_items[title] = item
            self._captions = getattr(self, "_captions", []) + [head]

    def _nav_row(self, title: str) -> int:
        return self.nav.row(self._nav_items[title])

    def _show_page(self, row: int) -> None:
        item = self.nav.item(row)
        title = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if title:
            if title == "Keywords":
                self._ensure_keywords()                              # built the first time it is opened
            self.pages.setCurrentIndex(self._page_index[title])

    def filter(self, text: str) -> int:
        """Show only settings matching *text* (every word), hiding empty groups.

        Returns:
            How many settings match. An empty query shows everything.
        """
        query = text.strip()
        if query:
            self._ensure_keywords()                                  # a search has to look in every page
        total = 0
        for title, rows in self._page_rows.items():
            hits = 0
            for row in rows:
                visible = not query or row.matches(query)
                row.setVisible(visible)
                hits += visible
            self._nav_items[title].setHidden(bool(query) and hits == 0)
            total += hits
        shown = {t for t, item in self._nav_items.items() if not item.isHidden()}
        for head, (_, titles) in zip(self._captions, self._groups):
            head.setHidden(not any(t in shown for t in titles))
        self.empty_label.setVisible(bool(query) and total == 0)
        current = self.nav.currentItem()
        if query and (current is None or current.isHidden()) and shown:
            first = next(t for _, titles in self._groups for t in titles if t in shown)
            self.nav.setCurrentRow(self._nav_row(first))
        return total

    # ------------------------------------------------------------------ #
    # Pages                                                                #
    # ------------------------------------------------------------------ #

    def _page(self, title: str, intro: str = "") -> QVBoxLayout:
        """Start a page: a scroll area with a title; returns the layout to add rows to."""
        scroll = QScrollArea()
        scroll.setObjectName("settingsPage")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        holder = QWidget()
        holder.setObjectName("settingsPageBody")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(36, 22, 36, 20)
        layout.setSpacing(0)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        if intro:
            note = QLabel(intro)
            note.setWordWrap(True)
            note.setProperty("muted", True)
            layout.addWidget(note)
        layout.addSpacing(8)
        scroll.setWidget(holder)
        self._page_index[title] = self.pages.addWidget(scroll)
        self._page_rows[title] = []
        return layout

    def _add(self, page: str, layout: QVBoxLayout, title: str, description: str, control: QWidget,
             keywords: str = "") -> SettingRow:
        row = SettingRow(title, description, control, keywords)
        layout.addWidget(row)
        self._page_rows[page].append(row)
        self.rows.append(row)
        return row

    def set_model_state(self, note: str, busy: bool) -> None:
        """Show whether the speech model is installed, or how its download is going (*note*, while *busy*)."""
        if self.model_row is None:
            return
        installed = bool(self._model_installed())
        if note:
            text = note
        elif installed:
            text = "Installed. Quill listens on this computer; nothing you say is sent anywhere."
        else:
            text = ("Not installed. Quill needs it to hear you. It is about 40 MB, downloaded once, and "
                    "then works without internet.")
        self.model_row.description_label.setText(text)
        self.model_row.description_label.setVisible(True)
        self.model_button.setEnabled(not busy and not installed)
        self.model_button.setText("Installed" if installed and not busy else "Download")

    def _build_pages(self) -> None:
        prefs = self._settings.preferences
        # --- General
        page = self._page("General")
        self.speak_check = ToggleSwitch()
        self.speak_check.setChecked(bool(prefs["speak_sort_prompts"]))
        self._add("General", page, "Speak Sort Term Prompts",
                  "Off by default. When on, the system voice tells you what to do for each term in the Term Helper "
                  "(“Which column is that? Say Color, Size…”). Quill uses spoken words nowhere else.",
                  self.speak_check, "speech voice speak read aloud guide prompts accessibility")
        self.auto_sort_check = ToggleSwitch()
        self.auto_sort_check.setChecked(bool(prefs["auto_voice_sort"]))
        self._add("General", page, "Sort by Voice Automatically",
                  "Start answering the Needs-sorting list by voice as soon as terms need sorting.",
                  self.auto_sort_check, "voice sorting")
        self.dock_check = ToggleSwitch()
        self.dock_check.setChecked(bool(prefs["hide_dock_icon"]))
        self._add("General", page, "Hide the Dock Icon",
                  "macOS. Quill stays in the menu bar; open it from the menu bar icon (or by opening the app "
                  "again). Off by default: Quill shows in both the Dock and the menu bar.",
                  self.dock_check, "dock menu bar macos")
        self.mini_top_check = ToggleSwitch()
        self.mini_top_check.setChecked(bool(prefs["mini_on_top"]))
        self._add("General", page, "Keep the Mini View on Top",
                  "The mini view floats above other windows so it can sit over your spreadsheet.",
                  self.mini_top_check, "overlay always on top float")
        self.mic_check = ToggleSwitch()
        self.mic_check.setChecked(bool(prefs["mic_always_on"]))
        self._add("General", page, "Keep the Microphone Open When Not Listening",
                  "Lets you say “start listening”. Off (the default): the microphone is only on while "
                  "Quill is listening, so nothing is heard otherwise.", self.mic_check, "privacy mic always on")
        self.auto_stop_check = ToggleSwitch()
        self.auto_stop_check.setChecked(bool(prefs["auto_stop"]))
        self._add("General", page, "Stop Listening When Quiet",
                  "Quill stops listening by itself when nothing has been said for a while, so the microphone "
                  "is never left open by accident. Turn it off to listen until you stop it.",
                  self.auto_stop_check, "auto off timer idle silence shut off timeout")
        self.auto_stop_spin = GuardedSpinBox()
        self.auto_stop_spin.setRange(*AUTO_STOP_RANGE)
        self.auto_stop_spin.setValue(int(prefs["auto_stop_seconds"]))
        self.auto_stop_spin.setSuffix(" seconds")
        self.auto_stop_spin.setEnabled(self.auto_stop_check.isChecked())
        self.auto_stop_spin.setToolTip("How long it can be quiet before Quill stops listening")
        self._add("General", page, "Quiet Time Before Stopping",
                  "Seconds of silence after which listening stops (3 to 3600).", self.auto_stop_spin,
                  "auto off timer idle silence shut off timeout seconds")
        logs = QPushButton("Open Log Folder")
        logs.setToolTip("Quill writes what it does, and any error, to a log file here")
        logs.clicked.connect(lambda: self._on_open_logs())
        self._add("General", page, "Troubleshooting",
                  "If something goes wrong, the log file shows what happened.", logs, "log file errors diagnostics")
        self.model_button = QPushButton("Download")
        self.model_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_button.clicked.connect(lambda: self._on_download_model())
        self.model_row = self._add("General", page, "Speech Model", "", self.model_button,
                                   "download vosk offline recognition voice model install")
        self.set_model_state("", False)
        self.history_spin = GuardedSpinBox()
        self.history_spin.setRange(*HISTORY_LIMIT_RANGE)
        self.history_spin.setValue(int(prefs["history_limit"]))
        self.history_spin.setSuffix(" actions")
        self.history_spin.setToolTip("How many sorting answers Undo can step back through")
        self._add("General", page, "Undo Remembers",
                  "How many of your latest sorting answers can be taken back.", self.history_spin, "history")
        page.addStretch(1)

        # --- Appearance
        page = self._page("Appearance")
        self.theme_combo = SegmentedControl()
        for key in THEMES:
            self.theme_combo.addItem(THEME_ICONS[key], key.title(), key)
        self.theme_combo.setCurrentIndex(THEMES.index(prefs["theme"]))
        self._add("Appearance", page, "Theme", "Follow the system, or always light or dark.",
                  self.theme_combo, "dark light auto colour scheme")
        self.accent_combo = FlatCombo()
        for key, (label, (light, _), _night) in ACCENTS.items():
            self.accent_combo.addItem(_swatch(light), label, key)
        self.accent_combo.setCurrentIndex(self.accent_combo.findData(prefs["accent"]))
        self._add("Appearance", page, "Accent Colour", "Used for the main button, badges and highlights.",
                  self.accent_combo, "color")
        self.spacing_combo = FlatCombo()
        for key in SPACINGS:
            self.spacing_combo.addItem(DENSITIES[key]["label"], key)
        self.spacing_combo.setCurrentIndex(SPACINGS.index(prefs["spacing"]))
        self._add("Appearance", page, "Spacing", "Compact packs controls closely; Comfortable gives them room.",
                  self.spacing_combo, "layout density padding margin")
        self.font_spin = GuardedSpinBox()
        self.font_spin.setRange(*FONT_SIZE_RANGE)
        self.font_spin.setValue(int(prefs["font_size"]))
        self.font_spin.setSuffix(" pt")
        self._add("Appearance", page, "Text Size", "The size of text throughout Quill (default 12).",
                  self.font_spin, "font")
        self.opacity_slider, self.opacity_label, box = _slider(
            *OPACITY_RANGE, int(prefs["opacity"]), "How see-through the whole window is, text included")
        self._add("Appearance", page, "Window Opacity",
                  "How solid the window is. 100% is completely solid; lower makes the whole window, text and "
                  "controls included, see-through. The lowest is 10%.", box,
                  "transparent transparency")
        self.blur_slider, self.blur_label, box = _slider(
            *BLUR_RANGE, int(prefs["blur"]), "How strongly the desktop behind the window is blurred")
        self._add("Appearance", page, "Window Blur",
                  "Frosts what you see through the window (macOS and Windows 11). Only visible when opacity is "
                  "below 100%, since a solid window hides it. 0% is off.", box,
                  "glass vibrancy acrylic")
        self.sorting_opacity_check = ToggleSwitch()
        self.sorting_opacity_check.setChecked(bool(prefs["sorting_follows_opacity"]))
        self._add("Appearance", page, "Term Helper Follows Window Opacity",
                  "The Term Helper asks you to do something, so it stays solid and easy to read. Turn this on to "
                  "make it see-through like the main window.", self.sorting_opacity_check,
                  "term helper sorting transparent follow")
        page.addStretch(1)

        # --- Sounds
        page = self._page("Sounds")
        self.feedback_combo = FlatCombo()
        for mode in MODES:
            self.feedback_combo.addItem(MODE_LABELS[mode], mode)
        self.feedback_combo.setCurrentIndex(MODES.index(prefs["feedback"]))
        self._add("Sounds", page, "Confirm With", "How Quill tells you it has done something. Choosing one plays it.",
                  self.feedback_combo, "feedback audio sound echo")
        self.pack_combo = FlatCombo()
        for key, label in PACKS.items():
            self.pack_combo.addItem(label, key)
        self.pack_combo.setCurrentIndex(self.pack_combo.findData(prefs["sound_pack"]))
        self._add("Sounds", page, "Sound Set", "Choosing one plays it.", self.pack_combo, "chime marimba glass")
        self.echo_combo = FlatCombo()
        for key, label in ECHO_WORDS.items():
            self.echo_combo.addItem(label, key)
        self.echo_combo.setCurrentIndex(self.echo_combo.findData(prefs["echo_style"]))
        self._add("Sounds", page, "Spoken Word", "What Quill says for a success when it speaks instead.",
                  self.echo_combo, "echo voice")
        self.feedback_combo.currentIndexChanged.connect(self._update_feedback_choices)
        self._update_feedback_choices()
        self.feedback_combo.activated.connect(lambda _=0: self.play_sample())    # picking a choice plays it, so there is
        self.pack_combo.activated.connect(lambda _=0: self.play_sample())        # no separate Play button to press
        self.echo_combo.activated.connect(lambda _=0: self.play_sample())
        page.addStretch(1)

        # --- Keywords (the table gets all the height the window has)
        self._keywords_layout = self._page(
            "Keywords", "Say a phrase on the left and Quill does the action on the right.")
        self._keywords_built = False
        if not self._lazy_keywords:
            self._ensure_keywords()
        if self.SHOW_ACCOUNT:
            self._build_account_page()

    def _ensure_keywords(self) -> None:
        """Build the Keywords page now if it has not been built yet."""
        if self._keywords_built:
            return
        self._keywords_built = True
        page = self._keywords_layout
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["When You Say…", "Quill Does…"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(280)
        self._fill_table(self._settings.keywords.items())
        keyword_box = QWidget()
        inner = QVBoxLayout(keyword_box)
        inner.setContentsMargins(0, 6, 0, 0)
        inner.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        for label, slot in (("Add", self.add_row), ("Remove", self.remove_selected),
                            ("Restore Defaults", self.restore_defaults)):
            button = QPushButton(label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        inner.addLayout(buttons)
        page.addWidget(keyword_box, 1)
        self._keyword_box = keyword_box
        self._keyword_row = _KeywordSearch(keyword_box, self)
        self._page_rows["Keywords"].append(self._keyword_row)

    def _build_account_page(self) -> None:
        """Wireframe of the Account page (sign-in, plan, billing). Hidden until ``SHOW_ACCOUNT`` is on.

        It only shows what ``Settings.account`` holds and opens the website's pages; signing in itself
        goes through :class:`~quill.licensing.LicenseService` once the service exists.
        """
        service = LicenseService(self._settings)
        standing = service.standing()
        page = self._page("Account", "Your Quill account, plan and billing.")
        self.account_label = QLabel(standing.email or "Not signed in")
        self._add("Account", page, "Account", "Sign in to use Quill on this device.", self.account_label,
                  "sign in email login")
        self.sign_in_button = QPushButton("Sign Out" if standing.signed_in else "Sign In…")
        self.sign_in_button.setEnabled(service.configured)
        self.sign_in_button.setToolTip("" if service.configured else "Accounts are not available yet")
        self._add("Account", page, "Sign In", "Opens the sign-in form.", self.sign_in_button, "log in out")
        self.plan_label = QLabel(" · ".join(p for p in (standing.plan_label, standing.status_text) if p))
        self._add("Account", page, "Plan", "What you have and when it renews.", self.plan_label,
                  "subscription license renew trial")
        self.plan_button = QPushButton("Choose a Plan…")
        self.plan_button.setEnabled(bool(service.checkout_url("monthly")))
        self._add("Account", page, "Change Plan", "Monthly, yearly or a one-time purchase, paid securely "
                  "on the Quill website.", self.plan_button, "buy purchase upgrade monthly yearly lifetime")
        self.billing_button = QPushButton("Manage Billing…")
        self.billing_button.setEnabled(bool(service.manage_url()))
        self._add("Account", page, "Billing", "Payment method, receipts and cancellation.",
                  self.billing_button, "payment invoice receipt cancel")
        page.addStretch(1)

    @staticmethod
    def _open_log_folder() -> None:
        """Show the folder holding quill.log in Finder / Explorer."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from quill.diagnostics import log_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir())))

    def _update_feedback_choices(self) -> None:
        """Only the choice that applies to the selected way of confirming is enabled."""
        mode = self.feedback_combo.currentData()
        self.pack_combo.setEnabled(mode == "sounds")
        self.echo_combo.setEnabled(mode == "echo")

    def play_sample(self) -> None:
        """Play only the selected sound set's chime, or say only the selected word."""
        self._on_preview(self.feedback_combo.currentData(), self.pack_combo.currentData(),
                         self.echo_combo.currentData())

    # ------------------------------------------------------------------ #
    # Table editing                                                        #
    # ------------------------------------------------------------------ #

    def _fill_table(self, rows) -> None:
        self.table.setRowCount(0)
        for phrase, action in rows:
            self.add_row(phrase, action)

    def add_row(self, phrase: str = "", action: Action = Action.NEXT_ROW) -> None:
        """Append an editable keyword row."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(phrase if isinstance(phrase, str) else ""))
        combo = GuardedCombo()
        combo.setMinimumHeight(34)          # tall enough that the text is not clipped top and bottom
        for candidate in BINDABLE_ACTIONS:
            combo.addItem(action_label(candidate), candidate)
        combo.setCurrentIndex(BINDABLE_ACTIONS.index(action if isinstance(action, Action) else Action.NEXT_ROW))
        self.table.setCellWidget(row, 1, combo)

    def remove_selected(self) -> None:
        """Delete the selected rows (or the current one)."""
        rows = {i.row() for i in self.table.selectedIndexes()} or {self.table.currentRow()}
        for row in sorted((r for r in rows if r >= 0), reverse=True):
            self.table.removeRow(row)

    def restore_defaults(self) -> None:
        """Reload the shipped keywords into the table (not saved until OK)."""
        from quill.config.settings import Settings
        self._fill_table(Settings.defaults().keywords.items())

    def collect_rows(self) -> list[tuple[str, Action]]:
        """Read the table back as ``(phrase, action)`` pairs (the saved ones if the page was never opened)."""
        if not self._keywords_built:
            return list(self._settings.keywords.items())
        rows = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            rows.append((item.text() if item else "", self.table.cellWidget(r, 1).currentData()))
        return rows

    # ------------------------------------------------------------------ #
    # Accepting                                                            #
    # ------------------------------------------------------------------ #

    def try_accept(self, dialog: QDialog | None = None) -> bool:
        """Validate, save and close. Returns False (dialog stays open) on errors."""
        rows = self.collect_rows()
        errors = self._settings.validate_keywords(rows)
        if errors:
            self.nav.setCurrentRow(self._nav_row("Keywords"))
            self.show_errors(errors)
            return False
        self._settings.set_keywords(rows)
        self._store_preferences()
        self._settings.save()
        (dialog or self._dialog).accept()
        return True

    def show_errors(self, errors: list[str]) -> None:
        """Tell the user what is wrong (overridden in tests to avoid a modal box)."""
        QMessageBox.warning(self._dialog, "Check Your Keywords", "\n".join(errors))


class _KeywordSearch:
    """Makes the keyword editor searchable like a row (it matches its phrases and actions)."""

    def __init__(self, widget: QWidget, dialog: "SettingsDialog") -> None:
        self._widget, self._dialog = widget, dialog

    @property
    def search_text(self) -> str:
        words = ["keywords", "when you say", "quill does", "commands", "phrases"]
        for phrase, action in self._dialog.collect_rows():
            words += [phrase, action_label(action)]
        return " ".join(words).lower()

    def matches(self, query: str) -> bool:
        text = self.search_text
        return all(word in text for word in query.lower().split())

    def setVisible(self, visible: bool) -> None:                 # noqa: N802 (Qt name)
        self._widget.setVisible(visible)
