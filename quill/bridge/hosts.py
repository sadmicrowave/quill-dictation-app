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

from quill.bridge.processes import running_executables

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
        if failed is not None:
            failed.append(args[0])
        return ""


class SpreadsheetHosts:
    """Finds spreadsheet programs and the Excel files they have open, and refreshes them after a save.

    Args:
        platform: ``sys.platform`` value to behave as (tests).
        runner: Replaces the command runner (tests).
    """

    def __init__(self, platform: str | None = None, runner: Runner | None = None) -> None:
        self._platform = platform or sys.platform
        self._native_processes = runner is None and platform is None      # (tests that give a runner see its `ps` instead)
        self._failed: list[str] = []                             # commands that could not answer during the look under way
        self._run = runner or (lambda args: _run(args, self._failed))
        self._found_by_name: dict[str, pathlib.Path] = {}        # documents a program reported by name only, and their files
        self.last_look_complete = True
        """Did every question of the last :meth:`open_files` get answered? (False: a time-out or a failing command, so an
        empty answer there means "could not ask", not "nothing is open")."""

    # ------------------------------------------------------------------ #

    def running(self) -> list[HostApp]:
        """Spreadsheet programs that are running now, in the order of :data:`APPS`.

        Where it runs commands that can stall (they are given a time limit), call it off the GUI thread.
        """
        if self._platform == "darwin":
            native = running_executables() if self._native_processes else None
            if native is not None:                           # the system's own list: no process is started
                return [a for a in APPS if a.mac_process and a.mac_process.lower() in native]
            # `ps` needs no permission, unlike asking System Events, which would show Quill's users a
            # "Quill wants to control System Events" prompt for no visible reason.
            paths = self._run(["ps", "-axo", "comm="]).splitlines()
            names = {pathlib.PurePosixPath(line.strip()).name.lower() for line in paths if line.strip()}
            return [a for a in APPS if a.mac_process and a.mac_process.lower() in names]
        if self._platform == "win32":
            lines = self._run(["tasklist", "/fo", "csv", "/nh"]).lower()
            return [a for a in APPS if a.win_process and f'"{a.win_process.lower()}"' in lines]
        return []

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

    #: Where each program lives on a Mac (checked in /Applications and the user's own Applications folder).
    _MAC_BUNDLES = {"numbers": "Numbers.app", "libreoffice": "LibreOffice.app", "excel": "Microsoft Excel.app"}

    def installed(self, program: str) -> bool:
        """Is *program* (``auto``, ``numbers``, ``libreoffice``, ``excel``) on this computer? ``auto`` always is."""
        if program == "auto":
            return True
        if self._platform == "darwin":
            bundle = self._MAC_BUNDLES.get(program)
            return bool(bundle) and any((root / bundle).is_dir() for root in (pathlib.Path("/Applications"), pathlib.Path.home() / "Applications"))
        if self._platform == "win32":
            roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
            if program == "libreoffice":
                return any((pathlib.Path(r) / "LibreOffice" / "program" / "soffice.exe").is_file() for r in roots)
            if program == "excel":
                return any(list(pathlib.Path(r, "Microsoft Office").glob("**/EXCEL.EXE")) for r in roots if pathlib.Path(r, "Microsoft Office").is_dir())
            return False
        import shutil
        return program == "libreoffice" and shutil.which("soffice") is not None

    def launch(self, path: str | pathlib.Path, program: str = "auto") -> bool:
        """Open *path* in a program, without bringing that program to the front (macOS): the system's program for the
        file, or the one the user chose (``numbers``, ``libreoffice``, ``excel``).

        Returns:
            True if the request was made.
        """
        if os.environ.get("QUILL_NO_HOSTS"):
            return False
        try:
            if self._platform == "darwin":
                chosen = self.OPEN_WITH.get(program) if self.installed(program) else None       # (not installed: the system's choice)
                command = ["open", "-g", *(["-a", chosen] if chosen else []), str(path)]
                return subprocess.run(command, capture_output=True, timeout=COMMAND_TIMEOUT_S,                # noqa: S603
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
        return bool(self._run(["osascript", "-e", _RELOAD_NUMBERS, str(path)]).strip() == "ok")

    # ------------------------------------------------------------------ #

    @staticmethod
    def _split(text: str, sep: str) -> list[str]:
        return [part.strip() for part in text.strip().split(sep) if part.strip()]

    #: Where a file found by name is not taken from (the Trash, and programs' own cache, support, container and mail folders;
    #: cloud drives, which live under ``Library/CloudStorage``, are fine).
    _NOT_FROM = ("/.Trash/", "/Library/Caches/", "/Library/Application Support/", "/Library/Containers/", "/Library/Mail/",
                 "/Library/Logs/")

    def find_by_name(self, name: str, prefer: tuple[str, ...] = ()) -> pathlib.Path | None:
        """The spreadsheet file a program calls *name* when it reports the document by name only.

        Numbers does that for a workbook imported from an ``.xlsx`` (it names the document without the extension and gives
        no file). The paths in *prefer* are matched first; then Spotlight is asked (one cheap local search; the newest match
        outside the Trash and programs' own folders wins) and the answer is remembered while the file is still there.
        """
        stem = name[:-len(".numbers")] if name.lower().endswith(".numbers") else name
        for path in prefer:
            candidate = pathlib.Path(path)
            if candidate.stem == stem and candidate.suffix.lower() in SUPPORTED_SUFFIXES and candidate.is_file():
                return candidate
        known = self._found_by_name.get(stem)
        if known is not None and known.is_file():
            return known
        beside = self._beside(stem, prefer)
        if beside is not None:
            self._remember_name(stem, beside)
            return beside
        if self._platform != "darwin" or not stem:
            return None
        safe = stem.replace("\\", "\\\\").replace("'", "\\'")
        matches: list[pathlib.Path] = []
        for suffix in SUPPORTED_SUFFIXES:
            for line in self._run(["mdfind", f"kMDItemFSName == '{safe}{suffix}'c"]).splitlines():
                candidate = pathlib.Path(line.strip())
                if (line.startswith("/") and candidate.is_file() and candidate.suffix.lower() in SUPPORTED_SUFFIXES
                        and not any(part in line for part in self._NOT_FROM)):
                    matches.append(candidate)
        if not matches:
            log.info("%s is open in a program, but no file with that name was found", stem)
            return None
        newest = max(matches, key=lambda m: m.stat().st_mtime)
        self._remember_name(stem, newest)
        return newest

    MAX_REMEMBERED_NAMES = 64

    def _remember_name(self, stem: str, path: pathlib.Path) -> None:
        """Remember *path* for the document called *stem* (the oldest are forgotten past :data:`MAX_REMEMBERED_NAMES`, so the
        memory never grows with every file that is ever opened)."""
        self._found_by_name[stem] = path
        while len(self._found_by_name) > self.MAX_REMEMBERED_NAMES:
            del self._found_by_name[next(iter(self._found_by_name))]

    #: Folders (besides the active file's own) where a document reported by name only is looked for first, by name.
    _USUAL_FOLDERS = ("Desktop", "Documents", "Downloads")

    def _beside(self, stem: str, prefer: tuple[str, ...]) -> pathlib.Path | None:
        """A file called *stem* (with a spreadsheet suffix) in the folder of a *prefer* path or in a usual folder: a plain
        look at those paths, which needs no Spotlight (it may not be allowed to search a cloud folder). Newest wins."""
        folders = [pathlib.Path(p).parent for p in prefer] + [pathlib.Path.home() / name for name in self._USUAL_FOLDERS]
        found = [folder / f"{stem}{suffix}" for folder in folders for suffix in SUPPORTED_SUFFIXES
                 if (folder / f"{stem}{suffix}").is_file()]
        return max(found, key=lambda f: f.stat().st_mtime) if found else None

    def _documents(self, app: HostApp, prefer: tuple[str, ...] = ()) -> list[pathlib.Path]:
        """Paths of the documents *app* has open."""
        return [path for path, _ in self._documents_with_sheets(app, prefer)]

    def _documents_with_sheets(self, app: HostApp, prefer: tuple[str, ...] = ()) -> list[tuple[pathlib.Path, str]]:
        """``(path, open sheet)`` of the documents *app* has open (the sheet is '' where the program does not say)."""
        if self._platform == "darwin" and app.key == "numbers":
            out = self._run(["osascript", "-e", _LIST_NUMBERS])
            found: list[tuple[pathlib.Path, str]] = []
            for line in (l.strip("\r\n") for l in out.splitlines() if l.strip()):
                parts = line.split("\t")
                name, path, sheet = (parts + ["", ""])[:3] if len(parts) > 1 else ("", parts[0], "")
                if path.strip():
                    found.append((pathlib.Path(path.strip()), sheet.strip()))
                elif name.strip():                                      # reported by name only: find the file
                    located = self.find_by_name(name.strip(), prefer)
                    if located is not None:
                        found.append((located, sheet.strip()))
            return found
        # Other programs: the files named on their command line.
        if self._platform == "win32":
            out = self._run(["wmic", "process", "where", f"name='{app.win_process}'", "get", "commandline"])
        else:
            out = self._run(["ps", "-axo", "command="])
            out = "\n".join(line for line in out.splitlines() if app.mac_process.lower() in line.lower())
        return [(pathlib.Path(m.strip('" ')), "") for m in re.findall(r'[^"\n]+\.(?:xlsx|csv|tsv)', out)
                if m.strip('" ').startswith(("/", "~")) or re.match(r'[A-Za-z]:\\', m.strip('" '))]


_LIST_NUMBERS = """
tell application "Numbers"
  set out to ""
  repeat with d in documents
    set docName to ""
    set docPath to ""
    set sheetName to ""
    try
      set docName to name of d
    end try
    try
      set docPath to POSIX path of (file of d as alias)
    end try
    try
      set sheetName to name of active sheet of d
    end try
    set out to out & docName & tab & docPath & tab & sheetName & linefeed
  end repeat
  return out
end tell
"""

_RELOAD_NUMBERS = """
on run argv
  set target to item 1 of argv
  try
    tell application "Numbers"
      repeat with d in documents
        try
          if POSIX path of (file of d as alias) is target and not (modified of d) then close d saving no
        end try
      end repeat
      open POSIX file target
    end tell
    return "ok"
  on error
    return "no"
  end try
end run
"""
