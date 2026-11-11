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


class TestSendingTheReport(unittest.TestCase):
    """``--selftest --send``: the report goes to the support relay (an issue in the private reports repository)."""

    RESULTS = [Check("a", OK, "fine"), Check("b", WARN, "hm"), Check("c", FAIL, "bad"), Check("i", selfcheck.INFO, "x")]

    def test_the_first_line_is_a_searchable_title_with_nothing_personal(self):
        first = selfcheck.message(self.RESULTS).splitlines()[0]
        self.assertTrue(first.startswith("Self-check: "), first)
        self.assertIn("1 ok, 1 to look at, 1 failed", first)
        self.assertLessEqual(len(first), 70)                                            # (the relay keeps 70 characters as the title)

    def test_the_message_fits_the_relays_limit_by_dropping_the_least_important_lines(self):
        many = [Check(f"info {n}", selfcheck.INFO, "x" * 100) for n in range(60)] + [Check("broken", FAIL, "it is")]
        text = selfcheck.message(many)
        self.assertLessEqual(len(text), 3800)
        self.assertIn("broken", text)                                                   # a failure is never the thing dropped

    def test_the_payload_is_what_the_relay_accepts(self):
        sent = []
        selfcheck.send(self.RESULTS, sender=lambda payload: sent.append(payload) or mock.Mock(ok=True))
        payload = sent[0]
        self.assertEqual(payload["kind"], "problem")
        self.assertEqual(payload["contact"], "")
        self.assertLessEqual(len(payload["message"]), 4000)
        self.assertTrue(payload["message"].startswith("Self-check: "))
        self.assertTrue(all(line for line in payload["log"]) and isinstance(payload["facts"], dict))

    def test_it_goes_through_the_real_sender_to_the_relay_address(self):
        from quill import support
        seen = []

        class Reply:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"ok": true, "reference": "#7"}'
        with mock.patch.object(support.urllib.request, "urlopen", lambda request, timeout: seen.append(request) or Reply()):
            result = selfcheck.send(self.RESULTS)
        self.assertTrue(result.ok)
        self.assertEqual(result.reference, "#7")
        self.assertTrue(seen[0].full_url.startswith("https://"))
        self.assertEqual(seen[0].get_method(), "POST")

    def test_the_outcome_is_shown_and_the_exit_code_says_which_part_failed(self):
        from quill.support import SendResult
        shown = []
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(selfcheck, "run_checks", return_value=[Check("a", OK)]):
            out = str(pathlib.Path(folder) / "r.txt")
            code = selfcheck.main(out, send_report=True, sender=lambda p: SendResult(True, reference="#9"), notify=shown.append)
            self.assertEqual((code, "#9" in shown[0]), (0, True))
            code = selfcheck.main(out, send_report=True, sender=lambda p: SendResult(False, error="no network"), notify=shown.append)
            self.assertEqual(code, 2)
            self.assertIn("NOT sent: no network", shown[1])
            self.assertTrue(pathlib.Path(out).is_file())                                # (the report is kept either way)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(selfcheck, "run_checks", return_value=[Check("a", FAIL, "bad")]):
            code = selfcheck.main(str(pathlib.Path(folder) / "r.txt"), send_report=True, sender=lambda p: SendResult(True), notify=shown.append)
            self.assertEqual(code, 1)

    def test_a_microphone_name_is_never_in_the_report(self):
        devices = [{"name": "Samantha's AirPods Pro", "max_input_channels": 1}]
        fake = mock.Mock(query_devices=lambda kind=None: devices[0] if kind else devices)
        with mock.patch.dict(sys.modules, {"sounddevice": fake}):
            text = selfcheck.report(selfcheck.microphone())
        self.assertNotIn("Samantha", text)
        self.assertIn("1 input device", text)

    def test_send_alone_runs_the_self_check_from_the_command_line(self):
        with tempfile.TemporaryDirectory() as folder:
            done = subprocess.run([sys.executable, str(ROOT / "main.py"), "--send", "--out", str(pathlib.Path(folder) / "r.txt"), "--help"],    # noqa: S603
                                  capture_output=True, text=True, timeout=60, cwd=folder)
        self.assertIn("--send", done.stdout)
