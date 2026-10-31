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
from typing import TYPE_CHECKING
import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSlider,
    QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from quill.config.settings import (
    BLUR_RANGE, FONT_SIZE_RANGE, HISTORY_LIMIT_RANGE, OPACITY_RANGE, SPACINGS, THEMES,
)
from quill.feedback import ECHO_WORDS, MODE_LABELS, MODES, PACKS
from quill.parser.commands import Action
from quill.ui.chrome import apply_chrome
from quill.ui.settings_widgets import (
    FlatCombo, GuardedCombo, GuardedSlider, GuardedSpinBox, SegmentedControl, SettingRow, ToggleSwitch,
)
from quill.ui.theme import ACCENTS, DENSITIES, apply_opacity, apply_spacing

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
    slider.setMinimumWidth(180)
    label = QLabel(f"{value}%")
    label.setMinimumWidth(40)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v: label.setText(f"{v}%"))
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(slider, 1)
    row.addWidget(label)
    return slider, label, box


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

    def __init__(self, settings: "Settings", parent=None, on_preview=None, on_change=None,
                 on_open_logs=None, on_help=None) -> None:
        self._on_help = on_help
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
        self.mini_top_check: ToggleSwitch | None = None
        self.dock_check: ToggleSwitch | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    #: The Settings window fades with the window-opacity setting but never below this, so it stays readable.
    MIN_DIALOG_OPACITY = 70

    def exec(self) -> bool:
        """Show modally. Returns True if the user saved changes."""
        self.build()
        self._apply_dialog_look()
        self._install_help_icon()
        return self._dialog.exec() == QDialog.DialogCode.Accepted

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
        apply_chrome(self._dialog, dark, colors_for(dark, str(prefs["accent"])),
                     opacity=opacity, blur=int(prefs["blur"]))
        apply_opacity(self.root, opacity)

    def build(self) -> QDialog:
        """Construct the dialog widgets (separate from exec for testing)."""
        dialog = QDialog(self._parent)
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)    # paint the themed background
        dialog.setWindowTitle("Quill Settings")
        dialog.resize(920, 740)
        dialog.setMinimumSize(720, 520)
        shell = QVBoxLayout(dialog)
        shell.setContentsMargins(0, 0, 0, 0)
        root = QWidget()
        root.setObjectName("settingsRoot")                     # paints the background; opacity applies to it
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
                        self.dock_check):
            control.toggled.connect(self._live)
        for control in (self.theme_combo, self.accent_combo, self.spacing_combo, self.feedback_combo,
                        self.pack_combo, self.echo_combo):
            control.currentIndexChanged.connect(self._live)
        for control in (self.font_spin, self.history_spin, self.opacity_slider, self.blur_slider):
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
        prefs.clear()
        prefs.update(copy.deepcopy(self._original))
        self._on_change()

    def _store_preferences(self) -> None:
        """Copy every control's value into ``settings.preferences`` (not saved to disk)."""
        prefs = self._settings.preferences
        prefs["theme"] = THEMES[self.theme_combo.currentIndex()]
        prefs["speak_prompts"] = self.speak_check.isChecked()
        prefs["auto_voice_sort"] = self.auto_sort_check.isChecked()
        prefs["mic_always_on"] = self.mic_check.isChecked()
        prefs["mini_on_top"] = self.mini_top_check.isChecked()
        prefs["hide_dock_icon"] = self.dock_check.isChecked()
        prefs["accent"] = self.accent_combo.currentData()
        prefs["spacing"] = self.spacing_combo.currentData()
        prefs["font_size"] = self.font_spin.value()
        prefs["opacity"] = self.opacity_slider.value()
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
        for caption, titles in GROUPS:
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
            self.pages.setCurrentIndex(self._page_index[title])

    def filter(self, text: str) -> int:
        """Show only settings matching *text* (every word), hiding empty groups.

        Returns:
            How many settings match. An empty query shows everything.
        """
        query = text.strip()
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
        for head, (_, titles) in zip(self._captions, GROUPS):
            head.setHidden(not any(t in shown for t in titles))
        self.empty_label.setVisible(bool(query) and total == 0)
        current = self.nav.currentItem()
        if query and (current is None or current.isHidden()) and shown:
            first = next(t for _, titles in GROUPS for t in titles if t in shown)
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

    def _build_pages(self) -> None:
        prefs = self._settings.preferences
        # --- General
        page = self._page("General")
        self.speak_check = ToggleSwitch()
        self.speak_check.setChecked(bool(prefs["speak_prompts"]))
        self._add("General", page, "Read Questions Aloud",
                  "Quill speaks its questions, such as “Add it to the list?”.", self.speak_check)
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
        logs = QPushButton("Open Log Folder")
        logs.setToolTip("Quill writes what it does, and any error, to a log file here")
        logs.clicked.connect(lambda: self._on_open_logs())
        self._add("General", page, "Troubleshooting",
                  "If something goes wrong, the log file shows what happened.", logs, "log file errors diagnostics")
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
        page.addStretch(1)

        # --- Sounds
        page = self._page("Sounds")
        self.feedback_combo = FlatCombo()
        for mode in MODES:
            self.feedback_combo.addItem(MODE_LABELS[mode], mode)
        self.feedback_combo.setCurrentIndex(MODES.index(prefs["feedback"]))
        self._add("Sounds", page, "Confirm With", "How Quill tells you it has done something.",
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
        self.pack_combo.activated.connect(lambda _=0: self.play_sample())    # picking one plays it
        self.echo_combo.activated.connect(lambda _=0: self.play_sample())
        sample = QPushButton("Play Sample")
        sample.setToolTip("Hear the sound set (or word) selected above")
        sample.clicked.connect(self.play_sample)
        self._add("Sounds", page, "Preview", "Plays the selected sound, or says the selected word.", sample)
        page.addStretch(1)

        # --- Keywords (the table gets all the height the window has)
        page = self._page("Keywords", "Say a phrase on the left and Quill does the action on the right.")
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
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        inner.addLayout(buttons)
        page.addWidget(keyword_box, 1)
        self._keyword_box = keyword_box
        self._keyword_row = _KeywordSearch(keyword_box, self)
        self._page_rows["Keywords"].append(self._keyword_row)

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
        """Read the table back as ``(phrase, action)`` pairs."""
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
