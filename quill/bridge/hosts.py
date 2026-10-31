"""Which spreadsheet program the user works in, and how Quill stays in step with it.

Excel is driven live (see ``xlwings_bridge``). Every other program (Numbers, LibreOffice Calc, WPS, a
Google Drive copy opened in a browser ...) is handled through the workbook *file*: Quill finds the file
the program has open, works on it directly (``XlsxBridge``), and after it has saved asks the program to
load the new rows. Nothing here may raise: detection is best effort and a missing helper only means the
user is told what to do by hand.

The commands that talk to the operating system go through an injectable *runner* so the logic is tested
without any spreadsheet program installed.
"""

from __future__ import annotations
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

Runner = Callable[[list[str]], str]
"""Runs a command and returns its standard output ('' if it failed or timed out)."""

XLSX = ".xlsx"


@dataclass(frozen=True)
class HostApp:
    """A spreadsheet program Quill knows about."""

    key: str
    name: str
    mac_process: str = ""
    """Process name as System Events reports it (macOS)."""
    win_process: str = ""
    """Executable name as ``tasklist`` reports it (Windows)."""
    live: bool = False
    """Driven live through its own automation (only Excel); others work through the file."""
    reloads: bool = False
    """Quill can ask it to load the file again after a save (without any user action)."""
    note: str = ""
    """One line of plain advice, shown only when something needs doing by hand."""


EXCEL = HostApp("excel", "Excel", "Microsoft Excel", "EXCEL.EXE", live=True)
NUMBERS = HostApp("numbers", "Numbers", "Numbers", "", reloads=True,
                  note="Save the sheet as an Excel file (File > Export To > Excel…) so Quill can read it.")
LIBREOFFICE = HostApp("libreoffice", "LibreOffice Calc", "soffice", "soffice.exe",
                      note="Reload the file (File > Reload) to see the rows Quill added.")
WPS = HostApp("wps", "WPS Office", "wpsoffice", "et.exe",
              note="Reopen the file to see the rows Quill added.")

APPS: tuple[HostApp, ...] = (EXCEL, NUMBERS, LIBREOFFICE, WPS)


def _run(args: list[str]) -> str:
    if os.environ.get("QUILL_NO_HOSTS"):              # the tests never ask the system
        return ""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=6, check=False)
        return done.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _quote(path: str) -> str:
    """*path* as the inside of an AppleScript string."""
    return path.replace("\\", "\\\\").replace('"', '\\"')


class SpreadsheetHosts:
    """Finds spreadsheet programs and the Excel files they have open, and refreshes them after a save.

    Args:
        platform: ``sys.platform`` value to behave as (tests).
        runner: Replaces the command runner (tests).
    """

    def __init__(self, platform: str | None = None, runner: Runner | None = None) -> None:
        self._platform = platform or sys.platform
        self._run = runner or _run

    # ------------------------------------------------------------------ #

    def running(self) -> list[HostApp]:
        """Spreadsheet programs that are running now, in the order of :data:`APPS`."""
        if self._platform == "darwin":
            names = self._split(self._run(["osascript", "-e",
                                           'tell application "System Events" to get name of every '
                                           "application process whose background only is false"]), ",")
            return [a for a in APPS if a.mac_process and a.mac_process.lower() in {n.lower() for n in names}]
        if self._platform == "win32":
            lines = self._run(["tasklist", "/fo", "csv", "/nh"]).lower()
            return [a for a in APPS if a.win_process and f'"{a.win_process.lower()}"' in lines]
        return []

    def open_excel_files(self) -> list[tuple[HostApp, pathlib.Path]]:
        """``.xlsx`` files that the running non-Excel programs have open (best effort, may be empty)."""
        found: list[tuple[HostApp, pathlib.Path]] = []
        for app in self.running():
            if app.live:
                continue
            for path in self._documents(app):
                if path.suffix.lower() == XLSX and path.is_file():
                    found.append((app, path))
        return found

    def reload(self, app: HostApp, path: str | pathlib.Path) -> bool:
        """Ask *app* to load *path* again after Quill saved it. False when that is not possible."""
        if not app.reloads or self._platform != "darwin":
            return False
        script = _RELOAD_NUMBERS.format(path=_quote(str(path)))
        return bool(self._run(["osascript", "-e", script]).strip() == "ok")

    # ------------------------------------------------------------------ #

    @staticmethod
    def _split(text: str, sep: str) -> list[str]:
        return [part.strip() for part in text.strip().split(sep) if part.strip()]

    def _documents(self, app: HostApp) -> list[pathlib.Path]:
        """Paths of the documents *app* has open."""
        if self._platform == "darwin" and app.key == "numbers":
            out = self._run(["osascript", "-e", _LIST_NUMBERS])
            return [pathlib.Path(p) for p in self._split(out, "\n")]
        # Other programs: the files named on their command line.
        if self._platform == "win32":
            out = self._run(["wmic", "process", "where", f"name='{app.win_process}'", "get", "commandline"])
        else:
            out = self._run(["ps", "-axo", "command="])
            out = "\n".join(line for line in out.splitlines() if app.mac_process.lower() in line.lower())
        return [pathlib.Path(m.strip('" ')) for m in re.findall(r'[^"\n]+\.xlsx', out)
                if m.strip('" ').startswith(("/", "~")) or re.match(r'[A-Za-z]:\\', m.strip('" '))]


_LIST_NUMBERS = """
tell application "Numbers"
  set out to ""
  repeat with d in documents
    try
      set out to out & POSIX path of (file of d as alias) & linefeed
    end try
  end repeat
  return out
end tell
"""

_RELOAD_NUMBERS = """
try
  tell application "Numbers"
    repeat with d in documents
      try
        if POSIX path of (file of d as alias) is "{path}" and not (modified of d) then close d saving no
      end try
    end repeat
    open POSIX file "{path}"
  end tell
  return "ok"
on error
  return "no"
end try
"""
