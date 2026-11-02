"""Live Excel bridge shared by macOS and Windows, built on xlwings.

Cell reads/writes go through the running Excel (so unsaved edits are seen).
The *structure* (which columns have drop-down lists and where) is read from
the workbook's file on disk with openpyxl, because it is identical on both
platforms and far less fragile than driving validation objects through
AppleScript. Consequence: validation rules added since the last save are not
seen until the user saves and the app refreshes.
"""

from __future__ import annotations
import pathlib

import openpyxl

from quill.bridge.base import BridgeError
from quill.bridge.grid import XlwingsGrid
from quill.bridge.grid_bridge import GridBridge
from quill.bridge.introspect import Discovery, discover


class XlwingsBridge(GridBridge):
    """WorkbookBridge over a live Excel session.

    Args:
        xw_module: Injected xlwings module (tests pass a fake). Imported
            lazily when omitted so the package loads without xlwings.
    """

    #: Extra text appended to "can't reach Excel" errors; platforms override.
    PERMISSION_HINT = ""

    def __init__(self, xw_module=None) -> None:
        super().__init__()
        self._xw = xw_module
        self._book = None
        self.discovery_warning: str | None = None
        """Why lists could not be read from disk, if that failed (else None)."""

    # ------------------------------------------------------------------ #
    # Connection                                                           #
    # ------------------------------------------------------------------ #

    def _xlwings(self):
        if self._xw is None:
            try:
                import xlwings
            except ImportError as exc:
                raise BridgeError("xlwings is not installed") from exc
            self._xw = xlwings
        return self._xw

    def _books(self) -> list:
        """Every open workbook across all running Excel instances."""
        try:
            return [book for app in self._xlwings().apps for book in app.books]
        except Exception as exc:
            raise BridgeError(
                f"Could not reach your spreadsheet program: {exc}. {self.PERMISSION_HINT}".strip()
            ) from exc

    def open_workbooks(self) -> list[str]:
        return [book.name for book in self._books()]

    def open_workbook_files(self) -> list[tuple[str, str]]:
        """``(name, full path)`` of every open workbook ('' for the path of one that has not been saved)."""
        files = []
        for book in self._books():
            full = str(getattr(book, "fullname", "") or "")
            files.append((book.name, full if ("/" in full or "\\" in full) else ""))
        return files

    def connect(self, workbook: str | None = None) -> None:
        books = self._books()
        if not books:
            raise BridgeError("No workbook is open in your spreadsheet program. Open one and try again.")
        if workbook:
            matches = [b for b in books if b.name == workbook]
            if not matches:
                raise BridgeError(f"Workbook '{workbook}' is not open in your spreadsheet program.")
            book = matches[0]
        else:
            book = self._active_book(books)
        self._book = book
        self._name = book.name
        self._grid = XlwingsGrid(book)
        self._load_structure()

    def _active_book(self, books: list):
        """The frontmost workbook, falling back to the first one open."""
        try:
            active_app = self._xlwings().apps.active
            if active_app is not None and active_app.books.active is not None:
                return active_app.books.active
        except Exception:
            pass
        return books[0]

    def disconnect(self) -> None:
        super().disconnect()
        self._book = None

    def activate(self) -> None:
        """Bring Excel and this workbook to the front."""
        if self._book is None:
            return
        try:
            self._book.activate()
            self._book.app.activate(steal_focus=True)
        except Exception as exc:
            raise BridgeError(f"Could not bring '{self._name}' to the front: {exc}") from exc

    def refresh(self) -> None:
        self._require()
        self._load_structure()

    def _load_structure(self) -> None:
        """Read list structure from the saved file; never raise on failure."""
        self.discovery_warning = None
        self._discovery = Discovery()
        path = pathlib.Path(getattr(self._book, "fullname", "") or "")
        if not path.is_file():
            self.discovery_warning = (
                f"'{self._name}' has not been saved, so its drop-down lists can't be read. "
                "Save the workbook and refresh."
            )
            return
        try:
            wb = openpyxl.load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm")
            self._discovery = discover(wb, self._vertical)
        except Exception as exc:
            self.discovery_warning = f"Could not read lists from {path.name}: {exc}"
