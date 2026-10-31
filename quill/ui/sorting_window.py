"""The "Needs sorting" window: a small, resizable list of unrecognised terms.

Each row is one term Quill heard but could not place:

    You said ‘90s’ — is that an Era?
    [ 90s        ] [ Era ▾ ] [Add] [Same as ▾] [Ignore]

The user can correct the words, pick (or change) the column, then
  * **Add** it as a new value of that column,
  * say it is the **Same as** an existing value ("extra large" = XL), or
  * **Ignore** it.
The window only reports decisions through a callback; the controller does the
work and the app refreshes the list.

Voice sorting: click the first term (or the microphone button) and speak. Each
command resolves the top term, it leaves the list and the next one moves up
while the stream continues; see :mod:`quill.sorting_voice`.
"""
from __future__ import annotations
import contextlib
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from quill.parser.tokens import display_name
from quill.parser.vocab import Vocabulary
from quill.session import Decision, TermKey
from quill.ui.settings_widgets import FlatCombo
from quill.ui.theme import apply_spacing

#: Called with (key, decision, corrected words) when the user decides.
ResolveCallback = Callable[[TermKey, Decision, str], None]

PLACEHOLDER = "Choose Column…"

#: Height (px) of the controls in a row, and the gap kept between a row's question and its controls.
CONTROL_HEIGHT = 34
PROMPT_GAP = 5


def question_for(column: str | None, term: str) -> str:
    """The line shown above a term: ``You said ‘90s’ — is that an Era?``."""
    if not column:
        return f"You said ‘{term}’ — which column is that?"
    article = "an" if column[:1].lower() in "aeiou" else "a"
    return f"You said ‘{term}’ — is that {article} {column}?"


class TermRow(QFrame):
    """One unrecognised term and its controls."""

    def __init__(self, key: TermKey, vocab: Vocabulary, on_resolve: ResolveCallback,
                 on_activate: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.setObjectName("termRow")
        self.key = key
        self._on_activate = on_activate
        self._vocab = vocab
        self._on_resolve = on_resolve
        column, term = key
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self.prompt = QLabel(question_for(column, term))
        self.prompt.setObjectName("termPrompt")      # larger than body text (see theme)
        self.prompt.setWordWrap(True)
        self.edit = QLineEdit(term)
        self.edit.setToolTip("Correct the words if Quill heard too much")
        self.hint = QLabel()                          # what to say, while the voice stream is answering this row
        self.hint.setProperty("note", True)
        self.hint.setWordWrap(True)
        self.hint.setVisible(False)
        self.combo = FlatCombo()                      # the same controls the Settings pages use
        self.combo.addItem(PLACEHOLDER, None)
        # Columns with an unfilled slot are not known here; list them in sheet order.
        for name in vocab.columns():
            self.combo.addItem(name, name)
        if column and self.combo.findData(column) >= 0:
            self.combo.setCurrentIndex(self.combo.findData(column))
        self.add_button = QPushButton("Add")
        self.add_button.setToolTip("Add this as a new value in the chosen column")
        self.same_button = QPushButton("Same As…")
        self.same_button.setToolTip("It is another name for a value that is already in the list")
        self.same_menu = QMenu(self.same_button)
        self.same_menu.aboutToShow.connect(self._fill_same_menu)
        self.same_button.setMenu(self.same_menu)
        self.ignore_button = QPushButton("Ignore")

        for control in (self.edit, self.combo, self.add_button, self.same_button, self.ignore_button):
            control.setMinimumHeight(CONTROL_HEIGHT)
        top = QVBoxLayout(self)
        top.addWidget(self.prompt)
        top.addSpacing(PROMPT_GAP)                    # room between the question and its controls
        top.addWidget(self.hint)
        controls = QHBoxLayout()
        controls.addWidget(self.edit, 1)
        controls.addWidget(self.combo)
        for button in (self.add_button, self.same_button, self.ignore_button):
            controls.addWidget(button)
        top.addLayout(controls)

        apply_spacing(self)
        self.combo.currentIndexChanged.connect(self._update_enabled)
        self.add_button.clicked.connect(self.add)
        self.ignore_button.clicked.connect(self.ignore)
        self._update_enabled()

    def set_active(self, active: bool) -> None:
        """Highlight this row as the one the voice stream is answering."""
        self.setStyleSheet("#termRow { border: 2px solid palette(highlight); }" if active else "")
        self.hint.setText(self._spoken_hint())
        self.hint.setVisible(active)

    def _spoken_hint(self) -> str:
        """What the user can say to answer this row: the columns to choose from if it has none yet."""
        if self.column is None:
            names = [c for c in self._vocab.columns() if self._vocab.is_list_column(c)]
            return "🎤 Say a column: " + " · ".join(names) if names else "🎤 Say ignore, or later"
        return f"🎤 Say: yes (adds to {self.column}) · same as … · ignore · later"

    def mousePressEvent(self, event) -> None:
        """Clicking the (first) row starts answering it by voice."""
        if self._on_activate is not None:
            self._on_activate()
        super().mousePressEvent(event)

    @property
    def column(self) -> str | None:
        """The column currently chosen in the drop-down (None if not chosen)."""
        return self.combo.currentData()

    @property
    def words(self) -> str:
        return self.edit.text().strip()

    def _update_enabled(self) -> None:
        ready = self.column is not None and bool(self.words)
        self.add_button.setEnabled(ready)
        self.same_button.setEnabled(ready)

    def _fill_same_menu(self) -> None:
        self.same_menu.clear()
        for value in self._vocab.values_for(self.column or ""):
            self.same_menu.addAction(value, lambda v=value: self.same_as(v))

    # -- decisions ---------------------------------------------------------

    def add(self) -> None:
        if self.column and self.words:
            self._on_resolve(self.key, Decision.add(self.column, display_name(self.words)), self.words)

    def same_as(self, canonical: str) -> None:
        if self.column and self.words:
            self._on_resolve(self.key, Decision.alias(self.column, canonical), self.words)

    def ignore(self) -> None:
        self._on_resolve(self.key, Decision.ignore(), self.words)


class SortingWindow:
    """Small floating window listing terms that need a decision.

    Args:
        vocab: Vocabulary of the active sheet (supplies columns and values).
        on_resolve: Called with each decision.
        on_voice: Called when the user toggles voice sorting (button or click
            on the first term).
    """

    #: What can be said while voice sorting is on (the button's tooltip).
    VOICE_HINT = ("Say: yes · a column name · same as … · ignore · later · done   "
                  "(or ‘add all’, ‘ignore all’)")

    #: Space (px) kept around the list, and the width the window may grow to when it opens.
    MARGIN = 12
    SIDE_ALLOWANCE = 36

    def __init__(self, vocab: Vocabulary, on_resolve: ResolveCallback,
                 on_voice: Callable[[], None] | None = None,
                 on_undo: Callable[[], None] | None = None,
                 batch: Callable[[str], object] | None = None) -> None:
        self._vocab = vocab
        self._on_resolve = on_resolve
        self._on_undo = on_undo or (lambda: None)
        self._batch = batch or (lambda label: contextlib.nullcontext())
        self._on_voice = on_voice or (lambda: None)
        self._voice_active = False
        self._window: QWidget | None = None
        self.root: QWidget | None = None       # the widget that paints the background (set in setup)
        self.rows: list[TermRow] = []

    def setup(self, parent: QWidget | None = None) -> None:
        """Build the window (call once, after the QApplication exists).

        With a *parent* (the main window) this window stays above it, and only it: not above other
        applications' windows, and it drops back with the app when Quill loses focus.
        """
        # A normal window, not a tool window: tool windows hide whenever the app is not frontmost,
        # and their title bar buttons are drawn at a third of the usual size.
        window = QWidget(parent, Qt.WindowType.Window)
        window.setObjectName("sortingWindow")
        window.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        window.setWindowTitle("Needs Sorting")
        window.resize(460, 300)
        window.setMinimumSize(320, 160)
        shell = QVBoxLayout(window)
        shell.setContentsMargins(0, 0, 0, 0)
        root = QWidget()
        root.setObjectName("sortingRoot")                      # paints the background; opacity applies to it
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell.addWidget(root)
        self.root = root
        layout = QVBoxLayout(root)
        root.setProperty("keepMargins", True)                  # the spacing setting must not widen these
        layout.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.intro = QLabel("These terms were heard but couldn't be placed. Decide what to do for each one.")
        self.intro.setWordWrap(True)
        self.intro.setProperty("info", True)                   # a full-width info box
        layout.addWidget(self.intro)

        voice_row = QHBoxLayout()
        self.voice_button = QPushButton()
        self.voice_button.setCheckable(True)
        self.voice_button.clicked.connect(lambda: self._on_voice())
        self.voice_button.setToolTip(self.VOICE_HINT)
        voice_row.addWidget(self.voice_button)
        self.voice_status = QLabel()                          # only what was just heard; empty (and hidden) otherwise
        self.voice_status.setWordWrap(True)
        self.voice_status.setVisible(False)
        voice_row.addWidget(self.voice_status, 1)
        layout.addLayout(voice_row)
        self._render_voice()

        self._list = QVBoxLayout()
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.addStretch(1)
        holder = QWidget()
        holder.setProperty("keepMargins", True)
        holder.setLayout(self._list)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)             # the rows run to the window's own margins
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)
        self.scroll = scroll

        footer = QHBoxLayout()
        self.add_all_button = QPushButton("Add All With a Column")
        self.add_all_button.clicked.connect(self.add_all)
        self.ignore_all_button = QPushButton("Ignore All")
        self.ignore_all_button.clicked.connect(self.ignore_all)
        footer.addWidget(self.add_all_button)
        self.undo_button = QPushButton("↶ Undo")
        self.undo_button.setToolTip("Take back the last answer (you can keep stepping back)")
        self.undo_button.clicked.connect(lambda: self._on_undo())
        footer.addWidget(self.undo_button)
        footer.addStretch(1)
        footer.addWidget(self.ignore_all_button)
        layout.addLayout(footer)
        self._window = window

    @property
    def widget(self) -> QWidget | None:
        return self._window

    def set_items(self, items: list[TermKey]) -> None:
        """Replace the list with *items*; hides the window when it is empty."""
        for row in self.rows:
            self._list.removeWidget(row)
            row.hide()               # leave the screen now, not when Qt gets to deleteLater
            row.setParent(None)
            row.deleteLater()
        self.rows = []
        for key in items:
            first = not self.rows
            row = TermRow(key, self._vocab, self._on_resolve,
                          on_activate=self._start_voice if first and not self._voice_active else None)
            row.set_active(first and self._voice_active)
            self._list.insertWidget(self._list.count() - 1, row)
            self.rows.append(row)
        if self._window is not None:
            self._window.setWindowTitle(f"Needs Sorting ({len(items)})" if items else "Needs Sorting")
            self.add_all_button.setEnabled(bool(items))
            self.ignore_all_button.setEnabled(bool(items))
            if not items:
                self._window.hide()

    # -- voice sorting -----------------------------------------------------

    @property
    def voice_active(self) -> bool:
        return self._voice_active

    def _start_voice(self) -> None:
        self._on_voice()

    def set_voice_active(self, active: bool) -> None:
        """Reflect voice sorting being on/off (highlight, button, hint)."""
        self._voice_active = active
        if not active:
            self.voice_status.setText("")
            self.voice_status.setVisible(False)
        self._render_voice()
        self.set_items([r.key for r in self.rows])   # re-arm click and highlight

    def set_voice_status(self, heard: str, message: str) -> None:
        """Show what was heard and what Quill did with it."""
        text = f"Heard ‘{heard}’ → {message}" if heard else message
        self.voice_status.setText(text)
        self.voice_status.setVisible(bool(text))

    def _render_voice(self) -> None:
        self.voice_button.setChecked(self._voice_active)
        self.voice_button.setText("🎤 Listening… (click to stop)" if self._voice_active
                                  else "🎤 Sort by Voice")

    def show(self) -> None:
        if self._window is not None and self.rows:
            self._fit_width()
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    def _fit_width(self) -> None:
        """Widen the window, if needed, so a whole row fits without scrolling sideways (never beyond the screen)."""
        window = self._window
        need = max(row.sizeHint().width() for row in self.rows) + 2 * self.MARGIN + self.SIDE_ALLOWANCE
        screen = window.screen()
        if screen is not None:
            need = min(need, screen.availableGeometry().width() - 40)
        if window.width() < need:
            window.resize(need, window.height())

    def add_all(self) -> None:
        """Add every row that already has a column chosen."""
        with self._batch("Added terms"):
            for row in list(self.rows):
                if row.column and row.words:
                    row.add()

    def ignore_all(self) -> None:
        with self._batch("Ignored terms"):
            for row in list(self.rows):
                row.ignore()

    def set_undo_available(self, count: int) -> None:
        """Enable the Undo button while there is something to take back."""
        if self._window is not None:
            self.undo_button.setEnabled(count > 0)
            self.undo_button.setText(f"↶ Undo ({count})" if count else "↶ Undo")
