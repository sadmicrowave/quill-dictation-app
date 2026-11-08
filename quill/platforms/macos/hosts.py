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
import sys

from quill.bridge.hosts import SUPPORTED_SUFFIXES, files_named_in
from quill.platforms.macos.processes import running_executables as _native_list
from quill.diagnostics import exc_kind, syslog

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

    def reload(self, app, path) -> bool:
        """Ask *app* (Numbers) to load *path* again after Quill saved it."""
        return bool(self._run(["osascript", "-l", "JavaScript", "-e", _RELOAD_NUMBERS, str(path)]).strip() == "ok")

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

_RELOAD_NUMBERS = """
function run(argv) {
  const target = argv[0];
  try {
    const app = Application("Numbers");
    const documents = app.documents();
    for (let i = 0; i < documents.length; i++) {
      try {
        const file = documents[i].file();
        if (file && String(file) === target && !documents[i].modified()) app.close(documents[i], {saving: "no"});
      } catch (e) {}
    }
    app.open(Path(target));
    return "ok";
  } catch (e) {
    return "no";
  }
}
"""
