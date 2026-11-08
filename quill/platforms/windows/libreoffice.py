"""LibreOffice on Windows: where its user scripts live, where the program is, and whether it is running."""

from __future__ import annotations

import os
import pathlib
import subprocess


def profile_scripts_dir(home: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(os.environ.get("APPDATA", str(home))) / "LibreOffice" / "4" / "user" / "Scripts" / "python"


def find_soffice() -> str | None:
    for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        candidate = pathlib.Path(root) / "LibreOffice" / "program" / "soffice.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def is_running() -> bool:
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=6, check=False).stdout.lower()  # noqa: S603, S607
    return '"soffice.exe"' in out or '"soffice.bin"' in out
