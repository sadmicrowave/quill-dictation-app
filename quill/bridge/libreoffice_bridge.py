"""Working in an open LibreOffice document directly (the live mode, like live Excel).

Over the live link (:mod:`quill.bridge.libreoffice_live`) Quill reads and writes the cells of the document as it is open
in LibreOffice, saved or not. So a new sheet, a heading just typed or a drop-down list just added is seen at once, and
rows Quill writes appear in LibreOffice and stay unsaved there until the user saves, exactly as with live Excel: Quill
does not touch the file while LibreOffice has it open.

* :class:`LiveDocument`: one document's questions over the link (every failure becomes a :class:`BridgeError`).
* :class:`LibreOfficeGrid`: the cell-level :class:`~quill.bridge.grid.Grid` over it.
* :class:`LibreOfficeBridge`: the workbook bridge. It is an :class:`XlsxBridge` that does not write the file, so everything
  that treats "the file Quill works on" (the Open Spreadsheets list, a closed window, the sheet) keeps working unchanged.
* :func:`build_workbook`: the structure LibreOffice reports (headings, lists, names) as an in-memory workbook, so the same
  discovery code that reads a file reads the live document.
"""

from __future__ import annotations

import datetime as dt
import pathlib
from typing import Callable

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from quill.bridge.base import BridgeError
from quill.bridge.filters import ColumnFilter
from quill.bridge.grid import Grid
from quill.bridge.introspect import ListSource, discover
from quill.bridge.libreoffice_live import LiveLink
from quill.bridge.libreoffice_mirror import change_fields, file_addresses
from quill.bridge.xlsx_bridge import INLINE_LIST_LIMIT, XlsxBridge

NOT_ANSWERING = "{program} is not answering. Check that it is open, then try again."
#: Seconds to wait for LibreOffice on a question the dictation waits for.
ASK_TIMEOUT_S = 5.0


class LiveDocument:
    """The open LibreOffice document at some file address, as questions over the live link.

    Args:
        link: Returns the live link (None when there is none): asked at every question, so a link that comes back is used.
        urls: The ``file:///`` addresses LibreOffice may know the document by.
    """

    def __init__(self, link: Callable[[], LiveLink | None], urls: list[str], program: str = "LibreOffice") -> None:
        self._link, self.urls, self.program = link, urls, program
        self._not_answering = NOT_ANSWERING.format(program=program)

    def info(self) -> dict:
        """What the link knows of the document now (``sheet``, ``sheets``, ``modified``)."""
        link = self._link()
        doc = link.find(self.urls) if link is not None and link.connected else None
        if doc is None:
            raise BridgeError(self._not_answering)
        return doc

    def ask(self, command: str, timeout: float = ASK_TIMEOUT_S, **fields) -> dict:
        link = self._link()
        if link is None or not link.connected:
            raise BridgeError(self._not_answering)
        answer = link.request(command, timeout=timeout, urls=self.urls, **fields)
        if answer is None:
            raise BridgeError(self._not_answering)
        if not answer.get("ok"):
            if answer.get("error") == "nodoc":
                raise BridgeError(f"The document is no longer open in {self.program}.")
            raise BridgeError(f"{self.program} could not do that ({answer.get('error', 'unknown')}).")
        return answer

    def is_open(self) -> bool:
        link = self._link()
        return link is not None and link.connected and link.find(self.urls) is not None


class LibreOfficeGrid(Grid):
    """The cells of a live LibreOffice document (values as the document holds them, saved or not)."""

    def __init__(self, document: LiveDocument) -> None:
        self._doc = document
        self._hidden: dict[str, list[int]] = {}               # rows a search hid, per sheet, so that clearing it shows them again

    def sheet_names(self) -> list[str]:
        return list(self._doc.info().get("sheets") or [])

    def active_sheet(self) -> str:
        return str(self._doc.info().get("sheet") or "")

    def set_active(self, sheet: str) -> bool:
        return False                                              # LibreOffice says which sheet is open; Quill never moves the user

    def last_row(self, sheet: str) -> int:
        return int(self._doc.ask("used", sheet=sheet)["rows"])

    def last_col(self, sheet: str) -> int:
        return int(self._doc.ask("used", sheet=sheet)["cols"])

    def read(self, sheet: str, top: int, left: int, rows: int, cols: int) -> list[list[object]]:
        if rows <= 0 or cols <= 0:
            return []
        block = self._doc.ask("read", sheet=sheet, top=top, left=left, rows=rows, cols=cols)["cells"]
        return [[_plain(value) for value in row] for row in block]

    def write(self, sheet: str, row: int, col: int, value: object) -> None:
        self._doc.ask("apply", changes=[change_fields(sheet, row, col, value)])

    # Searching: rows that do not match are hidden (and shown again when the search is cleared).

    def set_autofilter(self, sheet, header_row, first_col, last_col, last_row, criteria: dict[int, ColumnFilter]):
        self.clear_autofilter(sheet)
        count = max(last_row - header_row, 0)
        block = self.read(sheet, header_row + 1, first_col, count, last_col - first_col + 1) if count else []
        hide, matched = [], 0
        for offset, row in enumerate(block):
            if all(flt.matches(row[col - first_col]) for col, flt in criteria.items()):
                matched += 1
            else:
                hide.append(header_row + 1 + offset)
        if hide:
            self._doc.ask("hide", sheet=sheet, rows=hide, visible=False)
        self._hidden[sheet] = hide
        return matched

    def clear_autofilter(self, sheet: str) -> None:
        rows = self._hidden.pop(sheet, [])
        if rows:
            self._doc.ask("hide", sheet=sheet, rows=rows, visible=True)

    def get_cursor(self, sheet: str):
        try:
            answer = self._doc.ask("cursor")
            return int(answer["row"]), int(answer["col"])
        except (BridgeError, KeyError):
            return None

    def set_cursor(self, sheet: str, row: int, col: int) -> None:
        try:
            self._doc.ask("cursor", set=True, sheet=sheet, row=row, col=col)
        except BridgeError:
            pass                                                   # a courtesy: never fail a search over the scroll position


def _plain(value: object) -> object:
    """A cell as the link sends it, as the rest of Quill reads cells (a date is a datetime)."""
    if isinstance(value, dict) and "d" in value:
        return dt.datetime.fromisoformat(value["d"])
    return value


def build_workbook(snapshot: dict) -> Workbook:
    """An in-memory workbook with the headings, drop-down rules and names LibreOffice reported (no file is involved)."""
    wb = Workbook()
    wb.remove(wb.active)
    for info in snapshot.get("sheets", []):
        ws = wb.create_sheet(title=str(info["name"]))
        for part in ("left", "block"):                                         # (the top rows of every column, and the first columns far down)
            for r, row in enumerate(info.get(part, []), 1):
                for c, value in enumerate(row, 1):
                    if value is not None:
                        ws.cell(row=r, column=c, value=_plain(value))
        if info.get("used_rows"):
            ws.cell(row=int(info["used_rows"]), column=1)                       # (the sheet's real size, past what was sent)
        if info.get("used_cols"):
            ws.cell(row=1, column=int(info["used_cols"]))
        for rule in info.get("validations", []):
            validation = DataValidation(type="list", formula1=rule["formula"], allow_blank=True)
            ws.add_data_validation(validation)
            validation.add(f"{get_column_letter(int(rule['col']))}{int(rule['row'])}")
    for named in snapshot.get("names", []):
        wb.defined_names[named["name"]] = DefinedName(named["name"], attr_text=named["ref"])
    return wb


class LibreOfficeBridge(XlsxBridge):
    """The workbook bridge for a file that is open in LibreOffice, through the live link.

    Args:
        path: The file (it names the document and is what the Open Spreadsheets list matches).
        link: Returns the live link, or None.
    """

    #: The program's name in what the user reads, and the grid class over its questions (a program with the same kind of link sets its own).
    PROGRAM = "LibreOffice"
    GRID = None                                                       # (None: LibreOfficeGrid, which is defined above)

    def __init__(self, path: str | pathlib.Path, link: Callable[[], LiveLink | None]) -> None:
        super().__init__(path)
        self._link = link
        self._doc: LiveDocument | None = None
        self._stamp = 0

    @property
    def addresses(self) -> list[str]:
        """The ``file:///`` addresses LibreOffice may know this document by."""
        return file_addresses(self._path) if self._path else []

    #: The app asks the bridge, not the file, whether anything changed.
    @property
    def change_stamp(self) -> int:
        return self._stamp

    def touch(self) -> None:
        """LibreOffice said the document was edited: the next look re-reads its lists and headings."""
        self._stamp += 1

    def connect(self, workbook: str | None = None) -> None:
        if self._path is None:
            raise BridgeError("No workbook path given")
        document = LiveDocument(self._link, self.addresses, self.PROGRAM)
        if not document.is_open():
            raise BridgeError(NOT_ANSWERING.format(program=self.PROGRAM))
        self._doc = document
        self._wb = None
        self._name = self._path.name
        self._grid = (self.GRID or LibreOfficeGrid)(document)
        self._list_edits = []
        self._load_structure()

    def disconnect(self) -> None:
        super().disconnect()
        self._doc = None

    def _load_structure(self) -> None:
        snapshot = self._doc.ask("snapshot", timeout=15.0)
        self._discovery = discover(build_workbook(snapshot), self._vertical, self._headings_row)

    def _rediscover(self) -> None:
        if self._doc is not None:
            self._load_structure()

    def refresh(self) -> None:
        self._require()
        self._load_structure()

    def open_workbooks(self) -> list[str]:
        return [self._path.name] if self._path and self._doc is not None and self._doc.is_open() else []

    # LibreOffice holds the document: nothing is written to the file, nothing waits to be saved, nothing is shown twice.

    def take_changes(self) -> list[tuple[str, int, int, object]]:
        return []

    def _after_write(self) -> None:
        pass

    @property
    def dirty(self) -> bool:
        return False

    def flush(self) -> bool:
        return True

    def save_copy(self) -> str:
        return ""

    def _add_inline(self, source: ListSource, value: str) -> None:
        """Add *value* to a typed drop-down list, in the open document."""
        if "," in value or '"' in value or ";" in value:
            raise BridgeError(f"'{value}' can't go into the '{source.column}' list: it contains a comma, semicolon or quote mark.")
        new_items = [*source.items, value]
        if len(",".join(new_items)) > INLINE_LIST_LIMIT:
            raise BridgeError(f"The '{source.column}' list is too long to extend inline (the limit is {INLINE_LIST_LIMIT} characters).")
        answer = self._doc.ask("inline_list", old=list(source.items), new=new_items)
        if not answer.get("changed"):
            raise BridgeError(f"{self.PROGRAM} could not find the '{source.column}' list to extend.")
        self._discovery.sources[source.column] = ListSource(column=source.column, items=tuple(new_items))
