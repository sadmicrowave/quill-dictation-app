"""LibreOffice on this machine: Quill finds a file that LibreOffice has open (through the command line of the real process, with an accented and
spaced file name), writes a row into it while LibreOffice holds it, and the program is still running afterwards. Run by the VM job runner
(``libreoffice`` job). Needs LibreOffice installed (``winget install TheDocumentFoundation.LibreOffice``); without it every check is skipped.

Not covered yet: reading the open document's cells back through LibreOffice's own interface to prove the live link wrote them.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time

from common import Report, parse, scratch_folder, start_qt, wait


def main(argv=None) -> int:
    args = parse(__doc__, argv)
    app = start_qt(args.offscreen)
    report = Report(args.out, args.offscreen)

    from quill import platforms
    from quill.bridge.hosts import SpreadsheetHosts
    from quill.bridge.xlsx_bridge import XlsxBridge
    from quill.config.settings import Settings
    from quill.controller import Controller
    from tests.fixtures import make_workbook
    from tests.test_app import FakeSpeaker
    import openpyxl

    if sys.platform != "win32":                                          # (its command-line lookup, file names and flags are the Windows ones)
        report.skip("LibreOffice on this machine", "this journey is for Windows")
        print("not Windows: nothing to check")
        return 0
    other = platforms.offered(None, "libreoffice")
    soffice = other.find_soffice() if other is not None and hasattr(other, "find_soffice") else None
    if soffice is None:
        report.skip("LibreOffice is installed", "soffice was not found (winget install TheDocumentFoundation.LibreOffice)")
        print("LibreOffice is not installed: nothing to check")
        return 0
    report.check("LibreOffice is installed", True, soffice)

    folder = scratch_folder("quill-vm-lo-")
    path = make_workbook(folder / "Bilan été – août 2026 (copie).xlsx")                  # (accents, an en dash, spaces and brackets)
    profile = folder / "lo-profile"
    process = subprocess.Popen([soffice, f"-env:UserInstallation={profile.as_uri()}", "--calc", "--norestart", "--nologo", "--nodefault", str(path)],
                               creationflags=0x08000000 if sys.platform == "win32" else 0)       # noqa: S603
    hosts = SpreadsheetHosts()
    try:
        started = time.monotonic()
        found = False
        while time.monotonic() - started < 90:
            time.sleep(2)
            files = hosts.open_files()
            if any(pathlib.Path(f.path).name == path.name for f in files):
                found = True
                break
        report.check("Quill sees the file LibreOffice has open (accents and spaces in its name)", found,
                     f"after {time.monotonic() - started:.1f} s" if found else f"not found in 90 s; open files: {[f.name for f in hosts.open_files()]}")
        report.check("LibreOffice is listed as running", any(a.key == "libreoffice" for a in hosts.running()))

        events: list = []
        controller = Controller(XlsxBridge(path), Settings.load(folder / "cfg"), FakeSpeaker(), on_event=events.append, today=lambda: __import__("datetime").date(2026, 10, 30))
        controller.connect()
        for phrase in ("start listening", "fern small bright price twelve dollars", "next row"):
            controller.handle_transcript(phrase)
        row = [openpyxl.load_workbook(path)["Inventory"].cell(4, c).value for c in (1, 2, 3, 5)]
        report.check("a row is written to the file while LibreOffice holds it", row == ["Fern", "Small", "Bright", 12.0], f"{row}; events: {[e.kind for e in events][-4:]}")
        report.check("LibreOffice is still running afterwards", process.poll() is None)
        report.skip("the row shows in the open LibreOffice document", "reading the open document back is not built yet")
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=30, check=False,       # noqa: S603, S607
                       creationflags=0x08000000) if sys.platform == "win32" else process.terminate()
    failed = [c for c in report.checks if not c["ok"]]
    print(f"{len(report.checks) - len(failed)} of {len(report.checks)} checks held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
