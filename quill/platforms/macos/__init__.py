"""The macOS provider (see :mod:`quill.platforms` for what a provider may offer): the window chrome and title-bar icons,
Numbers and LibreOffice scripting, Spotlight, the live Excel bridge and the system voice."""

from quill.platforms.macos import chrome
from quill.platforms.macos.bridge import MacBridge
from quill.platforms.macos.hosts import MacHosts
from quill.platforms.macos.numbers_mirror import NumbersMirror


def new_live_bridge():
    """The live Excel bridge (xlwings + AppleScript)."""
    return MacBridge()


def make_hosts(run, native: bool = False) -> MacHosts:
    """The object that finds and starts the spreadsheet programs (see :class:`quill.bridge.hosts.SpreadsheetHosts`)."""
    return MacHosts(run, native)


__all__ = ["chrome", "MacBridge", "MacHosts", "NumbersMirror", "make_hosts", "new_live_bridge"]
