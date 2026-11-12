"""A file opened inside a running LibreOffice (File > Open, or handed to the running program) is on no command line. LibreOffice names every open
document in its window title, so Quill reads those, and places the name in a folder through the active file or LibreOffice's list of recent files."""
import pathlib
import tempfile
import unittest

from quill.bridge.hosts import SpreadsheetHosts
from quill.platforms.windows import hosts as winhosts

SUFFIXES = (".xlsx", ".csv", ".tsv")
CALC = "SALFRAME"


def titles(*names, kind=CALC):
    return [(kind, name) for name in names]


class TestReadingTheTitles(unittest.TestCase):
    def names(self, *windows):
        return winhosts.calc_document_names(list(windows), SUFFIXES)

    def test_a_calc_window_names_its_document(self):
        self.assertEqual(self.names((CALC, "Plants.xlsx - LibreOffice Calc")), ["Plants.xlsx"])

    def test_the_dash_may_be_a_hyphen_an_en_dash_or_an_em_dash(self):
        for dash in ("-", "\u2013", "\u2014"):
            self.assertEqual(self.names((CALC, f"Stock.xlsx {dash} LibreOffice Calc")), ["Stock.xlsx"], dash)

    def test_a_read_only_document_is_named_without_the_note(self):
        self.assertEqual(self.names((CALC, "Stock.xlsx (read-only) - LibreOffice Calc")), ["Stock.xlsx"])

    def test_names_with_accents_spaces_dashes_and_brackets_are_kept_whole(self):
        name = "Bilan \u00e9t\u00e9 \u2013 ao\u00fbt 2026 (copie).xlsx"
        self.assertEqual(self.names((CALC, f"{name} - LibreOffice Calc")), [name])

    def test_other_programs_windows_and_other_libreoffice_windows_are_left_out(self):
        self.assertEqual(self.names(("Chrome_WidgetWin_1", "Inbox - Mail"), (CALC, "Untitled 1 - LibreOffice Calc"),
                                    (CALC, "Report.docx - LibreOffice Writer"), (CALC, "Budget.ods - LibreOffice Calc"),
                                    (CALC, ""), (CALC, "LibreOffice Calc")), [])

    def test_a_csv_counts_and_a_name_is_listed_once(self):
        self.assertEqual(self.names((CALC, "a.csv - LibreOffice Calc"), (CALC, "a.csv - LibreOffice Calc"), (CALC, "b.xlsx - LibreOffice Calc")),
                         ["a.csv", "b.xlsx"])


XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Histories/Histories/org.openoffice.Office.Histories:HistoryList['PickList']/org.openoffice.Office.Histories:ItemList"><node oor:name="file:///C:/Users/me/Documents/Plants.xlsx" oor:op="replace"><prop oor:name="OpenTime" oor:op="fuse"><value>1</value></prop></node></item>
<item oor:path="/org.openoffice.Office.Histories/Histories/org.openoffice.Office.Histories:HistoryList['PickList']/org.openoffice.Office.Histories:ItemList"><node oor:name="file:///C:/Users/me/Bilan%20%C3%A9t%C3%A9%20%E2%80%93%20ao%C3%BBt%20(copie).xlsx" oor:op="replace"/></item>
<item oor:path="/x"><node oor:name="file://fileserver/team/Stock%20%26%20more.xlsx" oor:op="replace"/></item>
<item oor:path="/x"><node oor:name="file:///C:/Users/me/Documents/Plants.xlsx" oor:op="replace"/></item>
<item oor:path="/y"><prop oor:name="Other"><value>not a file</value></prop></item>
</oor:items>
"""


class TestTheRecentFiles(unittest.TestCase):
    def test_every_file_address_becomes_a_windows_path_newest_first_and_once(self):
        found = [str(p) for p in winhosts.recent_paths(XCU)]
        self.assertEqual(found, ["C:\\Users\\me\\Documents\\Plants.xlsx",
                                 "C:\\Users\\me\\Bilan \u00e9t\u00e9 \u2013 ao\u00fbt (copie).xlsx"[:0] or "C:\\Users\\me\\Bilan \u00e9t\u00e9 \u2013 ao\u00fbt (copie).xlsx",
                                 "\\\\fileserver\\team\\Stock & more.xlsx"])

    def test_nothing_in_a_file_with_no_addresses(self):
        self.assertEqual(winhosts.recent_paths("<oor:items/>"), [])
        self.assertEqual(winhosts.recent_paths(""), [])

    def test_an_address_that_is_not_a_local_or_network_file_is_ignored(self):
        self.assertEqual(winhosts.recent_paths('<node oor:name="http://example.com/a.xlsx"/>'), [])


class FakeRunner:
    """tasklist says LibreOffice runs; its one process was started with one file on its command line."""

    def __init__(self, command_file=None):
        self.command_file = command_file

    def __call__(self, args):
        if args[0] == "tasklist":
            return '"soffice.exe","4242","Console","1","100,000 K"\n"soffice.bin","4243","Console","1","300,000 K"\n'
        if args[0] == "powershell":
            import base64
            if not self.command_file:
                return ""
            line = f'"C:\\Program Files\\LibreOffice\\program\\scalc.exe" -o "{self.command_file}" --calc'
            return base64.b64encode(line.encode("utf-8")).decode() + "\n"
        return ""


class TestPlacingTheNames(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.first = self.dir / "Plants.xlsx"
        self.second = self.dir / "Bilan \u00e9t\u00e9.xlsx"
        for path in (self.first, self.second):
            path.write_bytes(b"x")

    def make(self, windows, recent, command_file):
        provider = winhosts.WinHosts(FakeRunner(command_file), windows=lambda: windows, recent=lambda: recent)
        shell = SpreadsheetHosts("win32", FakeRunner(command_file))
        shell._os = provider
        return shell

    def listed(self, shell, prefer=()):
        return sorted((f.name, f.path) for f in shell.open_files(prefer=tuple(str(p) for p in prefer)))

    def test_a_file_on_a_command_line_is_found_as_before_and_not_twice(self):
        shell = self.make(titles("Plants.xlsx - LibreOffice Calc"), "", str(self.first))
        self.assertEqual(self.listed(shell), [("Plants.xlsx", str(self.first))])

    def test_a_file_opened_inside_the_program_is_found_through_the_active_file(self):
        shell = self.make(titles("Plants.xlsx - LibreOffice Calc", "Bilan \u00e9t\u00e9.xlsx - LibreOffice Calc"), "", str(self.first))
        self.assertEqual(self.listed(shell, prefer=[self.second]), sorted([("Plants.xlsx", str(self.first)), ("Bilan \u00e9t\u00e9.xlsx", str(self.second))]))

    def test_it_is_found_through_the_recent_files_when_it_is_not_the_active_one(self):
        recent = '<node oor:name="file:///C:/Users/me/Bilan%20%C3%A9t%C3%A9.xlsx"/>'
        provider = winhosts.WinHosts(FakeRunner(str(self.first)), windows=lambda: titles("Plants.xlsx - LibreOffice Calc", "Bilan \u00e9t\u00e9.xlsx - LibreOffice Calc"),
                                     recent=lambda: recent, is_file=lambda path: path.startswith("C:\\Users\\me\\"))

        class App:
            key = "libreoffice"
        found = provider.documents(App())
        self.assertEqual([(p.name if "\\" not in str(p) else str(p), s) for p, s in found][-1], ("C:\\Users\\me\\Bilan \u00e9t\u00e9.xlsx", ""))
        self.assertEqual(len(found), 2)

    def test_the_active_file_is_tried_before_the_recent_ones(self):
        recent = f'<node oor:name="file:///C:/old/{self.second.name}"/>'
        provider = winhosts.WinHosts(FakeRunner(str(self.first)), windows=lambda: titles(f"{self.second.name} - LibreOffice Calc"),
                                     recent=lambda: recent, is_file=lambda path: True)

        class App:
            key = "libreoffice"
        found = provider.documents(App(), prefer=(str(self.second),))
        self.assertEqual(str(found[-1][0]), str(self.second))

    def test_a_name_that_cannot_be_placed_is_left_out_not_guessed(self):
        shell = self.make(titles("Stranger.xlsx - LibreOffice Calc"), XCU, None)
        self.assertEqual(self.listed(shell), [])

    def test_no_windows_listed_changes_nothing(self):
        shell = self.make([], "", str(self.first))
        self.assertEqual(self.listed(shell), [("Plants.xlsx", str(self.first))])

    def test_a_failing_window_list_never_breaks_the_look(self):
        def boom():
            raise OSError("no desktop")
        shell = self.make([], "", str(self.first))
        shell._os._windows = boom
        self.assertEqual(self.listed(shell), [("Plants.xlsx", str(self.first))])

    def test_other_programs_are_not_read_this_way(self):
        provider = winhosts.WinHosts(FakeRunner(None), windows=lambda: titles("Plants.xlsx - LibreOffice Calc"), recent=lambda: "")

        class App:
            key = "excel"
        self.assertEqual(provider.documents(App(), prefer=(str(self.first),)), [])


if __name__ == "__main__":
    unittest.main()
