"""The list on Settings > Words To Skip: words Quill never makes part of a new value.

Words get here when a word is trimmed off a term in the Term Helper, or when they are added by hand on this page. The list is drawn
like the Learned Words list (a word is a violet pill, hairlines between roomy rows), a word is added with the box above it
(**Enter** or **Add**), and removed with **Remove Selected** or **Remove All** (the latter asks first). Every change is saved at once.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from quill.config.settings import Settings
from quill.ui.confirm import confirm
from quill.ui.learned_page import _ListDelegate

EMPTY_TEXT = "No words yet. Trim a word off a term in the Term Helper, or add one above."
NONE_MATCH_TEXT = "No skipped words match."


class SkippedWordsPanel(QWidget):
    """Add, search and remove the words Quill skips.

    Args:
        settings: The settings whose ``skip_words`` are shown (changed in place; ``changed`` fires after each change so they get saved).
        parent: Optional parent.
    """

    #: The list changed: the settings should be saved and applied.
    changed = Signal()

    title = "Words To Skip"
    search_text = "words to skip skip ignore words filler learned trimmed leave out add remove"

    def matches(self, query: str) -> bool:
        """For the Settings search: true if every word of *query* is about this list."""
        return all(word in self.search_text for word in query.lower().split())

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(8)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText("Add a word to skip")
        self.add_edit.setToolTip("A word Quill leaves out of new values. Press Enter to add it.")
        self.add_edit.returnPressed.connect(self.add_typed)
        add_row.addWidget(self.add_edit, 1)
        self.add_button = QPushButton("Add")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.add_typed)
        add_row.addWidget(self.add_button)
        layout.addLayout(add_row)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Search the skipped words.")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setObjectName("learnedList")
        self.tree.setColumnCount(1)
        self.tree.setHeaderLabels(["Words Quill Skips"])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setItemDelegate(_ListDelegate(self.tree))
        self.tree.setMouseTracking(True)
        self.tree.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumHeight(240)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.tree, 1)

        self.empty = QLabel(EMPTY_TEXT)
        self.empty.setWordWrap(True)
        self.empty.setProperty("muted", True)
        layout.addWidget(self.empty)

        bottom = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setProperty("muted", True)
        bottom.addWidget(self.count_label, 1)
        self.remove_selected_button = QPushButton("Remove Selected")
        self.remove_all_button = QPushButton("Remove All Shown")
        for button in (self.remove_selected_button, self.remove_all_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            bottom.addWidget(button)
        self.remove_selected_button.clicked.connect(self.remove_selected)
        self.remove_all_button.clicked.connect(self.remove_shown)
        layout.addLayout(bottom)
        self.refresh()

    # ------------------------------------------------------------------ #

    def _shown(self) -> list[str]:
        query = self.search.text().lower().split()
        return [w for w in sorted(self._settings.skip_words) if all(q in w for q in query)]

    def refresh(self, *_args) -> None:
        """Rebuild the list from the settings (after a search or a change)."""
        shown = self._shown()
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        for word in shown:
            item = QTreeWidgetItem([word])
            item.setData(0, Qt.ItemDataRole.UserRole, word)
            self.tree.addTopLevelItem(item)
        self.tree.setUpdatesEnabled(True)
        total = len(self._settings.skip_words)
        self.empty.setText(EMPTY_TEXT if not total else NONE_MATCH_TEXT)
        self.empty.setVisible(not shown)
        self.tree.setVisible(bool(shown))
        self.count_label.setText(f"{len(shown)} of {total} skipped words shown" if total else "")
        self.remove_all_button.setEnabled(bool(shown))
        self._selection_changed()

    def _selection_changed(self) -> None:
        self.remove_selected_button.setEnabled(bool(self.tree.selectedItems()))

    def add_typed(self) -> None:
        """Add what was typed (several words may be separated by commas or spaces); the box is emptied."""
        words = [w for w in self.add_edit.text().lower().replace(";", " ").replace(",", " ").split() if w]
        self.add_edit.clear()
        if words and self._settings.add_skip_words(words):
            self.changed.emit()
        self.search.clear()
        self.refresh()

    def remove_selected(self) -> None:
        """Remove the selected words (more than one asks first)."""
        self._remove([item.data(0, Qt.ItemDataRole.UserRole) for item in self.tree.selectedItems()], always_ask=False)

    def remove_shown(self) -> None:
        """Remove every word the list shows right now (always asks first)."""
        self._remove(self._shown(), always_ask=True)

    def _remove(self, words: list[str], always_ask: bool) -> None:
        if not words:
            return
        count = len(words)
        if count > 1 or always_ask:
            noun = "word" if count == 1 else "words"
            if not confirm(self.window(), f"Remove {count} skipped {noun}?",
                           f"Quill will stop skipping {'this word' if count == 1 else f'these {count} words'}, so "
                           f"{'it' if count == 1 else 'they'} can become part of a new value again.",
                           f"Remove {count} {noun.title()}"):
                return
        self._settings.skip_words = [w for w in self._settings.skip_words if w not in set(words)]
        self.changed.emit()
        self.refresh()
