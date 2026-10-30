"""Keyword editor dialog — editable table of phrase -> action bindings.

Saves to user TOML on OK. Full implementation in Phase 6.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from quill.config.settings import Settings

class SettingsDialog:
    def __init__(self, settings: "Settings", parent=None) -> None:
        self._settings = settings
        self._parent = parent
        self._dialog = None  # QDialog, built in exec()

    def exec(self) -> bool:
        """Show modally. Returns True if user saved changes."""
        # TODO Phase 6: QTableWidget of keyword rows + validation
        return False
