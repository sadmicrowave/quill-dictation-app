"""Return the correct WorkbookBridge for the current platform."""

from __future__ import annotations
import sys
from quill.bridge.base import WorkbookBridge


def get_bridge() -> WorkbookBridge:
    """Instantiate and return the platform-appropriate bridge.

    Raises:
        NotImplementedError: on an unsupported platform.
    """
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
