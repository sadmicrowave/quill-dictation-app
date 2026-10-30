"""Keyword editor dialog — editable table of phrase -> action bindings.

Also hosts the appearance and speech preferences. Nothing is saved until the
user confirms with OK, and a keyword table that fails validation keeps the
dialog open with the reasons shown.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from quill.config.settings import THEMES
from quill.parser.commands import Action

if TYPE_CHECKING:
    from quill.config.settings import Settings

#: Actions a user can bind a phrase to (NONE is internal).
BINDABLE_ACTIONS = [a for a in Action if a is not Action.NONE]


def action_label(action: Action) -> str:
    """Human-readable action name: ``NEXT_ROW`` -> ``Next Row``."""
    return action.name.replace("_", " ").title()


class SettingsDialog:
    """Modal editor for keywords and preferences.

    Args:
        settings: The Settings object to edit (mutated and saved on OK).
        parent: Optional parent QWidget.
    """

    def __init__(self, settings: "Settings", parent=None) -> None:
        self._settings = settings
        self._parent = parent
        self._dialog: QDialog | None = None
        self.table: QTableWidget | None = None
        self.theme_combo: QComboBox | None = None
        self.speak_check: QCheckBox | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def exec(self) -> bool:
        """Show modally. Returns True if the user saved changes."""
        self.build()
        return self._dialog.exec() == QDialog.DialogCode.Accepted

    def build(self) -> QDialog:
        """Construct the dialog widgets (separate from exec for testing)."""
        dialog = QDialog(self._parent)
        dialog.setWindowTitle("Quill Settings")
        dialog.resize(440, 440)
        layout = QVBoxLayout(dialog)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["When you say…", "Quill does…"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)
        self._fill_table(self._settings.keywords.items())

        buttons = QHBoxLayout()
        for label, slot in (("Add", self.add_row), ("Remove", self.remove_selected),
                            ("Restore defaults", self.restore_defaults)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        form = QFormLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems([t.title() for t in THEMES])
        self.theme_combo.setCurrentIndex(THEMES.index(self._settings.preferences["theme"]))
        form.addRow("Appearance", self.theme_combo)
        self.speak_check = QCheckBox("Read questions aloud")
        self.speak_check.setChecked(bool(self._settings.preferences["speak_prompts"]))
        form.addRow("", self.speak_check)
        layout.addLayout(form)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(lambda: self.try_accept(dialog))
        box.rejected.connect(dialog.reject)
        layout.addWidget(box)
        self._dialog = dialog
        return dialog

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
        combo = QComboBox()
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
            self.show_errors(errors)
            return False
        self._settings.set_keywords(rows)
        self._settings.preferences["theme"] = THEMES[self.theme_combo.currentIndex()]
        self._settings.preferences["speak_prompts"] = self.speak_check.isChecked()
        self._settings.save()
        (dialog or self._dialog).accept()
        return True

    def show_errors(self, errors: list[str]) -> None:
        """Tell the user what is wrong (overridden in tests to avoid a modal box)."""
        QMessageBox.warning(self._dialog, "Check your keywords", "\n".join(errors))
