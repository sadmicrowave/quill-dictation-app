"""Pretend LibreOffice Calc documents: enough of the UNO objects that Quill's helper script touches, kept in plain Python.

The helper script that runs inside LibreOffice is run here for real (compiled from the text Quill installs) against these
objects, so the live link, the commands and the bridge on top are tested together without LibreOffice. The shapes follow
LibreOffice's API (``getCellByPosition(column, row)`` is zero-based, ``getDataArray`` gives floats and strings, ...).
"""

from __future__ import annotations

import contextlib
import sys
import types


class Enum:
    def __init__(self, value): self.value = value


class Validation:
    def __init__(self, kind="ANY", formula=""): self.Type, self._formula = Enum(kind), formula
    def getFormula1(self): return self._formula
    def setFormula1(self, text): self._formula = text
    def copy(self): return Validation(self.Type.value, self._formula)


class Cell:
    def __init__(self):
        self.data, self.formula, self.NumberFormat, self.IsTextWrapped = "", "", 0, False
        self.Validation = Validation()
    def getType(self): return Enum("EMPTY" if self.data == "" and not self.formula else "VALUE")
    def setString(self, text): self.data, self.formula = text, text
    def setValue(self, number): self.data, self.formula = float(number), repr(float(number))


class Range:
    def __init__(self, sheet, c1, r1, c2, r2): self.sheet, self.box = sheet, (c1, r1, c2, r2)
    def _cells(self):
        c1, r1, c2, r2 = self.box
        return [[self.sheet.cell(c, r) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]
    def getDataArray(self): return tuple(tuple(c.data for c in row) for row in self._cells())
    def getFormulaArray(self): return tuple(tuple(c.formula for c in row) for row in self._cells())
    @property
    def Validation(self): return self._cells()[0][0].Validation
    @Validation.setter
    def Validation(self, validation):
        for row in self._cells():
            for cell in row:
                cell.Validation = validation.copy()


class Cursor:
    def __init__(self, sheet): self.sheet, self.end = sheet, (0, 0)
    def gotoEndOfUsedArea(self, expand):
        used = [(r, c) for (c, r), cell in self.sheet.cells.items() if cell.data != "" or cell.formula]
        self.end = (max((r for r, _ in used), default=0), max((c for _, c in used), default=0))
    def getRangeAddress(self): return types.SimpleNamespace(EndRow=self.end[0], EndColumn=self.end[1])


class Row:
    IsVisible = True


class Rows:
    def __init__(self): self.rows = {}
    def getByIndex(self, i): return self.rows.setdefault(i, Row())


class Sheet:
    def __init__(self, name): self.Name, self.cells, self.rows = name, {}, Rows()
    def cell(self, c, r): return self.cells.setdefault((c, r), Cell())
    def getCellByPosition(self, c, r): return self.cell(c, r)
    def getCellRangeByPosition(self, c1, r1, c2, r2): return Range(self, c1, r1, c2, r2)
    def createCursor(self): return Cursor(self)
    def getRows(self): return self.rows
    def put(self, row, col, value):
        """Set a cell by 1-based row and column: text, number or a date given as ("date", serial)."""
        cell = self.cell(col - 1, row - 1)
        if isinstance(value, tuple):
            cell.setValue(value[1])
            cell.NumberFormat = 36
        elif isinstance(value, (int, float)):
            cell.setValue(value)
        else:
            cell.setString(value)
        return cell
    def validate(self, row, col, kind, formula):
        self.cell(col - 1, row - 1).Validation = Validation(kind, formula)


class Sheets:
    def __init__(self, names): self.sheets = {n: Sheet(n) for n in names}
    def getElementNames(self): return tuple(self.sheets)
    def hasByName(self, name): return name in self.sheets
    def getByName(self, name):
        if name not in self.sheets:
            raise KeyError(name)
        return self.sheets[name]
    def getByIndex(self, i): return list(self.sheets.values())[i]
    def insert(self, name): self.sheets[name] = Sheet(name); return self.sheets[name]


class NumberFormats:
    def getByKey(self, key): return types.SimpleNamespace(Type=2 if key == 36 else 1)
    def queryKey(self, text, locale, flag): return -1
    def addNew(self, text, locale): return 36


class NamedRanges:
    def __init__(self): self.items = {}
    def getElementNames(self): return tuple(self.items)
    def getByName(self, name): return types.SimpleNamespace(Content=self.items[name])


class Controller:
    def __init__(self, document): self.document, self.selected = document, (0, 0)
    def getActiveSheet(self): return self.document.sheets.getByName(self.document.active)
    def setActiveSheet(self, sheet): self.document.active = sheet.Name
    def select(self, cell):
        for sheet in self.document.sheets.sheets.values():
            for (c, r), candidate in sheet.cells.items():
                if candidate is cell:
                    self.selected = (r, c)
    def getSelection(self):
        row, col = self.selected
        return types.SimpleNamespace(getRangeAddress=lambda: types.SimpleNamespace(StartRow=row, StartColumn=col))


class Document:
    """A spreadsheet document open in the pretend LibreOffice."""

    def __init__(self, url, names=("Sheet1",)):
        self.URL, self.sheets, self.active, self.modified, self.saved = url, Sheets(names), names[0], False, 0
        self.controller, self.NamedRanges, self.listeners = Controller(self), NamedRanges(), []
    def supportsService(self, name): return name == "com.sun.star.sheet.SpreadsheetDocument"
    def getCurrentController(self): return self.controller
    def getSheets(self): return self.sheets
    def getNumberFormats(self): return NumberFormats()
    def isModified(self): return self.modified
    def store(self): self.saved += 1; self.modified = False
    def addModifyListener(self, listener): self.listeners.append(listener)
    def edit(self):
        """Something was typed in LibreOffice: its modify listeners are called."""
        self.modified = True
        for listener in self.listeners:
            listener.modified(None)
    def sheet(self, name): return self.sheets.getByName(name)


class Desktop:
    def __init__(self): self.documents = []
    def getDesktop(self): return self
    def getComponents(self): return self
    def createEnumeration(self):
        items = list(self.documents)
        return types.SimpleNamespace(hasMoreElements=lambda: bool(items), nextElement=lambda: items.pop(0))


@contextlib.contextmanager
def fake_uno():
    """The modules a script inside LibreOffice can import (``uno``, ``unohelper``, ``com.sun.star...``), as stand-ins."""
    names = ["uno", "unohelper", "com", "com.sun", "com.sun.star", "com.sun.star.lang", "com.sun.star.util"]
    saved = {n: sys.modules.get(n) for n in names}
    modules = {n: types.ModuleType(n) for n in names}
    modules["unohelper"].Base = type("Base", (), {})
    modules["com.sun.star.lang"].Locale = lambda: object()
    modules["com.sun.star.util"].XModifyListener = type("XModifyListener", (), {})
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
