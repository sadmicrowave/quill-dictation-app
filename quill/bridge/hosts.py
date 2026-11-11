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

from quill import platforms
from quill.diagnostics import exc_kind, syslog

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
    sheet: str = ""
    """The sheet that is open in it now, when the program said so in the same answer ('' otherwise)."""


@dataclass(frozen=True)
class HostApp:
    """A spreadsheet program Quill knows about."""

    key: str
    name: str
    mac_process: str = ""
    """Process name as System Events reports it (macOS)."""
    live: bool = False
    """Driven live through its own automation (only Excel); others work through the file."""
    reloads: bool = False
    """Quill can ask it to load the file again after a save (without any user action)."""
    note: str = ""
    """One line of plain advice, shown only when something needs doing by hand."""


EXCEL = HostApp("excel", "Excel", "Microsoft Excel", live=True)
NUMBERS = HostApp("numbers", "Numbers", "Numbers", reloads=True,
                  note="Save the sheet as an Excel file (File > Export To > Excel…) so Quill can read it.")
LIBREOFFICE = HostApp("libreoffice", "LibreOffice Calc", "soffice",
                      note="Reload the file (File > Reload) to see the rows Quill added.")
WPS = HostApp("wps", "WPS Office", "wpsoffice",
              note="Reopen the file to see the rows Quill added.")

APPS: tuple[HostApp, ...] = (EXCEL, NUMBERS, LIBREOFFICE, WPS)


def _run(args: list[str], failed: list[str] | None = None) -> str:
    """Run a command (never through a shell, never longer than :data:`COMMAND_TIMEOUT_S`) and return its output; '' if it
    fails or takes over 6 s. A failure (not starting, a time-out, a bad exit) adds the command's name to *failed*, so a
    caller can tell "nothing there" from "could not ask". The child is always reaped: ``subprocess.run`` kills it and waits
    when the time runs out."""
    if os.environ.get("QUILL_NO_HOSTS"):              # the tests never ask the system
        return ""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S, check=False)   # noqa: S603
        if done.returncode != 0 and failed is not None:
            failed.append(args[0])
        return done.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("command %s failed: %s", args[0], exc)
        syslog().debug("A helper command failed: %s", exc_kind(exc))
        if failed is not None:
            failed.append(args[0])
        return ""


class NoHosts:
    """The spreadsheet programs on a system with no provider: none are found, none can be started or asked."""

    def __init__(self, run=None, native: bool = False) -> None:
        pass

    def running(self, apps) -> list:
        return []

    def installed(self, program: str) -> bool:
        import shutil
        return program == "libreoffice" and shutil.which("soffice") is not None

    def launch(self, path, program: str = "auto") -> bool:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)   # noqa: S603, S607
        return True

    def reload(self, app, path) -> bool:
        return False

    def find_by_name(self, name: str, prefer: tuple[str, ...] = ()) -> pathlib.Path | None:
        return None

    def documents(self, app, prefer: tuple[str, ...] = ()) -> list[tuple[pathlib.Path, str]]:
        return []


class SpreadsheetHosts:
    """Finds spreadsheet programs and the Excel files they have open, and refreshes them after a save.

    How each system answers (the process list, AppleScript, ``lsof``, Spotlight, ``tasklist``) is in that system's provider
    (:mod:`quill.platforms`); this class asks it and puts the answers together.

    Args:
        platform: ``sys.platform`` value to behave as (tests).
        runner: Replaces the command runner (tests).
    """

    def __init__(self, platform: str | None = None, runner: Runner | None = None) -> None:
        self._platform = platform or sys.platform
        self._native_processes = runner is None and platform is None      # (tests that give a runner see its `ps` instead)
        self._failed: list[str] = []                             # commands that could not answer during the look under way
        self._run = runner or (lambda args: _run(args, self._failed))
        make = platforms.offered(self._platform, "make_hosts", NoHosts)
        self._os = make(lambda args: self._run(args), self._native_processes)      # (a runner set later is used too)
        self.live_documents: dict[str, Callable[[], list[tuple[pathlib.Path, str]] | None]] = {}
        """Per program key: a cheap answer from a live link the program keeps open to Quill (``(path, open sheet)`` of each
        document), or None when the link is not up. Used first, so the process list and ``lsof`` are not asked every look."""
        self.last_look_complete = True
        """Did every question of the last :meth:`open_files` get answered? (False: a time-out or a failing command, so an
        empty answer there means "could not ask", not "nothing is open")."""

    # ------------------------------------------------------------------ #

    def running(self) -> list[HostApp]:
        """Spreadsheet programs that are running now, in the order of :data:`APPS`.

        Where it runs commands that can stall (they are given a time limit), call it off the GUI thread.
        """
        return self._os.running(APPS)

    def open_excel_files(self, prefer: tuple[str, ...] = ()) -> list[tuple[HostApp, pathlib.Path]]:
        """``.xlsx`` files that the running non-Excel programs have open (best effort, may be empty). *prefer*: paths to take
        first when a program reports a document by name only (see :meth:`find_by_name`)."""
        found: list[tuple[HostApp, pathlib.Path]] = []
        for app in self.running():
            if app.live:
                continue
            for path in self._documents(app, prefer):
                if path.suffix.lower() == XLSX and path.is_file():
                    found.append((app, path))
        return found

    def open_files(self, excel_files: Callable[[], list[tuple[str, str]]] | None = None,
                   prefer: tuple[str, ...] = (), running: list[HostApp] | None = None) -> list[OpenFile]:
        """Every spreadsheet the running programs have open: Excel's workbooks (as ``(name, path)`` pairs from
        *excel_files*, asked only while Excel is running) and the files of the other programs. Best effort, may be empty.
        *prefer*: paths (the active file) to match first when a program reports a document by name only. *running*: the
        programs already known to be running (saves asking again). :attr:`last_look_complete` says whether every question
        was answered.

        Where it runs commands that can stall (they are given a time limit), call it off the GUI thread.
        """
        self._failed.clear()
        found: list[OpenFile] = []
        seen: set[str] = set()
        running = self.running() if running is None else running
        if excel_files is not None and any(a.live for a in running):
            try:
                pairs = excel_files()
            except Exception:                                # a helper must never take the app down
                log.debug("could not list Excel's workbooks", exc_info=True)
                self._failed.append("excel")
                pairs = []
            for name, path in pairs:
                key = os.path.realpath(path) if path else name
                if key not in seen:
                    seen.add(key)
                    found.append(OpenFile(name, path, EXCEL.name, live=True))
        for app in running:
            if app.live:
                continue
            for path, sheet in self._documents_with_sheets(app, prefer):
                if path.suffix.lower() in SUPPORTED_SUFFIXES and path.is_file() and os.path.realpath(path) not in seen:
                    seen.add(os.path.realpath(path))
                    found.append(OpenFile(path.name, str(path), app.name, sheet=sheet))
        self.last_look_complete = not self._failed
        return found

    #: The programs a user may choose to open files with (setting ``open_with``) and their names on a Mac.
    OPEN_WITH = {"numbers": "Numbers", "libreoffice": "LibreOffice", "excel": "Microsoft Excel"}

    def installed(self, program: str) -> bool:
        """Is *program* (``auto``, ``numbers``, ``libreoffice``, ``excel``) on this computer? ``auto`` always is."""
        return True if program == "auto" else bool(self._os.installed(program))

    def launch(self, path: str | pathlib.Path, program: str = "auto") -> bool:
        """Open *path* in a program, without bringing that program to the front (macOS): the system's program for the
        file, or the one the user chose (``numbers``, ``libreoffice``, ``excel``).

        Returns:
            True if the request was made.
        """
        if os.environ.get("QUILL_NO_HOSTS"):
            return False
        try:
            return bool(self._os.launch(path, program))
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("could not launch %s: %s", path, exc)
            return False

    def reload(self, app: HostApp, path: str | pathlib.Path) -> bool | str:
        """Ask *app* to load *path* again after Quill saved it. False when that is not possible; a word (``"kept"``: the document
        has unsaved changes and was left alone, ``"not open"``) when the program had a reason not to."""
        if not app.reloads:
            return False
        answer = self._os.reload(app, path)
        return answer if isinstance(answer, str) else bool(answer)

    def find_by_name(self, name: str, prefer: tuple[str, ...] = ()) -> pathlib.Path | None:
        """The spreadsheet file a program calls *name* when it reports the document by name only (Numbers, for a workbook
        imported from an ``.xlsx``)."""
        return self._os.find_by_name(name, prefer)

    def _documents(self, app: HostApp, prefer: tuple[str, ...] = ()) -> list[pathlib.Path]:
        """Paths of the documents *app* has open."""
        return [path for path, _ in self._documents_with_sheets(app, prefer)]

    def _documents_with_sheets(self, app: HostApp, prefer: tuple[str, ...] = ()) -> list[tuple[pathlib.Path, str]]:
        """``(path, open sheet)`` of the documents *app* has open (the sheet is '' where the program does not say)."""
        live = self.live_documents.get(app.key)
        if live is not None:
            try:
                answer = live()
            except Exception:                                # (a link that misbehaves is not used)
                log.debug("a live list failed", exc_info=True)
                answer = None
            if answer is not None:
                return answer
        return self._os.documents(app, prefer)


#: A Windows path in a command line: a drive (``C:\\`` or ``C:/``) or a network share (``\\\\server\\share``), up to the file type, quoted or not.
_WINDOWS_PATH = re.compile(r'(?:[A-Za-z]:[\\/]|\\\\)[^"\n]*?\.(?:xlsx|csv|tsv)(?=["\s]|$)', re.IGNORECASE)


def files_named_in(text: str) -> list[tuple[pathlib.Path, str]]:
    """Spreadsheet files named in *text* (a command line or several), as ``(path, '')``: POSIX paths (quoted), and Windows
    paths (quoted or not, any capitals in the file type)."""
    found = [pathlib.Path(m.strip('" ')) for m in re.findall(r'[^"\n]+\.(?:xlsx|csv|tsv)', text) if m.strip('" ').startswith(("/", "~"))]
    found += [pathlib.Path(m) for m in _WINDOWS_PATH.findall(text)]
    unique: list[pathlib.Path] = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return [(path, "") for path in unique]
