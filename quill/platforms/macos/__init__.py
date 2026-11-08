"""The macOS provider (see :mod:`quill.platforms` for what a provider may offer): the window chrome and title-bar icons,
Numbers and LibreOffice scripting, Spotlight, the live Excel bridge and the system voice."""

from quill.platforms.macos import chrome, excel_com, libreoffice
from quill.platforms.macos.processes import running_executables
from quill.platforms.macos.speech import render_clip, speak
from quill.platforms.macos.bridge import MacBridge
from quill.platforms.macos.hosts import MacHosts
from quill.platforms.macos.numbers_live import NumbersBridge, NumbersLink
from quill.platforms.macos.numbers_mirror import NumbersMirror


#: A menu bar that belongs to no window (shown while Settings, the Term Helper or Help is in front).
GLOBAL_MENU_BAR = True
#: The opacity setting thins the window's background only (vibrancy shows through); controls and text stay solid.
OPACITY_THINS_BACKGROUND = True


def open_file(path: str) -> None:
    """Open a file in the system's default program."""
    import subprocess
    subprocess.run(["open", path], check=False, timeout=6, capture_output=True)   # noqa: S603, S607


def new_live_bridge():
    """The live Excel bridge (xlwings + AppleScript)."""
    return MacBridge()


def make_hosts(run, native: bool = False) -> MacHosts:
    """The object that finds and starts the spreadsheet programs (see :class:`quill.bridge.hosts.SpreadsheetHosts`)."""
    return MacHosts(run, native)


__all__ = ["GLOBAL_MENU_BAR", "OPACITY_THINS_BACKGROUND", "open_file", "render_clip", "speak", "chrome", "excel_com", "libreoffice", "running_executables", "MacBridge", "MacHosts", "NumbersMirror", "NumbersLink", "NumbersBridge", "make_hosts", "new_live_bridge"]
