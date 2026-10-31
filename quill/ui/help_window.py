"""The help window: a sidebar of topics (with search) beside a reading pane, like the Settings window.

Every ``?`` icon in the app opens it on the topic about the place it sits in (``show(topic)``), so the
reader lands where they need to be, not at the top. The pages are Markdown files (see
:mod:`quill.helpdocs`), shown with their headings, lists, tables, code, emoji and pictures styled to
match the app.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtGui import QTextFrameFormat, QTextTable
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from quill import helpdocs
from quill.ui.theme import install_backdrop
from quill.helpdocs import Topic

#: Heading sizes as multiples of the body text.
_HEADING_SCALE = {1: 1.9, 2: 1.45, 3: 1.2, 4: 1.05}


class HelpWindow:
    """Help for the whole app.

    Args:
        topics: The pages to show (default: the bundled help).
        parent: A window to stay above (needed to be usable from a modal dialog such as Settings).
    """

    def __init__(self, topics: list[Topic] | None = None, parent: QWidget | None = None) -> None:
        self.topics = topics if topics is not None else helpdocs.load_topics()
        self._parent = parent
        self._window: QWidget | None = None
        self.root: QWidget | None = None
        self.current: Topic | None = None
        self._items: dict[str, QTreeWidgetItem] = {}
        self._loading = False

    # ------------------------------------------------------------------ #

    def setup(self) -> QWidget:
        """Build the window (once; it is reused each time help is opened)."""
        window = QWidget(self._parent, Qt.WindowType.Window)
        window.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        window.setWindowTitle("Quill Help")
        window.resize(980, 700)
        window.setMinimumSize(700, 460)
        shell = QVBoxLayout(window)
        shell.setContentsMargins(0, 0, 0, 0)
        root = QWidget()
        root.setObjectName("helpRoot")

        install_backdrop(root)                              # paints its own (see-through-able) background
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell.addWidget(root)
        self.root = root
        body = QHBoxLayout(root)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        side = QWidget()
        side.setObjectName("settingsSidebar")                  # the same look as Settings' sidebar
        side.setFixedWidth(280)
        side.setProperty("keepMargins", True)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 16, 14, 12)
        side_layout.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Help")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        side_layout.addWidget(self.search)
        self.empty_label = QLabel("No help pages match your search.")
        self.empty_label.setProperty("muted", True)
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(False)
        side_layout.addWidget(self.empty_label)
        self.nav = QTreeWidget()
        self.nav.setObjectName("helpNav")
        self.nav.setHeaderHidden(True)
        self.nav.setRootIsDecorated(False)
        self.nav.setIndentation(14)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nav.currentItemChanged.connect(self._nav_changed)
        side_layout.addWidget(self.nav, 1)
        body.addWidget(side)

        self.page = QTextBrowser()
        self.page.setObjectName("helpPage")
        self.page.setOpenLinks(False)
        self.page.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.page.setSearchPaths([str(helpdocs.help_dir())])
        self.page.document().setBaseUrl(QUrl.fromLocalFile(str(helpdocs.help_dir()) + "/"))
        self.page.document().setDocumentMargin(34)
        self.page.anchorClicked.connect(self._link_clicked)
        body.addWidget(self.page, 1)

        self._window = window
        self._fill_nav()
        return window

    @property
    def widget(self) -> QWidget | None:
        """The underlying window (None before :meth:`setup`)."""
        return self._window

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    def _fill_nav(self) -> None:
        self.nav.clear()
        self._items = {}
        for topic in self.topics:
            item = QTreeWidgetItem([topic.title])
            item.setData(0, Qt.ItemDataRole.UserRole, (topic.slug, None))
            self.nav.addTopLevelItem(item)
            self._items[topic.slug] = item
            for section in topic.sections:
                child = QTreeWidgetItem([section])
                child.setData(0, Qt.ItemDataRole.UserRole, (topic.slug, section))
                child.setForeground(0, self.nav.palette().placeholderText())
                item.addChild(child)

    def topic(self, slug: str) -> Topic | None:
        """The page with this slug, or None."""
        return next((t for t in self.topics if t.slug == slug), None)

    def show(self, topic: str | None = None, section: str | None = None) -> None:
        """Open the window on *topic* (a slug such as ``"term-helper"``), scrolled to *section* if given.

        An unknown or missing topic opens the first page.
        """
        if self._window is None:
            self.setup()
        self.search.clear()                                   # a search must not hide where help should land
        target = self.topic(topic or "") or (self.topics[0] if self.topics else None)
        if target is not None:
            self.goto(target.slug, section)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def goto(self, slug: str, section: str | None = None) -> None:
        """Select a topic (and optionally one of its sections) in the sidebar and show it."""
        item = self._items.get(slug)
        if item is None:
            return
        target = item
        if section:
            target = next((item.child(i) for i in range(item.childCount()) if item.child(i).text(0) == section), item)
        self.nav.setCurrentItem(target)                       # -> _nav_changed

    def _nav_changed(self, item: QTreeWidgetItem | None, _previous=None) -> None:
        if item is None or self._loading:
            return
        slug, section = item.data(0, Qt.ItemDataRole.UserRole)
        topic = self.topic(slug)
        if topic is None:
            return
        for other in self._items.values():                    # only the open topic lists its sections
            other.setExpanded(other is self._items[slug])
        if topic is not self.current:
            self._render(topic)
        if section:
            QTimer.singleShot(0, lambda: self._scroll_to(section))
        else:
            self.page.verticalScrollBar().setValue(0)

    def _link_clicked(self, url: QUrl) -> None:
        """``help:<topic>`` links jump within help; anything else opens in the browser."""
        if url.scheme() == "help":
            self.goto(url.path() or url.host())
        elif url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)

    def filter(self, text: str) -> None:
        """Show only the pages that mention *text* (the page being read stays selected if it still matches)."""
        shown = 0
        for topic in self.topics:
            visible = topic.matches(text)
            self._items[topic.slug].setHidden(not visible)
            shown += visible
        self.empty_label.setVisible(shown == 0)

    # ------------------------------------------------------------------ #
    # Reading pane                                                         #
    # ------------------------------------------------------------------ #

    def _render(self, topic: Topic) -> None:
        self.current = topic
        self.page.setMarkdown(topic.text)
        self._style_document()

    def _scroll_to(self, heading: str) -> None:
        doc = self.page.document()
        block = doc.begin()
        while block.isValid():
            if block.blockFormat().headingLevel() and block.text().strip() == heading:
                top = doc.documentLayout().blockBoundingRect(block).top()
                self.page.verticalScrollBar().setValue(max(int(top) - 12, 0))
                return
            block = block.next()

    @staticmethod
    def _holds_image(block) -> bool:
        it = block.begin()
        while not it.atEnd():
            if it.fragment().charFormat().isImageFormat():
                return True
            it += 1
        return False

    def _style_document(self) -> None:
        """Make the Markdown read nicely: airy lines, sized headings, code pills, bordered tables, quotes."""
        doc = self.page.document()
        palette = self.page.palette()
        base = QFont(self.page.font()).pointSizeF() or 12.0
        text = palette.text().color()
        tint = QColor(palette.highlight().color())
        tint.setAlpha(40)
        panel = QColor(text)
        panel.setAlpha(26)
        edge = QColor(text)
        edge.setAlpha(60)                                   # a quiet table border
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        block = doc.begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            c = QTextCursor(block)
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            fmt, bf = QTextCharFormat(), QTextBlockFormat()
            if level:
                fmt.setFontPointSize(base * _HEADING_SCALE.get(level, 1.0))
                fmt.setFontWeight(QFont.Weight.DemiBold if level > 1 else QFont.Weight.Bold)
                bf.setTopMargin(26 if level == 2 else (6 if level == 1 else 14))
                bf.setBottomMargin(10)
            else:
                if not self._holds_image(block):               # a tall line height would stretch a picture's block
                    bf.setLineHeight(158, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
                bf.setBottomMargin(9)
                if block.blockFormat().indent() or block.blockFormat().hasProperty(
                        QTextBlockFormat.Property.BlockQuoteLevel):
                    pass
            if block.blockFormat().intProperty(QTextBlockFormat.Property.BlockQuoteLevel):
                bf.setBackground(tint)
                bf.setLeftMargin(14)
                bf.setRightMargin(14)
                bf.setTopMargin(4)
                bf.setBottomMargin(8)
            c.mergeBlockFormat(bf)
            c.mergeCharFormat(fmt)
            # inline code: a pill-like background
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.charFormat().fontFixedPitch():
                    f = QTextCursor(doc)
                    f.setPosition(fragment.position())
                    f.setPosition(fragment.position() + fragment.length(), QTextCursor.MoveMode.KeepAnchor)
                    pill = QTextCharFormat()
                    pill.setBackground(QColor("#5E4A99"))
                    pill.setForeground(QColor("#FFFFFF"))
                    f.mergeCharFormat(pill)
                it += 1
            block = block.next()
        cursor.endEditBlock()
        for frame in doc.rootFrame().childFrames():
            if isinstance(frame, QTextTable):
                tf = frame.format()
                tf.setCellPadding(9)
                tf.setCellSpacing(0)
                tf.setBorder(1)
                tf.setBorderBrush(edge)
                tf.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
                tf.setTopMargin(6)
                tf.setBottomMargin(14)
                frame.setFormat(tf)

    # ------------------------------------------------------------------ #

    def restyle(self, prefs: dict, qapp) -> None:
        """Apply the current theme, accent, opacity and blur to this window (called by the app)."""
        if self._window is None:
            return
        from quill.ui.chrome import apply_chrome
        from quill.ui.theme import apply_opacity, colors_for, is_dark
        dark = is_dark(qapp)
        apply_chrome(self._window, dark, colors_for(dark, str(prefs["accent"])),
                     opacity=int(prefs["opacity"]), blur=int(prefs["blur"]))
        apply_opacity(self.root, int(prefs["opacity"]))
        if self.current is not None:
            self._render(self.current)                        # restyle for the new colours
