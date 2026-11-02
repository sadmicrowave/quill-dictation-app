"""Hover text for everything that can be clicked.

Every button, drop-down, switch, radio button and link in Quill explains itself when the pointer rests on it.
Most set their own text where they are made; :func:`fill_missing_tips` is the safety net that is run over a window
once it is built (and again when rows are added), so nothing clickable is ever silent. It also names the controls
the toolkit makes by itself.
"""

from __future__ import annotations

import re

from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QToolButton, QWidget

#: Plain words on a button -> what pressing it does.
KNOWN_TIPS = {
    "OK": "Save the changes and close",
    "Cancel": "Close without saving the changes",
    "Add": "Add this",
    "Remove": "Remove the selected line",
    "Ignore": "Forget this term; it will not be asked about again",
    "Restore Defaults": "Put back the keywords Quill came with",
    "Download": "Download this speech model (one time)",
    "Installed": "This speech model is already on this computer",
    "Open Log Folder": "Open the folder that holds Quill's log files",
    "Add All With a Column": "Add every term that already has a column chosen",
    "Ignore All": "Forget every term in the list",
    "Undo": "Take back the last answer (you can keep stepping back)",
}

#: Qt's own parts that are clickable but are not Quill's to explain.
_TOOLKIT = ("qt_menubar_ext_button", "qt_tableview_cornerbutton", "qt_scrollarea", "qt_")


_PICTOGRAPHS = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\uFE0F\u200D]")


def plain(text: str) -> str:
    """*text* without emoji and symbols (a heading such as "👋 Welcome" becomes "Welcome"), for hover text."""
    return " ".join(_PICTOGRAPHS.sub("", text).split())


def is_clickable(widget: QWidget) -> bool:
    """A button of any kind, a drop-down, or a label that holds a link (the toolkit's own parts excluded)."""
    if widget.objectName().startswith(_TOOLKIT):
        return False
    if isinstance(widget, (QAbstractButton, QComboBox)):
        return True
    return isinstance(widget, QLabel) and "href=" in widget.text() and not widget.property("hoverLinkTips")


def describe(widget: QWidget) -> str:
    """The best hover text available for *widget* without being told: a known phrase, its accessible name or its words."""
    if isinstance(widget, QToolButton) and isinstance(widget.parentWidget(), QLineEdit):
        return "Clear the text"                                        # the little x inside a search box
    text = widget.currentText() if isinstance(widget, QComboBox) else (widget.text() if hasattr(widget, "text") else "")
    plain = text.replace("&", "").strip()
    if plain in KNOWN_TIPS:
        return KNOWN_TIPS[plain]
    if widget.accessibleName():
        return widget.accessibleName()
    if isinstance(widget, QComboBox):
        return "Choose from the list"
    if isinstance(widget, QToolButton) and not plain:
        return widget.toolTip()
    return plain


def missing_tips(root: QWidget) -> list[QWidget]:
    """Every clickable widget under *root* (and *root* itself) that shows nothing on hover."""
    found = []
    for widget in [root, *root.findChildren(QWidget)]:
        if is_clickable(widget) and not widget.toolTip():
            found.append(widget)
    return found


def fill_missing_tips(root: QWidget) -> int:
    """Give every clickable widget under *root* that has no hover text one (see :func:`describe`). Returns how many."""
    count = 0
    for widget in missing_tips(root):
        tip = describe(widget)
        if tip:
            widget.setToolTip(tip)
            count += 1
    return count
