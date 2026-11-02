"""Live editing in LibreOffice Calc: the cells Quill writes to the file are also set in the open LibreOffice document.

Like :mod:`quill.bridge.numbers_mirror`, but LibreOffice has no AppleScript for cells and its own Python cannot be
used from outside (it is not allowed to run on a Mac without being opened once by hand). What every LibreOffice does
offer is: starting ``soffice`` with a script address while it is running hands the request to the running instance,
which runs the script inside itself. So Quill puts one small script in the user's LibreOffice profile, writes the cells
to a job file, and asks the running LibreOffice to run it; the script finds the document by its file address, sets the
cells and writes an answer file.

* The script is added to LibreOffice's *user* scripts folder (one file, ``quill_mirror.py``, marked as Quill's; it is
  put back when it is out of date and can be deleted at any time).
* It is only ever asked of a LibreOffice that is already running; Quill never starts it for this.
* The job and answer files are in Quill's own folder; nothing is spliced into a command line.

Nothing here may raise.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import pathlib
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable

from quill.bridge.numbers_mirror import MirrorResult

log = logging.getLogger("quill.libreoffice")

SCRIPT_NAME = "quill_mirror.py"
SCRIPT_VERSION = 2
#: Seconds to wait for LibreOffice to run the script and answer.
ANSWER_TIMEOUT_S = 10
#: Fields of a change, as the script gets them: ``[sheet, row, column, kind, text]``.
Runner = Callable[[list[str]], int]

#: The script that runs inside LibreOffice. ``@BASE@`` is Quill's job folder, filled in when it is installed.
SCRIPT = r'''# Quill live-rows helper (version @VERSION@). Installed by Quill; it is safe to delete, Quill puts it back when needed.
import datetime
import json
import os

BASE = @BASE@


def _answer(text):
    with open(os.path.join(BASE, "out.json"), "w", encoding="utf-8") as handle:
        handle.write(text)


def apply():
    try:
        with open(os.path.join(BASE, "in.json"), encoding="utf-8") as handle:
            job = json.load(handle)
        desktop = XSCRIPTCONTEXT.getDesktop()
        listing = desktop.getComponents().createEnumeration()
        document = None
        while listing.hasMoreElements():
            component = listing.nextElement()
            if getattr(component, "URL", "") in job["urls"] and component.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                document = component
                break
        if document is None:
            return _answer("nodoc")
        if job.get("probe"):
            return _answer("ok")
        sheets = document.getSheets()
        date_key = None
        for sheet_name, row, column, kind, text in job["changes"]:
            sheet = sheets.getByName(sheet_name) if sheets.hasByName(sheet_name) else sheets.getByIndex(0)
            cell = sheet.getCellByPosition(int(column) - 1, int(row) - 1)
            if kind == "e":
                cell.setString("")
            elif kind == "n":
                cell.setValue(float(text))
            elif kind == "d":
                if date_key is None:
                    import uno
                    from com.sun.star.lang import Locale
                    formats = document.getNumberFormats()
                    locale = Locale()
                    date_key = formats.queryKey("YYYY-MM-DD", locale, False)
                    if date_key == -1:
                        date_key = formats.addNew("YYYY-MM-DD", locale)
                year, month, day = (int(part) for part in text.split("-"))
                cell.setValue(float((datetime.date(year, month, day) - datetime.date(1899, 12, 30)).days))
                cell.NumberFormat = date_key
            else:
                cell.setString(text)
        _answer("ok")
    except Exception as exc:
        _answer("error " + repr(exc))
'''


def _app_data_dir() -> pathlib.Path:
    """Quill's own folder for the job and answer files."""
    try:
        from platformdirs import user_data_dir
        return pathlib.Path(user_data_dir("Quill", appauthor=False)) / "mirror"
    except ImportError:
        return pathlib.Path.home() / ".quill" / "mirror"


def profile_scripts_dir(platform: str | None = None, home: pathlib.Path | None = None) -> pathlib.Path:
    """LibreOffice's per-user folder for Python scripts."""
    platform = platform or sys.platform
    home = home or pathlib.Path.home()
    if platform == "darwin":
        return home / "Library" / "Application Support" / "LibreOffice" / "4" / "user" / "Scripts" / "python"
    if platform == "win32":
        return pathlib.Path(os.environ.get("APPDATA", str(home))) / "LibreOffice" / "4" / "user" / "Scripts" / "python"
    return home / ".config" / "libreoffice" / "4" / "user" / "Scripts" / "python"


def find_soffice(platform: str | None = None) -> str | None:
    """Where the ``soffice`` program is, if LibreOffice is installed."""
    platform = platform or sys.platform
    if platform == "darwin":
        candidate = pathlib.Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        return str(candidate) if candidate.is_file() else None
    if platform == "win32":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            candidate = pathlib.Path(root) / "LibreOffice" / "program" / "soffice.exe"
            if candidate.is_file():
                return str(candidate)
        return None
    import shutil
    return shutil.which("soffice")


def file_addresses(path: str | os.PathLike) -> list[str]:
    """The ``file:///`` addresses LibreOffice may report for *path* (with and without links resolved)."""
    found = []
    for candidate in (pathlib.Path(path), pathlib.Path(os.path.realpath(path))):
        uri = candidate.absolute().as_uri()
        if uri not in found:
            found.append(uri)
    return found


def change_fields(sheet: str, row: int, col: int, value: object) -> list:
    """One cell as the script gets it: ``[sheet, row, column, kind, text]`` (kind ``s`` text, ``n`` number, ``d`` date, ``e`` empty)."""
    if value is None or (isinstance(value, str) and not value):
        return [sheet, int(row), int(col), "e", ""]
    if isinstance(value, bool):
        return [sheet, int(row), int(col), "s", str(value)]
    if isinstance(value, (int, float)):
        return [sheet, int(row), int(col), "n", repr(float(value))]
    if isinstance(value, (dt.date, dt.datetime)):
        return [sheet, int(row), int(col), "d", value.strftime("%Y-%m-%d")]
    return [sheet, int(row), int(col), "s", str(value)]


def _system(args: list[str]) -> int:
    try:
        return subprocess.run(args, capture_output=True, timeout=ANSWER_TIMEOUT_S, check=False).returncode   # noqa: S603
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("soffice call failed: %s", exc)
        return 1


def _is_running(platform: str | None = None) -> bool:
    """Is LibreOffice running? (asked with ``ps`` / ``tasklist``, which need no permission)."""
    platform = platform or sys.platform
    try:
        if platform == "win32":
            out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=6, check=False).stdout.lower()  # noqa: S603, S607
            return '"soffice.exe"' in out or '"soffice.bin"' in out
        out = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, timeout=6, check=False).stdout   # noqa: S603, S607
        return any(pathlib.PurePosixPath(line.strip()).name.lower() in ("soffice", "soffice.bin") for line in out.splitlines())
    except (OSError, subprocess.SubprocessError):
        return False


@dataclass
class LibreOfficeMirror:
    """Sets cells in the open LibreOffice document that holds a file.

    Args:
        runner: Replaces starting ``soffice`` (tests); returns the exit code.
        scripts_dir: LibreOffice's user scripts folder (tests).
        base: Quill's job folder (tests).
        running: Replaces the "is LibreOffice running" check (tests).
        soffice: Where the program is (tests).
    """

    runner: Runner | None = None
    scripts_dir: pathlib.Path | None = None
    base: pathlib.Path | None = None
    running: Callable[[], bool] | None = None
    soffice: str | None = None
    wait_s: float = ANSWER_TIMEOUT_S
    installed_note: bool = False
    """True once Quill has put its script into the profile in this run (the app says so once)."""

    # ------------------------------------------------------------------ #

    def _dir(self) -> pathlib.Path:
        return self.base or _app_data_dir()

    def _scripts(self) -> pathlib.Path:
        return self.scripts_dir or profile_scripts_dir()

    def script_text(self) -> str:
        """The script as it is installed, with Quill's job folder filled in."""
        return SCRIPT.replace("@VERSION@", str(SCRIPT_VERSION)).replace("@BASE@", repr(str(self._dir())))

    def install(self) -> bool:
        """Put the script into LibreOffice's user scripts folder (or bring it up to date).

        Returns:
            True if it is there now; False if LibreOffice has no user profile yet (it has never been opened) or the
            folder cannot be written.
        """
        try:
            folder = self._scripts()
            if not folder.parent.parent.is_dir() and not folder.is_dir():          # no ".../user" profile: never run
                return False
            target = folder / SCRIPT_NAME
            text = self.script_text()
            if target.is_file() and target.read_text(encoding="utf-8") == text:
                return True
            folder.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, target)
            self.installed_note = True
            return True
        except OSError as exc:
            log.warning("could not install the LibreOffice script: %s", exc)
            return False

    def has_document(self, path: str | os.PathLike) -> bool:
        """Does a running LibreOffice have *path* open? (Asked through the same script, which then changes nothing.)"""
        return self.push(path, [], probe=True).ok

    def push(self, path: str | os.PathLike, changes: list[tuple[str, int, int, object]], probe: bool = False) -> MirrorResult:
        """Show *changes* (``(sheet, row, column, value)`` in sheet coordinates) in the LibreOffice document for *path*."""
        if not changes and not probe:
            return MirrorResult(True, "ok")
        if os.environ.get("QUILL_NO_HOSTS"):
            return MirrorResult(False, "disabled")
        soffice = self.soffice or find_soffice()
        if soffice is None:
            return MirrorResult(False, "notinstalled")
        if not (self.running or _is_running)():
            return MirrorResult(False, "notrunning")                              # never start LibreOffice for this
        if not self.install():
            return MirrorResult(False, "noprofile")
        folder = self._dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            answer = folder / "out.json"
            answer.unlink(missing_ok=True)
            job = {"urls": file_addresses(path), "changes": [change_fields(*c) for c in changes], "probe": probe}
            temp = folder / "in.json.tmp"
            temp.write_text(json.dumps(job), encoding="utf-8")
            os.replace(temp, folder / "in.json")
        except OSError as exc:
            return MirrorResult(False, "error", str(exc))
        try:
            return self._run_job(soffice, folder, answer)
        finally:
            for leftover in (folder / "in.json", answer):                         # the cells are not kept on disk
                leftover.unlink(missing_ok=True)

    def _run_job(self, soffice: str, folder: pathlib.Path, answer: pathlib.Path) -> MirrorResult:
        address = f"vnd.sun.star.script:{SCRIPT_NAME}$apply?language=Python&location=user"
        code = (self.runner or _system)([soffice, address])
        if code != 0:
            return MirrorResult(False, "error", f"soffice exited with {code}")
        deadline = time.monotonic() + self.wait_s
        while time.monotonic() < deadline:
            if answer.is_file():
                text = answer.read_text(encoding="utf-8").strip()
                if text == "ok":
                    return MirrorResult(True, "ok")
                if text == "nodoc":
                    return MirrorResult(False, "nodoc")
                return MirrorResult(False, "error", text)
            time.sleep(0.05)
        return MirrorResult(False, "error", "LibreOffice did not answer")
