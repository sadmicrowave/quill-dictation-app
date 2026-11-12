"""A self-check: asks the real system the questions Quill depends on and writes the answers to one text file.

    Quill.exe --selftest [--out FILE]        (or: python main.py --selftest)
    Quill.exe --selftest --send              also sends the report to the support relay, which opens an issue in the private repository

It starts no window, records no sound and changes nothing of the user's: it only reads, and writes into a temporary folder it removes.
The report is for sending to the developer when something does not work, instead of describing it. It holds versions, counts and
yes/no answers, never a file name, a sheet name, a word or a path under the user's name (the home folder is written ``~``).

The same checks run in the build on the GitHub runners (against the packaged ``Quill.exe``), so a broken download is found before anyone
gets it.
"""

from __future__ import annotations

import contextlib
import ctypes
import importlib
import locale
import os
import pathlib
import platform
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Callable

from quill import platforms

OK, WARN, FAIL, INFO, SKIP = "ok", "warn", "fail", "info", "skip"
LABELS = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL ", INFO: " info ", SKIP: " skip "}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str = ""


def private(text: str) -> str:
    """*text* with the user's home folder and user name written as ``~`` and ``<user>``."""
    text = str(text)
    home = str(pathlib.Path.home())
    for form in (home, home.replace("\\", "/")):
        text = text.replace(form, "~")
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    return text.replace(user, "<user>") if len(user) > 2 else text


# ---------------------------------------------------------------------------------------------------------------------------------------
# What each check asks. Each returns a list of Check and may raise: the runner turns a raise into a failure of that check.

def build() -> list[Check]:
    from quill import __version__
    try:
        commit = importlib.import_module("quill._build").BUILD
    except ImportError:
        commit = "not stamped (a build from source)"
    return [
        Check("Quill", INFO, f"{__version__}, build {commit}, {'packaged app' if getattr(sys, 'frozen', False) else 'from source'}"),
        Check("System", INFO, f"{platform.platform()}, {platform.machine()}, Python {platform.python_version()}"),
        Check("Text encoding", INFO, f"{locale.getpreferredencoding(False)} (files are read as UTF-8 first, then cp1252)"),
    ]


def libraries() -> list[Check]:
    found = []
    wanted = [("PySide6", True), ("openpyxl", True), ("vosk", True), ("sounddevice", True), ("platformdirs", False), ("xlwings", False)]
    if sys.platform == "win32":
        wanted += [("pyttsx3", True), ("win32com", True)]
    for module, needed in wanted:
        try:
            imported = importlib.import_module(module)
            found.append(Check(module, OK, str(getattr(imported, "__version__", "present"))))
        except Exception as exc:                                  # (an import can fail with more than ImportError: a missing DLL)
            found.append(Check(module, FAIL if needed else WARN, f"cannot be loaded ({type(exc).__name__}: {private(exc)})"))
    with contextlib.suppress(Exception):
        from PySide6 import QtCore
        found.append(Check("Qt", INFO, QtCore.qVersion()))
    return found


def microphone() -> list[Check]:
    import sounddevice
    inputs = [d for d in sounddevice.query_devices() if d.get("max_input_channels", 0) > 0]
    if not inputs:
        return [Check("Microphone", WARN, "no input device is listed")]
    try:
        sounddevice.query_devices(kind="input")
        default = "yes"
    except Exception:
        default = "none chosen"
    return [Check("Microphone", OK, f"{len(inputs)} input device(s); a default is set: {default} (names are left out: they can hold a person's name)")]


def speech_model() -> list[Check]:
    from quill.listener import model
    bundled = model.bundled_archive()
    user = model.user_model_dir()
    present = user.is_dir() and any(model.is_model_dir(p) for p in [user, *user.iterdir()] if p.is_dir())
    return [Check("Speech model", OK if (bundled or present) else WARN,
                  f"bundled archive: {'yes' if bundled else 'no'}; unpacked in the user's folder: {'yes' if present else 'no'}")]


def folders() -> list[Check]:
    from quill.config.settings import _config_dir
    from quill.diagnostics import log_dir
    out = []
    for name, folder in (("Settings folder", _config_dir()), ("Log folder", log_dir())):
        folder = pathlib.Path(folder)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=folder, prefix=".selfcheck-"):
                pass
            where = f"; inside the profile folder: {'yes' if _inside_profile(folder) else 'NO'}" if sys.platform == "win32" else ""
            out.append(Check(name, OK if _inside_profile(folder) or sys.platform != "win32" else WARN, f"{private(folder)} is writable{where}"))
        except OSError as exc:
            out.append(Check(name, FAIL, f"{private(folder)} cannot be written ({type(exc).__name__})"))
    return out


def _inside_profile(folder: pathlib.Path) -> bool:
    profile = pathlib.Path(os.environ.get("USERPROFILE") or pathlib.Path.home()).resolve()
    return profile in pathlib.Path(folder).resolve().parents


def programs() -> list[Check]:
    if os.environ.get("QUILL_NO_HOSTS"):
        return [Check("Spreadsheet programs", SKIP, "system lookups are switched off (QUILL_NO_HOSTS)")]
    from quill.bridge.hosts import SpreadsheetHosts
    hosts = SpreadsheetHosts()
    started = time.monotonic()
    running = hosts.running()
    took = time.monotonic() - started
    out = [Check("Spreadsheet programs running", INFO, ", ".join(a.name for a in running) or "none"),
           Check("Process list", OK if took < 3 else WARN, f"answered in {took:.2f} s"),
           Check("Installed", INFO, ", ".join(f"{p}: {'yes' if hosts.installed(p) else 'no'}" for p in ("excel", "libreoffice")))]
    started = time.monotonic()
    files = hosts.open_files(running=running)
    took = time.monotonic() - started
    out.append(Check("Open files found", OK if (took < 6 and hosts.last_look_complete) else WARN,
                     f"{len(files)} file(s) in {took:.2f} s{'' if hosts.last_look_complete else ' (a question could not be answered)'}"))
    return out


def workbook_round_trip() -> list[Check]:
    import openpyxl

    from quill.bridge.xlsx_bridge import XlsxBridge
    with tempfile.TemporaryDirectory(prefix="quill selfcheck é ") as folder:
        path = pathlib.Path(folder) / "Stock – août.xlsx"
        book = openpyxl.Workbook()
        book.active.title = "Stock"
        book.active.append(["Item", "Qty"])
        book.save(path)
        bridge = XlsxBridge(path)
        bridge.connect()
        bridge.append_row("Stock", {"Item": "Rosé", "Qty": 4})
        rows = list(openpyxl.load_workbook(path)["Stock"].values)
    ok = rows == [("Item", "Qty"), ("Rosé", 4)]
    return [Check("Write a row into a workbook (spaces and accents in the name)", OK if ok else FAIL, "the row is where it should be" if ok else f"found {rows}")]


def csv_round_trip() -> list[Check]:
    from quill.bridge.csv_bridge import CsvBridge
    raw = b"Item,Price\r\nCaf\xe9,\x80 5\r\n"                                      # what Excel on Windows writes for plain CSV
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / "plants.csv"
        path.write_bytes(raw)
        bridge = CsvBridge(path)
        bridge.connect()
        bridge.append_row("plants", {"Item": "Na\xefve"})
        after = path.read_bytes()
    ok = after == raw + b"Na\xefve,\r\n"
    return [Check("CSV saved by Excel on Windows keeps its encoding", OK if ok else FAIL, "yes" if ok else f"changed to {after!r}")]


GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL = 0x80000000, 0x1, 3, 0x80


class HeldLikeExcelHolds:
    """A file opened the way Excel opens a workbook: others may read it, nobody may write to it, rename it or delete it (Windows only)."""

    def __init__(self, path) -> None:
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)          # type: ignore[attr-defined]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                       wintypes.DWORD, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel = kernel
        self._handle = kernel.CreateFileW(str(path), GENERIC_READ, FILE_SHARE_READ, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        if self._handle in (None, wintypes.HANDLE(-1).value):
            raise OSError(ctypes.get_last_error(), "could not hold the file")

    def release(self) -> None:
        if self._handle is not None:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def held_file() -> list[Check]:
    if sys.platform != "win32":
        return [Check("A workbook another program holds", SKIP, "Windows only")]
    import openpyxl

    from quill.bridge.base import BridgeLockedError
    from quill.bridge.xlsx_bridge import XlsxBridge
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / "Stock.xlsx"
        book = openpyxl.Workbook()
        book.active.title = "Stock"
        book.active.append(["Item"])
        book.save(path)
        bridge = XlsxBridge(path)
        bridge.connect()
        held = HeldLikeExcelHolds(path)
        try:
            try:
                bridge.append_row("Stock", {"Item": "Palm"})
                refused = False
            except BridgeLockedError:
                refused = True
        finally:
            held.release()
        saved = bridge.flush() if refused else False
        rows = [r[0] for r in openpyxl.load_workbook(path)["Stock"].values]
    ok = refused and saved and rows == ["Item", "Palm"]
    return [Check("A workbook another program holds", OK if ok else FAIL,
                  "the row waited and was saved when the file was free" if ok else f"refused: {refused}, saved after: {saved}, rows: {rows}")]


def command_line_lookup() -> list[Check]:
    if sys.platform != "win32" or os.environ.get("QUILL_NO_HOSTS"):
        return [Check("Which file a program was started with", SKIP, "Windows only, with system lookups on")]
    import subprocess

    from quill.bridge import hosts
    from quill.platforms.windows import hosts as winhosts
    with tempfile.TemporaryDirectory(prefix="quill selfcheck é ") as folder:
        path = pathlib.Path(folder) / "Bilan – août.xlsx"
        path.write_bytes(b"")
        script = pathlib.Path(folder) / "wait.ps1"
        script.write_text("Start-Sleep -Seconds 40\n", encoding="utf-8")
        # (a stand-in program that has the file on its command line; not Python: inside the packaged app sys.executable is Quill.exe)
        child = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), str(path)],   # noqa: S603, S607
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **platforms.no_console())
        text, took = "", 0.0
        try:
            for _ in range(8):                                                 # (a slow machine needs a moment for the child to appear)
                started = time.monotonic()
                text = winhosts.command_lines("powershell.exe", lambda args: hosts._run(args))
                took = time.monotonic() - started
                if str(path) in text:
                    break
                time.sleep(1)
        finally:
            child.kill()
            child.wait()
    ok = str(path) in text
    return [Check("Which file a program was started with (PowerShell)", (OK if took < 6 else WARN) if ok else FAIL,
                  f"{'found, accents intact' if ok else 'NOT found'}; one question took {took:.2f} s (Quill asks again only when the programs change)")]


def long_paths() -> list[Check]:
    """Can this program use a folder whose path is longer than 260 characters? Windows says no until its long-paths setting is on (the default on a new
    PC is off), and a program has to be built to use it: this tries it, as this program."""
    if sys.platform != "win32":
        return [Check("Long file paths", SKIP, "Windows only")]
    with tempfile.TemporaryDirectory(prefix="quill-long-") as base:
        folder = pathlib.Path(base)
        while len(str(folder / "Stock list.xlsx")) < 280:
            folder = folder / f"level {len(folder.parts)} with a long folder name"
        try:
            folder.mkdir(parents=True)
            (folder / "probe.txt").write_text("ok", encoding="utf-8")
            works, why = True, ""
        except OSError as exc:
            works, why = False, type(exc).__name__
    return [Check("Long file paths (over 260 characters)", OK if works else INFO,
                  "work" if works else f"do not work on this PC ({why}; Windows' default): Quill works in folders with shorter paths")]


def excel_live() -> list[Check]:
    if sys.platform != "win32":
        return [Check("Live Excel", SKIP, "Windows only")]
    try:
        import xlwings
        count = len(xlwings.apps)
    except Exception as exc:
        return [Check("Live Excel", INFO, f"not reachable ({type(exc).__name__}): fine when Excel is not installed")]
    return [Check("Live Excel", INFO, f"{count} Excel instance(s) running")]


def window_look() -> list[Check]:
    if sys.platform != "win32":
        return [Check("Windows title bar look", SKIP, "Windows only")]
    from quill.platforms.windows import chrome
    build = sys.getwindowsversion().build                              # type: ignore[attr-defined]
    return [Check("Windows title bar look", OK if chrome._dwm_setter() is not None else WARN,
                  f"Windows build {build}; {'colours and rounded corners need build 22000 or later' if build < 22000 else 'all attributes available'}")]


CHECKS: list[tuple[str, Callable[[], list[Check]]]] = [
    ("build", build), ("libraries", libraries), ("microphone", microphone), ("speech model", speech_model), ("folders", folders),
    ("programs", programs), ("command lines", command_line_lookup), ("excel", excel_live), ("window look", window_look),
    ("workbook", workbook_round_trip), ("csv", csv_round_trip), ("held file", held_file), ("long paths", long_paths),
]


def run_checks(checks=None) -> list[Check]:
    """Every check, in order. A check that raises becomes one failed line; the rest still run."""
    results: list[Check] = []
    for name, check in checks or CHECKS:
        try:
            results.extend(check())
        except Exception as exc:
            results.append(Check(name, FAIL, f"the check itself failed: {type(exc).__name__}: {private(exc)}"))
    return results


def report(results: list[Check]) -> str:
    counts = {status: sum(1 for r in results if r.status == status) for status in (OK, WARN, FAIL)}
    lines = ["Quill self-check", time.strftime("%Y-%m-%d %H:%M:%S"),
             f"Result: {counts[OK]} ok, {counts[WARN]} to look at, {counts[FAIL]} failed", ""]
    lines += [f"[{LABELS[r.status]}] {r.name}" + (f": {private(r.detail)}" if r.detail else "") for r in results]
    lines += ["", "Send this file to the developer. It holds versions, counts and yes/no answers: no file names, words or sheet names."]
    return "\n".join(lines) + "\n"


#: The first line of the issue (the relay makes it the title): easy to search for, nothing personal.
TITLE = "Self-check"


def message(results: list[Check], limit: int = 3800) -> str:
    """The report as the message of a support report: a title line, then the report, shortened (``info`` lines first) to fit *limit*."""
    counts = {status: sum(1 for r in results if r.status == status) for status in (OK, WARN, FAIL)}
    system = platform.system() + (f" build {sys.getwindowsversion().build}" if sys.platform == "win32" else "")      # type: ignore[attr-defined]
    head = f"{TITLE}: {system}, {counts[OK]} ok, {counts[WARN]} to look at, {counts[FAIL]} failed"
    for kept in (results, [r for r in results if r.status != INFO], [r for r in results if r.status in (WARN, FAIL)]):
        text = f"{head}\n\n{report(kept)}"
        if len(text) <= limit:
            return text
    return text[:limit]


def send(results: list[Check], sender: Callable | None = None):
    """Send the report to the support relay (it opens an issue in the private reports repository). Returns a ``support.SendResult``."""
    from quill import support
    payload = support.Report(message=message(results), include_log=True).payload()
    return (sender or support.send)(payload)


def show(text: str) -> None:
    """Tell the person the outcome where there is no console: a message box on Windows, a dialog on a Mac."""
    with contextlib.suppress(Exception):
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, text, "Quill self-check", 0x40)           # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["osascript", "-e", "on run argv", "-e", "display dialog (item 1 of argv) with title \"Quill self-check\" buttons {\"OK\"}",     # noqa: S603, S607
                            "-e", "end run", text], timeout=120, check=False, capture_output=True, **platforms.no_console())


def default_path() -> pathlib.Path:
    desktop = pathlib.Path.home() / "Desktop"
    return (desktop if desktop.is_dir() else pathlib.Path.home()) / "Quill self-check.txt"


def main(out: str | None = None, send_report: bool = False, sender: Callable | None = None, notify: Callable[[str], None] | None = None) -> int:
    """Run the checks, write the report (to *out*, else the Desktop, and open it there), print it where there is a console. With
    *send_report* it is also sent to the support relay and the outcome shown. 0 when nothing failed, 1 when a check failed, 2 when only
    the sending failed."""
    results = run_checks()
    text = report(results)
    target = pathlib.Path(out) if out else default_path()
    target.write_text(text, encoding="utf-8")
    if sys.stdout is not None:                                         # (a packaged app without a console has none)
        with contextlib.suppress(Exception):
            print(text)
            print(f"Written to {private(target)}")
    failed = any(r.status == FAIL for r in results)
    if send_report:
        sent = send(results, sender)
        outcome = (f"The report was sent{(' as issue ' + sent.reference) if sent.reference else ''}." if sent.ok else f"The report was NOT sent: {sent.error}")
        outcome += f"\n\n{sum(1 for r in results if r.status == FAIL)} check(s) failed. A copy is in {private(target)}."
        if sys.stdout is not None:
            print(outcome)
        (notify or show)(outcome)
        return 1 if failed else (0 if sent.ok else 2)
    if not out:
        with contextlib.suppress(Exception):
            from quill import platforms
            opener = platforms.offered(sys.platform, "open_file")
            if opener is not None:
                opener(str(target))
    return 1 if failed else 0
