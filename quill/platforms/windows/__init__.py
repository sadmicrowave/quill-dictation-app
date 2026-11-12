"""The Windows provider (see :mod:`quill.platforms` for what a provider may offer).

Developed on the ``windows`` branch, because it can only be tested on a Windows machine. Everything Quill does differently on
Windows is in this package: the window look, the voice, live Excel through COM, the spreadsheet programs and LibreOffice.
"""

from quill.platforms.windows import chrome, excel_com, hosts, libreoffice
from quill.platforms.windows.bridge import WinBridge
from quill.platforms.windows.speech import render_clip, speak

NATIVE_QPA = "windows"
QUIT_LABEL = "Exit"
#: Cut a pop-up's corners (tooltip, menu, drop-down list, the file-settings overlay) with a mask as well: Windows kept square black
#: corners behind their rounded border.
ROUND_POPUPS_WITH_MASK = True
#: Default text size (points). A point is 96/72 of a pixel on Windows and one pixel on a Mac, so the 14 that suits a Mac looked too large here.
DEFAULT_FONT_SIZE = 12
TRAY_CLICK_OPENS_MENU = True


def make_hosts(run, native: bool = False):
    """The object that finds and starts the spreadsheet programs (see :class:`quill.bridge.hosts.SpreadsheetHosts`)."""
    return hosts.WinHosts(run, native)


def new_live_bridge():
    return WinBridge()


def open_file(path: str) -> None:
    import os
    os.startfile(path)                  # type: ignore[attr-defined]  # noqa: S606


__all__ = ["chrome", "excel_com", "hosts", "libreoffice", "make_hosts", "WinBridge", "render_clip", "speak",
           "NATIVE_QPA", "QUIT_LABEL", "TRAY_CLICK_OPENS_MENU", "new_live_bridge", "open_file"]
