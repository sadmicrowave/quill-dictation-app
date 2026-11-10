"""Finding and starting the spreadsheet programs on a Mac (what ``quill.bridge.hosts.SpreadsheetHosts`` asks of a provider).

Numbers is asked through AppleScript (it names its documents, their files and open sheets in one answer; an imported workbook
is reported by name only, so its file is found beside the active file, in the usual folders, in cloud-drive folders and with
Spotlight). LibreOffice and WPS are found from the files on their command line and the files their process holds open (``lsof``).
Programs are started with ``open``. Nothing here may raise: detection is best effort.
"""

from __future__ import annotations

import datetime
import logging
import os
import pathlib
import subprocess

from quill.bridge.hosts import SUPPORTED_SUFFIXES, files_named_in
from quill.platforms.macos.processes import running_executables as _native_list
from quill.diagnostics import syslog

log = logging.getLogger("quill.hosts")

#: Seconds a helper command may take (a program waiting on a permission dialog would otherwise hang it).
COMMAND_TIMEOUT_S = 6
#: The programs a user may choose to open files with (setting ``open_with``) and their names on a Mac.
OPEN_WITH = {"numbers": "Numbers", "libreoffice": "LibreOffice", "excel": "Microsoft Excel"}


class MacHosts:
    """What the system knows about the spreadsheet programs, on a Mac.

    Args:
        run: Runs a command and returns its standard output ('' if it failed).
        native: Read the running applications from the system's own list instead of starting ``ps`` (False in tests).
    """

    def __init__(self, run, native: bool = False, numbers_list=None) -> None:
        self._run = run
        self._native = native
        self._numbers_list = numbers_list                        # asks Numbers for its documents through one kept process (None: one launch per look)
        self._found_by_name: dict[str, pathlib.Path] = {}        # documents a program reported by name only, and their files

    def running(self, apps) -> list:
        """The programs of *apps* that are running now (the Mac name of each is its ``mac_process``)."""
        native = (None if os.environ.get("QUILL_NO_HOSTS") else _native_list()) if self._native else None
        if native is not None:                           # the system's own list: no process is started
            return [a for a in apps if a.mac_process and a.mac_process.lower() in native]
        # `ps` needs no permission, unlike asking System Events, which would show Quill's users a
        # "Quill wants to control System Events" prompt for no visible reason.
        paths = self._run(["ps", "-axo", "comm="]).splitlines()
        names = {pathlib.PurePosixPath(line.strip()).name.lower() for line in paths if line.strip()}
        return [a for a in apps if a.mac_process and a.mac_process.lower() in names]

    #: Where each program lives on a Mac (checked in /Applications and the user's own Applications folder).
    _MAC_BUNDLES = {"numbers": "Numbers.app", "libreoffice": "LibreOffice.app", "excel": "Microsoft Excel.app"}

    def installed(self, program: str) -> bool:
        bundle = self._MAC_BUNDLES.get(program)
        return bool(bundle) and any((root / bundle).is_dir() for root in (pathlib.Path("/Applications"), pathlib.Path.home() / "Applications"))

    def launch(self, path, program: str = "auto") -> bool:
        """Open *path* without bringing the program to the front: the system's program for the file, or the one chosen."""
        chosen = OPEN_WITH.get(program) if self.installed(program) else None       # (not installed: the system's choice)
        command = ["open", "-g", *(["-a", chosen] if chosen else []), str(path)]
        return subprocess.run(command, capture_output=True, timeout=COMMAND_TIMEOUT_S, check=False).returncode == 0   # noqa: S603

    #: What :meth:`reload` answers when the document has unsaved changes in the program, so Quill left it alone.
    KEPT = "kept"
    #: ... and when the program does not have the file open at all (there is nothing to refresh).
    NOT_OPEN = "not open"

    def reload(self, app, path):
        """Ask *app* (Numbers) to load *path* again after Quill saved it, without ever leaving a second copy open.

        Numbers opens another document every time it is asked to open a file, and it reports an imported workbook by name only
        (no file). So Quill looks at what Numbers has open first: documents that are the file (by file, or by name) are closed
        and the file is opened once; if one of them has unsaved changes nothing is touched (:attr:`KEPT`); if none is open,
        nothing is opened (:attr:`NOT_OPEN`: the user closed it). Returns True when reloaded, False when Numbers could not be
        asked, else one of those two words.
        """
        target = pathlib.Path(path)
        documents = self._numbers_documents()
        if documents is None:
            return False
        same = [d for d in documents if (d[1] and _same_file(d[1], target)) or d[0] in (target.stem, target.name)]
        if not same:
            return self.NOT_OPEN
        if any(d[2] for d in same):
            return self.KEPT
        indices = sorted((d[3] for d in same), reverse=True)                      # highest first: closing one never moves the next
        if self._run(["osascript", "-l", "JavaScript", "-e", _CLOSE_NUMBERS, *map(str, indices)]).strip() != "ok":
            return False
        self._run(["open", "-g", "-a", "Numbers", str(target)])                   # (once: the copies it replaces are closed)
        return True

    def _numbers_documents(self) -> list[tuple[str, str, bool, int]] | None:
        """``(name, file, has unsaved changes, position)`` of every document Numbers has open; None if it could not be asked."""
        out = self._run(["osascript", "-l", "JavaScript", "-e", _LIST_NUMBERS_FOR_RELOAD])
        if out.strip() == "no":
            return None
        found = []
        for line in out.splitlines():
            parts = line.rstrip("\r").split("\t")
            if len(parts) >= 4 and parts[3].strip().isdigit():
                found.append((parts[0].strip(), parts[1].strip(), parts[2].strip() == "1", int(parts[3])))
        return found

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
        if not stem:
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
            syslog().info("A file is open in a program, but no file with that name was found")
            return None
        newest = self._most_recently_used(matches)
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
    _USUAL_FOLDERS = ("Desktop", "Documents", "Downloads", "Library/Mobile Documents/com~apple~CloudDocs",
                      "Library/Mobile Documents/com~apple~Numbers/Documents", "Library/Mobile Documents/com~apple~Excel/Documents")

    def _beside(self, stem: str, prefer: tuple[str, ...]) -> pathlib.Path | None:
        """A file called *stem* (with a spreadsheet suffix) in the folder of a *prefer* path or in a usual folder: a plain
        look at those paths, which needs no Spotlight (it may not be allowed to search a cloud folder). Newest wins."""
        home = pathlib.Path.home()
        folders = [pathlib.Path(p).parent for p in prefer] + [home / name for name in self._USUAL_FOLDERS]
        cloud = home / "Library" / "CloudStorage"                       # Google Drive, Dropbox, OneDrive ... (one folder each)
        if cloud.is_dir():
            folders += [d for d in sorted(cloud.iterdir())[:12] if d.is_dir()] + [d / "My Drive" for d in sorted(cloud.iterdir())[:12]]
        found = [folder / f"{stem}{suffix}" for folder in folders for suffix in SUPPORTED_SUFFIXES
                 if (folder / f"{stem}{suffix}").is_file()]
        return self._most_recently_used(found)

    def _most_recently_used(self, paths: list[pathlib.Path]) -> pathlib.Path | None:
        """The file among *paths* the user opened last (macOS records when each file was last opened, which is what
        "the one open in the program now" usually is); a file with no such record is ranked by its modified time."""
        def key(path: pathlib.Path) -> tuple[float, float]:
            used = 0.0
            if len(paths) > 1:
                text = self._run(["mdls", "-raw", "-name", "kMDItemLastUsedDate", str(path)]).strip()
                try:
                    used = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z").timestamp()
                except ValueError:
                    used = 0.0
            return used, path.stat().st_mtime
        return max(paths, key=key) if paths else None

    def documents(self, app, prefer: tuple[str, ...] = ()) -> list[tuple[pathlib.Path, str]]:
        """``(path, open sheet)`` of the documents *app* has open (the sheet is '' where the program does not say)."""
        if app.key == "numbers":
            out = self._numbers_list() if self._numbers_list is not None else self._run(["osascript", "-l", "JavaScript", "-e", _LIST_NUMBERS])
            found: list[tuple[pathlib.Path, str]] = []
            for line in (text.strip("\r\n") for text in out.splitlines() if text.strip()):
                parts = line.split("\t")
                name, path, sheet = (parts + ["", ""])[:3] if len(parts) > 1 else ("", parts[0], "")
                if path.strip():
                    found.append((pathlib.Path(path.strip()), sheet.strip()))
                elif name.strip():                                      # reported by name only: find the file
                    located = self.find_by_name(name.strip(), prefer)
                    if located is not None:
                        found.append((located, sheet.strip()))
            return found
        # Other programs: the files named on their command line, then the files the process holds open.
        out = self._run(["ps", "-axo", "command="])
        out = "\n".join(line for line in out.splitlines() if app.mac_process.lower() in line.lower())
        listed = files_named_in(out)
        if app.mac_process:
            # A file opened from inside a running program (File > Open, or a double-click handed to it) is never on its
            # command line, so ask which spreadsheet files the process holds open (lsof needs no permission for our own).
            have = {os.path.realpath(path) for path, _ in listed}
            for line in self._run(["lsof", "-nP", "-c", app.mac_process, "-Fn"]).splitlines():
                if line.startswith("n/") and line.lower().endswith(SUPPORTED_SUFFIXES):
                    path = pathlib.Path(line[1:])
                    if os.path.realpath(path) not in have:
                        have.add(os.path.realpath(path))
                        listed.append((path, ""))
        return listed


_LIST_NUMBERS = """
function run() {
  const app = Application("Numbers");
  if (!app.running()) return "";
  const documents = app.documents();
  let out = "";
  for (let i = 0; i < documents.length; i++) {
    let name = "", path = "", sheet = "";
    try { name = documents[i].name(); } catch (e) {}
    try { const file = documents[i].file(); if (file) path = String(file); } catch (e) {}
    try { sheet = documents[i].activeSheet().name(); } catch (e) {}
    out += name + "\\t" + path + "\\t" + sheet + "\\n";
  }
  return out;
}
"""

_LIST_NUMBERS_FOR_RELOAD = """
function run() {
  try {
    const app = Application("Numbers");
    if (!app.running()) return "";
    const documents = app.documents();
    let out = "";
    for (let i = 0; i < documents.length; i++) {
      let name = "", path = "", modified = "0";
      try { name = documents[i].name(); } catch (e) {}
      try { const file = documents[i].file(); if (file) path = String(file); } catch (e) {}
      try { if (documents[i].modified()) modified = "1"; } catch (e) {}
      out += name + "\\t" + path + "\\t" + modified + "\\t" + i + "\\n";
    }
    return out;
  } catch (e) {
    return "no";
  }
}
"""

_CLOSE_NUMBERS = """
function run(argv) {
  try {
    const app = Application("Numbers");
    const documents = app.documents();
    for (const position of argv) app.close(documents[Number(position)], {saving: "no"});
    return "ok";
  } catch (e) {
    return "no";
  }
}
"""


def _same_file(reported: str, target: pathlib.Path) -> bool:
    """Is the file Numbers reports (a path or a file URL) the one at *target*?"""
    text = reported[len("file://"):] if reported.startswith("file://") else reported
    try:
        return os.path.realpath(text) == os.path.realpath(target)
    except OSError:
        return text == str(target)
