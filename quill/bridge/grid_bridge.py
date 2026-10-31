"""GridBridge: the shared WorkbookBridge logic, built on a Grid.

Everything that is not specific to *how* cells are reached lives here:
list lookup, header detection, finding the next free row, and appending
values to a list. Subclasses supply the connection (``connect``) and a
:class:`quill.bridge.grid.Grid`.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re

from quill.bridge.base import BridgeError, WorkbookBridge
from quill.bridge.filters import ColumnFilter
from quill.bridge.grid import Grid, cell_text, is_blank
from quill.bridge.introspect import (
    HEADER_SCAN_ROWS,
    Discovery,
    ListSource,
    guess_header_row,
)


def normalize_header(text: object) -> str:
    """Lowercase and collapse whitespace so header lookups are forgiving."""
    return " ".join(str(text).lower().split())


def _looks_like_formula(text: str) -> bool:
    """True if a spreadsheet would treat *text* as a formula (a typed value could then run something)."""
    if text[0] in "=@":
        return True
    if text[0] in "+-":
        try:
            float(text)
            return False                         # a plain signed number
        except ValueError:
            return True
    return False


class GridBridge(WorkbookBridge):
    """A WorkbookBridge implemented over a :class:`Grid` and a :class:`Discovery`."""

    def __init__(self) -> None:
        self._grid: Grid | None = None
        self._discovery = Discovery()
        self._name = ""
        # Where the user was before the first search of a run: (sheet, row, col)
        self._saved_cursor: tuple[str, int, int] | None = None

    # ------------------------------------------------------------------ #
    # Hooks for subclasses                                                 #
    # ------------------------------------------------------------------ #

    def _after_write(self) -> None:
        """Called after every successful write (e.g. to save a file)."""

    def _add_inline(self, source: ListSource, value: str) -> None:
        """Append *value* to an inline (literal) validation list."""
        raise BridgeError(
            f"The '{source.column}' list is typed into the validation rule itself "
            "and can't be extended here. Move it to a range on a Config sheet."
        )

    # ------------------------------------------------------------------ #
    # Connection state                                                     #
    # ------------------------------------------------------------------ #

    @property
    def workbook_name(self) -> str:
        if self._grid is None:
            raise BridgeError("Not connected")
        return self._name

    def disconnect(self) -> None:
        self._grid = None
        self._discovery = Discovery()
        self._name = ""

    def _require(self) -> Grid:
        if self._grid is None:
            raise BridgeError("Not connected to a workbook")
        return self._grid

    # ------------------------------------------------------------------ #
    # Introspection                                                        #
    # ------------------------------------------------------------------ #

    def get_lists(self) -> dict[str, list[str]]:
        grid = self._require()
        return {col: self._read_values(grid, src) for col, src in self._discovery.sources.items()}

    def active_sheet_name(self) -> str:
        return self._require().active_sheet()

    def get_headers(self, sheet_name: str | None = None) -> list[str]:
        grid = self._require()
        sheet = sheet_name or grid.active_sheet()
        row = self._header_row(grid, sheet)
        width = grid.last_col(sheet)
        if width == 0:
            return []
        cells = grid.read(sheet, row, 1, 1, width)[0]
        return [str(c).strip() for c in cells if not is_blank(c)]

    @staticmethod
    def _read_values(grid: Grid, src: ListSource) -> list[str]:
        """Read a list's current values, de-duplicated, in order."""
        if src.is_inline:
            raw: list[object] = list(src.items)
        else:
            rows = max(src.last_row - src.first_row + 1, 0)
            raw = [r[0] for r in grid.read(src.sheet, src.first_row, src.col, rows, 1)]
        seen: set[str] = set()
        values: list[str] = []
        for item in raw:
            text = cell_text(item)
            if text and text.lower() not in seen:
                seen.add(text.lower())
                values.append(text)
        return values

    def _header_row(self, grid: Grid, sheet: str) -> int:
        known = self._discovery.header_rows.get(sheet)
        if known:
            return known
        width = max(grid.last_col(sheet), 1)
        return guess_header_row(grid.read(sheet, 1, 1, HEADER_SCAN_ROWS, width))

    # ------------------------------------------------------------------ #
    # Writing                                                              #
    # ------------------------------------------------------------------ #

    def append_row(self, sheet_name: str, values: dict[str, object]) -> int:
        grid = self._require()
        if sheet_name not in grid.sheet_names():
            raise BridgeError(f"No sheet named '{sheet_name}'")
        header_row = self._header_row(grid, sheet_name)
        width = grid.last_col(sheet_name)
        header_cells = grid.read(sheet_name, header_row, 1, 1, max(width, 1))[0]
        columns: dict[str, int] = {}
        for index, cell in enumerate(header_cells, start=1):
            if not is_blank(cell):
                columns.setdefault(normalize_header(cell), index)

        missing = [name for name in values if normalize_header(name) not in columns]
        if missing:
            raise BridgeError(
                f"Sheet '{sheet_name}' has no column named {', '.join(repr(m) for m in missing)}"
            )

        row = self._next_free_row(grid, sheet_name, header_row, sorted(columns.values()))
        for name, value in values.items():
            if value is not None:
                grid.write(sheet_name, row, columns[normalize_header(name)], value)
        self._after_write()
        return row

    def set_value(self, sheet_name: str, row: int, column: str, value: object) -> bool:
        grid = self._require()
        if sheet_name not in grid.sheet_names():
            return False
        header_row = self._header_row(grid, sheet_name)
        width = grid.last_col(sheet_name)
        headers = grid.read(sheet_name, header_row, 1, 1, max(width, 1))[0]
        wanted = normalize_header(column)
        index = next((i for i, h in enumerate(headers, 1)
                      if not is_blank(h) and normalize_header(h) == wanted), None)
        if index is None or not is_blank(grid.read(sheet_name, row, index, 1, 1)[0][0]):
            return False
        grid.write(sheet_name, row, index, value)
        self._after_write()
        return True

    def clear_value(self, sheet_name: str, row: int, column: str, expected: object) -> bool:
        grid = self._require()
        if sheet_name not in grid.sheet_names():
            return False
        header_row = self._header_row(grid, sheet_name)
        width = grid.last_col(sheet_name)
        headers = grid.read(sheet_name, header_row, 1, 1, max(width, 1))[0]
        wanted = normalize_header(column)
        index = next((i for i, h in enumerate(headers, 1)
                      if not is_blank(h) and normalize_header(h) == wanted), None)
        if index is None:
            return False
        if cell_text(grid.read(sheet_name, row, index, 1, 1)[0][0]).lower() != cell_text(expected).lower():
            return False
        grid.write(sheet_name, row, index, None)
        self._after_write()
        return True

    @staticmethod
    def _next_free_row(grid: Grid, sheet: str, header_row: int, columns: list[int]) -> int:
        """First row below the header whose *columns* cells are all empty or computed.

        Only header columns are checked, so stray cells elsewhere on the sheet
        (a helper list parked to the right, say) never block a row.
        """
        last = grid.last_row(sheet)
        count = last - header_row
        if count > 0 and columns:
            block = grid.read(sheet, header_row + 1, 1, count, max(columns))
            for offset, cells in enumerate(block):
                if all(is_blank(cells[c - 1]) for c in columns):
                    return header_row + 1 + offset
        return max(last, header_row) + 1

    # ------------------------------------------------------------------ #
    # Search                                                               #
    # ------------------------------------------------------------------ #

    #: A column is numeric when at least this share of its entries are numbers.
    _NUMERIC_SHARE = 0.8
    #: Rows sampled below the header when judging whether a column is numeric.
    _SAMPLE_ROWS = 200

    @property
    def workbook_path(self) -> str:
        return self._grid.path() if self._grid is not None else ""

    def numeric_columns(self, sheet_name: str | None = None) -> list[str]:
        grid = self._require()
        sheet = sheet_name or grid.active_sheet()
        header_row = self._header_row(grid, sheet)
        width = grid.last_col(sheet)
        rows = min(grid.last_row(sheet) - header_row, self._SAMPLE_ROWS)
        if width == 0 or rows <= 0:
            return []
        headers = grid.read(sheet, header_row, 1, 1, width)[0]
        data = grid.read(sheet, header_row + 1, 1, rows, width)
        found = []
        for index, header in enumerate(headers):
            if is_blank(header):
                continue
            entries = [r[index] for r in data if not is_blank(r[index])]
            numbers = [v for v in entries
                       if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if entries and len(numbers) / len(entries) >= self._NUMERIC_SHARE:
                found.append(str(header).strip())
        return found

    #: Header words that make an empty column a date column.
    _DATE_HEADER_WORDS = frozenset({"date", "dated"})

    def date_columns(self, sheet_name: str | None = None) -> list[str]:
        """Headers holding dates: most entries are dates, or (for an empty column) the header says "date"."""
        grid = self._require()
        sheet = sheet_name or grid.active_sheet()
        header_row = self._header_row(grid, sheet)
        width = grid.last_col(sheet)
        rows = min(grid.last_row(sheet) - header_row, self._SAMPLE_ROWS)
        if width == 0:
            return []
        headers = grid.read(sheet, header_row, 1, 1, width)[0]
        data = grid.read(sheet, header_row + 1, 1, max(rows, 0), width) if rows > 0 else []
        found = []
        for index, header in enumerate(headers):
            if is_blank(header):
                continue
            entries = [r[index] for r in data if not is_blank(r[index])]
            dates = [v for v in entries if isinstance(v, (dt.date, dt.datetime))]
            words = set(re.findall(r"[a-z]+", str(header).lower()))
            if (entries and len(dates) / len(entries) >= self._NUMERIC_SHARE) or (not entries and words & self._DATE_HEADER_WORDS):
                found.append(str(header).strip())
        return found

    def apply_filters(self, sheet_name: str, filters: list[ColumnFilter]) -> int | None:
        grid = self._require()
        if sheet_name not in grid.sheet_names():
            raise BridgeError(f"No sheet named '{sheet_name}'")
        header_row = self._header_row(grid, sheet_name)
        width = grid.last_col(sheet_name)
        header_cells = grid.read(sheet_name, header_row, 1, 1, max(width, 1))[0]
        columns = {normalize_header(c): i for i, c in enumerate(header_cells, 1) if not is_blank(c)}
        criteria: dict[int, ColumnFilter] = {}
        for flt in filters:
            index = columns.get(normalize_header(flt.column))
            if index is None:
                raise BridgeError(f"Sheet '{sheet_name}' has no column named '{flt.column}'")
            criteria[index] = flt

        if self._saved_cursor is None:   # remember only the pre-search position
            cursor = grid.get_cursor(sheet_name)
            if cursor:
                self._saved_cursor = (sheet_name, *cursor)
            else:
                self._saved_cursor = (sheet_name, header_row + 1, 1)
        count = grid.set_autofilter(
            sheet_name, header_row, 1, width, max(grid.last_row(sheet_name), header_row + 1), criteria
        )
        grid.set_cursor(sheet_name, header_row + 1, 1)
        self._after_write()
        return count

    def clear_filters(self, sheet_name: str) -> bool:
        grid = self._require()
        saved, self._saved_cursor = self._saved_cursor, None
        if saved is None:
            return False
        grid.clear_autofilter(saved[0] if saved[0] in grid.sheet_names() else sheet_name)
        if saved[0] in grid.sheet_names():
            grid.set_cursor(*saved)
        self._after_write()
        return True

    def add_to_list(self, column_name: str, value: str) -> None:
        grid = self._require()
        source = self._find_source(column_name)
        text = value.strip()
        if not text:
            return
        if _looks_like_formula(text):
            raise BridgeError(f"'{text}' can't be added: a value starting with = + - or @ would be read as a formula.")
        if text.lower() in (v.lower() for v in self._read_values(grid, source)):
            return  # already present; nothing to do

        if source.is_inline:
            self._add_inline(source, text)
            self._after_write()
            return

        rows = max(source.last_row - source.first_row + 1, 0)
        cells = [r[0] for r in grid.read(source.sheet, source.first_row, source.col, rows, 1)]
        target = next(
            (source.first_row + i for i, c in enumerate(cells) if c is None or c == ""), None
        )
        if target is None:
            if not source.growable:
                raise BridgeError(
                    f"The '{source.column}' list is full ({rows} slots). "
                    "Extend its range in the workbook first."
                )
            target = source.last_row + 1
            self._discovery.sources[source.column] = dataclasses.replace(source, last_row=target)
        grid.write(source.sheet, target, source.col, text)
        self._after_write()

    def remove_from_list(self, column_name: str, value: str) -> bool:
        grid = self._require()
        source = self._find_source(column_name)
        if source.is_inline:
            return False
        rows = max(source.last_row - source.first_row + 1, 0)
        cells = [r[0] for r in grid.read(source.sheet, source.first_row, source.col, rows, 1)]
        wanted = value.strip().lower()
        for offset in range(len(cells) - 1, -1, -1):      # last match: the one just added
            if cell_text(cells[offset]).lower() == wanted:
                grid.write(source.sheet, source.first_row + offset, source.col, None)
                self._after_write()
                return True
        return False

    def _find_source(self, column_name: str) -> ListSource:
        wanted = normalize_header(column_name)
        for name, source in self._discovery.sources.items():
            if normalize_header(name) == wanted:
                return source
        raise BridgeError(f"No list found for column '{column_name}'")
