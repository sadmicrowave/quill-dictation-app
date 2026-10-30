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
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from quill.parser.tokens import display_name
from quill.parser.vocab import Vocabulary
from quill.session import Decision, TermKey

#: Called with (key, decision, corrected words) when the user decides.
ResolveCallback = Callable[[TermKey, Decision, str], None]

PLACEHOLDER = "Choose column…"


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
        self.prompt.setWordWrap(True)
        self.edit = QLineEdit(term)
        self.edit.setToolTip("Correct the words if Quill heard too much")
        self.combo = QComboBox()
        self.combo.addItem(PLACEHOLDER, None)
        # Columns with an unfilled slot are not known here; list them in sheet order.
        for name in vocab.columns():
            self.combo.addItem(name, name)
        if column and self.combo.findData(column) >= 0:
            self.combo.setCurrentIndex(self.combo.findData(column))
        self.add_button = QPushButton("Add")
        self.add_button.setToolTip("Add this as a new value in the chosen column")
        self.same_button = QPushButton("Same as…")
        self.same_button.setToolTip("It is another name for a value that is already in the list")
        self.same_menu = QMenu(self.same_button)
        self.same_menu.aboutToShow.connect(self._fill_same_menu)
        self.same_button.setMenu(self.same_menu)
        self.ignore_button = QPushButton("Ignore")

        top = QVBoxLayout(self)
        top.addWidget(self.prompt)
        controls = QHBoxLayout()
        controls.addWidget(self.edit, 1)
        controls.addWidget(self.combo)
        for button in (self.add_button, self.same_button, self.ignore_button):
            controls.addWidget(button)
        top.addLayout(controls)

        self.combo.currentIndexChanged.connect(self._update_enabled)
        self.add_button.clicked.connect(self.add)
        self.ignore_button.clicked.connect(self.ignore)
        self._update_enabled()

    def set_active(self, active: bool) -> None:
        """Highlight this row as the one the voice stream is answering."""
        self.setStyleSheet("#termRow { border: 2px solid palette(highlight); }" if active else "")

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

    #: Shown while voice sorting is on.
    VOICE_HINT = ("Say: yes · a column name · same as … · ignore · later · done   "
                  "(or ‘add all’, ‘ignore all’)")

    def __init__(self, vocab: Vocabulary, on_resolve: ResolveCallback,
                 on_voice: Callable[[], None] | None = None) -> None:
        self._vocab = vocab
        self._on_resolve = on_resolve
        self._on_voice = on_voice or (lambda: None)
        self._voice_active = False
        self._window: QWidget | None = None
        self.rows: list[TermRow] = []

    def setup(self) -> None:
        """Build the window (call once, after the QApplication exists)."""
        window = QWidget(None, Qt.WindowType.Tool)
        window.setWindowTitle("Needs sorting")
        window.resize(460, 300)
        window.setMinimumSize(320, 160)
        layout = QVBoxLayout(window)
        self.intro = QLabel("Quill heard these but couldn't place them. Tell it what each one is.")
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)

        voice_row = QHBoxLayout()
        self.voice_button = QPushButton()
        self.voice_button.setCheckable(True)
        self.voice_button.clicked.connect(lambda: self._on_voice())
        voice_row.addWidget(self.voice_button)
        self.voice_status = QLabel()
        self.voice_status.setWordWrap(True)
        voice_row.addWidget(self.voice_status, 1)
        layout.addLayout(voice_row)
        self._render_voice()

        self._list = QVBoxLayout()
        self._list.addStretch(1)
        holder = QWidget()
        holder.setLayout(self._list)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)
        self.scroll = scroll

        footer = QHBoxLayout()
        self.add_all_button = QPushButton("Add all with a column")
        self.add_all_button.clicked.connect(self.add_all)
        self.ignore_all_button = QPushButton("Ignore all")
        self.ignore_all_button.clicked.connect(self.ignore_all)
        footer.addWidget(self.add_all_button)
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
            self._window.setWindowTitle(f"Needs sorting ({len(items)})" if items else "Needs sorting")
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
        self._render_voice()
        self.set_items([r.key for r in self.rows])   # re-arm click and highlight

    def set_voice_status(self, heard: str, message: str) -> None:
        """Show what was heard and what Quill did with it."""
        self.voice_status.setText(f"Heard ‘{heard}’ → {message}" if heard else message)

    def _render_voice(self) -> None:
        self.voice_button.setChecked(self._voice_active)
        self.voice_button.setText("🎤 Listening… (click to stop)" if self._voice_active
                                  else "🎤 Sort by voice")
        if self._voice_active and not self.voice_status.text():
            self.voice_status.setText(self.VOICE_HINT)

    def show(self) -> None:
        if self._window is not None and self.rows:
            self._window.show()
            self._window.raise_()

    def add_all(self) -> None:
        """Add every row that already has a column chosen."""
        for row in list(self.rows):
            if row.column and row.words:
                row.add()

    def ignore_all(self) -> None:
        for row in list(self.rows):
            row.ignore()
