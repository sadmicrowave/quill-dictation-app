"""Spreadsheet programs other than Excel: finding the file they have open, and reloading it."""
import pathlib
import tempfile
import unittest

import openpyxl

from quill.bridge import hosts
from quill.bridge.hosts import EXCEL, LIBREOFFICE, NUMBERS, SpreadsheetHosts


def make_file(directory, name="stock.xlsx"):
    path = pathlib.Path(directory) / name
    openpyxl.Workbook().save(path)
    return path


class FakeRunner:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, args):
        self.calls.append(args)
        for key, reply in self.replies.items():
            if key in " ".join(args):
                return reply
        return ""


class TestRunning(unittest.TestCase):
    def test_mac_lists_the_known_programs_that_are_running(self):
        runner = FakeRunner({"comm=": "/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder\n/Applications/Numbers.app/Contents/MacOS/Numbers\n"})
        found = SpreadsheetHosts("darwin", runner).running()
        self.assertEqual([a.key for a in found], ["numbers"])

    def test_excel_is_recognised_too(self):
        runner = FakeRunner({"comm=": "/Applications/Microsoft Excel.app/Contents/MacOS/Microsoft Excel\n/Applications/Numbers.app/Contents/MacOS/Numbers"})
        self.assertEqual([a.key for a in SpreadsheetHosts("darwin", runner).running()], ["excel", "numbers"])

    def test_windows_reads_the_task_list(self):
        runner = FakeRunner({"tasklist": '"EXCEL.EXE","1","Console"\n"soffice.exe","2","Console"'})
        self.assertEqual([a.key for a in SpreadsheetHosts("win32", runner).running()], ["excel", "libreoffice"])

    def test_other_systems_and_failures_find_nothing(self):
        self.assertEqual(SpreadsheetHosts("linux", FakeRunner({})).running(), [])
        self.assertEqual(SpreadsheetHosts("darwin", FakeRunner({})).running(), [])

    def test_the_environment_switch_silences_the_real_runner(self):
        self.assertEqual(hosts._run(["echo", "hi"]), "")


class TestOpenFiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = make_file(self.dir.name)

    def test_numbers_documents_are_read_from_its_script(self):
        runner = FakeRunner({"comm=": "/Applications/Numbers.app/Contents/MacOS/Numbers", "Numbers": f"{self.path}\n/gone/old.numbers\n"})
        found = SpreadsheetHosts("darwin", runner).open_excel_files()
        self.assertEqual(found, [(NUMBERS, self.path)])

    def test_files_named_on_a_command_line_are_found(self):
        line = f'/Applications/LibreOffice.app/Contents/MacOS/soffice --calc "{self.path}"'
        runner = FakeRunner({"comm=": "/Applications/LibreOffice.app/Contents/MacOS/soffice", "command=": line})
        found = SpreadsheetHosts("darwin", runner).open_excel_files()
        self.assertEqual(found, [(LIBREOFFICE, self.path)])

    def test_files_that_are_not_excel_files_or_do_not_exist_are_ignored(self):
        runner = FakeRunner({"comm=": "/Applications/Numbers.app/Contents/MacOS/Numbers", "Numbers": "/x/a.numbers\n/x/missing.xlsx\n"})
        self.assertEqual(SpreadsheetHosts("darwin", runner).open_excel_files(), [])

    def test_excel_itself_is_left_to_live_automation(self):
        runner = FakeRunner({"comm=": "/Applications/Microsoft Excel.app/Contents/MacOS/Microsoft Excel"})
        self.assertEqual(SpreadsheetHosts("darwin", runner).open_excel_files(), [])


class TestReload(unittest.TestCase):
    def test_numbers_is_asked_to_reload_the_saved_file(self):
        runner = FakeRunner({"osascript": "ok\n"})
        self.assertTrue(SpreadsheetHosts("darwin", runner).reload(NUMBERS, '/a/"b".xlsx'))
        self.assertIn('/a/\\"b\\".xlsx', runner.calls[0][-1])

    def test_a_failed_script_reports_false(self):
        self.assertFalse(SpreadsheetHosts("darwin", FakeRunner({"osascript": "no"})).reload(NUMBERS, "/a.xlsx"))

    def test_programs_that_cannot_be_asked_report_false_without_running_anything(self):
        runner = FakeRunner({})
        self.assertFalse(SpreadsheetHosts("darwin", runner).reload(LIBREOFFICE, "/a.xlsx"))
        self.assertFalse(SpreadsheetHosts("darwin", runner).reload(EXCEL, "/a.xlsx"))
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
