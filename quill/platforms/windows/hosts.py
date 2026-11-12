"""Finding and starting the spreadsheet programs on Windows (what ``quill.bridge.hosts.SpreadsheetHosts`` asks of a provider).

The process list comes from ``tasklist``; the files a program was started with come from its command line, asked of PowerShell
(``Get-CimInstance Win32_Process``) first and of ``wmic`` only when PowerShell gives nothing (newer Windows builds no longer ship
``wmic``). Installed-program checks look in Program Files; ``os.startfile`` opens a file.

A file opened *inside* a running LibreOffice (File > Open, or a second file handed to the running program) is on no command line. LibreOffice
names every open document in its window title (``Plants.xlsx - LibreOffice Calc``), which Windows lists for any program, so those names are read
too. A title holds the name only; the folder comes from the active file (``prefer``) or from LibreOffice's own list of recent files. (WPS is
not looked at this way.) LibreOffice's live link (``quill.bridge.libreoffice_live``) also answers while it is up.
"""

from __future__ import annotations

import base64
import csv
import os
import pathlib
import re
import sys
import urllib.parse
from typing import Callable

#: Executable names as ``tasklist`` reports them.
PROCESS_NAMES = {"excel": "EXCEL.EXE", "libreoffice": "soffice.exe", "wps": "et.exe"}


def running(apps, run) -> list:
    """The programs of *apps* that are running (*run*: a command runner that returns standard output)."""
    lines = run(["tasklist", "/fo", "csv", "/nh"]).lower()
    return [a for a in apps if PROCESS_NAMES.get(a.key) and f'"{PROCESS_NAMES[a.key].lower()}"' in lines]


def installed(program: str) -> bool:
    roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
    if program == "libreoffice":
        return any((pathlib.Path(r) / "LibreOffice" / "program" / "soffice.exe").is_file() for r in roots)
    if program == "excel":
        return any(list(pathlib.Path(r, "Microsoft Office").glob("**/EXCEL.EXE")) for r in roots if pathlib.Path(r, "Microsoft Office").is_dir())
    return False


def launch(path, program: str = "auto") -> bool:
    os.startfile(str(path))                       # type: ignore[attr-defined]  # noqa: S606
    return True


def command_lines(process: str, run) -> str:
    """The command lines of every running *process* (an image name from :data:`PROCESS_NAMES`), one per line; '' when none or unknown.

    PowerShell writes its answer in the console's code page, which turns an accent or a non-Latin letter in a folder name into
    ``?`` (and a user called José or 山田 is not rare). So each line is sent as base64 of its UTF-8 bytes, which no code page changes.
    """
    if not process:
        return ""
    query = (f"Get-CimInstance Win32_Process -Filter \"name='{process}'\" | ForEach-Object {{ if ($_.CommandLine) "
             "{ [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($_.CommandLine)) } }")
    lines = []
    for line in run(["powershell", "-NoProfile", "-NonInteractive", "-Command", query]).splitlines():
        try:
            lines.append(base64.b64decode(line.strip(), validate=True).decode("utf-8"))
        except ValueError:                                    # (not one of ours: a warning or a banner)
            continue
    if lines:
        return "\n".join(lines)
    return run(["wmic", "process", "where", f"name='{process}'", "get", "commandline"])


def process_numbers(process: str, run) -> tuple[str, ...]:
    """The process numbers of every running *process*, sorted ('' tuple when none or unreadable): a cheap question (about 50 ms)."""
    if not process:
        return ()
    rows = csv.reader(run(["tasklist", "/fo", "csv", "/nh", "/fi", f"imagename eq {process}"]).splitlines())
    return tuple(sorted(row[1] for row in rows if len(row) > 1 and row[0].lower() == process.lower()))


#: A LibreOffice Calc window's title: the document's name, ``(read-only)`` when it is, then the program's name after a hyphen or a dash.
_CALC_TITLE = re.compile(r"^(?P<name>.+?)(?: \(read-only\))? [-\u2013\u2014] LibreOffice Calc$")


def enumerate_windows() -> list[tuple[str, str]]:
    """``(class name, title)`` of every visible top-level window (what Windows lists for any program)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32                         # type: ignore[attr-defined]
    found: list[tuple[str, str]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            kind = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, kind, 256)
            title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
            user32.GetWindowTextW(hwnd, title, len(title))
            found.append((kind.value, title.value))
        return True

    user32.EnumWindows(callback_type(each), 0)
    return found


def calc_document_names(windows: list[tuple[str, str]], suffixes: tuple[str, ...]) -> list[str]:
    """The names of the documents LibreOffice Calc has open, read from its windows' titles (in window order, each once). A window named *Untitled 1*, or
    for a file type Quill does not use, is left out."""
    names: list[str] = []
    for _, title in windows:
        found = _CALC_TITLE.match(title.strip())
        if found and found["name"].lower().endswith(suffixes) and found["name"] not in names:
            names.append(found["name"])
    return names


def _file_uri_to_path(uri: str) -> pathlib.PureWindowsPath | None:
    """A ``file:`` address as LibreOffice writes it, as a Windows path (``file:///C:/a%20b.xlsx`` and ``file://server/share/a.xlsx``)."""
    if not uri.startswith("file:"):
        return None
    rest = urllib.parse.unquote(uri[len("file:"):])
    if re.match(r"^/{2,}[A-Za-z]:/", rest):
        return pathlib.PureWindowsPath(rest.lstrip("/").replace("/", "\\"))
    if rest.startswith("//"):
        return pathlib.PureWindowsPath("\\\\" + rest.lstrip("/").replace("/", "\\"))
    return None


def recent_paths(profile_text: str) -> list[pathlib.PureWindowsPath]:
    """The files LibreOffice lists as recent (``registrymodifications.xcu``), newest first: how a window's document name finds its folder."""
    found: list[pathlib.PureWindowsPath] = []
    for match in re.finditer(r'oor:name="(file:[^"]+)"', profile_text):
        path = _file_uri_to_path(match.group(1).replace("&amp;", "&").replace("&apos;", "'").replace("&quot;", '"'))
        if path is not None and path not in found:
            found.append(path)
    return found


def _recent_profile_text() -> str:
    """LibreOffice's own settings file for the user (where its list of recent documents lives); '' when it cannot be read."""
    folder = pathlib.Path(os.environ.get("APPDATA", "")) / "LibreOffice" / "4" / "user" / "registrymodifications.xcu"
    try:
        return folder.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def documents(app, run) -> list[tuple[pathlib.Path, str]]:
    """``(path, open sheet)`` of the spreadsheets *app* was started with (the sheet is '' where the program does not say)."""
    from quill.bridge.hosts import files_named_in
    return files_named_in(command_lines(PROCESS_NAMES.get(app.key, ""), run))


class WinHosts:
    """The object ``quill.bridge.hosts.SpreadsheetHosts`` asks (the same questions as the Mac one), over the functions above."""

    def __init__(self, run, native: bool = False, windows: Callable[[], list[tuple[str, str]]] | None = None,
                 recent: Callable[[], str] | None = None, is_file: Callable[[str], bool] | None = None) -> None:
        self._run = run
        self._is_file = is_file or (lambda path: pathlib.Path(path).is_file())
        self._windows = windows or (enumerate_windows if sys.platform == "win32" else (lambda: []))
        self._recent = recent or _recent_profile_text
        self._asked: dict[str, tuple[tuple[str, ...], list[tuple[pathlib.Path, str]]]] = {}
        """Per program: the process numbers it had and the files its command lines named then. A command line cannot change while a
        process lives, and PowerShell needs seconds to answer, so the question is asked again only when the numbers change."""

    def running(self, apps) -> list:
        return running(apps, self._run)

    def installed(self, program: str) -> bool:
        return installed(program)

    def launch(self, path, program: str = "auto") -> bool:
        return launch(path, program)

    def reload(self, app, path) -> bool:
        return False                       # no program here can be asked to reload (Windows programs hold the file open)

    def find_by_name(self, name: str, prefer: tuple[str, ...] = ()):
        return None                        # (only Numbers reports a document by name)

    def documents(self, app, prefer: tuple[str, ...] = ()) -> list:
        numbers = process_numbers(PROCESS_NAMES.get(app.key, ""), self._run)
        known = self._asked.get(app.key)
        if numbers and known is not None and known[0] == numbers:
            found = list(known[1])
        else:
            found = documents(app, self._run)
            if numbers:                              # (no numbers: the list could not be read, so nothing is remembered)
                self._asked[app.key] = (numbers, list(found))
        return found + self._from_windows(app, prefer, found) if app.key == "libreoffice" else found

    def _from_windows(self, app, prefer: tuple[str, ...], known: list) -> list:
        """The documents LibreOffice has open that no command line names (opened inside it): found by the window titles, then placed in a folder through the
        active file (*prefer*) or LibreOffice's list of recent files. A name that cannot be placed is left out."""
        from quill.bridge.hosts import SUPPORTED_SUFFIXES
        try:
            names = calc_document_names(self._windows(), tuple(SUPPORTED_SUFFIXES))
        except Exception:                            # noqa: BLE001 (a helper must never take the app down)
            return []
        have = {path.name.lower() for path, _ in known}
        wanted = [name for name in names if name.lower() not in have]
        if not wanted:
            return []
        candidates = [str(p) for p in prefer] + [str(p) for p in recent_paths(self._recent())]
        placed = []
        for name in wanted:
            path = next((c for c in candidates if pathlib.PureWindowsPath(c).name.lower() == name.lower() and self._is_file(c)), None)
            if path is not None:
                placed.append((pathlib.Path(path), ""))
        return placed
