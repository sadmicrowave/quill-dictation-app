"""macOS bridge: live Excel through xlwings (AppleScript underneath).

Requires: xlwings
Platform: macOS only

First use triggers an Automation permission prompt from macOS asking to
allow Quill to control Microsoft Excel. Grant it once
(System Settings > Privacy & Security > Automation).
"""

from __future__ import annotations
from quill.bridge.xlwings_bridge import XlwingsBridge


class MacBridge(XlwingsBridge):
    """Connects to Excel on macOS via xlwings + AppleScript."""

    PERMISSION_HINT = (
        "If macOS asked to let Quill control Excel, choose OK "
        "(System Settings > Privacy & Security > Automation)."
    )
