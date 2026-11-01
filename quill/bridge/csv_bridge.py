"""File-based bridge for a ``.csv`` (or ``.tsv``) file.

A CSV file is plain text: no sheets, no drop-down lists, no filters. So this bridge reads the file into an
in-memory sheet (every cell stays exactly the text in the file, so saving never changes what was there) and
learns from the data itself:

* a column whose entries repeat (and are neither numbers nor dates nor long free text) is a **list column**;
  its distinct entries are the values Quill matches speech against;
* a column with no data yet (a brand new file) has an empty list, so every word said for it goes to the
  Term Helper to be sorted, which is how its list starts to grow;
* searching is not available (a CSV file cannot be filtered); asking for it says so.

Rows are appended to the file (written to a temporary file first, then moved into place).
"""

from __future__ import annotations
import csv
import datetime as dt
import io
import os
import pathlib
import re

import openpyxl
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from quill.bridge.base import BridgeError
from quill.bridge.grid import OpenpyxlGrid, cell_text, is_blank
from quill.bridge.introspect import Discovery
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.parser.vocab import money_header, value_kind

#: Largest file read into memory.
MAX_BYTES = 20 * 1024 * 1024
#: A column with more distinct entries than this is not a list.
MAX_LIST_VALUES = 100
#: An entry with more words than this is free text, so its column is not a list.
MAX_LIST_WORDS = 4
#: A column of at least this many entries that are nearly all different is an identifier or free text.
UNIQUE_AFTER = 12
UNIQUE_SHARE = 0.8
#: The date layouts recognised in the file, in order; new dates are written the way the file writes its own.
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d.%m.%Y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y")

SEARCH_MESSAGE = "a .csv file has no filters, so it can't be searched. Open it in a spreadsheet program to search."


class CsvBridge(XlsxBridge):
    """WorkbookBridge over a delimited text file (see the module notes)."""

    #: Nothing else is showing this file, so there is no program to ask to reload it.
    host_reload = False

    def __init__(self, path: str | pathlib.Path | None = None) -> None:
        super().__init__(path)
        self._delimiter = ","
        self._newline = "\n"
        self._bom = False
        self._sheet = ""
        self._added: dict[str, list[str]] = {}          # values taught since the file was read
        self._date_format: dict[int, str] = {}          # column index -> the layout its dates use

    # ------------------------------------------------------------------ #
    # Connection                                                           #
    # ------------------------------------------------------------------ #

    def connect(self, workbook: str | None = None) -> None:
        if workbook and not (self._path and workbook == self._path.name):
            path = pathlib.Path(workbook)
        else:
            path = self._path
        if path is None:
            raise BridgeError("No file given")
        if not path.exists():
            raise BridgeError(f"File not found: {path}")
        try:
            if path.stat().st_size > MAX_BYTES:
                raise BridgeError(f"{path.name} is too large to open ({MAX_BYTES // (1024 * 1024)} MB at most).")
            raw = path.read_bytes()
            self._bom = raw.startswith(b"\xef\xbb\xbf")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")             # an older Excel export; every byte is a character
            self._newline = "\r\n" if "\r\n" in text else "\n"
            self._delimiter = self._sniff(path, text)
            rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=self._delimiter))
        except BridgeError:
            raise
        except (OSError, csv.Error) as exc:
            raise BridgeError(f"Could not open {path.name}: {exc}") from exc
        self._wb = openpyxl.Workbook()
        sheet = self._wb.active
        self._sheet = sheet.title = self._sheet_name(path)
        for r, row in enumerate(rows, start=1):
            for c, text in enumerate(row, start=1):
                if text.strip():
                    sheet.cell(row=r, column=c).value = ILLEGAL_CHARACTERS_RE.sub("", text)
        self._path = path
        self._name = path.name
        self._grid = OpenpyxlGrid(self._wb)
        self._discovery = Discovery(header_rows={self._sheet: 1})      # the first line is the header
        self._added = {}
        self._date_format = self._learn_date_formats()

    @staticmethod
    def _sheet_name(path: pathlib.Path) -> str:
        return (re.sub(r"[\[\]:*?/\\]", " ", path.stem).strip() or "Sheet")[:31]

    @staticmethod
    def _sniff(path: pathlib.Path, text: str) -> str:
        if path.suffix.lower() == ".tsv":
            return "\t"
        try:
            return csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            return ","

    # ------------------------------------------------------------------ #
    # What the data says                                                   #
    # ------------------------------------------------------------------ #

    def _columns(self) -> dict[str, list[str]]:
        """Header -> the entries below it (text, blanks left out), in sheet order."""
        grid = self._require()
        width, last = grid.last_col(self._sheet), grid.last_row(self._sheet)
        if width == 0:
            return {}
        headers = grid.read(self._sheet, 1, 1, 1, width)[0]
        data = grid.read(self._sheet, 2, 1, max(last - 1, 0), width) if last > 1 else []
        found: dict[str, list[str]] = {}
        for index, header in enumerate(headers):
            if is_blank(header):
                continue
            found.setdefault(str(header).strip(), [cell_text(r[index]) for r in data if not is_blank(r[index])])
        return found

    @staticmethod
    def _kind(entries: list[str]) -> str:
        """``"number"``, ``"date"`` or ``"text"`` for a column's entries (when nearly all agree)."""
        if not entries:
            return "text"
        kinds = [value_kind(e) for e in entries]
        for kind in ("number", "date"):
            if kinds.count(kind) / len(kinds) >= 0.8:
                return kind
        return "text"

    def _is_list(self, header: str, entries: list[str]) -> bool:
        if not entries:                                           # nothing to learn from yet
            return not money_header(header) and not self._date_header(header)
        distinct = {e.lower() for e in entries}
        if self._kind(entries) != "text" or len(distinct) > MAX_LIST_VALUES:
            return False
        if any(len(e.split()) > MAX_LIST_WORDS for e in entries):
            return False
        return not (len(entries) >= UNIQUE_AFTER and len(distinct) / len(entries) > UNIQUE_SHARE)

    @staticmethod
    def _date_header(header: str) -> bool:
        return bool({"date", "dated"} & set(re.findall(r"[a-z]+", header.lower())))

    def get_lists(self) -> dict[str, list[str]]:
        lists: dict[str, list[str]] = {}
        for header, entries in self._columns().items():
            if not self._is_list(header, entries):
                continue
            seen: set[str] = set()
            values: list[str] = []
            for text in [*entries, *self._added.get(header, [])]:
                if text.lower() not in seen:
                    seen.add(text.lower())
                    values.append(text)
            lists[header] = values
        return lists

    @staticmethod
    def _is_number(value: object) -> bool:
        return isinstance(value, str) and value_kind(value) == "number"

    @staticmethod
    def _is_date(value: object) -> bool:
        return isinstance(value, str) and value_kind(value) == "date"

    # ------------------------------------------------------------------ #
    # Lists that grow                                                      #
    # ------------------------------------------------------------------ #

    def add_to_list(self, column_name: str, value: str) -> None:
        """Teach a value: it joins the column's list now, and is in the file once a row holds it."""
        text = value.strip()
        header = next((h for h in self._columns() if h.lower() == column_name.strip().lower()), None)
        if header is None:
            raise BridgeError(f"No column named '{column_name}'")
        if text and text.lower() not in (v.lower() for v in self.get_lists().get(header, [])):
            self._added.setdefault(header, []).append(text)

    def remove_from_list(self, column_name: str, value: str) -> bool:
        items = self._added.get(column_name, [])
        for index in range(len(items) - 1, -1, -1):
            if items[index].lower() == value.strip().lower():
                del items[index]
                return True
        return False

    # ------------------------------------------------------------------ #
    # Searching is not possible                                            #
    # ------------------------------------------------------------------ #

    def apply_filters(self, sheet_name, filters):
        raise BridgeError(SEARCH_MESSAGE)

    def clear_filters(self, sheet_name):
        raise BridgeError(SEARCH_MESSAGE)

    # ------------------------------------------------------------------ #
    # Saving                                                               #
    # ------------------------------------------------------------------ #

    def _learn_date_formats(self) -> dict[int, str]:
        """For each column, the date layout its entries use (so a new date is written the same way)."""
        grid = self._grid
        width, last = grid.last_col(self._sheet), grid.last_row(self._sheet)
        formats: dict[int, str] = {}
        for index in range(1, width + 1):
            for row in grid.read(self._sheet, 2, index, max(last - 1, 0), 1):
                text = cell_text(row[0])
                layout = next((f for f in DATE_FORMATS if _parses(text, f)), None) if text else None
                if layout:
                    formats[index] = layout
                    break
        return formats

    def _text(self, value: object, column: int) -> str:
        if value is None:
            return ""
        if isinstance(value, dt.datetime):
            value = value.date() if (value.hour, value.minute, value.second) == (0, 0, 0) else value
        if isinstance(value, dt.datetime):
            return value.isoformat(sep=" ")
        if isinstance(value, dt.date):
            return value.strftime(self._date_format.get(column, "%Y-%m-%d"))
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _after_write(self) -> None:
        grid = self._require()
        sheet = self._wb[self._sheet]
        last, width = grid.last_row(self._sheet), grid.last_col(self._sheet)
        tmp = self._path.with_name(self._path.name + ".quill-tmp")
        try:
            with open(tmp, "w", encoding="utf-8-sig" if self._bom else "utf-8", newline="") as handle:
                writer = csv.writer(handle, delimiter=self._delimiter, lineterminator=self._newline)
                for row in sheet.iter_rows(min_row=1, max_row=last, max_col=width, values_only=True):
                    writer.writerow([self._text(v, c) for c, v in enumerate(row, start=1)])
            os.replace(tmp, self._path)
        except OSError as exc:
            raise BridgeError(f"Could not save {self._path.name}: {exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)


def _parses(text: str, layout: str) -> bool:
    try:
        dt.datetime.strptime(text, layout)
        return True
    except ValueError:
        return False
