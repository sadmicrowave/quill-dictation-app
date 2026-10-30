"""File-based bridge: reads and writes an ``.xlsx`` directly with openpyxl.

Needs no running Excel, so it is the bridge used in tests and a fallback when
live automation is unavailable. Changes are saved to the file after each write;
do not use it on a workbook that is open and unsaved in Excel.
"""

from __future__ import annotations
import pathlib

import openpyxl

from quill.bridge.base import BridgeError
from quill.bridge.grid import OpenpyxlGrid
from quill.bridge.grid_bridge import GridBridge
from quill.bridge.introspect import ListSource, discover

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

    def connect(self, workbook: str | None = None) -> None:
        path = pathlib.Path(workbook) if workbook else self._path
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
        self._discovery = discover(self._wb)

    def disconnect(self) -> None:
        super().disconnect()
        self._wb = None

    def open_workbooks(self) -> list[str]:
        return [self._path.name] if self._path else []

    def refresh(self) -> None:
        """Reload the file from disk, discarding unsaved in-memory state."""
        self.connect()

    def _after_write(self) -> None:
        self._wb.save(self._path)

    def _add_inline(self, source: ListSource, value: str) -> None:
        """Rewrite the inline validation formula(s) to include *value*."""
        new_items = [*source.items, value]
        formula = '"' + ",".join(new_items) + '"'
        if len(formula) - 2 > INLINE_LIST_LIMIT:
            raise BridgeError(
                f"The '{source.column}' list is too long to extend inline "
                f"(Excel limit is {INLINE_LIST_LIMIT} characters)."
            )
        old = '"' + ",".join(source.items) + '"'
        for ws in self._wb.worksheets:
            for dv in ws.data_validations.dataValidation:
                if dv.type == "list" and (dv.formula1 or "").lstrip("=").strip() == old:
                    dv.formula1 = formula
        self._discovery.sources[source.column] = ListSource(
            column=source.column, items=tuple(new_items)
        )
