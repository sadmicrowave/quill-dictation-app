"""The self-check (``Quill.exe --selftest``): it reports instead of crashing, keeps private things out, and works as the packaged entry point."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from quill import selfcheck
from quill.selfcheck import FAIL, OK, SKIP, WARN, Check

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestRunning(unittest.TestCase):
    def test_every_check_answers_on_this_system(self):
        results = selfcheck.run_checks()
        self.assertGreater(len(results), 10)
        crashed = [r for r in results if "the check itself failed" in r.detail]
        self.assertEqual(crashed, [], crashed)

    def test_the_things_this_system_must_have_pass(self):
        by_name = {r.name: r for r in selfcheck.run_checks()}
        for name in ("PySide6", "openpyxl", "vosk", "Write a row into a workbook (spaces and accents in the name)",
                     "CSV saved by Excel on Windows keeps its encoding"):
            self.assertEqual(by_name[name].status, OK, by_name[name])

    def test_a_check_that_raises_becomes_one_failure_and_the_rest_still_run(self):
        def broken():
            raise RuntimeError("boom at C:\\Users\\sam\\x")
        results = selfcheck.run_checks([("broken", broken), ("fine", lambda: [Check("fine", OK)])])
        self.assertEqual([r.status for r in results], [FAIL, OK])
        self.assertIn("the check itself failed: RuntimeError", results[0].detail)

    def test_windows_only_checks_say_so_on_other_systems(self):
        if sys.platform == "win32":
            self.skipTest("this is the other systems' case")
        by_name = {r.name: r for r in selfcheck.run_checks()}
        self.assertEqual(by_name["A workbook another program holds"].status, SKIP)
        self.assertEqual(by_name["Windows title bar look"].status, SKIP)

    @unittest.skipUnless(sys.platform == "win32", "needs Windows")
    def test_the_windows_checks_pass_on_windows(self):
        by_name = {r.name: r for r in selfcheck.run_checks()}
        self.assertEqual(by_name["A workbook another program holds"].status, OK, by_name["A workbook another program holds"])
        if not os.environ.get("QUILL_NO_HOSTS"):
            self.assertEqual(by_name["Which file a program was started with (PowerShell)"].status, OK)


class TestTheReport(unittest.TestCase):
    def test_it_counts_and_lists_every_line(self):
        text = selfcheck.report([Check("a", OK, "fine"), Check("b", WARN, "hm"), Check("c", FAIL, "bad")])
        self.assertIn("Result: 1 ok, 1 to look at, 1 failed", text)
        for line in ("] a: fine", "] b: hm", "] c: bad"):
            self.assertIn(line, text)

    def test_the_home_folder_and_user_name_never_appear(self):
        home = str(pathlib.Path.home())
        user = "samantha"
        with mock.patch.dict(os.environ, {"USERNAME": user, "USER": user}):
            text = selfcheck.report([Check("x", OK, f"{home}/Documents/a.xlsx and {user}'s folder")])
        self.assertNotIn(home, text)
        self.assertNotIn(user, text)
        self.assertIn("~", text)

    def test_the_real_report_holds_no_home_folder(self):
        text = selfcheck.report(selfcheck.run_checks())
        self.assertNotIn(str(pathlib.Path.home()), text)


class TestTheCommand(unittest.TestCase):
    def run_it(self, *extra):
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder) / "report.txt"
            env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QUILL_NO_SOUND": "1"}
            done = subprocess.run([sys.executable, str(ROOT / "main.py"), "--selftest", "--out", str(out), *extra],      # noqa: S603
                                  capture_output=True, text=True, timeout=120, env=env, cwd=folder)
            return done, out.read_text(encoding="utf-8") if out.exists() else ""

    def test_the_command_writes_the_report_opens_no_window_and_exits_clean(self):
        done, text = self.run_it()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Quill self-check", text)
        self.assertIn("Result:", text)

    def test_the_report_file_is_written_where_asked_and_the_default_is_the_desktop_or_home(self):
        self.assertIn(selfcheck.default_path().parent, (pathlib.Path.home() / "Desktop", pathlib.Path.home()))
        self.assertEqual(selfcheck.default_path().name, "Quill self-check.txt")
