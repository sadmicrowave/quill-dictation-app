"""File-based bridge: reads and writes an ``.xlsx`` directly with openpyxl.

Needs no running Excel, so it is the bridge used in tests and a fallback when
live automation is unavailable. Changes are saved to the file after each write;
do not use it on a workbook that is open and unsaved in Excel.
"""

from __future__ import annotations
import logging
import os
import pathlib
import subprocess
import sys

import openpyxl

from quill.bridge.base import BridgeError, BridgeLockedError
from quill.bridge.grid import OpenpyxlGrid
from quill.bridge.grid_bridge import GridBridge
from quill.bridge.introspect import ListSource, discover
from quill.bridge.xlsx_patch import Unsupported, patch_package

log = logging.getLogger("quill.xlsx")
#: Seconds the system's ``open`` may take to hand a file over (it only asks; it never waits for the program).
OPEN_TIMEOUT_S = 6

#: Excel's limit for an inline validation list, in characters.
INLINE_LIST_LIMIT = 255


class XlsxBridge(GridBridge):
    """WorkbookBridge over a workbook file.

    Args:
        path: Workbook to open. May also be given to :meth:`connect`.
    """

    def __init__(self, path: str | pathlib.Path | None = None) -> None:
        super().__init__()
        self._path = pathlib.Path(path) if path else None
        self._wb = None
        self._dirty = False                      # changes are in memory but the file is held by another program
        self._list_edits: list[tuple[str, str]] = []     # inline list formulas rewritten since the file was last saved

    def connect(self, workbook: str | None = None) -> None:
        # The picker and saved settings pass a workbook *name*; only a path that
        # differs from the one we already hold is treated as a new file.
        if workbook and not (self._path and workbook == self._path.name):
            path = pathlib.Path(workbook)
        else:
            path = self._path
        if path is None:
            raise BridgeError("No workbook path given")
        if not path.exists():
            raise BridgeError(f"Workbook not found: {path}")
        try:
            self._wb = openpyxl.load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm")
        except Exception as exc:  # corrupt / unsupported file
            raise BridgeError(f"Could not open {path.name}: {exc}") from exc
        self._path = path
        self._name = path.name
        self._grid = OpenpyxlGrid(self._wb)
        self._list_edits = []
        self._discovery = discover(self._wb, self._vertical, self._headings_row)

    def disconnect(self) -> None:
        super().disconnect()
        self._wb = None

    @property
    def workbook_path(self) -> str:
        return str(self._path.resolve()) if self._path else ""

    def activate(self) -> None:
        """Open the file in the system's default spreadsheet application."""
        if self._path is None:
            return
        if sys.platform == "win32":
            os.startfile(str(self._path))   # type: ignore[attr-defined]
        else:
            try:
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(self._path)],    # noqa: S603, S607
                               check=False, timeout=OPEN_TIMEOUT_S, capture_output=True)
            except (OSError, subprocess.SubprocessError) as exc:      # (it never hangs or raises: it only asks)
                log.debug("could not open %s: %s", self._path, exc)

    def open_workbooks(self) -> list[str]:
        return [self._path.name] if self._path and self._path.exists() else []

    def _rediscover(self) -> None:
        if self._wb is not None:
            self._discovery = discover(self._wb, self._vertical, self._headings_row)

    def refresh(self) -> None:
        """Reload the file from disk, discarding unsaved in-memory state."""
        self.connect()

    def take_changes(self) -> list[tuple[str, int, int, object]]:
        """The cells written since the last call, which are then forgotten (empty if too many had piled up: reload instead)."""
        grid = self._grid
        if grid is None or not hasattr(grid, "changes"):
            return []
        taken = [] if getattr(grid, "changes_lost", False) else list(grid.changes)
        grid.changes.clear()
        grid.changes_lost = False
        return taken

    @property
    def dirty(self) -> bool:
        return self._dirty

    def _store(self, target: pathlib.Path) -> None:
        """Write the changes to *target*: into the existing file where that is safe, else the whole workbook.

        Patching keeps everything Quill did not touch (stored formula results above all) exactly as it was, so the
        spreadsheet program shows no "edited with formulas" notice. See :mod:`quill.bridge.xlsx_patch`.
        """
        grid = self._grid
        if not grid.restructured:
            try:
                patch_package(self._path, target, self._wb, grid.unsaved, self._list_edits)
                return
            except Unsupported as why:
                log.info("Saving %s in full instead of patching it: %s", self._path.name, why)
        self._wb.save(target)

    def _saved(self) -> None:
        """The file now holds every change made so far."""
        self._grid.unsaved.clear()
        self._grid.restructured = False
        self._list_edits.clear()

    def _after_write(self) -> None:
        try:
            self._store(self._path)
        except OSError as exc:                       # another program holds the file (Excel on Windows does)
            self._dirty = True
            raise BridgeLockedError(f"{self._path.name} is in use by another program ({exc.strerror or exc})") from exc
        self._saved()
        self._dirty = False

    def flush(self) -> bool:
        if not self._dirty:
            return True
        try:
            self._after_write()
        except BridgeLockedError:
            return False
        return True

    def save_copy(self) -> str:
        copy = self._path.with_name(f"{self._path.stem} (Quill copy){self._path.suffix}")
        try:
            self._write_copy(copy)
        except OSError:
            return ""
        return str(copy)

    def _write_copy(self, target: pathlib.Path) -> None:
        self._store(target)

    def _add_inline(self, source: ListSource, value: str) -> None:
        """Rewrite the inline validation formula(s) to include *value*."""
        if "," in value or '"' in value:
            raise BridgeError(f"'{value}' can't go into the '{source.column}' list: it contains a comma or a quote mark.")
        new_items = [*source.items, value]
        formula = '"' + ",".join(new_items) + '"'
        if len(formula) - 2 > INLINE_LIST_LIMIT:
            raise BridgeError(
                f"The '{source.column}' list is too long to extend inline "
                f"(the limit is {INLINE_LIST_LIMIT} characters)."
            )
        old = '"' + ",".join(source.items) + '"'
        for ws in self._wb.worksheets:
            for dv in ws.data_validations.dataValidation:
                if dv.type == "list" and (dv.formula1 or "").lstrip("=").strip() == old:
                    dv.formula1 = formula
        self._list_edits.append((old, formula))
        self._discovery.sources[source.column] = ListSource(
            column=source.column, items=tuple(new_items)
        )
