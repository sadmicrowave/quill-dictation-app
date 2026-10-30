"""WorkbookBridge: abstract interface for talking to an open Excel workbook.

Concrete implementations:
  win_bridge.py   — Windows, live Excel via xlwings COM
  mac_bridge.py   — macOS, live Excel via xlwings + AppleScript
  xlsx_bridge.py  — file-based (openpyxl); no Excel needed, used for
                    testing and as a fallback when Excel is unavailable

Use bridge.factory.get_bridge() to obtain the right one at runtime.
"""

from __future__ import annotations
from abc import ABC, abstractmethod


class WorkbookBridge(ABC):
    """Thin, platform-neutral interface to an open Excel workbook."""

    # ------------------------------------------------------------------ #
    # Connection                                                           #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def connect(self, workbook: str | None = None) -> None:
        """Connect to an open Excel workbook.

        Args:
            workbook: Name of the workbook to target. When omitted, the
                active workbook is used.

        Raises:
            BridgeError: if no workbook is open or Excel is not running.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Release any COM/AppleScript handles."""

    @property
    @abstractmethod
    def workbook_name(self) -> str:
        """Display name of the connected workbook (filename without path)."""

    def open_workbooks(self) -> list[str]:
        """Names of every workbook that can be targeted (for a picker).

        The default reports nothing; live bridges override it.
        """
        return []

    # ------------------------------------------------------------------ #
    # Introspection                                                        #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def get_lists(self) -> dict[str, list[str]]:
        """Return every data-validated column discovered in the workbook.

        Returns:
            A dict mapping column_header -> list of valid string values.
            E.g. {"Brand": ["Nike", "Adidas"], "Size": ["S", "M", "L"]}
        """

    @abstractmethod
    def active_sheet_name(self) -> str:
        """Name of the sheet that is currently visible / active."""

    @abstractmethod
    def get_headers(self, sheet_name: str | None = None) -> list[str]:
        """Return the column headers of *sheet_name* (default: active sheet).

        The parser uses these as spoken field words, so a column that has
        no drop-down list (a price, a date, notes) can still be dictated.
        """

    @abstractmethod
    def refresh(self) -> None:
        """Re-read the workbook structure after the user edited it."""

    # ------------------------------------------------------------------ #
    # Writing                                                              #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def append_row(self, sheet_name: str, values: dict[str, object]) -> int:
        """Write one record to the next empty row of *sheet_name*.

        Args:
            sheet_name: Target sheet (usually the active sheet).
            values: Mapping of column_header -> value to write.

        Returns:
            The 1-based row number that was written.

        Raises:
            BridgeError: if the sheet does not exist or the write fails.
        """

    @abstractmethod
    def add_to_list(self, column_name: str, value: str) -> None:
        """Append *value* to the validated list for *column_name*.

        This writes to whatever backing range supplies the data validation
        for that column (e.g. a Config sheet list, a named range, or an
        inline formula range).

        Raises:
            BridgeError: if the column or its list source cannot be found.
        """


class BridgeError(Exception):
    """Raised when the bridge cannot connect or perform an operation."""
