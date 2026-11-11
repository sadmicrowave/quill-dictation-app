"""What a real Windows does (these run on a Windows machine only: the GitHub ``windows-2025`` runner runs them on every push).

The tests beside this one fake the system's answers. These ask the real ``tasklist``, the real PowerShell, a real child process and a
real file that another program holds, because the fakes can only repeat what we believe Windows says.
"""
import ctypes
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import openpyxl

from quill.bridge import hosts as hosts_module
from quill.bridge.base import BridgeLockedError
from quill.bridge.hosts import LIBREOFFICE, SpreadsheetHosts
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.platforms.windows import hosts as winhosts

ON_WINDOWS = sys.platform == "win32"
IMAGE = os.path.basename(sys.executable)                          # ("python.exe": the program every test below starts)


def real_commands():
    env = mock.patch.dict(os.environ)
    env.start()
    os.environ.pop("QUILL_NO_HOSTS", None)                         # (CI sets it so that no test asks the system by accident)
    return env


@unittest.skipUnless(ON_WINDOWS, "asks a real Windows")
class TestTheRealTaskList(unittest.TestCase):
    def setUp(self):
        self.addCleanup(real_commands().stop)

    def test_tasklist_answers_in_the_csv_form_the_provider_reads(self):
        out = hosts_module._run(["tasklist", "/fo", "csv", "/nh"])
        self.assertIn(f'"{IMAGE.lower()}"', out.lower())            # this very test run is a python process
        first = out.splitlines()[0]
        self.assertTrue(first.startswith('"') and first.count('","') >= 3, first)

    def test_a_program_that_is_running_is_found_and_one_that_is_not_is_not(self):
        with mock.patch.dict(winhosts.PROCESS_NAMES, {"libreoffice": IMAGE, "excel": "no-such-program-quill.exe"}):
            keys = [a.key for a in SpreadsheetHosts().running()]
        self.assertIn("libreoffice", keys)
        self.assertNotIn("excel", keys)


@unittest.skipUnless(ON_WINDOWS, "asks a real Windows")
class TestTheRealCommandLine(unittest.TestCase):
    """A real child process started with a spreadsheet's name on its command line, then asked about the way Quill asks."""

    def setUp(self):
        self.addCleanup(real_commands().stop)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        folder = pathlib.Path(self.dir.name) / "Mes classeurs été"
        folder.mkdir()
        self.path = folder / "Stock list & more (1).xlsx"
        openpyxl.Workbook().save(self.path)
        self.child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", str(self.path)])   # noqa: S603
        self.addCleanup(self.child.wait)
        self.addCleanup(self.child.kill)
        time.sleep(0.5)

    def test_the_file_a_program_was_started_with_is_found_through_powershell(self):
        with mock.patch.dict(winhosts.PROCESS_NAMES, {"libreoffice": IMAGE}):
            started = time.monotonic()
            text = winhosts.command_lines(IMAGE, lambda args: hosts_module._run(args))
            took = time.monotonic() - started
            found = winhosts.documents(LIBREOFFICE, lambda args: hosts_module._run(args))
        self.assertIn(str(self.path), text)
        self.assertIn(self.path, [path for path, _ in found])
        self.assertLess(took, hosts_module.COMMAND_TIMEOUT_S, "PowerShell is too slow to ask on every look")
        print(f"\nPowerShell command-line question took {took:.2f} s")

    def test_the_whole_look_lists_it_for_the_side_panel(self):
        with mock.patch.dict(winhosts.PROCESS_NAMES, {"libreoffice": IMAGE}):
            hosts = SpreadsheetHosts()
            files = hosts.open_files()
        self.assertIn((self.path.name, str(self.path)), [(f.name, f.path) for f in files])
        self.assertTrue(hosts.last_look_complete)

    def test_wmic_is_not_needed(self):
        """Windows 11 24H2 and Windows Server 2025 no longer start with ``wmic``: the question must not depend on it."""
        calls = []

        def run(args):
            calls.append(args[0])
            return "" if args[0] == "wmic" else hosts_module._run(args)
        with mock.patch.dict(winhosts.PROCESS_NAMES, {"libreoffice": IMAGE}):
            found = winhosts.documents(LIBREOFFICE, run)
        self.assertIn(self.path, [path for path, _ in found])
        self.assertNotIn("wmic", calls)


@unittest.skipUnless(ON_WINDOWS, "asks a real Windows")
class TestACommandThatTakesTooLong(unittest.TestCase):
    """Windows counterpart of ``test_the_child_is_gone_and_the_failure_is_reported`` (which needs ``os.kill``)."""

    def setUp(self):
        self.addCleanup(real_commands().stop)

    @staticmethod
    def alive(pid):
        out = subprocess.run(["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"], capture_output=True, text=True, check=False).stdout   # noqa: S603, S607
        return f'"{pid}"' in out

    def test_the_child_is_gone_and_the_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            pid_file = pathlib.Path(folder) / "pid"
            script = f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
            failed = []
            with mock.patch.object(hosts_module, "COMMAND_TIMEOUT_S", 1.0):
                started = time.monotonic()
                out = hosts_module._run([sys.executable, "-c", script], failed)
            self.assertEqual(out, "")
            self.assertLess(time.monotonic() - started, 5)
            self.assertEqual(len(failed), 1)
            pid = int(pid_file.read_text())
            for _ in range(20):
                if not self.alive(pid):
                    break
                time.sleep(0.25)
            self.assertFalse(self.alive(pid))

    def test_a_program_that_does_not_exist_is_a_failure_not_a_crash(self):
        failed = []
        self.assertEqual(hosts_module._run([r"C:\no\such\program-xyz.exe"], failed), "")
        self.assertEqual(len(failed), 1)


# ---- a file another program holds ----------------------------------------------------------------------------------------------------

GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL = 0x80000000, 0x1, 3, 0x80


class HeldLikeExcelHolds:
    """The file opened the way Excel opens a workbook: others may read it, nobody may write to it, rename it or delete it."""

    def __init__(self, path):
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                       wintypes.DWORD, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel = kernel
        self._handle = kernel.CreateFileW(str(path), GENERIC_READ, FILE_SHARE_READ, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        if self._handle in (None, wintypes.HANDLE(-1).value):
            raise OSError(ctypes.get_last_error(), "could not hold the file")

    def release(self):
        if self._handle is not None:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def make_stock(path):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Stock"
    sheet.append(["Item", "Qty"])
    sheet.append(["Fern", 3])
    book.save(path)
    return path


@unittest.skipUnless(ON_WINDOWS, "needs Windows' file sharing rules")
class TestAFileExcelHolds(unittest.TestCase):
    """Windows refuses a write to a workbook Excel has open (a Mac does not). Quill must keep the row and save it when the file is free,
    and never leave the file half written or a temporary file beside it."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = make_stock(pathlib.Path(self.dir.name) / "Stock.xlsx")
        self.bridge = XlsxBridge(self.path)
        self.bridge.connect()
        self.held = HeldLikeExcelHolds(self.path)
        self.addCleanup(self.held.release)

    def test_a_held_file_refuses_a_write_and_the_row_waits(self):
        before = self.path.read_bytes()
        with self.assertRaises(BridgeLockedError):
            self.bridge.append_row("Stock", {"Item": "Palm", "Qty": 7})
        self.assertTrue(self.bridge.dirty)
        self.assertEqual(self.path.read_bytes(), before)                                   # untouched
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["Stock.xlsx"])     # no temporary file left

    def test_the_waiting_row_is_saved_when_the_file_is_free(self):
        with self.assertRaises(BridgeLockedError):
            self.bridge.append_row("Stock", {"Item": "Palm", "Qty": 7})
        self.assertFalse(self.bridge.flush())                                              # still held
        self.held.release()
        self.assertTrue(self.bridge.flush())
        rows = list(openpyxl.load_workbook(self.path)["Stock"].values)
        self.assertEqual(rows, [("Item", "Qty"), ("Fern", 3), ("Palm", 7)])

    def test_a_held_file_can_still_be_read(self):
        bridge = XlsxBridge(self.path)
        bridge.connect()                                                                   # (opening for reading is allowed)
        self.assertEqual(list(openpyxl.load_workbook(self.path)["Stock"].values)[0], ("Item", "Qty"))

    def test_two_rows_that_waited_are_both_saved_in_order(self):
        for item in ("Palm", "Aloe"):
            with self.assertRaises(BridgeLockedError):
                self.bridge.append_row("Stock", {"Item": item, "Qty": 1})
        self.held.release()
        self.assertTrue(self.bridge.flush())
        items = [row[0] for row in openpyxl.load_workbook(self.path)["Stock"].values]
        self.assertEqual(items, ["Item", "Fern", "Palm", "Aloe"])

