"""Return the correct WorkbookBridge for the current platform."""

from __future__ import annotations
import pathlib
import sys
from quill import platforms
from quill.bridge.base import WorkbookBridge


def startup_bridge(settings, cli_path: str | None = None, factory=None) -> WorkbookBridge:
    """The bridge to start with: a file given on the command line (a developer convenience), else the
    spreadsheet file the user last opened with *Open File* (if it is still there), else live Excel.
    """
    factory = factory or get_bridge
    path = cli_path
    if not path:
        remembered = str(settings.preferences.get("workbook_file", "") or "")
        if remembered and pathlib.Path(remembered).is_file():
            path = remembered
        elif remembered:                               # the file was moved or deleted: back to live Excel
            settings.preferences["workbook_file"] = ""
    return factory(path or None)


def get_bridge(xlsx_path: str | pathlib.Path | None = None) -> WorkbookBridge:
    """Instantiate and return the appropriate bridge.

    Args:
        xlsx_path: When given, return a file-based bridge for that workbook (or .csv file)
            instead of driving a live Excel (no Excel needed).

    Raises:
        NotImplementedError: where no live bridge exists (live Excel only).
    """
    if xlsx_path is not None:
        if pathlib.Path(xlsx_path).suffix.lower() in (".csv", ".tsv"):
            from quill.bridge.csv_bridge import CsvBridge
            return CsvBridge(xlsx_path)
        from quill.bridge.xlsx_bridge import XlsxBridge
        return XlsxBridge(xlsx_path)
    if sys.platform == "darwin":
        from quill.bridge.mac_bridge import MacBridge
        return MacBridge()
    make = platforms.offered(sys.platform, "new_live_bridge")
    if make is not None:
        return make()
    raise NotImplementedError(
        f"Quill has no live spreadsheet bridge for platform '{sys.platform}' in this build. "
        "Open a spreadsheet file instead."
    )
