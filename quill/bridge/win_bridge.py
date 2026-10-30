"""Windows bridge: live Excel through xlwings (COM underneath).

Requires: xlwings (pulls in pywin32 on Windows).
Platform: Windows only. Excel must be running with the workbook open.
"""

from __future__ import annotations
from quill.bridge.xlwings_bridge import XlwingsBridge


class WinBridge(XlwingsBridge):
    """Connects to Excel on Windows via xlwings COM automation."""

    PERMISSION_HINT = "Make sure Excel is running and not busy editing a cell."
