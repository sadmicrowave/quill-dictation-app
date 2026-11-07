"""Finding and starting the spreadsheet programs on Windows (the provider is a stub: see quill/platforms/windows/hosts.py)."""
import pathlib
import tempfile
import unittest

from quill.bridge.hosts import LIBREOFFICE, SpreadsheetHosts
from tests.test_hosts import FakeRunner, make_file


class TestWindowsHosts(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = make_file(self.dir.name)

    def test_windows_reads_the_task_list(self):
        runner = FakeRunner({"tasklist": '"EXCEL.EXE","1","Console"\n"soffice.exe","2","Console"'})
        self.assertEqual([a.key for a in SpreadsheetHosts("win32", runner).running()], ["excel", "libreoffice"])

    def test_windows_still_reads_the_command_line_until_its_branch_is_built(self):
        runner = FakeRunner({"tasklist": '"soffice.exe","2","Console"', "wmic": f'soffice.exe --calc "{self.path}"'})
        found = SpreadsheetHosts("win32", runner).open_excel_files()
        self.assertEqual(found, [(LIBREOFFICE, self.path)])

    def test_only_macos_asks_spotlight(self):
        h = SpreadsheetHosts("win32", FakeRunner({}))
        self.assertIsNone(h.find_by_name("stock"))
