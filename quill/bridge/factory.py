"""Return the correct WorkbookBridge for the current platform."""

from __future__ import annotations
import pathlib
import sys
from quill.bridge.base import WorkbookBridge


def get_bridge(xlsx_path: str | pathlib.Path | None = None) -> WorkbookBridge:
    """Instantiate and return the appropriate bridge.

    Args:
        xlsx_path: When given, return a file-based bridge for that workbook
            instead of driving a live Excel (no Excel needed).

    Raises:
        NotImplementedError: on an unsupported platform (live Excel only).
    """
    if xlsx_path is not None:
        from quill.bridge.xlsx_bridge import XlsxBridge
        return XlsxBridge(xlsx_path)
    if sys.platform == "win32":
        from quill.bridge.win_bridge import WinBridge
        return WinBridge()
    elif sys.platform == "darwin":
        from quill.bridge.mac_bridge import MacBridge
        return MacBridge()
    else:
        raise NotImplementedError(
            f"Quill does not support platform '{sys.platform}'. "
            "Windows and macOS are supported."
        )
