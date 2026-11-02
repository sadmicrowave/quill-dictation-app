"""Workbook introspection: discover the drop-down lists a workbook defines.

This module reads the *structure* of an ``.xlsx`` workbook (through openpyxl)
and works out which columns carry a list-type data validation and where the
valid values live. It never stores the values themselves; bridges read those
through a :class:`quill.bridge.grid.Grid` so live edits are picked up.

Supported validation sources:
  * inline lists         ``"A,B,C"``
  * ranges               ``Config!$A$5:$A$54``, ``'My Sheet'!$A$1:$A$9``, ``$A$1:$A$9``
  * workbook/sheet names ``=ColorList`` (a defined name that resolves to a range)

In a sheet named ``Config`` or ``Settings``, a column whose header ends with
``_list`` is also treated as a list, named after the header without the suffix.

No domain-specific knowledge lives here; the workbook teaches the app.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field

from openpyxl.utils.cell import range_boundaries

#: Sheet names (lowercase) whose ``*_list`` columns are read as extra lists.
CONFIG_SHEET_NAMES = ("config", "settings")

#: Header suffix that marks an enumerable column on a config sheet.
LIST_SUFFIX = "_list"

#: Rows scanned from the top of a sheet when guessing which row is the header.
HEADER_SCAN_ROWS = 10


@dataclass(frozen=True)
class ListSource:
    """Where the valid values for one column come from.

    Attributes:
        column: Header text of the column the list validates.
        items: Literal values, for inline lists (empty for range sources).
        sheet: Sheet holding the backing range (range sources only).
        col: 1-based column index of the backing range.
        first_row: 1-based first row of the backing range.
        last_row: 1-based last row of the backing range.
        growable: True when the range may extend downward as values are added
            (config-sheet ``*_list`` columns); False for fixed validation ranges.
    """

    column: str
    items: tuple[str, ...] = ()
    sheet: str = ""
    col: int = 0
    first_row: int = 0
    last_row: int = 0
    growable: bool = False

    @property
    def is_inline(self) -> bool:
        """True when the values are literals rather than a worksheet range."""
        return not self.sheet


@dataclass
class Discovery:
    """Result of introspecting a workbook.

    Attributes:
        sources: Header text -> where its list of valid values lives.
        header_rows: Sheet name -> 1-based row number holding the headers.
    """

    sources: dict[str, ListSource] = field(default_factory=dict)
    header_rows: dict[str, int] = field(default_factory=dict)


# ------------------------------------------------------------------ #
# Reference parsing                                                   #
# ------------------------------------------------------------------ #

def parse_reference(ref: str) -> tuple[str | None, tuple[int, int, int, int]] | None:
    """Split a reference such as ``'My Sheet'!$A$1:$A$9`` into its parts.

    Args:
        ref: A cell/range reference, optionally sheet-qualified and optionally
            prefixed with ``=``.

    Returns:
        ``(sheet_or_None, (min_col, min_row, max_col, max_row))``, or None if
        *ref* is not a plain range (a formula, an invalid address, etc.).
    """
    text = ref.strip().lstrip("=").strip()
    sheet: str | None = None
    if "!" in text:
        sheet_part, text = text.rsplit("!", 1)
        sheet = sheet_part.strip()
        if sheet.startswith("'") and sheet.endswith("'") and len(sheet) >= 2:
            sheet = sheet[1:-1].replace("''", "'")
    try:
        bounds = range_boundaries(text.replace("$", ""))
    except (ValueError, TypeError):
        return None
    if any(b is None for b in bounds):
        return None
    return sheet, bounds


def _inline_items(formula: str) -> tuple[str, ...] | None:
    """Return the literal items of an inline list formula, else None."""
    text = formula.strip().lstrip("=").strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return tuple(p.strip() for p in text[1:-1].split(",") if p.strip())
    return None


def _resolve_name(wb, sheet_title: str, name: str) -> str | None:
    """Return the reference text a defined name points at, or None."""
    candidates = []
    if sheet_title in wb.sheetnames:
        candidates.append(wb[sheet_title].defined_names)
    candidates.append(wb.defined_names)
    for names in candidates:
        defined = names.get(name)
        if defined is not None and defined.attr_text:
            return defined.attr_text
    return None


def resolve_source(wb, sheet_title: str, column: str, formula: str) -> ListSource | None:
    """Turn a validation formula into a :class:`ListSource`.

    Args:
        wb: An openpyxl workbook.
        sheet_title: Sheet that holds the validation (unqualified references
            resolve against it).
        column: Header text of the validated column.
        formula: The validation's ``formula1`` text.

    Returns:
        The resolved source, or None for anything unsupported (computed
        formulas, multi-column ranges, unknown names).
    """
    items = _inline_items(formula)
    if items is not None:
        return ListSource(column=column, items=items)

    text = formula.strip().lstrip("=").strip()
    parsed = parse_reference(text)
    if parsed is None:
        named = _resolve_name(wb, sheet_title, text)
        parsed = parse_reference(named) if named else None
    if parsed is None:
        return None

    sheet, (c1, r1, c2, r2) = parsed
    if c1 != c2:  # only single-column lists are supported
        return None
    return ListSource(
        column=column,
        sheet=sheet or sheet_title,
        col=c1,
        first_row=r1,
        last_row=r2,
    )


# ------------------------------------------------------------------ #
# Header rows                                                          #
# ------------------------------------------------------------------ #

def guess_header_row(rows: list[list[object]]) -> int:
    """Guess the 1-based header row from the top rows of a sheet.

    The header is the row (within the first ``HEADER_SCAN_ROWS``) that holds
    the most non-empty text cells; ties go to the earliest row.

    Args:
        rows: The sheet's leading rows, each a list of cell values.

    Returns:
        A 1-based row number (1 if the rows are all empty).
    """
    best_row, best_count = 1, 0
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS], start=1):
        count = sum(1 for v in row if isinstance(v, str) and v.strip() and not v.startswith("="))
        if count > best_count:
            best_row, best_count = index, count
    return best_row


def _sheet_header_row(ws) -> int:
    """Header row of an openpyxl worksheet: its first table, else a guess."""
    for table in ws.tables.values():
        bounds = parse_reference(table.ref)
        if bounds:
            return bounds[1][1]
    rows = [
        list(r) for r in ws.iter_rows(
            min_row=1, max_row=min(HEADER_SCAN_ROWS, ws.max_row), values_only=True
        )
    ]
    return guess_header_row(rows)


def _header_text(value: object) -> str:
    """Normalise a header cell to stripped text ('' if not text-like)."""
    if value is None:
        return ""
    return str(value).strip()


def _column_header(ws, header_row: int, col: int, first_row: int) -> str:
    """Find the header text above a validated range starting at *first_row*."""
    if header_row <= first_row:
        return _header_text(ws.cell(row=header_row, column=col).value)
    for row in range(first_row - 1, 0, -1):
        text = _header_text(ws.cell(row=row, column=col).value)
        if text:
            return text
    return ""


# ------------------------------------------------------------------ #
# Discovery                                                            #
# ------------------------------------------------------------------ #

def discover(wb, vertical: bool = False) -> Discovery:
    """Introspect an openpyxl workbook for list sources and header rows.

    Args:
        wb: An openpyxl workbook (loaded with formulas, not cached values).
        vertical: The headings run down the first column (one record per column), so a list's drop-down covers
            a *row* range and its heading is in that row's first cell. The header rows are then not used.

    Returns:
        A :class:`Discovery`. When the same header has lists on several sheets
        (e.g. one tab per year), the first one found is used.
    """
    result = Discovery()
    for ws in wb.worksheets:
        if not vertical:
            result.header_rows[ws.title] = _sheet_header_row(ws)

    for ws in wb.worksheets:
        header_row = result.header_rows.get(ws.title, 1)
        for dv in ws.data_validations.dataValidation:
            if dv.type != "list" or not dv.formula1:
                continue
            for cell_range in dv.sqref.ranges:
                if vertical:
                    headers = [_header_text(ws.cell(row=row, column=1).value)
                               for row in range(cell_range.min_row, cell_range.max_row + 1)]
                else:
                    headers = [_column_header(ws, header_row, col, cell_range.min_row)
                               for col in range(cell_range.min_col, cell_range.max_col + 1)]
                for header in headers:
                    if not header or header in result.sources:
                        continue
                    source = resolve_source(wb, ws.title, header, dv.formula1)
                    if source is not None:
                        result.sources[header] = source

    for ws in wb.worksheets:
        if ws.title.lower() in CONFIG_SHEET_NAMES:
            _discover_config_lists(ws, result)
    return result


def _discover_config_lists(ws, result: Discovery) -> None:
    """Add ``<name>_list`` columns of a config sheet to *result*."""
    header_row = result.header_rows.get(ws.title) or _sheet_header_row(ws)      # (a config sheet's lists are columns either way)
    for col in range(1, ws.max_column + 1):
        raw = _header_text(ws.cell(row=header_row, column=col).value)
        if not raw.lower().endswith(LIST_SUFFIX):
            continue
        name = re.sub(r"[\s_]+$", "", raw[: -len(LIST_SUFFIX)])
        if not name or name in result.sources:
            continue
        result.sources[name] = ListSource(
            column=name,
            sheet=ws.title,
            col=col,
            first_row=header_row + 1,
            last_row=max(ws.max_row, header_row + 1),
            growable=True,
        )
