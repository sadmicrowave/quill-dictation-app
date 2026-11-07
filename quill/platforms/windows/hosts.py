"""Finding and starting the spreadsheet programs on Windows (what ``quill.bridge.hosts.SpreadsheetHosts`` asks of a provider).

STUB, to be finished and tested on a Windows machine. What exists is a straight move of what ``hosts.py`` did for Windows
before it was split out: the process list from ``tasklist``, the files named on a program's command line through ``wmic``,
installed-program checks in Program Files, and ``os.startfile`` to open a file.

To do here:
  1. Ask for command lines with PowerShell (``Get-CimInstance Win32_Process -Filter "name='soffice.exe'"``) and fall back to
     ``wmic`` only when PowerShell is unavailable (newer Windows 11 builds no longer ship ``wmic``).
  2. Add the "files the program holds open" step that ``lsof`` gives on a Mac: LibreOffice and WPS write a lock file beside every
     open document (``.~lock.<name>#`` for LibreOffice), which can be listed without any permission.
  3. Tests with a fake runner, as the Mac ones have, and the Windows rows of the end-to-end checklist.
"""

from __future__ import annotations

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


def documents(app, run) -> list[tuple[pathlib.Path, str]]:
    """``(path, open sheet)`` of the spreadsheets *app* has open (the sheet is '' where the program does not say)."""
    from quill.bridge.hosts import files_named_in
    out = run(["wmic", "process", "where", f"name='{PROCESS_NAMES.get(app.key, '')}'", "get", "commandline"])
    return files_named_in(out)
