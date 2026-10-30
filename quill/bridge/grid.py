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
from abc import ABC, abstractmethod


class Grid(ABC):
    """Cell-level access to one workbook."""

    @abstractmethod
    def sheet_names(self) -> list[str]:
        """Names of all sheets, in workbook order."""

    @abstractmethod
    def active_sheet(self) -> str:
        """Name of the sheet currently active."""

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


class OpenpyxlGrid(Grid):
    """A :class:`Grid` over an openpyxl workbook object."""

    def __init__(self, wb) -> None:
        self._wb = wb

    def sheet_names(self) -> list[str]:
        return list(self._wb.sheetnames)

    def active_sheet(self) -> str:
        return self._wb.active.title

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
        self._ws(sheet).cell(row=row, column=col).value = value

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

    def __init__(self, book) -> None:
        self._book = book

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
        self._book.sheets[sheet].range((row, col)).value = value


def _as_block(raw: object, rows: int, cols: int) -> list[list[object]]:
    """Normalise xlwings' scalar / 1-D / 2-D reads to a rows x cols block."""
    if rows == 1 and cols == 1:
        return [[raw]]
    if rows == 1:
        return [list(raw)]
    if cols == 1:
        return [[v] for v in raw]
    return [list(r) for r in raw]
