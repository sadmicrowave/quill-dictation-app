"""Finding and starting the spreadsheet programs on Windows, with a pretend command runner (these run on any system; the same
questions asked of a real Windows are in ``test_windows_system.py``).

The Mac tests of ``tests/test_hosts.py`` fake a Mac's answers (``ps``, ``lsof``, AppleScript, Spotlight). These are their Windows
counterparts: what ``tasklist`` says, what PowerShell says about a command line, and how Windows paths and names are read.
"""
import base64
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from quill import platforms
from quill.bridge.hosts import APPS, EXCEL, LIBREOFFICE, NUMBERS, SpreadsheetHosts, files_named_in
from quill.platforms.windows import hosts as winhosts
from quill.platforms.windows import libreoffice as win_lo
from tests.test_hosts import FakeRunner, make_file


def ps(*lines):
    """What the PowerShell question answers: each command line as base64 of its UTF-8 bytes."""
    return "\n".join(base64.b64encode(line.encode("utf-8")).decode("ascii") for line in lines)


def named(text):
    return [str(path) for path, _ in files_named_in(text)]


def spelled(*paths):
    """The paths as this system spells them (Windows turns ``/`` into ``\\``)."""
    return [str(pathlib.Path(p)) for p in paths]


class TestWhatTasklistSays(unittest.TestCase):
    def running(self, text):
        return [a.key for a in SpreadsheetHosts("win32", FakeRunner({"tasklist": text})).running()]

    def test_the_known_programs_are_found_in_the_order_of_the_list(self):
        self.assertEqual(self.running('"EXCEL.EXE","1","Console"\n"soffice.exe","2","Console"\n"et.exe","3","Console"'),
                         ["excel", "libreoffice", "wps"])

    def test_capitals_do_not_matter(self):
        self.assertEqual(self.running('"SOFFICE.EXE","2","Console"'), ["libreoffice"])

    def test_a_program_with_a_longer_name_is_not_taken_for_one(self):
        self.assertEqual(self.running('"notsoffice.exe","2","Console"\n"set.exe","3","Console"\n"EXCEL.EXE.bak","4","Console"'), [])

    def test_numbers_is_never_found_on_windows(self):
        self.assertNotIn("numbers", self.running('"Numbers.exe","1","Console"'))

    def test_a_task_list_that_could_not_be_read_finds_nothing(self):
        self.assertEqual(self.running(""), [])

    def test_the_task_list_is_asked_without_a_shell_and_without_a_header(self):
        runner = FakeRunner({})
        SpreadsheetHosts("win32", runner).running()
        self.assertEqual(runner.calls, [["tasklist", "/fo", "csv", "/nh"]])


class TestWhoIsAskedAboutCommandLines(unittest.TestCase):
    def test_powershell_is_asked_first_with_a_fixed_script(self):
        runner = FakeRunner({"powershell": ps('soffice.exe --calc "C:\\a\\b.xlsx"')})
        winhosts.documents(LIBREOFFICE, runner)
        self.assertEqual(len(runner.calls), 1)
        command = runner.calls[0]
        self.assertEqual(command[:4], ["powershell", "-NoProfile", "-NonInteractive", "-Command"])
        self.assertIn("Get-CimInstance Win32_Process", command[4])
        self.assertIn("name='soffice.exe'", command[4])

    def test_wmic_is_asked_only_when_powershell_says_nothing(self):
        runner = FakeRunner({"wmic": 'soffice.exe --calc "C:\\a\\b.xlsx"'})
        self.assertEqual(named_in(winhosts.documents(LIBREOFFICE, runner)), ["C:\\a\\b.xlsx"])
        self.assertEqual([c[0] for c in runner.calls], ["powershell", "wmic"])

    def test_accents_and_other_scripts_in_a_folder_name_survive_the_trip(self):
        """PowerShell's own text goes through the console's code page, which loses them; the base64 trip does not."""
        line = 'soffice.exe --calc "C:\\Users\\José 山田\\Mes classeurs été\\Bilan – août.xlsx"'
        runner = FakeRunner({"powershell": ps(line)})
        self.assertEqual(named_in(winhosts.documents(LIBREOFFICE, runner)), ["C:\\Users\\José 山田\\Mes classeurs été\\Bilan – août.xlsx"])

    def test_lines_that_are_not_an_answer_are_ignored(self):
        runner = FakeRunner({"powershell": "WARNING: something\n" + ps('soffice.exe "C:\\a\\b.xlsx"') + "\n\n"})
        self.assertEqual(named_in(winhosts.documents(LIBREOFFICE, runner)), ["C:\\a\\b.xlsx"])
        self.assertEqual([c[0] for c in runner.calls], ["powershell"])

    def test_several_instances_each_give_their_files(self):
        runner = FakeRunner({"powershell": ps('soffice.exe "C:\\a\\one.xlsx"', 'soffice.exe "C:\\a\\two.csv"')})
        self.assertEqual(named_in(winhosts.documents(LIBREOFFICE, runner)), ["C:\\a\\one.xlsx", "C:\\a\\two.csv"])

    def test_nothing_is_asked_of_a_program_that_has_no_windows_process(self):
        runner = FakeRunner({})
        self.assertEqual(winhosts.documents(NUMBERS, runner), [])
        self.assertEqual(runner.calls, [])

    def test_every_program_name_in_a_script_is_one_of_ours(self):
        for app in APPS:
            runner = FakeRunner({})
            winhosts.documents(app, runner)
            for command in runner.calls:
                self.assertIn(winhosts.PROCESS_NAMES[app.key], " ".join(command))


def named_in(pairs):
    return [str(path) for path, _ in pairs]


class TestPowerShellIsAskedOnlyWhenTheProgramsChange(unittest.TestCase):
    """PowerShell needs seconds to answer, and a process's command line never changes: ask again only when its process numbers do."""

    def make(self):
        self.numbers = '"soffice.exe","100","Console","1","50,000 K"'
        self.lines = ps('soffice.exe "C:\\a\\one.xlsx"')
        self.calls = []

        def run(args):
            self.calls.append(args[0])
            if args[0] == "tasklist":
                return self.numbers
            if args[0] == "powershell":
                return self.lines
            return ""
        return winhosts.WinHosts(run)

    def test_the_same_programs_are_not_asked_about_again(self):
        hosts = self.make()
        self.assertEqual(named_in(hosts.documents(LIBREOFFICE)), ["C:\\a\\one.xlsx"])
        self.assertEqual(named_in(hosts.documents(LIBREOFFICE)), ["C:\\a\\one.xlsx"])
        self.assertEqual(self.calls.count("powershell"), 1)

    def test_a_new_process_is_asked_about(self):
        hosts = self.make()
        hosts.documents(LIBREOFFICE)
        self.numbers = '"soffice.exe","100","Console","1","50,000 K"\n"soffice.exe","200","Console","1","50,000 K"'
        self.lines = ps('soffice.exe "C:\\a\\one.xlsx"', 'soffice.exe "C:\\a\\two.xlsx"')
        self.assertEqual(named_in(hosts.documents(LIBREOFFICE)), ["C:\\a\\one.xlsx", "C:\\a\\two.xlsx"])
        self.assertEqual(self.calls.count("powershell"), 2)

    def test_a_restarted_program_with_a_new_number_is_asked_about(self):
        hosts = self.make()
        hosts.documents(LIBREOFFICE)
        self.numbers = '"soffice.exe","300","Console","1","50,000 K"'
        self.lines = ps('soffice.exe "C:\\a\\other.xlsx"')
        self.assertEqual(named_in(hosts.documents(LIBREOFFICE)), ["C:\\a\\other.xlsx"])

    def test_nothing_is_remembered_when_the_process_list_cannot_be_read(self):
        hosts = self.make()
        self.numbers = ""
        hosts.documents(LIBREOFFICE)
        hosts.documents(LIBREOFFICE)
        self.assertEqual(self.calls.count("powershell"), 2)

    def test_the_cached_answer_is_a_copy(self):
        hosts = self.make()
        hosts.documents(LIBREOFFICE).clear()
        self.assertEqual(len(hosts.documents(LIBREOFFICE)), 1)


class TestWindowsPathsOnACommandLine(unittest.TestCase):
    def test_a_quoted_program_and_a_quoted_file_with_spaces(self):
        line = r'"C:\Program Files\LibreOffice\program\soffice.exe" --calc "C:\Users\Sam Lee\My Docs\stock list.xlsx"'
        self.assertEqual(named(line), [r"C:\Users\Sam Lee\My Docs\stock list.xlsx"])

    def test_an_unquoted_file(self):
        self.assertEqual(named(r"soffice.exe --calc C:\Users\sam\stock.xlsx"), [r"C:\Users\sam\stock.xlsx"])

    def test_an_unquoted_file_with_an_option_after_it(self):
        self.assertEqual(named(r"soffice.exe C:\Users\sam\stock.xlsx --norestore"), [r"C:\Users\sam\stock.xlsx"])

    def test_two_files_and_every_kind_of_capitals(self):
        line = r'et.exe "C:\a\one.XLSX" "D:\b\two.Csv" "E:\c\three.tsv"'
        self.assertEqual(named(line), [r"C:\a\one.XLSX", r"D:\b\two.Csv", r"E:\c\three.tsv"])

    def test_forward_slashes_are_a_path_too(self):
        self.assertEqual(named('soffice.exe "C:/Users/sam/stock.xlsx"'), spelled("C:/Users/sam/stock.xlsx"))

    def test_a_network_share(self):
        self.assertEqual(named('soffice.exe "\\\\fileserver\\team\\stock.xlsx"'), ["\\\\fileserver\\team\\stock.xlsx"])

    def test_a_file_listed_twice_is_listed_once(self):
        self.assertEqual(named(r'soffice.exe "C:\a\one.xlsx" C:\a\one.xlsx'), [r"C:\a\one.xlsx"])

    def test_other_documents_and_backup_names_are_not_spreadsheets(self):
        self.assertEqual(named(r'soffice.exe "C:\a\letter.docx" "C:\a\old.xlsx.bak" C:\a\notes.txt'), [])

    def test_a_relative_name_is_not_a_place_to_look(self):
        self.assertEqual(named("soffice.exe stock.xlsx"), [])

    def test_names_with_shell_characters_arrive_whole(self):
        for name in ("a & b.xlsx", "100% done.xlsx", "$(calc) `x`.xlsx", "it's; calc.xlsx", "a^b (copy).xlsx", "Bilan été – 2026.xlsx"):
            with self.subTest(name=name):
                self.assertEqual(named(f'soffice.exe "C:\\Users\\sam\\{name}"'), [f"C:\\Users\\sam\\{name}"])

    def test_the_mac_way_of_naming_a_file_still_works(self):
        self.assertEqual(named('/Applications/LibreOffice.app/Contents/MacOS/soffice --calc "/Users/sam/stock.xlsx"'), spelled("/Users/sam/stock.xlsx"))


class TestNamesNeverBecomeCommandsOnWindows(unittest.TestCase):
    """Windows counterpart of ``TestNamesNeverBecomeCommands`` (``tests/test_check_loop.py``): a file name is data, never part of a
    command. Windows names may hold ``&``, ``%``, ``^``, ``'``, ``$`` and backticks (not ``"``, which a Mac name may)."""

    NASTY = ["C:\\a\\x & del y.xlsx", "C:\\a\\%PATH%.xlsx", "C:\\a\\^&calc.xlsx", "C:\\a\\it's; calc.xlsx", "C:\\a\\$(calc)`x`.xlsx",
             "C:\\a\\back\\\\slash.xlsx", "\\\\server\\share\\a & b.xlsx"]

    def test_looking_for_open_files_asks_only_fixed_questions(self):
        runner = FakeRunner({"tasklist": '"soffice.exe","2","Console"', "powershell": ps(*[f'soffice.exe "{p}"' for p in self.NASTY])})
        SpreadsheetHosts("win32", runner).open_excel_files()
        for command in runner.calls:
            for path in self.NASTY:
                self.assertNotIn(path, " ".join(command))

    def test_opening_a_file_hands_the_whole_name_to_windows_and_runs_no_command(self):
        runner = FakeRunner({})
        for path in self.NASTY:
            with mock.patch.dict(os.environ), mock.patch.object(os, "startfile", create=True) as startfile:
                os.environ.pop("QUILL_NO_HOSTS", None)
                self.assertTrue(SpreadsheetHosts("win32", runner).launch(path))
            startfile.assert_called_once_with(path)
        self.assertEqual(runner.calls, [])

    def test_reloading_and_finding_by_name_ask_nothing(self):
        runner = FakeRunner({})
        hosts = SpreadsheetHosts("win32", runner)
        for path in self.NASTY:
            self.assertFalse(hosts.reload(NUMBERS, path))
            self.assertIsNone(hosts.find_by_name(path))
        self.assertEqual(runner.calls, [])

    def test_the_provider_offers_no_choice_of_program(self):
        """On Windows the file opens in the system's own program whatever ``open_with`` says: no program name reaches a command."""
        for program in ("auto", "numbers", "libreoffice", "excel", "x; calc"):
            with mock.patch.dict(os.environ), mock.patch.object(os, "startfile", create=True) as startfile:
                os.environ.pop("QUILL_NO_HOSTS", None)
                SpreadsheetHosts("win32", FakeRunner({})).launch("C:\\a\\b.xlsx", program)
            startfile.assert_called_once_with("C:\\a\\b.xlsx")


class TestOpenFilesAsWindowsReportsThem(unittest.TestCase):
    """The whole look, with files that exist (the paths are this system's own, quoted)."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = make_file(self.dir.name, "stock list.xlsx")

    def test_a_file_on_the_command_line_of_a_running_libreoffice_is_found(self):
        runner = FakeRunner({"tasklist": '"soffice.exe","2","Console"', "powershell": ps(f'soffice.exe --calc "{self.path}"')})
        self.assertEqual(SpreadsheetHosts("win32", runner).open_excel_files(), [(LIBREOFFICE, self.path)])

    def test_the_side_panel_lists_it_with_the_program_that_has_it(self):
        runner = FakeRunner({"tasklist": '"et.exe","2","Console"', "powershell": ps(f'et.exe "{self.path}"')})
        files = SpreadsheetHosts("win32", runner).open_files()
        self.assertEqual([(f.name, f.path, f.app) for f in files], [("stock list.xlsx", str(self.path), "WPS Office")])

    def test_a_file_that_is_gone_is_not_listed(self):
        runner = FakeRunner({"tasklist": '"soffice.exe","2","Console"', "powershell": ps(f'soffice.exe "{self.dir.name}\\gone.xlsx"')})
        self.assertEqual(SpreadsheetHosts("win32", runner).open_excel_files(), [])

    def test_excel_is_left_to_live_automation(self):
        runner = FakeRunner({"tasklist": '"EXCEL.EXE","1","Console"', "powershell": ps(f'EXCEL.EXE "{self.path}"')})
        self.assertEqual(SpreadsheetHosts("win32", runner).open_excel_files(), [])
        self.assertTrue(EXCEL.live)


class TestInstalledPrograms(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = pathlib.Path(self.dir.name)
        env = mock.patch.dict(os.environ, {"ProgramFiles": str(self.root / "pf"), "ProgramFiles(x86)": str(self.root / "pf86")})
        env.start()
        self.addCleanup(env.stop)

    def touch(self, *parts):
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")

    def test_nothing_installed(self):
        self.assertFalse(winhosts.installed("libreoffice"))
        self.assertFalse(winhosts.installed("excel"))
        self.assertFalse(winhosts.installed("numbers"))

    def test_libreoffice_in_either_program_files_folder(self):
        self.touch("pf", "LibreOffice", "program", "soffice.exe")
        self.assertTrue(winhosts.installed("libreoffice"))
        self.assertEqual(win_lo.find_soffice(), str(self.root / "pf" / "LibreOffice" / "program" / "soffice.exe"))
        (self.root / "pf" / "LibreOffice" / "program" / "soffice.exe").unlink()
        self.touch("pf86", "LibreOffice", "program", "soffice.exe")
        self.assertTrue(winhosts.installed("libreoffice"))

    def test_excel_whichever_office_folder_it_is_in(self):
        self.touch("pf", "Microsoft Office", "root", "Office16", "EXCEL.EXE")
        self.assertTrue(winhosts.installed("excel"))

    def test_the_hosts_object_answers_the_same(self):
        self.touch("pf", "LibreOffice", "program", "soffice.exe")
        hosts = SpreadsheetHosts("win32", FakeRunner({}))
        self.assertTrue(hosts.installed("libreoffice"))
        self.assertTrue(hosts.installed("auto"))
        self.assertFalse(hosts.installed("excel"))


class TestLibreOfficeOnWindows(unittest.TestCase):
    def test_user_scripts_live_in_the_roaming_profile(self):
        with mock.patch.dict(os.environ, {"APPDATA": r"C:\Users\sam\AppData\Roaming"}):
            found = win_lo.profile_scripts_dir(pathlib.Path("home"))
        self.assertEqual(found.parts[-5:], ("LibreOffice", "4", "user", "Scripts", "python"))
        self.assertTrue(str(found).startswith(r"C:\Users\sam\AppData\Roaming"))

    def test_the_mirror_asks_the_windows_provider(self):
        from quill.bridge import libreoffice_mirror as mirror
        self.assertIs(platforms.offered("win32", "libreoffice"), win_lo)
        with mock.patch.dict(os.environ, {"APPDATA": "ROAM"}):
            self.assertEqual(mirror.profile_scripts_dir("win32", pathlib.Path("home")), win_lo.profile_scripts_dir(pathlib.Path("home")))

    def test_running_reads_the_task_list(self):
        for text, expected in (('"soffice.bin","2","Console"', True), ('"soffice.exe","2","Console"', True), ('"calc.exe","2"', False), ("", False)):
            with self.subTest(text=text), mock.patch("subprocess.run") as run:
                run.return_value.stdout = text
                self.assertIs(win_lo.is_running(), expected)

    def test_the_script_is_given_the_job_folder_as_one_safe_text(self):
        """The helper script is installed with Quill's job folder written into it. A Windows folder has backslashes (``\\U`` of
        ``C:\\Users`` would be a broken escape in a plain string), apostrophes and accents."""
        import ast
        from quill.bridge.libreoffice_mirror import LibreOfficeMirror
        for folder in (r"C:\Users\Ünal O'Brien\AppData\Local\Quill\mirror", r"C:\Users\sam\x\n\table", r"\\server\share\q"):
            with self.subTest(folder=folder):
                mirror = LibreOfficeMirror(base=pathlib.Path(folder))
                tree = ast.parse(mirror.script_text())                              # (a broken line would not even parse)
                value = next(n.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "BASE")
                self.assertEqual(ast.literal_eval(value), str(pathlib.Path(folder)))

