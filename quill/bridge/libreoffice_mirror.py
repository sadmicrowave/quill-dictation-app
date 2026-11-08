"""Live editing in LibreOffice Calc: the cells Quill writes to the file are also set in the open LibreOffice document.

Like the Numbers mirror (:mod:`quill.platforms.macos.numbers_mirror`), but LibreOffice has no AppleScript for cells and its own Python cannot be
used from outside (it is not allowed to run on a Mac without being opened once by hand). What every LibreOffice does
offer is: starting ``soffice`` with a script address while it is running hands the request to the running instance,
which runs the script inside itself. So Quill puts one small script in the user's LibreOffice profile, writes the cells
to a job file, and asks the running LibreOffice to run it; the script finds the document by its file address, sets the
cells and writes an answer file.

* The script is added to LibreOffice's *user* scripts folder (one file, ``quill_mirror_v<version>.py``, marked as Quill's; it is
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
import threading
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from quill import platforms
from quill.bridge.libreoffice_live import LiveLink
from quill.bridge.mirror import MirrorResult

from quill.bridge.processes import running_executables
from quill.diagnostics import exc_kind, syslog

log = logging.getLogger("quill.libreoffice")

SCRIPT_VERSION = 5
#: The helper's file name carries its version. A running LibreOffice keeps the helper it already loaded under a name, so a
#: newer helper under the same name would not be seen (the call fails with a scripting error box in LibreOffice); a new name is
#: always loaded fresh. Older Quill helpers are removed when the new one is put in place.
SCRIPT_PREFIX = "quill_mirror"
SCRIPT_NAME = f"{SCRIPT_PREFIX}_v{SCRIPT_VERSION}.py"
#: Seconds to wait for LibreOffice to run the script and answer.
ANSWER_TIMEOUT_S = 10
#: Fields of a change, as the script gets them: ``[sheet, row, column, kind, text]``.
Runner = Callable[[list[str]], int]

#: The script that runs inside LibreOffice. ``@BASE@`` is Quill's job folder, filled in when it is installed.
SCRIPT = r'''# Quill live-rows helper (version @VERSION@). Installed by Quill; it is safe to delete, Quill puts it back when needed.
import datetime
import hmac
import json
import os
import secrets
import socket
import sys
import threading
import time

BASE = @BASE@
VERSION = @VERSION@
WATCH_S = 0.3                    # how often the server looks at the open documents
IDLE_STOP_S = 600                # the server stops when no Quill has been connected for this long


def _answer(text):
    with open(os.path.join(BASE, "out.json"), "w", encoding="utf-8") as handle:
        handle.write(text)


def _spreadsheets(desktop):
    found = []
    listing = desktop.getComponents().createEnumeration()
    while listing.hasMoreElements():
        component = listing.nextElement()
        try:
            if component.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                found.append(component)
        except Exception:
            pass
    return found


def _find(desktop, urls):
    for component in _spreadsheets(desktop):
        if getattr(component, "URL", "") in urls:
            return component
    return None


def _describe(document):
    controller = document.getCurrentController()
    sheet = controller.getActiveSheet().Name if controller is not None else ""
    return {"url": document.URL, "sheet": sheet, "sheets": list(document.getSheets().getElementNames()),
            "modified": bool(document.isModified())}


def _apply_changes(document, changes):
    sheets = document.getSheets()
    date_key = None
    for sheet_name, row, column, kind, text in changes:
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


def apply():
    # One-off job (the way Quill talks to LibreOffice when no live link is up): job in in.json, answer in out.json.
    try:
        with open(os.path.join(BASE, "in.json"), encoding="utf-8") as handle:
            job = json.load(handle)
        document = _find(XSCRIPTCONTEXT.getDesktop(), job["urls"])
        if document is None:
            return _answer("nodoc")
        if job.get("save"):
            document.store()                          # saves in the file's own format (no "keep format" question)
            return _answer("ok")
        if job.get("sheet"):
            return _answer("sheet:" + document.getCurrentController().getActiveSheet().Name)
        if job.get("probe"):
            return _answer("ok")
        _apply_changes(document, job["changes"])
        _answer("ok")
    except Exception as exc:
        _answer("error " + repr(exc))


class _Server:
    # The live link: a small server inside this LibreOffice that Quill connects to. It answers a fixed set of commands
    # (state, sheet, save, apply, quit; nothing else is ever run) and tells Quill when a document opens, closes or
    # moves to another sheet. It listens on this computer only and wants a secret that only Quill's own folder holds.

    def __init__(self, desktop):
        self.desktop = desktop
        self.version = VERSION
        self.token = secrets.token_hex(16)
        self.lock = threading.Lock()                  # one thing at a time touches the documents
        self.clients = []
        self.clients_lock = threading.Lock()
        self.known = {}
        self.stopping = False
        self.last_client = time.time()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]

    def alive(self):
        return not self.stopping

    def start(self):
        os.makedirs(BASE, mode=0o700, exist_ok=True)
        path = os.path.join(BASE, "live.json")
        descriptor = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"port": self.port, "token": self.token, "version": VERSION, "pid": os.getpid()}, handle)
        os.replace(path + ".tmp", path)
        self.known = self._look()
        threading.Thread(target=self._accept, name="quill-live-accept", daemon=True).start()
        threading.Thread(target=self._watch, name="quill-live-watch", daemon=True).start()

    def stop(self):
        self.stopping = True
        try:
            self.sock.close()
        except Exception:
            pass
        try:
            os.remove(os.path.join(BASE, "live.json"))
        except OSError:
            pass
        with self.clients_lock:
            for client in list(self.clients):
                self._hang_up(client)
            self.clients = []

    def _look(self):
        found = {}
        with self.lock:
            for document in _spreadsheets(self.desktop):
                try:
                    if document.URL:
                        found[document.URL] = _describe(document)
                except Exception:
                    pass
        return found

    def _send(self, client, message):
        try:
            client.sendall((json.dumps(message) + "\n").encode("utf-8"))
            return True
        except Exception:
            return False

    def _tell(self, message):
        with self.clients_lock:
            clients = list(self.clients)
        for client in clients:
            if not self._send(client, message):
                self._drop(client)

    def _drop(self, client):
        with self.clients_lock:
            if client in self.clients:
                self.clients.remove(client)
        self._hang_up(client)

    def _hang_up(self, client):
        for action in (lambda: client.shutdown(socket.SHUT_RDWR), client.close):     # (shutdown: the reader's own handle would keep it open)
            try:
                action()
            except Exception:
                pass

    def _watch(self):
        while not self.stopping:
            time.sleep(WATCH_S)
            try:
                with self.clients_lock:
                    if self.clients:
                        self.last_client = time.time()
                if time.time() - self.last_client > IDLE_STOP_S:
                    return self.stop()
                now = self._look()
                for url, info in now.items():
                    before = self.known.get(url)
                    if before is None:
                        self._tell(dict(info, event="opened"))
                    elif before["sheet"] != info["sheet"] or before["sheets"] != info["sheets"]:
                        self._tell(dict(info, event="sheet"))
                for url in self.known:
                    if url not in now:
                        self._tell({"event": "closed", "url": url})
                self.known = now
            except Exception:
                pass

    def _accept(self):
        while not self.stopping:
            try:
                client, _ = self.sock.accept()
            except Exception:
                return
            threading.Thread(target=self._serve_client, args=(client,), name="quill-live-client", daemon=True).start()

    def _serve_client(self, client):
        try:
            client.settimeout(10)
            reader = client.makefile("r", encoding="utf-8", newline="\n")
            hello = json.loads(reader.readline() or "{}")
            if not hmac.compare_digest(str(hello.get("hello", "")), self.token):
                return client.close()
            client.settimeout(None)
            with self.clients_lock:
                self.clients.append(client)
            self._send(client, {"hello": "ok", "version": VERSION, "docs": list(self.known.values())})
            for line in reader:
                if self.stopping:
                    break
                try:
                    request = json.loads(line)
                    reply = self._handle(request)
                except Exception as exc:
                    request, reply = {}, {"ok": False, "error": repr(exc)}
                reply["id"] = request.get("id")
                if not self._send(client, reply):
                    break
        except Exception:
            pass
        finally:
            self._drop(client)

    def _handle(self, request):
        command = request.get("cmd")
        if command == "state":
            return {"ok": True, "docs": list(self._look().values())}
        if command == "quit":
            threading.Thread(target=self.stop, daemon=True).start()
            return {"ok": True}
        urls = request.get("urls") or []
        with self.lock:
            document = _find(self.desktop, urls)
            if document is None:
                return {"ok": False, "error": "nodoc"}
            if command == "sheet":
                return {"ok": True, "sheet": document.getCurrentController().getActiveSheet().Name}
            if command == "save":
                document.store()
                return {"ok": True}
            if command == "apply":
                _apply_changes(document, request.get("changes") or [])
                return {"ok": True}
        return {"ok": False, "error": "unknown command"}


def serve():
    # Start the live link (once per LibreOffice; a newer helper replaces an older one) and return.
    try:
        current = getattr(sys, "_quill_live", None)
        if current is not None and current.alive():
            if current.version >= VERSION:
                return _answer("ok")
            current.stop()
        server = _Server(XSCRIPTCONTEXT.getDesktop())
        server.start()
        sys._quill_live = server
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
    other = platforms.offered(platform, "libreoffice")
    if other is not None:
        return other.profile_scripts_dir(home)
    return home / ".config" / "libreoffice" / "4" / "user" / "Scripts" / "python"


def find_soffice(platform: str | None = None) -> str | None:
    """Where the ``soffice`` program is, if LibreOffice is installed."""
    platform = platform or sys.platform
    other = platforms.offered(platform, "libreoffice")
    if other is not None:
        return other.find_soffice()
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
    native = running_executables() if platform == sys.platform else None
    if native is not None:                                          # the system's own list: no process is started
        return bool(native & {"soffice", "soffice.bin"})
    try:
        other = platforms.offered(platform, "libreoffice")
        if other is not None and hasattr(other, "is_running"):
            return other.is_running()
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
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    """One job at a time: the job and answer files are shared, so a look and a write must not overlap."""
    on_event: Callable[[str, str, str], None] | None = None
    """Told ``(kind, url, sheet)`` when LibreOffice opens or closes a document or moves it to another sheet (live link only)."""
    use_live: bool = True
    """False: always the older way, one script launch per question (tests of that way)."""
    live_retry_s: float = 10.0
    """Seconds to wait before trying to bring the live link up again after it could not be."""
    _live: LiveLink | None = field(default=None, repr=False, compare=False)
    _live_next: float = field(default=0.0, repr=False, compare=False)
    _live_logged: bool = field(default=False, repr=False, compare=False)

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
            self._remove_older_helpers(folder)
            self.installed_note = True
            return True
        except OSError as exc:
            log.warning("could not install the LibreOffice script: %s", exc)
            syslog().warning("Could not install the LibreOffice script: %s", exc_kind(exc))
            return False

    @staticmethod
    def _remove_older_helpers(folder: pathlib.Path) -> None:
        """Delete Quill's helpers of other versions (only files that start with the marker line Quill writes)."""
        for old in folder.glob(f"{SCRIPT_PREFIX}*.py"):
            if old.name == SCRIPT_NAME:
                continue
            try:
                if old.read_text(encoding="utf-8").startswith("# Quill live-rows helper"):
                    old.unlink()
            except OSError:
                pass

    def has_document(self, path: str | os.PathLike) -> bool:
        """Does a running LibreOffice have *path* open? (Asked through the same script, which then changes nothing.)"""
        return self.push(path, [], probe=True).ok

    def save(self, path: str | os.PathLike) -> bool:
        """Ask the running LibreOffice to save the document for *path* in the file's own format (True if it did)."""
        return self.push(path, [], probe=True, save=True).ok

    def active_sheet(self, path: str | os.PathLike) -> str | None:
        """The name of the sheet open now in the LibreOffice document for *path* (None if it is not open or would not say)."""
        result = self.push(path, [], probe=True, want_sheet=True)
        return result.detail if result.ok and result.reason == "sheet" and result.detail else None

    def push(self, path: str | os.PathLike, changes: list[tuple[str, int, int, object]], probe: bool = False,
             want_sheet: bool = False, save: bool = False) -> MirrorResult:
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
        live = self._live_link(soffice)
        if live is not None:
            result = self._via_live(live, path, changes, probe, want_sheet, save)
            if result is not None:
                return result
        with self._lock:                                                          # (a look and a write never share the files)
            return self._job(soffice, path, changes, probe, want_sheet, save)

    # ------------------------------------------------------------------ #
    # The live link                                                        #
    # ------------------------------------------------------------------ #

    @property
    def live_connected(self) -> bool:
        """Is the live link up (LibreOffice tells Quill what happens in it)?"""
        return self._live is not None and self._live.connected

    def _live_link(self, soffice: str) -> LiveLink | None:
        """The live link, brought up if it is not (the helper's server is started in the running LibreOffice at most once
        every :attr:`live_retry_s` seconds); None when it cannot be."""
        if not self.use_live or os.environ.get("QUILL_NO_LIVE"):
            return None
        if self._live is None:
            self._live = LiveLink(self._dir(), on_event=self._told)
        link = self._live
        if link.connected and link.version >= SCRIPT_VERSION:
            return link
        if link.connected:                                                        # an older helper still runs: replace it
            link.ask_to_quit()
        if time.monotonic() < self._live_next:
            return None
        if not link.connect() or link.version < SCRIPT_VERSION:
            with self._lock:                                                      # (starting the server is a script call: one at a time)
                self._start_server(soffice)
            if not link.connect():
                self._live_next = time.monotonic() + self.live_retry_s
                syslog().info("The LibreOffice live link could not be started")
                return None
        if not self._live_logged:
            self._live_logged = True
            syslog().info("The LibreOffice live link is up")
        return link

    def _start_server(self, soffice: str) -> None:
        folder = self._dir()
        answer = folder / "out.json"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            answer.unlink(missing_ok=True)
        except OSError:
            return
        try:
            self._run_job(soffice, folder, answer, "serve")
        finally:
            answer.unlink(missing_ok=True)

    def _told(self, kind: str, url: str, sheet: str) -> None:
        if self.on_event is not None:
            self.on_event(kind, url, sheet)

    def _via_live(self, link: LiveLink, path, changes, probe: bool, want_sheet: bool, save: bool) -> MirrorResult | None:
        """The same questions, asked over the live link. None means "use the older way" (the link broke meanwhile)."""
        urls = file_addresses(path)
        doc = link.find(urls)
        if doc is None:
            return MirrorResult(False, "nodoc")
        if want_sheet:
            return MirrorResult(True, "sheet", doc.get("sheet") or "") if doc.get("sheet") else MirrorResult(False, "error", "no sheet")
        if save:
            answer = link.request("save", urls=urls)
        elif changes:
            answer = link.request("apply", urls=urls, changes=[change_fields(*c) for c in changes])
        else:
            return MirrorResult(True, "ok")                                       # (a probe: the document is open)
        if answer is None:
            return None
        if answer.get("ok"):
            return MirrorResult(True, "ok")
        return MirrorResult(False, "nodoc" if answer.get("error") == "nodoc" else "error", str(answer.get("error", "")))

    def _job(self, soffice: str, path: str | os.PathLike, job_changes: list, probe: bool, want_sheet: bool,
             save: bool = False) -> MirrorResult:
        folder = self._dir()
        temp = folder / "in.json.tmp"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            answer = folder / "out.json"
            answer.unlink(missing_ok=True)
            job = {"urls": file_addresses(path), "changes": [change_fields(*c) for c in job_changes],
                   "probe": probe, "sheet": want_sheet, "save": save}
            temp.write_text(json.dumps(job), encoding="utf-8")
            os.replace(temp, folder / "in.json")
        except OSError as exc:
            temp.unlink(missing_ok=True)
            return MirrorResult(False, "error", str(exc))
        try:
            return self._run_job(soffice, folder, answer)
        finally:
            for leftover in (folder / "in.json", answer):                         # the cells are not kept on disk
                leftover.unlink(missing_ok=True)

    def _run_job(self, soffice: str, folder: pathlib.Path, answer: pathlib.Path, entry: str = "apply") -> MirrorResult:
        address = f"vnd.sun.star.script:{SCRIPT_NAME}${entry}?language=Python&location=user"
        # "--headless": without it every call starts a second LibreOffice process that shows its own Dock icon for a moment
        # (once per look, so every few seconds). With it the request is still handed to the running LibreOffice, silently.
        code = (self.runner or _system)([soffice, "--headless", address])
        if code != 0:
            return MirrorResult(False, "error", f"soffice exited with {code}")
        deadline = time.monotonic() + self.wait_s
        while time.monotonic() < deadline:
            if answer.is_file():
                text = answer.read_text(encoding="utf-8").strip()
                if text == "ok":
                    return MirrorResult(True, "ok")
                if text.startswith("sheet:"):
                    return MirrorResult(True, "sheet", text[6:])
                if text == "nodoc":
                    return MirrorResult(False, "nodoc")
                return MirrorResult(False, "error", text)
            time.sleep(0.05)
        return MirrorResult(False, "error", "LibreOffice did not answer")
