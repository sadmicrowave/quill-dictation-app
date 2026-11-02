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

from quill.bridge.filters import ColumnFilter


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

    @property
    def workbook_path(self) -> str:
        """Full path of the connected workbook ('' if unknown or unsaved)."""
        return ""

    def activate(self) -> None:
        """Bring the connected workbook to the front. Default: do nothing."""

    @property
    def vertical(self) -> bool:
        """True when the sheet is read with its headings down the first column (one record per column)."""
        return False

    def set_vertical(self, vertical: bool) -> None:
        """Choose the sheet layout: headings across the first row (the default) or down the first column.

        The default ignores it; the grid-based bridges honour it.
        """

    def set_start_row(self, number: int) -> None:
        """The first row (first column when the headings run down) a new record may use; 0 = the first empty one."""

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

    def append_to_row(self, sheet_name: str, row: int | None, values: dict[str, object]) -> int:
        """Add *values* to one record instead of starting a new one: each cell that already holds something gets
        the new value after a comma. With *row* None the record is the next free one.

        Returns:
            The record (row, or column when the sheet runs the other way) that was written.

        Raises:
            BridgeError: if this bridge cannot, the sheet does not exist or the write fails.
        """
        raise BridgeError("This bridge cannot add to an existing row.")

    @abstractmethod
    def add_to_list(self, column_name: str, value: str) -> None:
        """Append *value* to the validated list for *column_name*.

        This writes to whatever backing range supplies the data validation
        for that column (e.g. a Config sheet list, a named range, or an
        inline formula range).

        Raises:
            BridgeError: if the column or its list source cannot be found.
        """


    def remove_from_list(self, column_name: str, value: str) -> bool:
        """Take *value* back out of the list for *column_name* (undo of ``add_to_list``).

        Returns True if it was found and cleared; False if it wasn't there or
        this bridge can't (the default).
        """
        return False

    def clear_value(self, sheet_name: str, row: int, column: str, expected: object) -> bool:
        """Empty one cell, but only if it still holds *expected* (undo of ``set_value``).

        Never removes something the user typed over it. Returns True if cleared.
        """
        return False

    def set_value(self, sheet_name: str, row: int, column: str, value: object) -> bool:
        """Fill one cell of an existing row, only if it is currently empty.

        Used to back-fill a value the user taught Quill after the row was
        already saved. Returns True if written, False if the column is missing
        or the cell already holds something (never overwrites).
        """
        return False

    # ------------------------------------------------------------------ #
    # Search (optional capability)                                         #
    # ------------------------------------------------------------------ #

    def numeric_columns(self, sheet_name: str | None = None) -> list[str]:
        """Headers whose data is mostly numbers (candidates for "under 50")."""
        return []

    def date_columns(self, sheet_name: str | None = None) -> list[str]:
        """Headers that hold dates, in sheet order (so a spoken date can go into the right column)."""
        return []

    def apply_filters(self, sheet_name: str, filters: list[ColumnFilter]) -> int | None:
        """Filter *sheet_name* to rows matching every filter.

        Turns on AutoFilter on the header row. The cursor position is
        remembered the first time so :meth:`clear_filters` can return to it.

        Returns:
            The number of matching rows when known, else None.

        Raises:
            BridgeError: if filtering is unsupported or fails.
        """
        raise BridgeError("This bridge cannot filter.")

    def clear_filters(self, sheet_name: str) -> bool:
        """Show every row again and return to where the user was.

        Returns:
            True if a search was active (and has been cleared).
        """
        raise BridgeError("This bridge cannot filter.")


class BridgeError(Exception):
    """Raised when the bridge cannot connect or perform an operation."""
