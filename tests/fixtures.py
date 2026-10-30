"""Shared test fixtures: a small plant-inventory workbook and fake xlwings.

The workbook deliberately exercises every validation-source style the
introspection supports, in a domain unrelated to anything in the app code.
"""

from __future__ import annotations
import pathlib

import openpyxl
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

#: Lists as the fixture workbook defines them.
SPECIES = ["Fern", "Cactus", "Orchid", "Monstera"]
LIGHT = ["Low", "Medium", "Bright"]
HEALTH = ["Thriving", "Okay", "Struggling"]
POT = ["Small", "Medium", "Large"]

HEADERS = ["Species", "Pot Size", "Light", "Health", "Price", "Acquired", "Notes", "Tag"]


def make_workbook(path: pathlib.Path) -> pathlib.Path:
    """Write the fixture workbook to *path* and return it.

    Layout:
      * ``Inventory`` — headers on row 3 (a title sits above), five input
        columns plus a formula column ``Tag`` that must not block free rows.
        - Species  -> range on Config with spare slots (``Config!$A$2:$A$8``)
        - Pot Size -> inline list ``"Small,Medium,Large"``
        - Light    -> named range ``LightList`` (full, no spare slots)
        - Health   -> same-sheet range on Inventory (``$K$4:$K$6``)
      * ``Config`` — header row 1; ``Season_list`` is a ``*_list`` column
        that is discovered by naming convention rather than by validation.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inventory"
    ws["A1"] = "Plant inventory"
    for col, name in enumerate(HEADERS, start=1):
        ws.cell(row=3, column=col, value=name)
    # Same-sheet list for Health in K4:K6.
    for i, value in enumerate(HEALTH):
        ws.cell(row=4 + i, column=11, value=value)

    cfg = wb.create_sheet("Config")
    cfg["A1"], cfg["B1"], cfg["C1"] = "Species", "Light", "Season_list"
    for i, value in enumerate(SPECIES):
        cfg.cell(row=2 + i, column=1, value=value)  # A2:A5 filled, A6:A8 spare
    for i, value in enumerate(LIGHT):
        cfg.cell(row=2 + i, column=2, value=value)  # B2:B4, exactly full
    for i, value in enumerate(["Spring", "Summer"]):
        cfg.cell(row=2 + i, column=3, value=value)

    wb.defined_names["LightList"] = DefinedName("LightList", attr_text="Config!$B$2:$B$4")

    def add_dv(formula: str, cell_range: str) -> None:
        dv = DataValidation(type="list", formula1=formula, allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(cell_range)

    add_dv("=Config!$A$2:$A$8", "A4:A200")
    add_dv('"Small,Medium,Large"', "B4:B200")
    add_dv("=LightList", "C4:C200")
    add_dv("=$K$4:$K$6", "D4:D200")

    # A formula in the Tag column of the first data row: computed, so the row is still free.
    ws["H4"] = '=IF(A4="","",ROW())'
    wb.save(path)
    return path


class FakeRange:
    """Minimal stand-in for ``xw.Range`` backed by a dict of cells."""

    def __init__(self, sheet: "FakeSheet", top_left, bottom_right=None) -> None:
        self.sheet = sheet
        self.tl = top_left
        self.br = bottom_right or top_left

    @property
    def formula(self):
        rows = range(self.tl[0], self.br[0] + 1)
        cols = range(self.tl[1], self.br[1] + 1)
        grid = [[self.sheet.cells.get((r, c)) for c in cols] for r in rows]
        if len(grid) == 1 and len(grid[0]) == 1:
            return grid[0][0]
        if len(grid) == 1:
            return grid[0]
        if len(grid[0]) == 1:
            return [row[0] for row in grid]
        return grid

    @property
    def value(self):
        cells = [v for v in self.sheet.cells.values() if v is not None]
        return cells[0] if cells else None

    @value.setter
    def value(self, v):
        self.sheet.cells[self.tl] = v

    @property
    def last_cell(self):
        rows = [r for r, _ in self.sheet.cells]
        cols = [c for _, c in self.sheet.cells]
        return type("Cell", (), {"row": max(rows), "column": max(cols)})()


class FakeSheet:
    """Minimal stand-in for ``xw.Sheet``."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.cells: dict[tuple[int, int], object] = {}

    def range(self, a, b=None):
        return FakeRange(self, a, b)

    @property
    def used_range(self):
        return FakeRange(self, (1, 1))


class FakeSheets(list):
    """Sheet collection with ``[name]`` lookup and ``.active``."""

    active = None

    def __getitem__(self, key):
        if isinstance(key, str):
            return next(s for s in self if s.name == key)
        return super().__getitem__(key)


class FakeBook:
    """Minimal stand-in for ``xw.Book``."""

    def __init__(self, name: str, fullname: str, sheets: list[FakeSheet]) -> None:
        self.name = name
        self.fullname = fullname
        self.sheets = FakeSheets(sheets)
        self.sheets.active = sheets[0]


class FakeBooks(list):
    active = None


class FakeApp:
    def __init__(self, books: list[FakeBook]) -> None:
        self.books = FakeBooks(books)
        self.books.active = books[0] if books else None


class FakeXlwings:
    """Stand-in for the ``xlwings`` module: ``apps`` and ``apps.active``."""

    class _Apps(list):
        active = None

    def __init__(self, apps: list[FakeApp]) -> None:
        self.apps = self._Apps(apps)
        self.apps.active = apps[0] if apps else None
