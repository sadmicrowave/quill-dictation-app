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


class TestNumbersDocumentsReportedByNameOnly(unittest.TestCase):
    """Numbers gives a document imported from an .xlsx no file: only its name, without the extension."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.numbers = {"comm=": "/Applications/Numbers.app/Contents/MacOS/Numbers"}

    def hosts(self, listing, spotlight=""):
        runner = FakeRunner({**self.numbers, "osascript": listing, "mdfind": spotlight})
        return SpreadsheetHosts("darwin", runner), runner

    def test_the_active_file_is_matched_by_name_without_asking_spotlight(self):
        path = make_file(self.dir.name, "Apparel Inventory.xlsx")
        h, runner = self.hosts("Apparel Inventory\t\n")
        files = h.open_files(prefer=(str(path),))
        self.assertEqual([(f.name, f.path, f.app) for f in files], [("Apparel Inventory.xlsx", str(path), "Numbers")])
        self.assertFalse(any("mdfind" in " ".join(c) for c in runner.calls))

    def test_another_file_is_found_with_spotlight_and_the_newest_copy_wins(self):
        old = make_file(self.dir.name, "stock.xlsx")
        new_dir = pathlib.Path(self.dir.name) / "newer"
        new_dir.mkdir()
        new = make_file(new_dir, "stock.xlsx")
        import os
        os.utime(old, (1_000_000_000, 1_000_000_000))
        h, runner = self.hosts("stock\t\n", f"{old}\n{new}\n")
        self.assertEqual([f.path for f in h.open_files()], [str(new)])
        self.assertTrue(any("kMDItemFSName == 'stock.xlsx'c" in " ".join(c) for c in runner.calls))

    def test_the_trash_and_programs_own_folders_are_never_used(self):
        trash = pathlib.Path(self.dir.name) / ".Trash"
        trash.mkdir()
        gone = make_file(trash, "stock.xlsx")
        cache = pathlib.Path(self.dir.name) / "Library" / "Caches" / "x"
        cache.mkdir(parents=True)
        cached = make_file(cache, "stock.xlsx")
        h, _ = self.hosts("stock\t\n", f"{gone}\n{cached}\n")
        self.assertEqual(h.open_files(), [])

    def test_a_cloud_drive_folder_is_fine(self):
        cloud = pathlib.Path(self.dir.name) / "Library" / "CloudStorage" / "GoogleDrive-x" / "My Drive"
        cloud.mkdir(parents=True)
        path = make_file(cloud, "stock.xlsx")
        h, _ = self.hosts("stock\t\n", f"{path}\n")
        self.assertEqual([f.path for f in h.open_files()], [str(path)])

    def test_a_name_that_is_found_is_remembered_and_a_name_that_is_not_is_skipped(self):
        path = make_file(self.dir.name, "stock.xlsx")
        calls = []

        def runner(args):
            calls.append(args)
            joined = " ".join(args)
            if "comm=" in joined:
                return self.numbers["comm="]
            if "osascript" in joined:
                return "stock\t\nmystery\t\n"
            if "mdfind" in joined:
                return f"{path}\n" if "'stock.xlsx'" in joined else ""
            return ""

        h = SpreadsheetHosts("darwin", runner)
        self.assertEqual([f.name for f in h.open_files()], ["stock.xlsx"])
        searched = [c[1] for c in calls if c[0] == "mdfind"]
        self.assertEqual(len(searched), 6)                                  # "stock" and "mystery", each in three file types
        h.open_files()
        again = [c[1] for c in calls if c[0] == "mdfind"][6:]
        self.assertEqual(len(again), 3)                                     # only "mystery" is looked for again
        self.assertTrue(all("mystery" in q for q in again))

    def test_a_document_edited_in_numbers_is_called_name_dot_numbers_and_still_matches(self):
        path = make_file(self.dir.name, "stock.xlsx")
        h, _ = self.hosts("stock.numbers\t\n")
        self.assertEqual([f.path for f in h.open_files(prefer=(str(path),))], [str(path)])

    def test_documents_with_a_path_still_work_and_the_old_one_line_format_too(self):
        path = make_file(self.dir.name)
        for listing in (f"stock\t{path}\n", f"{path}\n"):
            h, _ = self.hosts(listing)
            self.assertEqual([f.path for f in h.open_files()], [str(path)])

    def test_only_macos_asks_spotlight(self):
        h = SpreadsheetHosts("win32", FakeRunner({}))
        self.assertIsNone(h.find_by_name("stock"))


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
