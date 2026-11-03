"""Grid: the smallest cell-level interface the bridges need.

A :class:`Grid` reads and writes rectangular blocks of cells on named sheets.
Two implementations exist:

  * :class:`OpenpyxlGrid` — an in-memory ``.xlsx`` (tests, file fallback)
  * :class:`XlwingsGrid`  — a live Excel workbook through xlwings

Reads return formulas as strings that start with ``=`` and constants as their
value, so callers can tell computed columns from typed-in data.
"""

from __future__ import annotations
import datetime as dt
import sys
from abc import ABC, abstractmethod

from quill.bridge.filters import ColumnFilter


class Grid(ABC):
    """Cell-level access to one workbook."""

    @abstractmethod
    def sheet_names(self) -> list[str]:
        """Names of all sheets, in workbook order."""

    @abstractmethod
    def active_sheet(self) -> str:
        """Name of the sheet currently active."""

    def set_active(self, sheet: str) -> bool:
        """Make *sheet* the active one (False where that is not possible: a live program already says which is open)."""
        return False

    @abstractmethod
    def last_row(self, sheet: str) -> int:
        """Last used row (1-based); 0 for an empty sheet."""

    @abstractmethod
    def last_col(self, sheet: str) -> int:
        """Last used column (1-based); 0 for an empty sheet."""

    @abstractmethod
    def read(self, sheet: str, top: int, left: int, rows: int, cols: int) -> list[list[object]]:
        """Read a *rows* x *cols* block whose top-left cell is (*top*, *left*).

        Cells outside the used area come back as None.
        """

    @abstractmethod
    def write(self, sheet: str, row: int, col: int, value: object) -> None:
        """Write one cell."""


    # Optional capabilities: implemented by grids that can filter/navigate.

    def set_autofilter(
        self, sheet: str, header_row: int, first_col: int, last_col: int, last_row: int,
        criteria: dict[int, ColumnFilter],
    ) -> int | None:
        """Turn on AutoFilter over the table and apply *criteria* (col index -> filter).

        Returns the matching row count when known, else None.
        """
        from quill.bridge.base import BridgeError
        raise BridgeError("Filtering is not supported here.")

    def clear_autofilter(self, sheet: str) -> None:
        """Show all rows again (the filter arrows stay on)."""
        from quill.bridge.base import BridgeError
        raise BridgeError("Filtering is not supported here.")

    def get_cursor(self, sheet: str) -> tuple[int, int] | None:
        """The selected cell as (row, col), or None if unknown."""
        return None

    def set_cursor(self, sheet: str, row: int, col: int) -> None:
        """Select a cell and scroll it into view."""

    def path(self) -> str:
        """Full path of the workbook ('' if unsaved/unknown)."""
        return ""


class TransposedGrid(Grid):
    """A view of another grid with rows and columns swapped.

    A sheet laid out the other way round (headings down the first column, one record per column) reads
    through this view exactly like the usual layout (headings across the first row, one record per row), so
    everything built on :class:`Grid` works for both without knowing which it has.
    """

    def __init__(self, base: Grid) -> None:
        self._base = base

    def sheet_names(self) -> list[str]:
        return self._base.sheet_names()

    def active_sheet(self) -> str:
        return self._base.active_sheet()

    def last_row(self, sheet: str) -> int:
        return self._base.last_col(sheet)

    def last_col(self, sheet: str) -> int:
        return self._base.last_row(sheet)

    def read(self, sheet: str, top: int, left: int, rows: int, cols: int) -> list[list[object]]:
        if rows <= 0 or cols <= 0:
            return []
        block = self._base.read(sheet, left, top, cols, rows)
        return [[block[c][r] for c in range(cols)] for r in range(rows)]

    def write(self, sheet: str, row: int, col: int, value: object) -> None:
        self._base.write(sheet, col, row, value)

    def get_cursor(self, sheet: str) -> tuple[int, int] | None:
        cursor = self._base.get_cursor(sheet)
        return (cursor[1], cursor[0]) if cursor else None

    def set_cursor(self, sheet: str, row: int, col: int) -> None:
        self._base.set_cursor(sheet, col, row)

    def path(self) -> str:
        return self._base.path()


def is_blank(value: object) -> bool:
    """True for None, empty/whitespace text, and formulas (computed cells)."""
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        return not text or text.startswith("=")
    return False


def cell_text(value: object) -> str:
    """Render a cell value as list text ('' when blank).

    Whole-number floats lose their ``.0`` so ``5.0`` reads back as ``5``.
    """
    if is_blank(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


#: Most written cells remembered for a viewer program between one push and the next (a turn writes a handful). Past it
#: the list is dropped and the viewer is asked to reload the file instead (see :meth:`OpenpyxlGrid.take_changes`).
MAX_CHANGES = 500


class OpenpyxlGrid(Grid):
    """A :class:`Grid` over an openpyxl workbook object."""

    def __init__(self, wb) -> None:
        self._wb = wb
        self.changes: list[tuple[str, int, int, object]] = []      # cells written, in sheet coordinates, until taken
        self.changes_lost = False                   # too many were waiting: the list was dropped, a viewer must reload
        self.unsaved: set[tuple[str, int, int]] = set()   # cells written since the file was last saved (see xlsx_patch)
        self.restructured = False                   # something beyond cells changed (hidden rows): only a full save keeps it
        self._hidden: dict[str, set[int]] = {}      # rows we hid, per sheet
        self._cursor: dict[str, tuple[int, int]] = {}

    def sheet_names(self) -> list[str]:
        return list(self._wb.sheetnames)

    def active_sheet(self) -> str:
        return self._wb.active.title

    def set_active(self, sheet: str) -> bool:
        """Make *sheet* the one Quill writes to (the workbook's active sheet). False if there is no such sheet."""
        if sheet not in self._wb.sheetnames:
            return False
        self._wb.active = self._wb[sheet]
        return True

    def last_row(self, sheet: str) -> int:
        ws = self._ws(sheet)
        return ws.max_row if ws.max_row > 1 or ws.cell(1, 1).value is not None else 0

    def last_col(self, sheet: str) -> int:
        ws = self._ws(sheet)
        return ws.max_column if ws.max_column > 1 or ws.cell(1, 1).value is not None else 0

    def read(self, sheet: str, top: int, left: int, rows: int, cols: int) -> list[list[object]]:
        ws = self._ws(sheet)
        block: list[list[object]] = [[None] * cols for _ in range(rows)]
        bottom = min(top + rows - 1, ws.max_row)
        if bottom < top:
            return block
        right = min(left + cols - 1, ws.max_column)
        for r, row in enumerate(
            ws.iter_rows(min_row=top, max_row=bottom, min_col=left, max_col=right,
                         values_only=True)
        ):
            for c, value in enumerate(row):
                block[r][c] = value
        return block

    def write(self, sheet: str, row: int, col: int, value: object) -> None:
        cell = self._ws(sheet).cell(row=row, column=col)
        cell.value = value
        self.unsaved.add((sheet, row, col))
        if not self.changes_lost:
            self.changes.append((sheet, row, col, value))      # (so a viewer program can be shown the same cells)
            if len(self.changes) > MAX_CHANGES:                # nobody is taking them: do not keep them, say so instead
                self.changes.clear()
                self.changes_lost = True
        if isinstance(value, str) and "\n" in value:          # several values in one cell: one per line
            from copy import copy
            alignment = copy(cell.alignment)
            alignment.wrap_text = True
            cell.alignment = alignment

    def set_autofilter(self, sheet, header_row, first_col, last_col, last_row, criteria):
        """Record the filter in the file and hide non-matching rows.

        Excel only re-applies a stored filter on demand, so the rows are
        hidden explicitly to keep the file consistent with the criteria.
        """
        from openpyxl.utils import get_column_letter
        ws = self._ws(sheet)
        self.restructured = True
        self.clear_autofilter(sheet)
        ws.auto_filter.ref = (
            f"{get_column_letter(first_col)}{header_row}:{get_column_letter(last_col)}{last_row}"
        )
        matched = 0
        for row in range(header_row + 1, last_row + 1):
            keep = all(f.matches(ws.cell(row=row, column=col).value) for col, f in criteria.items())
            if keep:
                matched += 1
            else:
                ws.row_dimensions[row].hidden = True
                self._hidden.setdefault(sheet, set()).add(row)
        return matched

    def clear_autofilter(self, sheet: str) -> None:
        ws = self._ws(sheet)
        self.restructured = True
        for row in self._hidden.pop(sheet, set()):
            ws.row_dimensions[row].hidden = False

    def get_cursor(self, sheet: str):
        return self._cursor.get(sheet)

    def set_cursor(self, sheet: str, row: int, col: int) -> None:
        self._cursor[sheet] = (row, col)

    def _ws(self, sheet: str):
        if sheet not in self._wb.sheetnames:
            from quill.bridge.base import BridgeError
            raise BridgeError(f"No sheet named '{sheet}'")
        return self._wb[sheet]


class XlwingsGrid(Grid):
    """A :class:`Grid` over a live xlwings ``Book``.

    Only the cross-platform xlwings API is used (``book.sheets``,
    ``sheet.range``, ``used_range``), so the same class serves Windows
    and macOS.
    """

    def __init__(self, book, platform: str | None = None) -> None:
        self._book = book
        self._platform = platform or sys.platform

    def sheet_names(self) -> list[str]:
        return [s.name for s in self._book.sheets]

    def active_sheet(self) -> str:
        return self._book.sheets.active.name

    def last_row(self, sheet: str) -> int:
        used = self._book.sheets[sheet].used_range
        if used.value is None:
            return 0
        return used.last_cell.row

    def last_col(self, sheet: str) -> int:
        used = self._book.sheets[sheet].used_range
        if used.value is None:
            return 0
        return used.last_cell.column

    def read(self, sheet: str, top: int, left: int, rows: int, cols: int) -> list[list[object]]:
        if rows <= 0 or cols <= 0:
            return []
        rng = self._book.sheets[sheet].range((top, left), (top + rows - 1, left + cols - 1))
        raw = rng.formula
        return _as_block(raw, rows, cols)

    def write(self, sheet: str, row: int, col: int, value: object) -> None:
        if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
            value = dt.datetime(value.year, value.month, value.day)
        target = self._book.sheets[sheet].range((row, col))
        target.value = value
        if isinstance(value, str) and "\n" in value:          # several values in one cell: one per line
            try:
                if self._platform == "win32":
                    target.api.WrapText = True
                else:
                    target.api.wrap_text.set(True)
            except Exception:
                pass                                         # cosmetic: the values are written either way


    # ---- filtering / navigation ------------------------------------------------
    #
    # Excel's filter object model is not exposed by xlwings itself, so these go
    # through the native API (COM on Windows, AppleScript on macOS) via ``.api``.
    # Not yet exercised against a real Excel; see the To Do.

    _XL_AND = 1
    _XL_FILTER_VALUES = 7

    def set_autofilter(self, sheet, header_row, first_col, last_col, last_row, criteria):
        from quill.bridge.base import BridgeError
        ws = self._book.sheets[sheet]
        table = ws.range((header_row, first_col), (max(last_row, header_row + 1), last_col))
        try:
            if self._platform == "win32":
                if ws.api.AutoFilterMode:
                    ws.api.AutoFilterMode = False
                for col, flt in criteria.items():
                    self._apply_windows(table.api, col - first_col + 1, flt)
            else:
                if ws.api.autofilter_mode.get():
                    ws.api.autofilter_mode.set(False)
                for col, flt in criteria.items():
                    self._apply_mac(table.api, col - first_col + 1, flt)
        except Exception as exc:
            raise BridgeError(f"The spreadsheet program would not apply the filter: {exc}") from exc
        return None   # visible-row count is not read back from Excel

    def _apply_windows(self, rng_api, field: int, flt: ColumnFilter) -> None:
        if flt.values:
            if len(flt.values) == 1:
                rng_api.AutoFilter(Field=field, Criteria1="=" + flt.values[0])
            else:
                rng_api.AutoFilter(Field=field, Criteria1=list(flt.values),
                                   Operator=self._XL_FILTER_VALUES)
            return
        tests = [f"{op}{limit:g}" for op, limit in flt.comparisons]
        if len(tests) == 1:
            rng_api.AutoFilter(Field=field, Criteria1=tests[0])
        else:
            rng_api.AutoFilter(Field=field, Criteria1=tests[0], Operator=self._XL_AND,
                               Criteria2=tests[1])

    def _apply_mac(self, rng_api, field: int, flt: ColumnFilter) -> None:
        from appscript import k
        if flt.values:
            rng_api.autofilter(field=field, criteria1="=" + flt.values[0])
            if len(flt.values) > 1:   # AppleScript has no value-list form; OR the first two
                rng_api.autofilter(field=field, criteria1="=" + flt.values[0], operator=k.autofilter_or,
                                   criteria2="=" + flt.values[1])
            return
        tests = [f"{op}{limit:g}" for op, limit in flt.comparisons]
        if len(tests) == 1:
            rng_api.autofilter(field=field, criteria1=tests[0])
        else:
            rng_api.autofilter(field=field, criteria1=tests[0], operator=k.autofilter_and,
                               criteria2=tests[1])

    def clear_autofilter(self, sheet: str) -> None:
        from quill.bridge.base import BridgeError
        ws = self._book.sheets[sheet]
        try:
            if self._platform == "win32":
                if ws.api.FilterMode:
                    ws.api.ShowAllData()
            elif ws.api.filter_mode.get():
                ws.api.show_all_data()
        except Exception as exc:
            raise BridgeError(f"The spreadsheet program would not clear the filter: {exc}") from exc

    def get_cursor(self, sheet: str):
        try:
            cell = self._book.app.selection
            return cell.row, cell.column
        except Exception:
            return None

    def set_cursor(self, sheet: str, row: int, col: int) -> None:
        try:
            ws = self._book.sheets[sheet]
            ws.activate()
            ws.range((row, col)).select()
        except Exception:
            pass   # cosmetic; never fail a search over scroll position

    def path(self) -> str:
        full = getattr(self._book, "fullname", "") or ""
        return full if ("/" in full or "\\" in full) else ""


def _as_block(raw: object, rows: int, cols: int) -> list[list[object]]:
    """Normalise xlwings' scalar / 1-D / 2-D reads to a rows x cols block."""
    if rows == 1 and cols == 1:
        return [[raw]]
    if rows == 1:
        return [list(raw)]
    if cols == 1:
        return [[v] for v in raw]
    return [list(r) for r in raw]
