"""The list on Settings > Learned Words: every word Quill was taught to read as a column.

A search box, an "All files / This file" choice, a grouping choice (by file, by column or none), and a list whose
headings sort it. Forgetting one or several words is immediate and saved, and forgetting many always asks first
(see :mod:`quill.ui.confirm`): a list built over months of use must not vanish with one click.

Words are kept by column name, not by file, so a word learned in one file helps every file that has the column; each
link remembers the files it was learned in, which is what "This file" and the "Learned in" column show.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from quill.learning import Link, LinkStore
from quill.ui.confirm import confirm
from quill.ui.settings_widgets import FlatCombo

GROUPINGS = (("file", "Group by File"), ("column", "Group by Column"), ("none", "No Grouping"))
EMPTY_TEXT = ("Nothing learned yet. Change a line's column in the Current Row box, or say “spotted means Observation Date” "
              "(a word, “means”, a column name) while Quill is listening.")
NONE_MATCH_TEXT = "No learned words match."
HEADINGS = ("Word", "Column", "Learned In", "Status", "Used")


class LearnedWordsPanel(QWidget):
    """Search, filter, group and forget learned words.

    Args:
        links: The store being shown (changed in place; ``changed`` fires after each forget so it can be saved).
        learn_after: Gives the current "corrections before learning" setting, for the Status column.
        active_file: Gives ``(path, name, columns)`` of the active file ("" and [] when there is none).
        parent: Optional parent.
    """

    #: A forget happened: the settings should be saved.
    changed = Signal()

    def __init__(self, links: LinkStore, learn_after: Callable[[], int],
                 active_file: Callable[[], tuple[str, str, list[str]]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._links = links
        self._learn_after = learn_after
        self._active_file = active_file
        self._shown: list[Link] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setToolTip("Search words, columns and file names.")
        self.search.setMinimumWidth(140)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        controls.addWidget(self.search, 1)
        self.scope = FlatCombo()
        self.scope.addItem("All Files", "all")
        self.scope.addItem("This File", "file")
        self.scope.setToolTip("All Files: every learned word. This File: words learned in the active file, and words for "
                              "columns it has.")
        self.scope.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.scope)
        self.grouping = FlatCombo()
        for key, label in GROUPINGS:
            self.grouping.addItem(label, key)
        self.grouping.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.grouping)
        layout.addLayout(controls)

        self.tree = QTreeWidget()
        self.tree.setObjectName("learnedList")
        self.tree.setColumnCount(len(HEADINGS))
        self.tree.setHeaderLabels(list(HEADINGS))
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(14)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumHeight(240)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 110)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
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
        self.forget_selected_button = QPushButton("Forget Selected")
        self.forget_all_button = QPushButton("Forget All Shown")
        for button in (self.forget_selected_button, self.forget_all_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            bottom.addWidget(button)
        self.forget_selected_button.clicked.connect(self.forget_selected)
        self.forget_all_button.clicked.connect(self.forget_shown)
        layout.addLayout(bottom)
        self.refresh()

    # ------------------------------------------------------------------ #

    def show_this_file(self, on: bool = True) -> None:
        """Switch the list to the active file's words (the shortcut in the Files panel does this)."""
        self.scope.setCurrentIndex(1 if on else 0)

    def _in_scope(self, link: Link) -> bool:
        if self.scope.currentIndex() == 0:
            return True
        path, _name, columns = self._active_file()
        return link in self._links.for_file(path, columns)

    def _visible_links(self) -> list[Link]:
        query = self.search.text().lower().split()
        out = []
        for link in self._links.links():
            if not self._in_scope(link):
                continue
            text = " ".join([link.shown, link.column, *(s.name for s in link.sources)]).lower()
            if all(word in text for word in query):
                out.append(link)
        return out

    def _status(self, link: Link) -> str:
        need = self._learn_after()
        if link.taught:
            return "Taught"
        return "In use" if link.count >= need else f"Learning ({link.count} of {need})"

    def refresh(self, *_args) -> None:
        """Rebuild the list from the store (after a search, filter, grouping or setting change, or a forget)."""
        self._shown = self._visible_links()
        mode = self.grouping.currentData()
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for link in sorted(self._shown, key=lambda l: l.shown.lower()):
            if mode == "none":
                self.tree.addTopLevelItem(self._item(link))
                continue
            if mode == "column":
                keys = [link.column]
            else:
                keys = [s.name for s in link.sources] or ["(unknown file)"]       # a word learned in several files is under each
            for key in keys:
                holder = groups.get(key)
                if holder is None:
                    holder = groups[key] = QTreeWidgetItem([key])
                    font = holder.font(0)
                    font.setBold(True)
                    holder.setFont(0, font)
                    holder.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self.tree.addTopLevelItem(holder)
                holder.addChild(self._item(link))
        self.tree.expandAll()
        self.tree.setUpdatesEnabled(True)
        total = len(self._links)
        self.empty.setText(EMPTY_TEXT if not total else NONE_MATCH_TEXT)
        self.empty.setVisible(not self._shown)
        self.tree.setVisible(bool(self._shown))
        self.count_label.setText(f"{len(self._shown)} of {total} learned words shown" if total else "")
        self.forget_all_button.setEnabled(bool(self._shown))
        self._selection_changed()

    def _item(self, link: Link) -> QTreeWidgetItem:
        sources = ", ".join(s.name for s in link.sources)
        item = QTreeWidgetItem([link.shown, link.column, sources, self._status(link), str(link.used)])
        item.setData(0, Qt.ItemDataRole.UserRole, (link.word, link.column))
        item.setToolTip(2, "\n".join(s.path or s.name for s in link.sources))
        item.setTextAlignment(4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _selected_links(self) -> list[Link]:
        found: dict[tuple[str, str], Link] = {}
        for item in self.tree.selectedItems():
            key = item.data(0, Qt.ItemDataRole.UserRole)
            link = self._links.get(key[0], key[1]) if key else None
            if link is not None:
                found[(link.word, link.column)] = link
        return list(found.values())

    def _selection_changed(self) -> None:
        self.forget_selected_button.setEnabled(bool(self._selected_links()))

    # ------------------------------------------------------------------ #

    def forget_selected(self) -> None:
        """Forget the selected words (more than one asks first)."""
        self._forget(self._selected_links(), "selected")

    def forget_shown(self) -> None:
        """Forget every word the list shows right now: the search and filter decide which (always asks first)."""
        self._forget(list(self._shown), "shown", always_ask=True)

    def _forget(self, links: list[Link], which: str, always_ask: bool = False) -> None:
        if not links:
            return
        count = len(links)
        word = "word" if count == 1 else "words"
        if count > 1 or always_ask:
            where = ""
            if which == "shown" and (self.search.text().strip() or self.scope.currentIndex() == 1):
                where = " that match the current search and filter"
            if not confirm(self.window(), f"Forget {count} learned {word}?",
                           f"Quill will stop using {'this word' if count == 1 else f'these {count} words'}{where}, and will "
                           "have to be taught again. This can't be undone.",
                           f"Forget {count} {word.title()}"):
                return
        self._links.forget_many(links)
        self.changed.emit()
        self.refresh()
