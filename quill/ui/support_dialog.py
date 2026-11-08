"""The *Report a Problem* window: a form that needs no GitHub account.

The person writes what happened, may leave an address for a reply, and chooses whether the diagnostic log goes with it.
*Show exactly what will be sent* opens the very text that is posted (nothing is sent unless the person presses Send),
*Copy Diagnostics* puts that text on the clipboard for an e-mail or chat, and a link above the box opens the known
issues so a problem that is already tracked can be found first. The window sends through a callback so it holds no
network code: the app runs it off the window's thread and calls :meth:`finished` with the result.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from quill import support


class SupportDialog(QDialog):
    """Title, form, preview and buttons.

    Args:
        parent: The window it opens over.
        send: ``send(payload)`` starts sending off the window's thread; the app then calls :meth:`finished`.
        open_privacy: Opens the privacy page of the help.
        kind: ``"problem"``, or ``"crash"`` when the program hit an unexpected error last time.
        log_folder: Where the log is (tests pass their own).
        configured: Whether sending is set up in this version (default: :data:`quill.support.SUPPORT_URL` is set).
    """

    def __init__(self, parent: QWidget | None, send: Callable[[dict], None], open_privacy: Callable[[], None],
                 kind: str = "problem", log_folder=None, configured: bool | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("supportDialog")
        self.setWindowTitle("Report a Problem")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._send, self._kind, self._log_folder = send, kind, log_folder
        self._configured = bool(support.SUPPORT_URL) if configured is None else configured
        self._sent = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)
        heading = QLabel("Quill hit an unexpected error last time" if kind == "crash" else "Report a Problem")
        heading.setObjectName("confirmTitle")
        layout.addWidget(heading)
        intro = QLabel("Tell us what went wrong and what you were doing. You don't need a GitHub account.")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        layout.addWidget(intro)

        links = QLabel('<a href="known">Check the known problems first</a> &nbsp;·&nbsp; <a href="privacy">What is sent and what isn\'t</a>')
        links.setProperty("panelNote", True)
        links.setTextFormat(Qt.TextFormat.RichText)
        links.linkActivated.connect(lambda key: QDesktopServices.openUrl(QUrl(support.ISSUES_URL)) if key == "known" else open_privacy())
        layout.addWidget(links)

        self.message = QPlainTextEdit()
        self.message.setPlaceholderText("What happened? What did you expect?")
        self.message.setFixedHeight(110)
        self.message.textChanged.connect(self._changed)
        layout.addWidget(self.message)

        self.contact = QLineEdit()
        self.contact.setPlaceholderText("Your e-mail, only if you'd like a reply (optional)")
        self.contact.textChanged.connect(self._changed)
        layout.addWidget(self.contact)

        self.include_log = QCheckBox("Include the diagnostic log")
        self.include_log.setChecked(True)
        self.include_log.toggled.connect(self._changed)
        layout.addWidget(self.include_log)
        log_note = QLabel("Only fixed wording: never file names, sheet names, words or values.")
        log_note.setWordWrap(True)
        log_note.setProperty("panelNote", True)
        layout.addWidget(log_note)

        self.preview_link = QLabel('<a href="toggle">Show exactly what will be sent</a>')
        self.preview_link.setProperty("panelNote", True)
        self.preview_link.setTextFormat(Qt.TextFormat.RichText)
        self.preview_link.linkActivated.connect(lambda _: self.toggle_preview())
        layout.addWidget(self.preview_link)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(190)
        self.preview.setVisible(False)
        layout.addWidget(self.preview)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setProperty("muted", True)
        if not self._configured:
            self.status.setText("Sending isn't set up in this version yet. Copy Diagnostics puts the report on your clipboard; "
                                "paste it into an e-mail or the GitHub issues page.")
        layout.addWidget(self.status)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.copy_button = QPushButton("Copy Diagnostics")
        self.cancel_button = QPushButton("Cancel")
        self.send_button = QPushButton("Send Report")
        self.send_button.setProperty("accent", True)
        row.addWidget(self.copy_button)
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        row.addWidget(self.send_button)
        for button in (self.copy_button, self.cancel_button, self.send_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoDefault(False)
        layout.addLayout(row)
        self.cancel_button.setDefault(True)
        self.copy_button.clicked.connect(self.copy_diagnostics)
        self.cancel_button.clicked.connect(self.reject)
        self.send_button.clicked.connect(self.send_clicked)
        self._changed()

    # ------------------------------------------------------------------ #

    def report(self) -> support.Report:
        return support.Report(self.message.toPlainText(), self.contact.text(), self.include_log.isChecked(),
                              self._kind, self._log_folder)

    def _changed(self) -> None:
        text = self.message.toPlainText()
        if len(text) > support.MAX_MESSAGE:                      # the limit is a limit: nothing is cut silently after the fact
            self.message.setPlainText(text[:support.MAX_MESSAGE])
            return
        self.send_button.setEnabled(self._configured and not self._sent and bool(text.strip()))
        self.send_button.setToolTip("" if self.send_button.isEnabled() else
                                    ("Write a few words about what happened first." if self._configured else
                                     "Sending isn't set up in this version yet."))
        if not self.preview.isHidden():
            self.preview.setPlainText(self.report().text())

    def toggle_preview(self) -> None:
        show = self.preview.isHidden()
        self.preview.setVisible(show)
        self.preview_link.setText('<a href="toggle">%s</a>' % ("Hide what will be sent" if show else "Show exactly what will be sent"))
        if show:
            self.preview.setPlainText(self.report().text())
        self.adjustSize()

    def copy_diagnostics(self) -> None:
        QGuiApplication.clipboard().setText(self.report().text())
        self.status.setText("Copied. Paste it into an e-mail or the GitHub issues page.")

    def send_clicked(self) -> None:
        self.send_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.status.setText("Sending…")
        self._send(self.report().payload())

    def finished(self, result: support.SendResult) -> None:
        """The app calls this with the outcome of the send."""
        self.copy_button.setEnabled(True)
        if result.ok:
            self._sent = True
            ref = f" Your reference is {result.reference}." if result.reference else ""
            self.status.setText("Thank you: the report was sent." + ref)
            self.send_button.setText("Sent")
            self.cancel_button.setText("Close")
            self.send_button.setEnabled(False)
        else:
            self.status.setText(result.error)
            self._changed()
