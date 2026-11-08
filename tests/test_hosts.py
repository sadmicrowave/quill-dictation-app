"""Spreadsheet programs other than Excel: finding the file they have open, and reloading it."""
import pathlib
import tempfile
import sys
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

    @unittest.skipIf(sys.platform == "win32", "these fake a Mac's output (POSIX paths); the Windows provider has its own tests")

    def test_a_file_opened_inside_a_running_libreoffice_is_found_from_its_open_files(self):
        runner = FakeRunner({"comm=": "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                             "command=": "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                             "lsof": f"p1\nn/System/Library/Fonts/a.ttc\nn{self.path}\n"})
        found = SpreadsheetHosts("darwin", runner).open_excel_files()
        self.assertEqual(found, [(LIBREOFFICE, self.path)])

    def test_a_libreoffice_file_on_the_command_line_and_in_lsof_is_listed_once(self):
        line = f'/Applications/LibreOffice.app/Contents/MacOS/soffice --calc "{self.path}"'
        runner = FakeRunner({"comm=": "/Applications/LibreOffice.app/Contents/MacOS/soffice", "command=": line, "lsof": f"n{self.path}\n"})
        self.assertEqual(SpreadsheetHosts("darwin", runner).open_excel_files(), [(LIBREOFFICE, self.path)])

    @unittest.skipIf(sys.platform == "win32", "these fake a Mac's output (POSIX paths); the Windows provider has its own tests")

    def test_a_file_opened_inside_a_running_wps_is_found_the_same_way(self):
        runner = FakeRunner({"comm=": "/Applications/wpsoffice.app/Contents/MacOS/wpsoffice",
                             "command=": "/Applications/wpsoffice.app/Contents/MacOS/wpsoffice", "lsof": f"n{self.path}\n"})
        found = SpreadsheetHosts("darwin", runner).open_excel_files()
        self.assertEqual([p for _, p in found], [self.path])
        self.assertIn(["lsof", "-nP", "-c", "wpsoffice", "-Fn"], runner.calls)


    def test_the_most_recently_opened_of_two_same_named_files_wins(self):
        other = make_file(tempfile.mkdtemp(dir=self.dir.name))
        stamps = {str(self.path): "2026-11-06 10:00:00 +0000", str(other): "2026-11-01 10:00:00 +0000"}
        runner = lambda args: stamps.get(args[-1], "") if args[0] == "mdls" else ""
        self.assertEqual(SpreadsheetHosts("darwin", runner)._os._most_recently_used([self.path, other]), self.path)

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

    def test_a_second_document_is_found_beside_the_active_file_without_spotlight(self):
        active = make_file(self.dir.name, "Apparel Inventory SAMPLE.xlsx")
        other = make_file(self.dir.name, "Apparel Inventory.xlsx")
        h, runner = self.hosts("Apparel Inventory SAMPLE\t\nApparel Inventory\t\n")
        files = h.open_files(prefer=(str(active),))
        self.assertEqual([f.path for f in files], [str(active), str(other)])
        self.assertFalse(any("mdfind" in " ".join(c) for c in runner.calls))

    @unittest.skipIf(sys.platform == "win32", "these fake a Mac's output (POSIX paths); the Windows provider has its own tests")

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

    @unittest.skipIf(sys.platform == "win32", "these fake a Mac's output (POSIX paths); the Windows provider has its own tests")

    def test_a_cloud_drive_folder_is_fine(self):
        cloud = pathlib.Path(self.dir.name) / "Library" / "CloudStorage" / "GoogleDrive-x" / "My Drive"
        cloud.mkdir(parents=True)
        path = make_file(cloud, "stock.xlsx")
        h, _ = self.hosts("stock\t\n", f"{path}\n")
        self.assertEqual([f.path for f in h.open_files()], [str(path)])

    @unittest.skipIf(sys.platform == "win32", "these fake a Mac's output (POSIX paths); the Windows provider has its own tests")

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



class TestReload(unittest.TestCase):
    def test_numbers_is_asked_to_reload_the_saved_file(self):
        runner = FakeRunner({"osascript": "ok\n"})
        self.assertTrue(SpreadsheetHosts("darwin", runner).reload(NUMBERS, '/a/"b".xlsx'))
        self.assertEqual(runner.calls[0][-1], '/a/"b".xlsx')                   # the path is an argument, never part of the script
        self.assertNotIn('"b"', runner.calls[0][2])

    def test_a_failed_script_reports_false(self):
        self.assertFalse(SpreadsheetHosts("darwin", FakeRunner({"osascript": "no"})).reload(NUMBERS, "/a.xlsx"))

    def test_programs_that_cannot_be_asked_report_false_without_running_anything(self):
        runner = FakeRunner({})
        self.assertFalse(SpreadsheetHosts("darwin", runner).reload(LIBREOFFICE, "/a.xlsx"))
        self.assertFalse(SpreadsheetHosts("darwin", runner).reload(EXCEL, "/a.xlsx"))
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()


class TestALiveLinkAnswersFirst(unittest.TestCase):
    def test_a_live_answer_replaces_the_process_list_and_lsof(self):
        import pathlib
        from quill.bridge.hosts import LIBREOFFICE
        runner = FakeRunner({})
        hosts = SpreadsheetHosts("darwin", runner)
        hosts.live_documents["libreoffice"] = lambda: [(pathlib.Path("/a/b.xlsx"), "Sheet2")]
        self.assertEqual(hosts._documents_with_sheets(LIBREOFFICE), [(pathlib.Path("/a/b.xlsx"), "Sheet2")])
        self.assertEqual(runner.calls, [])                                           # (nothing was started)

    def test_without_a_link_the_old_way_is_used_and_a_broken_link_is_not_trusted(self):
        from quill.bridge.hosts import LIBREOFFICE
        runner = FakeRunner({"ps": "", "lsof": ""})
        hosts = SpreadsheetHosts("darwin", runner)
        hosts.live_documents["libreoffice"] = lambda: None
        hosts._documents_with_sheets(LIBREOFFICE)
        self.assertTrue(runner.calls)
        runner.calls.clear()

        def broken():
            raise RuntimeError("x")
        hosts.live_documents["libreoffice"] = broken
        hosts._documents_with_sheets(LIBREOFFICE)
        self.assertTrue(runner.calls)
