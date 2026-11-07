"""The list on Settings > Learned Words: every word Quill was taught to read as a column.

A search box, an "All files / This file" choice, a grouping choice (by file, by column or none), the order the groups
come in (most recent first, by name, or by how many words they hold) and a list whose headings sort the words inside each
group. The list is drawn like the Keywords table: spoken words as pills, tinted group bands, status pills, roomy rows. Forgetting one or several words is immediate and saved, and forgetting many always asks first
(see :mod:`quill.ui.confirm`): a list built over months of use must not vanish with one click.

Words are kept by column name, not by file, so a word learned in one file helps every file that has the column; each
link remembers the files it was learned in, which is what "This file" and the "Learned in" column show.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from quill.learning import Link, LinkStore
from quill.ui.confirm import confirm
from quill.ui.settings_widgets import FlatCombo
from quill.ui.theme import PILL_BG, PILL_FG, colors_for, is_dark, mix

GROUPINGS = (("file", "Group by File"), ("column", "Group by Column"), ("none", "No Grouping"))
EMPTY_TEXT = ("Nothing learned yet. Change a line's column in the Current Row box, or say “spotted means Observation Date” "
              "(a word, “means”, a column name) while Quill is listening.")
NONE_MATCH_TEXT = "No learned words match."
HEADINGS = ("When You Say…", "Quill Reads It As…", "Learned In", "Status", "Used")
#: How the groups are ordered: (key, label). "recent" = the group something was last learned in comes first.
ORDERS = (("recent", "Most Recent First"), ("name", "Name A–Z"), ("words", "Most Words First"))
ROW_HEIGHT = 40
GROUP_ROLE = Qt.ItemDataRole.UserRole + 1                 # set on the tinted group rows
WORD_COLUMN, STATUS_COLUMN, USED_COLUMN = 0, 3, 4


class _ListDelegate(QStyledItemDelegate):
    """Draws the list like the Keywords table: spoken words as violet pills, status as a soft pill, group rows as tinted
    bands, a hairline under every row, and a soft accent tint (never a solid block) behind selected rows."""

    def sizeHint(self, option, index) -> QSize:                                      # noqa: N802 (Qt name)
        """Row height is fixed; a column is as wide as its pill or text needs (so the status never gets cut off)."""
        if index.data(GROUP_ROLE):
            return QSize(option.rect.width(), ROW_HEIGHT)
        room = {WORD_COLUMN: 30, STATUS_COLUMN: 34}.get(index.column(), 16)
        return QSize(QFontMetrics(option.font).horizontalAdvance(str(index.data() or "")) + room, ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        app = QApplication.instance()
        t = colors_for(is_dark(app), str(app.property("quillAccent") or "violet"))
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if index.data(GROUP_ROLE):
            painter.fillRect(rect, QColor(mix(t["surface"], t["accent"], 0.12)))
            painter.setPen(QColor(t["text"]))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect.adjusted(14, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             index.data() or "")
            painter.restore()
            return
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QColor(mix(t["surface"], t["accent"], 0.18)))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor(t["hover"]))
        painter.setPen(QColor(t["border"]))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        text, column = str(index.data() or ""), index.column()
        inner = rect.adjusted(14 if column == 0 else 6, 0, -8, 0)
        metrics = painter.fontMetrics()
        if column == WORD_COLUMN:
            width = metrics.horizontalAdvance(text) + 16
            pill = QRect(inner.left(), rect.top() + (rect.height() - 26) // 2, min(width, inner.width()), 26)
            painter.fillRect(pill, QColor(PILL_BG))
            painter.setPen(QColor(PILL_FG))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, metrics.elidedText(text, Qt.TextElideMode.ElideRight, pill.width() - 12))
        elif column == STATUS_COLUMN:
            fill, ink = self._status_colors(text, t)
            width = metrics.horizontalAdvance(text) + 22
            pill = QRectF(inner.left(), rect.top() + (rect.height() - 24) / 2, min(width, inner.width()), 24)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(pill, 12, 12)
            painter.setPen(QColor(ink))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        else:
            painter.setPen(QColor(t["muted"] if column >= 2 else t["text"]))
            align = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if column == USED_COLUMN else Qt.AlignmentFlag.AlignLeft)
            painter.drawText(inner, align, metrics.elidedText(text, Qt.TextElideMode.ElideRight, inner.width()))
        painter.restore()

    @staticmethod
    def _status_colors(text: str, t: dict[str, str]) -> tuple[str, str]:
        """(fill, text) of a status pill: taught = accent, in use = green, still learning = amber."""
        if text == "Taught":
            return mix(t["surface"], t["accent"], 0.20), t["text"]
        if text == "In use":
            return mix(t["surface"], "#3E9B52", 0.22), t["text"]
        return mix(t["surface"], "#D9A12B", 0.28), t["text"]


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
        self.order = FlatCombo()
        for key, label in ORDERS:
            self.order.addItem(label, key)
        self.order.setToolTip("The order of the groups. Most Recent First puts the file (or column) something was last "
                              "learned in at the top. Click a heading to sort the words inside each group.")
        self.order.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.order)
        layout.addLayout(controls)

        self.tree = QTreeWidget()
        self.tree.setObjectName("learnedList")
        self.tree.setColumnCount(len(HEADINGS))
        self.tree.setHeaderLabels(list(HEADINGS))
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setSortingEnabled(False)                       # sorted here: the groups have their own order
        self.tree.setItemDelegate(_ListDelegate(self.tree))
        self.tree.setMouseTracking(True)
        self.tree.setFrameShape(QTreeWidget.Shape.NoFrame)
        self._sort_column, self._sort_order = 0, Qt.SortOrder.AscendingOrder
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumHeight(240)
        self.tree.setCursor(Qt.CursorShape.ArrowCursor)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 170)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        header.sectionClicked.connect(self._heading_clicked)
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

    def _heading_clicked(self, column: int) -> None:
        """A heading sorts the words inside each group; clicking it again reverses the order."""
        if column == self._sort_column:
            self._sort_order = (Qt.SortOrder.DescendingOrder if self._sort_order == Qt.SortOrder.AscendingOrder
                                else Qt.SortOrder.AscendingOrder)
        else:
            self._sort_column, self._sort_order = column, Qt.SortOrder.AscendingOrder
        self.tree.header().setSortIndicator(self._sort_column, self._sort_order)
        self.refresh()

    def _sort_key(self, link: Link):
        """What a word is sorted by under the clicked heading."""
        column = self._sort_column
        if column == 1:
            return (link.column.lower(), link.shown.lower())
        if column == 2:
            return (", ".join(s.name for s in link.sources).lower(), link.shown.lower())
        if column == STATUS_COLUMN:
            need = self._learn_after()
            rank = 0 if link.taught else 1 if link.count >= need else 2
            return (rank, -link.count, link.shown.lower())
        if column == USED_COLUMN:
            return (link.used, link.shown.lower())
        return (link.shown.lower(), link.column.lower())

    def _group_order(self, groups: dict[str, list[Link]], mode: str) -> list[str]:
        """The group names in the order chosen (a file's recency is when something was last learned in it)."""
        how = self.order.currentData()
        if how == "name":
            return sorted(groups, key=str.lower)
        if how == "words":
            return sorted(groups, key=lambda key: (-len(groups[key]), key.lower()))

        def newest(key: str) -> float:
            return max((s.last for link in groups[key] for s in link.sources if mode != "file" or s.name == key), default=0.0)
        return sorted(groups, key=lambda key: (-newest(key), key.lower()))

    def refresh(self, *_args) -> None:
        """Rebuild the list from the store (after a search, filter, grouping, order or setting change, or a forget)."""
        self._shown = self._visible_links()
        mode = self.grouping.currentData()
        self.order.setEnabled(mode != "none")
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        ordered = sorted(self._shown, key=self._sort_key, reverse=self._sort_order == Qt.SortOrder.DescendingOrder)
        if mode == "none":
            for link in ordered:
                self.tree.addTopLevelItem(self._item(link))
        else:
            groups: dict[str, list[Link]] = {}
            for link in ordered:
                keys = [link.column] if mode == "column" else [s.name for s in link.sources] or ["(unknown file)"]
                for key in keys:                                     # a word learned in several files is under each
                    groups.setdefault(key, []).append(link)
            for key in self._group_order(groups, mode):
                members = groups[key]
                holder = QTreeWidgetItem([f"{key}  ·  {len(members)}"])
                holder.setData(0, GROUP_ROLE, True)
                holder.setData(0, Qt.ItemDataRole.UserRole + 2, key)
                holder.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.tree.addTopLevelItem(holder)
                self.tree.setFirstColumnSpanned(self.tree.indexOfTopLevelItem(holder), QModelIndex(), True)   # the name reads in full
                for link in members:
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
