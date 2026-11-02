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
import logging
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("quill.hosts")

#: Seconds a helper command may take (a program waiting on a permission dialog would otherwise hang it).
COMMAND_TIMEOUT_S = 6

Runner = Callable[[list[str]], str]
"""Runs a command and returns its standard output ('' if it failed or timed out)."""

XLSX = ".xlsx"

#: File types Quill can work on directly.
SUPPORTED_SUFFIXES = (".xlsx", ".csv", ".tsv")


@dataclass(frozen=True)
class OpenFile:
    """A spreadsheet that some program has open right now (the side panel lists these)."""

    name: str
    path: str
    """Full path ('' for an Excel workbook that has not been saved)."""
    app: str
    """The program showing it, for the hover text."""
    live: bool = False
    """Open in Excel, which Quill can drive live (it is connected to by name, not by file)."""


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
    """Run a command (never through a shell) and return its output; '' if it fails or takes over 6 s."""
    if os.environ.get("QUILL_NO_HOSTS"):              # the tests never ask the system
        return ""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S, check=False)   # noqa: S603
        return done.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("command %s failed: %s", args[0], exc)
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
        """Spreadsheet programs that are running now, in the order of :data:`APPS`.

        Where it runs commands that can stall (they are given a time limit), call it off the GUI thread.
        """
        if self._platform == "darwin":
            # `ps` needs no permission, unlike asking System Events, which would show Quill's users a
            # "Quill wants to control System Events" prompt for no visible reason.
            paths = self._run(["ps", "-axo", "comm="]).splitlines()
            names = {pathlib.PurePosixPath(line.strip()).name.lower() for line in paths if line.strip()}
            return [a for a in APPS if a.mac_process and a.mac_process.lower() in names]
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

    def open_files(self, excel_files: Callable[[], list[tuple[str, str]]] | None = None) -> list[OpenFile]:
        """Every spreadsheet the running programs have open: Excel's workbooks (as ``(name, path)`` pairs from
        *excel_files*, asked only while Excel is running) and the files of the other programs. Best effort, may be empty.

        Where it runs commands that can stall (they are given a time limit), call it off the GUI thread.
        """
        found: list[OpenFile] = []
        seen: set[str] = set()
        running = self.running()
        if excel_files is not None and any(a.live for a in running):
            try:
                pairs = excel_files()
            except Exception:                                # a helper must never take the app down
                log.debug("could not list Excel's workbooks", exc_info=True)
                pairs = []
            for name, path in pairs:
                key = os.path.realpath(path) if path else name
                if key not in seen:
                    seen.add(key)
                    found.append(OpenFile(name, path, EXCEL.name, live=True))
        for app in running:
            if app.live:
                continue
            for path in self._documents(app):
                if path.suffix.lower() in SUPPORTED_SUFFIXES and path.is_file() and os.path.realpath(path) not in seen:
                    seen.add(os.path.realpath(path))
                    found.append(OpenFile(path.name, str(path), app.name))
        return found

    def launch(self, path: str | pathlib.Path) -> bool:
        """Open *path* in the system's program for it, without bringing that program to the front (macOS) .

        Returns:
            True if the request was made.
        """
        if os.environ.get("QUILL_NO_HOSTS"):
            return False
        try:
            if self._platform == "darwin":
                return subprocess.run(["open", "-g", str(path)], capture_output=True, timeout=COMMAND_TIMEOUT_S,   # noqa: S603, S607
                                      check=False).returncode == 0
            if self._platform == "win32":
                os.startfile(str(path))                       # type: ignore[attr-defined]  # noqa: S606
                return True
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)   # noqa: S603, S607
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("could not launch %s: %s", path, exc)
            return False

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
        return [pathlib.Path(m.strip('" ')) for m in re.findall(r'[^"\n]+\.(?:xlsx|csv|tsv)', out)
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
