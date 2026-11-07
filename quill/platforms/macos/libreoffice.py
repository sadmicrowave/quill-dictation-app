"""LibreOffice on a Mac: where its user scripts live and where the program is."""

from __future__ import annotations

import pathlib


def profile_scripts_dir(home: pathlib.Path) -> pathlib.Path:
    return home / "Library" / "Application Support" / "LibreOffice" / "4" / "user" / "Scripts" / "python"


def find_soffice() -> str | None:
    candidate = pathlib.Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    return str(candidate) if candidate.is_file() else None
