"""Windows COM bridge via xlwings.

Requires: xlwings, pywin32 (win32com)
Platform: Windows only
"""

from __future__ import annotations
from quill.bridge.base import WorkbookBridge, BridgeError


class WinBridge(WorkbookBridge):
    """Connects to Excel on Windows via xlwings COM automation."""

    def __init__(self) -> None:
        self._app = None   # xlwings App handle
        self._wb = None    # xlwings Book handle
        self._lists: dict[str, list[str]] = {}

    def connect(self) -> None:
        # TODO (Phase 4): implement xlwings connection on Windows
        raise NotImplementedError("WinBridge.connect not yet implemented")

    def disconnect(self) -> None:
        self._app = None
        self._wb = None

    @property
    def workbook_name(self) -> str:
        if self._wb is None:
            raise BridgeError("Not connected")
        return self._wb.name  # type: ignore[attr-defined]

    def get_lists(self) -> dict[str, list[str]]:
        return dict(self._lists)

    def active_sheet_name(self) -> str:
        raise NotImplementedError

    def append_row(self, sheet_name: str, values: dict[str, object]) -> int:
        raise NotImplementedError

    def add_to_list(self, column_name: str, value: str) -> None:
        raise NotImplementedError
