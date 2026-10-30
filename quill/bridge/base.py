"""WorkbookBridge: abstract interface for talking to an open Excel workbook.

Concrete implementations:
  win_bridge.py  — Windows COM via xlwings / pywin32
  mac_bridge.py  — macOS via xlwings + AppleScript

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
    def connect(self) -> None:
        """Connect to the currently active Excel workbook.

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
