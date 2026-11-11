"""Finding and starting the spreadsheet programs on Windows (what ``quill.bridge.hosts.SpreadsheetHosts`` asks of a provider).

The process list comes from ``tasklist``; the files a program was started with come from its command line, asked of PowerShell
(``Get-CimInstance Win32_Process``) first and of ``wmic`` only when PowerShell gives nothing (newer Windows builds no longer ship
``wmic``). Installed-program checks look in Program Files; ``os.startfile`` opens a file.

Not done: a file opened *inside* a running LibreOffice or WPS (File > Open) is on no command line. LibreOffice's own link
(``quill.bridge.libreoffice_live``) answers for it while that link is up.
"""

from __future__ import annotations

import base64
import os
import pathlib

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


def documents(app, run) -> list[tuple[pathlib.Path, str]]:
    """``(path, open sheet)`` of the spreadsheets *app* was started with (the sheet is '' where the program does not say)."""
    from quill.bridge.hosts import files_named_in
    return files_named_in(command_lines(PROCESS_NAMES.get(app.key, ""), run))


class WinHosts:
    """The object ``quill.bridge.hosts.SpreadsheetHosts`` asks (the same questions as the Mac one), over the functions above."""

    def __init__(self, run, native: bool = False) -> None:
        self._run = run

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
        return documents(app, self._run)
