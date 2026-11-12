"""LibreOffice on this machine. Run by the VM job runner (``libreoffice`` job). Needs LibreOffice installed (``winget install TheDocumentFoundation.LibreOffice``);
without it every check is skipped. It works whether or not LibreOffice is already running (a second launch is then handed to the running program, which is
exactly the case that has no command line).

It checks that Quill finds a file LibreOffice has open (accents, an en dash, spaces and brackets in its name) from the process's command line or, when the file
was handed to a running LibreOffice, from its window title; that a second file added to the running program is found too; that a row is written to the file
while LibreOffice holds it; and that nothing of this journey is left open.

Not covered yet: reading the open document's cells back through LibreOffice's own interface to prove the live link wrote them.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time

from common import Report, parse, scratch_folder, start_qt

NO_WINDOW = 0x08000000


def main(argv=None) -> int:
    args = parse(__doc__, argv)
    app = start_qt(args.offscreen)
    report = Report(args.out, args.offscreen)

    if sys.platform != "win32":                                          # (its window titles, command lines and flags are the Windows ones)
        report.skip("LibreOffice on this machine", "this journey is for Windows")
        print("not Windows: nothing to check")
        return 0

    import ctypes
    from ctypes import wintypes
    import datetime as dt
    import openpyxl

    from quill import platforms
    from quill.bridge import hosts as hosts_module
    from quill.bridge.hosts import SpreadsheetHosts
    from quill.bridge.xlsx_bridge import XlsxBridge
    from quill.config.settings import Settings
    from quill.controller import Controller
    from quill.platforms.windows import hosts as winhosts
    from tests.fixtures import make_workbook
    from tests.test_app import FakeSpeaker

    other = platforms.offered(None, "libreoffice")
    soffice = other.find_soffice() if other is not None and hasattr(other, "find_soffice") else None
    if soffice is None:
        report.skip("LibreOffice is installed", "soffice was not found (winget install TheDocumentFoundation.LibreOffice)")
        print("LibreOffice is not installed: nothing to check")
        return 0
    report.check("LibreOffice is installed", True, soffice)

    def soffice_running() -> bool:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=30, check=False,       # noqa: S603, S607
                             creationflags=NO_WINDOW).stdout.lower()
        return '"soffice.exe"' in out or '"soffice.bin"' in out

    def command_lines() -> str:
        found = []
        for name in ("soffice.exe", "soffice.bin"):
            try:
                found.append(f"{name}: {winhosts.command_lines(name, lambda a: hosts_module._run(a))!r}"[:500])
            except Exception as exc:                                    # noqa: BLE001
                found.append(f"{name}: (could not ask: {type(exc).__name__})")
        return " | ".join(found)

    def titles() -> list[str]:
        return [title for _, title in winhosts.enumerate_windows() if "LibreOffice" in title]

    def close_windows(names: list[str]) -> None:
        """Ask LibreOffice to close the windows of the documents this journey opened (the rest of the program, and the user's own documents, stay)."""
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def each(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
                user32.GetWindowTextW(hwnd, title, len(title))
                if "LibreOffice Calc" in title.value and any(title.value.startswith(n) for n in names):
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)               # WM_CLOSE
            return True
        user32.EnumWindows(callback_type(each), 0)

    folder = scratch_folder("quill-vm-lo-")
    first = make_workbook(folder / "Bilan été – août 2026 (copie).xlsx")                  # (accents, an en dash, spaces and brackets)
    second = make_workbook(folder / "Stock list & more (1).xlsx")
    profile = folder / "lo-profile"
    already = soffice_running()
    report.check("LibreOffice was already running", True, f"{already}: " + ("the files are handed to it" if already else "a new instance is started"))

    def open_in_libreoffice(path: pathlib.Path) -> None:
        extra = [] if already else [f"-env:UserInstallation={profile.as_uri()}"]
        subprocess.Popen([soffice, *extra, "--calc", "--norestart", "--nologo", str(path)], creationflags=NO_WINDOW)          # noqa: S603

    def wait_for(path: pathlib.Path, limit: float = 90.0) -> float | None:
        """Seconds until Quill lists *path* as open (the active file is *path*), or None."""
        hosts = SpreadsheetHosts()
        started = time.monotonic()
        while time.monotonic() - started < limit:
            if any(pathlib.Path(f.path).name == path.name for f in hosts.open_files(prefer=(str(path),))):
                return time.monotonic() - started
            time.sleep(2)
        return None

    try:
        open_in_libreoffice(first)
        took = wait_for(first)
        report.check("Quill sees the first file LibreOffice has open (accents and spaces in its name)", took is not None,
                     f"after {took:.1f} s" if took is not None else f"not found in 90 s; windows: {titles()}; {command_lines()}")

        open_in_libreoffice(second)
        took = wait_for(second)
        report.check("Quill sees a second file added to the running LibreOffice (found by its window title)", took is not None,
                     f"after {took:.1f} s" if took is not None else f"not found in 90 s; windows: {titles()}; {command_lines()}")

        hosts = SpreadsheetHosts()
        names = {pathlib.Path(f.path).name for f in hosts.open_files(prefer=(str(first), str(second)))}
        report.check("both files are listed together", {first.name, second.name} <= names, str(sorted(names)))
        report.check("LibreOffice is listed as running", any(a.key == "libreoffice" for a in hosts.running()))

        events: list = []
        controller = Controller(XlsxBridge(first), Settings.load(folder / "cfg"), FakeSpeaker(), on_event=events.append, today=lambda: dt.date(2026, 10, 30))
        controller.connect()
        for phrase in ("start listening", "fern small bright price twelve dollars", "next row"):
            controller.handle_transcript(phrase)
        row = [openpyxl.load_workbook(first)["Inventory"].cell(4, c).value for c in (1, 2, 3, 5)]
        report.check("a row is written to the file while LibreOffice holds it", row == ["Fern", "Small", "Bright", 12.0],
                     f"{row}; events: {[e.kind for e in events][-4:]}")
        report.check("LibreOffice is still running afterwards", soffice_running(), command_lines())
        report.skip("the row shows in the open LibreOffice document", "reading the open document back is not built yet")
    finally:
        close_windows([first.stem, second.stem])
        time.sleep(3)
        if not already:                                                  # (our own instance: end it; a user's is left alone)
            subprocess.run(["taskkill", "/F", "/T", "/IM", "soffice.exe"], capture_output=True, timeout=30, check=False, creationflags=NO_WINDOW)       # noqa: S603, S607
            subprocess.run(["taskkill", "/F", "/T", "/IM", "soffice.bin"], capture_output=True, timeout=30, check=False, creationflags=NO_WINDOW)       # noqa: S603, S607
    left = [t for t in titles() if first.stem in t or second.stem in t]
    report.check("nothing of this journey is left open in LibreOffice", not left, str(left))
    failed = [c for c in report.checks if not c["ok"]]
    print(f"{len(report.checks) - len(failed)} of {len(report.checks)} checks held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
