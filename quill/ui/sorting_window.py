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

import shiboken6
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from quill.parser.tokens import display_name
from quill.parser.vocab import Vocabulary
from quill.session import Decision, TermKey
from quill.ui.chrome import SYMBOL_HELP, SYMBOL_UNDO, add_titlebar_button
from quill.ui.settings_widgets import FlatCombo
from quill.ui.theme import install_backdrop, apply_spacing
from quill.ui.widgets import pill, pillify

#: Called with (key, decision, corrected words) when the user decides.
ResolveCallback = Callable[[TermKey, Decision, str], None]

PLACEHOLDER = "Choose Column…"

#: The help page the "?" icons open.
HELP_TOPIC = "term-helper"

#: Height (px) of the controls in a row, and the gap kept between a row's question and its controls.
CONTROL_HEIGHT = 34
PROMPT_GAP = 5


def question_for(column: str | None, term: str) -> str:
    """The line shown above a term: ``You said ‘90s’ — is that an Era?``."""
    if not column:
        return f"You said ‘{term}’ — which column is that?"
    article = "an" if column[:1].lower() in "aeiou" else "a"
    return f"You said ‘{term}’ — is that {article} {column}?"


def question_html(column: str | None, term: str, short_code: str | None = None) -> str:
    """:func:`question_for` as rich text, with the spoken term in a code pill.

    *short_code* is the value the term probably spells out ("M" for "medium"); the question is then about that.
    """
    shown = pill(term)
    if column and short_code:
        return f"You said {shown} — same as {pill(short_code)}?"
    if not column:
        return f"You said {shown} — which column is that?"
    article = "an" if column[:1].lower() in "aeiou" else "a"
    return f"You said {shown} — is that {article} {column}?"


class TermRow(QFrame):
    """One unrecognised term and its controls."""

    def __init__(self, key: TermKey, vocab: Vocabulary, on_resolve: ResolveCallback,
                 on_activate: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.setObjectName("termRow")
        self.key = key
        self._on_activate = on_activate
        self.chosen = False                           # a column was picked by voice (the row blinks after the list does)
        self._vocab = vocab
        self._on_resolve = on_resolve
        column, term = key
        self.setFrameShape(QFrame.Shape.StyledPanel)

        hint = vocab.abbreviation_for(term)
        self.short_code = hint[1] if hint and column in (None, hint[0]) else None
        if self.short_code:
            column = hint[0]
        self.prompt = QLabel(question_html(column, term, self.short_code))
        self.prompt.setTextFormat(Qt.TextFormat.RichText)
        self.prompt.setObjectName("termPrompt")      # larger than body text (see theme)
        self.prompt.setWordWrap(True)
        self.edit = QLineEdit(display_name(term))          # words are capitalised as they are placed here
        self.edit.setToolTip("Correct the words if Quill heard too much")
        self.hint = QLabel()                          # what to say, while the voice stream is answering this row
        self.hint.setProperty("note", True)
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.TextFormat.RichText)
        self.hint.setVisible(False)
        self.combo = FlatCombo()                      # the same controls the Settings pages use
        self.combo.addItem(PLACEHOLDER, None)
        # Columns with an unfilled slot are not known here; list them in sheet order.
        for name in vocab.columns_for(term):                  # only columns the term could belong to ("teal" is no date)
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
        self.match_button = QPushButton(f"Same As {self.short_code}" if self.short_code else "")
        self.match_button.setProperty("accent", True)          # the likely answer, filled in the theme colour
        self.match_button.setVisible(bool(self.short_code))
        self.match_button.setToolTip("Another name for the short code Quill thinks this is")

        for control in (self.edit, self.combo, self.match_button, self.add_button, self.same_button, self.ignore_button):
            control.setMinimumHeight(CONTROL_HEIGHT)
        top = QVBoxLayout(self)
        top.addWidget(self.prompt)
        top.addSpacing(PROMPT_GAP)                    # room between the question and its controls
        top.addWidget(self.hint)
        controls = QHBoxLayout()
        controls.addWidget(self.edit, 1)
        controls.addWidget(self.combo)
        for button in (self.match_button, self.add_button, self.same_button, self.ignore_button):
            controls.addWidget(button)
        top.addLayout(controls)

        apply_spacing(self)
        self.combo.currentIndexChanged.connect(self._update_enabled)
        self.add_button.clicked.connect(self.add)
        self.match_button.clicked.connect(lambda: self.short_code and self.same_as(self.short_code))
        self.ignore_button.clicked.connect(self.ignore)
        self._update_enabled()

    def set_active(self, active: bool) -> None:
        """Highlight this row as the one the voice stream is answering."""
        self.setStyleSheet("#termRow { border: 2px solid palette(highlight); }" if active else "")
        self.hint.setText(self._spoken_hint())
        self.hint.setVisible(active)
        if active and self.column is None:
            QTimer.singleShot(200, self._open_column_list)       # so the columns to choose from are in view

    def _open_column_list(self) -> None:
        """Open the Choose Column list (once the row is on screen and still the one being answered)."""
        if self.isVisible() and self.hint.isVisible() and self.column is None and self.combo.count() > 1:
            self.combo.showPopup()

    def guidance(self) -> str:
        """What to do for this row, as plain sentences for the system voice (spoken only if the user turned that on)."""
        term = display_name(self.key[1])
        if self.short_code:
            return f"{term} looks like {self.short_code}. Say yes to use it, same as another value, ignore, or later."
        if self.column is None:
            names = self._vocab.columns_for(self.key[1])
            if not names:
                return f"{term}. Say ignore, or later."
            return f"{term}. Which column is that? Say {', '.join(names)}, or ignore, or later."
        return f"{term}. Say yes to add it to {self.column}, same as another value, ignore, or later."

    def _spoken_hint(self) -> str:
        """What the user can say to answer this row: the columns to choose from if it has none yet."""
        if self.column is None:
            names = self._vocab.columns_for(self.key[1])
            if not names:
                return f"🎤 Say {pill('ignore')} or {pill('later')}"
            return "🎤 Say a column: " + " ".join(pill(n) for n in names)
        meaning = f"same as {self.short_code}" if self.short_code else f"adds to {self.column}"
        return (f"🎤 Say: {pill('yes')} ({meaning}) {pill('same as …')} {pill('ignore')} "
                f"{pill('later')}")

    #: Border and tint of the blink that confirms an answer: (border colour, tint) per outcome.
    FLASH_STYLES = {
        "accepted": ("#34C759", "rgba(52, 199, 89, 0.14)"),      # green: the term was added or made an alias
        "ignored": ("#8E8E93", "rgba(142, 142, 147, 0.16)"),     # grey: a deliberate "no", nothing was added
        "error": ("#FF3B30", "rgba(255, 59, 48, 0.14)"),         # red: the answer could not be carried out
    }

    #: How long the chosen column is shown lit in the drop-down before the row itself blinks (ms).
    CHOICE_MS = 240

    def choose(self, column: str) -> None:
        """A column was picked by voice: select it and blink it in the drop-down list, then (see the window) the row blinks.

        Two quick, back-to-back signals that the word was heard: the choice lights up in the list, then the
        whole row confirms it was satisfied.
        """
        index = self.combo.findData(column)
        if index < 0:
            return
        self.chosen = True
        self.combo.setCurrentIndex(index)
        view = self.combo.view()
        if view.isVisible():
            view.setCurrentIndex(view.model().index(index, 0))
        on = ("QAbstractItemView::item:selected { background: #34C759; color: #FFFFFF; border-radius: 6px; }"
              if view.isVisible() else "")
        combo_on = "QComboBox { border: 2px solid #34C759; }"
        for delay, lit in ((0, True), (80, False), (120, True)):
            QTimer.singleShot(delay, lambda lit=lit: self._light(view, on if lit else "", combo_on if lit else ""))
        QTimer.singleShot(self.CHOICE_MS, self._close_choice)

    def _light(self, view, view_style: str, combo_style: str) -> None:
        if shiboken6.isValid(self):
            view.setStyleSheet(view_style)
            self.combo.setStyleSheet(combo_style)

    def _close_choice(self) -> None:
        if shiboken6.isValid(self):
            self.combo.hidePopup()
            self.combo.view().setStyleSheet("")
            self.combo.setStyleSheet("")

    def flash(self, outcome: str = "accepted") -> None:
        """Blink the row's border and tint it: green when accepted, grey when ignored, red on an error."""
        border, tint = self.FLASH_STYLES.get(outcome, self.FLASH_STYLES["accepted"])
        self.setStyleSheet(f"#termRow {{ border: 2px solid {border}; background: {tint}; }}")

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
        """The term as currently typed in the row's text box (the user may have corrected it)."""
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
        """Add the term as a new value in the chosen column."""
        if self.column and self.words:
            self._on_resolve(self.key, Decision.add(self.column, display_name(self.words)), self.words)

    def same_as(self, canonical: str) -> None:
        """Record the term as another name for the existing value *canonical*."""
        if self.column and self.words:
            self._on_resolve(self.key, Decision.alias(self.column, canonical), self.words)

    def ignore(self) -> None:
        """Forget the term."""
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

    #: How long an answered row flashes, and how long it takes to ease away (ms; 0 = no animation).
    FLASH_MS = 160
    animation_ms = 220

    def __init__(self, vocab: Vocabulary, on_resolve: ResolveCallback,
                 on_voice: Callable[[], None] | None = None,
                 on_undo: Callable[[], None] | None = None,
                 batch: Callable[[str], object] | None = None,
                 on_help: Callable[[str], None] | None = None,
                 on_speak: Callable[[str], None] | None = None) -> None:
        self._on_help = on_help or (lambda topic: None)
        self._on_speak = on_speak or (lambda text: None)          # speaks a row's guidance (when the user turned that on)
        self._spoken_key: TermKey | None = None                    # the row whose guidance was last spoken
        self._vocab = vocab
        self._on_resolve = on_resolve
        self._on_undo = on_undo or (lambda: None)
        self._batch = batch or (lambda label: contextlib.nullcontext())
        self._on_voice = on_voice or (lambda: None)
        self._voice_active = False
        self._queue: list[TermRow] = []                    # answered rows waiting their turn to leave
        self._outcomes: dict[TermKey, str] = {}            # how each answered term was answered (picks the blink colour)
        self._retiring = False
        self._titlebar = None
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
        window.setWindowTitle("Term Helper")
        window.resize(460, 300)
        window.setMinimumSize(320, 160)
        shell = QVBoxLayout(window)
        shell.setContentsMargins(0, 0, 0, 0)
        root = QWidget()
        root.setObjectName("sortingRoot")

        install_backdrop(root)                              # paints its own (see-through-able) background
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell.addWidget(root)
        self.root = root
        layout = QVBoxLayout(root)
        root.setProperty("keepMargins", True)                  # the spacing setting must not widen these
        layout.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)

        voice_row = QHBoxLayout()
        self.voice_button = QPushButton()
        self.voice_button.setCheckable(True)
        self.voice_button.clicked.connect(lambda: self._on_voice())
        self.voice_button.setToolTip(self.VOICE_HINT)
        voice_row.addWidget(self.voice_button, 1)
        inside = QHBoxLayout(self.voice_button)             # the quiet countdown sits at the button's right edge
        inside.setContentsMargins(12, 0, 12, 0)
        inside.addStretch(1)
        self.voice_countdown = QLabel()
        self.voice_countdown.setProperty("countdown", True)
        self.voice_countdown.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.voice_countdown.setVisible(False)
        inside.addWidget(self.voice_countdown)
        # Help ("?"): in the title bar on macOS (install_titlebar), otherwise this small icon button.
        self.help_button = QToolButton()
        self.help_button.setProperty("flatIcon", True)
        self.help_button.setAutoRaise(True)
        self.help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.help_button.setToolTip("Help")
        self.help_button.clicked.connect(lambda: self._on_help(HELP_TOPIC))
        self.help_button.setAccessibleName("Help")
        voice_row.addWidget(self.help_button)
        layout.addLayout(voice_row)
        self.voice_status = QLabel()                          # what was just heard, under the button; hidden when empty
        self.voice_status.setTextFormat(Qt.TextFormat.RichText)
        self.voice_status.setWordWrap(True)
        self.voice_status.setVisible(False)
        layout.addWidget(self.voice_status)
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
        """The underlying window (None before :meth:`setup`)."""
        return self._window

    def refresh_icons(self, color: str = "#1F1E1D") -> None:
        """Redraw the in-window help icon in the theme's text colour."""
        if self._window is None:
            return
        from quill.ui.icons import make_icon
        self.help_button.setIcon(make_icon("question", color, 18))

    def install_titlebar(self) -> None:
        """Put Help ("?") and Undo in the title bar (macOS), beside the close and zoom buttons.

        Elsewhere the window keeps its own in-window icon and Undo button.
        """
        if self._window is None or self._titlebar is not None:
            return
        self._titlebar = add_titlebar_button(
            self._window, lambda: self._on_undo(), symbol=SYMBOL_UNDO, tip="Undo the Last Answer",
            extra=[(SYMBOL_HELP, "Help", lambda: self._on_help(HELP_TOPIC))], side="left")
        native = self._titlebar is not None
        self.help_button.setVisible(not native)
        self.undo_button.setVisible(not native)
        if native:
            self._titlebar.set_enabled(self.undo_button.isEnabled())

    def set_items(self, items: list[TermKey]) -> None:
        """Make the list show *items*; the window hides when it is empty.

        Rows for terms that are still waiting are kept (so anything typed in them stays). Rows for
        terms that were just answered flash green, then ease away one after another, and the window
        closes after the last one when nothing is left, so the answers can be seen being accepted.
        """
        old = {row.key: row for row in self.rows}
        for row in self.rows:
            self._list.removeWidget(row)
        rows = []
        for key in items:
            first = not rows
            row = old.pop(key, None)
            if row is None:
                row = TermRow(key, self._vocab, self._on_resolve)
            row._on_activate = self._start_voice if first and not self._voice_active else None
            row.set_active(first and self._voice_active)
            if first and self._voice_active and key != self._spoken_key:
                self._spoken_key = key
                self._on_speak(row.guidance())                       # tell the user what to do for this row
            rows.append(row)
        if not self._voice_active:
            self._spoken_key = None
        leaving = list(old.values())
        animate = self.animation_ms > 0 and self._window is not None and self._window.isVisible()
        for row in leaving + rows:                          # answered rows stay on top while they play out
            self._list.insertWidget(self._list.count() - 1, row)
        self.rows = rows
        if animate and leaving:
            self._retire(leaving)
        else:
            for row in leaving:
                self._drop(row)
        if self._window is not None:
            self._window.setWindowTitle(f"Term Helper ({len(items)})" if items else "Term Helper")
            self.add_all_button.setEnabled(bool(items))
            self.ignore_all_button.setEnabled(bool(items))
            if not items and not self._retiring:
                self._window.hide()

    def note_choice(self, key: TermKey, column: str) -> None:
        """The user picked *column* for *key* by voice: show it chosen in the row's list."""
        for row in self.rows:
            if row.key == key:
                row.choose(column)

    def note_outcome(self, key: TermKey, outcome: str) -> None:
        """Say how *key* was answered: ``"accepted"``, ``"ignored"`` or ``"error"``.

        The row blinks in the matching colour as it leaves; an error blinks red at once and the row stays.
        """
        if outcome == "error":
            for row in self.rows:
                if row.key == key:
                    row.flash("error")
            return
        self._outcomes[key] = outcome

    # -- answered rows leaving ---------------------------------------------

    def _retire(self, rows: list[TermRow]) -> None:
        """Queue *rows* to flash and ease out, one after the other."""
        self._queue.extend(rows)
        if not self._retiring:
            self._next_retire()

    def _next_retire(self) -> None:
        if not self._queue:
            self._retiring = False
            if not self.rows and self._window is not None:
                self._window.hide()                        # nothing left: close the window
            return
        self._retiring = True
        row = self._queue.pop(0)
        wait = TermRow.CHOICE_MS if row.chosen else 0                # let the picked column show in the list first
        outcome = self._outcomes.pop(row.key, "accepted")
        if wait:
            QTimer.singleShot(wait, lambda: self._flash_then_collapse(row, outcome))
        else:
            self._flash_then_collapse(row, outcome)

    def _flash_then_collapse(self, row: TermRow, outcome: str) -> None:
        row.flash(outcome)
        QTimer.singleShot(self.FLASH_MS, lambda: self._collapse(row))

    def _collapse(self, row: TermRow) -> None:
        """Ease *row* shut (height and fade together), then remove it and go on to the next."""
        row.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        row.setMinimumHeight(0)
        effect = QGraphicsOpacityEffect(row)
        row.setGraphicsEffect(effect)
        height = QPropertyAnimation(row, b"maximumHeight", row)
        height.setDuration(self.animation_ms)
        height.setEasingCurve(QEasingCurve.Type.InOutCubic)
        height.setStartValue(row.height())
        height.setEndValue(0)
        fade = QPropertyAnimation(effect, b"opacity", row)
        fade.setDuration(self.animation_ms)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        height.finished.connect(lambda: (self._drop(row), self._next_retire()))
        row._animations = (height, fade)                   # keep them alive
        height.start()
        fade.start()

    def _drop(self, row: TermRow) -> None:
        self._list.removeWidget(row)
        row.hide()                                         # leave the screen now, not when Qt gets to deleteLater
        row.setParent(None)
        row.deleteLater()

    # -- voice sorting -----------------------------------------------------

    @property
    def voice_active(self) -> bool:
        """True while voice sorting is on."""
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
        if not self._voice_active:
            return                                            # nothing to report once voice sorting is off
        text = f"Heard ‘{heard}’ → {message}" if heard else message
        self.voice_status.setText(pillify(text))
        self.voice_status.setVisible(bool(text))

    def set_voice_countdown(self, seconds: int | None) -> None:
        """Show the seconds left before voice sorting stops because it is quiet (None hides it)."""
        self.voice_countdown.setVisible(seconds is not None and self._voice_active)
        if seconds is not None:
            self.voice_countdown.setText(f"Stops in {seconds}s")

    def _render_voice(self) -> None:
        self.voice_button.setChecked(self._voice_active)
        self.voice_button.setText("🎤 Listening (click to stop)" if self._voice_active
                                  else "🎤 Sort by Voice")

    def show(self) -> None:
        """Show the window (and bring it to the front)."""
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
        """Forget every term in the list."""
        with self._batch("Ignored terms"):
            for row in list(self.rows):
                row.ignore()

    def set_undo_available(self, count: int) -> None:
        """Enable the Undo button while there is something to take back."""
        if self._window is not None:
            self.undo_button.setEnabled(count > 0)
            self.undo_button.setText(f"↶ Undo ({count})" if count else "↶ Undo")
            if self._titlebar is not None:
                self._titlebar.set_enabled(count > 0)
