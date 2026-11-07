"""The one check loop: one timer, one look at a time, bounded commands, nothing left running or growing, and no way for a
file name to become a command."""

import ast
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from quill.bridge import hosts as hosts_module
from quill.bridge.hosts import NUMBERS, OpenFile, SpreadsheetHosts
from quill.bridge.libreoffice_mirror import LibreOfficeMirror
from quill.bridge.numbers_mirror import NumbersMirror
from tests.test_side_panel_and_turns import FILE_PAGE, NoMirror, PanelApp

ROOT = pathlib.Path(__file__).resolve().parents[1] / "quill"


class FakeRunner:
    """Records every command and answers each by its program name."""

    def __init__(self, answers=None):
        self.answers, self.calls = answers or {}, []

    def __call__(self, args):
        self.calls.append(list(args))
        return self.answers.get(args[0], "")


class TestTheLoopIsOne(PanelApp):
    def setUp(self):
        super().setUp()
        self.hosts.files = [OpenFile("plants.xlsx", str(self.plants), "Numbers")]

    def test_there_is_one_timer_and_it_defaults_to_10_seconds(self):
        self.assertEqual(self.app._watcher.interval(), 10_000)
        for name in ("_panel_timer", "_sheet_timer"):
            self.assertFalse(hasattr(self.app, name), name)
        self.assertEqual(self.settings.preferences["sheet_check_seconds"], 10)

    def test_a_tick_takes_exactly_one_look(self):
        looks = []
        self.app.run_in_background = lambda work, done: (looks.append(work), done(work()))
        self.app.poll_workbooks()
        self.assertEqual(len(looks), 1)
        self.assertEqual(looks[0].__name__, "_scan")

    def test_a_look_that_never_finishes_is_never_stacked_and_the_next_one_runs_once_after_it(self):
        started, finish = [], []
        self.app.run_in_background = lambda work, done: (started.append(work), finish.append(done))
        for _ in range(60):                                                     # an hour of ticks, 10 s apart, while it hangs
            self.app.poll_workbooks()
        self.assertEqual(len(started), 1)
        finish[0](None)                                                          # it gives up (a time-out)
        self.assertEqual(len(started), 2)                                       # ONE look that was asked for meanwhile
        finish[1](None)
        self.assertEqual(len(started), 2)
        self.assertFalse(self.app._open_files_busy)

    def test_a_refresh_pressed_during_a_look_is_not_lost(self):
        started, finish = [], []
        self.app.run_in_background = lambda work, done: (started.append(work), finish.append(done))
        self.app.refresh_open_files()
        seen = []
        self.app.refresh_open_files(manual=True, then=lambda: seen.append("start"))
        finish[0](None)
        self.assertEqual(len(started), 2)
        finish[1](None)
        self.assertEqual(seen, ["start"])                                       # the waiting Start still gets its answer

    def test_a_failing_look_frees_the_loop(self):
        self.app.run_in_background = lambda work, done: done(None)              # what run_in_background reports for an exception
        self.app.refresh_open_files()
        self.assertFalse(self.app._open_files_busy)

    def test_the_look_asks_nothing_when_no_program_is_running(self):
        asked = []
        self.app.mirror = type("M", (), {"active_sheet": lambda s, p: asked.append(1), "has_document": lambda s, p: asked.append(2)})()
        self.app.lo_mirror = self.app.mirror
        self.hosts.running = lambda: []
        self.hosts.files = []
        self.app.refresh_open_files()
        self.assertEqual(asked, [])                                              # nothing is started or asked

    def test_the_look_after_a_late_timer_on_a_gone_window_does_nothing(self):
        self.app._quitting = True
        calls = []
        self.app.run_in_background = lambda work, done: calls.append(1)
        self.app.refresh_open_files()
        self.assertEqual(calls, [])


class TestStartChecksFirst(PanelApp):
    def setUp(self):
        super().setUp()
        self._env = mock.patch.dict("os.environ", {}, clear=False)
        self._env.start()
        os.environ.pop("QUILL_NO_HOSTS", None)
        self.hosts.running = lambda: []

    def tearDown(self):
        self._env.stop()
        super().tearDown()

    def test_start_after_the_window_was_closed_records_nothing(self):
        self.hosts.files = [OpenFile("plants.xlsx", str(self.plants), "Numbers")]
        self.app.refresh_open_files()                                            # it was open
        self.hosts.files = []                                                    # and now it is closed, before the timer saw it
        self.app.toggle_listening(True)
        self.assertFalse(self.app.controller.session.listening)                  # no microphone, no rows
        self.assertFalse(self.app.connected)
        self.assertEqual(self.app.window.panel.file_button.text_label.full_text, "Open File")

    def test_a_closed_file_shows_the_note_with_reopen_and_shakes_start(self):
        self.hosts.files = [OpenFile("plants.xlsx", str(self.plants), "Numbers")]
        self.app.refresh_open_files()                                            # it was open
        self.hosts.files = []
        self.app.window.toggle_button.shake_ms = 0                               # (the blink only: no swing in a test)
        self.app.refresh_open_files()                                            # the look that finds it closed
        panel = self.app.window.panel
        self.assertFalse(self.app.connected)
        self.assertFalse(panel.closed_note.isHidden())
        self.assertEqual(panel.closed_title.text(), "plants.xlsx was closed")
        self.assertIn("255, 59, 48", self.app.window.toggle_button.styleSheet())  # Start blinked red
        self.assertEqual(self.app.window.panel_page, "file")                      # the Files panel is open
        self.assertEqual(os.path.realpath(self.app._closed_file), os.path.realpath(self.plants))

    def test_reopen_opens_that_file_again_and_clears_the_note(self):
        self.hosts.files = [OpenFile("plants.xlsx", str(self.plants), "Numbers")]
        self.app.refresh_open_files()
        self.hosts.files = []
        self.app.refresh_open_files()
        opened = []
        self.app.open_workbook_file = lambda path, **kw: opened.append(str(path))
        self.app.window.panel.reopen_button.click()
        self.assertEqual([os.path.realpath(o) for o in opened], [os.path.realpath(self.plants)])
        self.assertTrue(self.app.window.panel.closed_note.isHidden())

    def test_dismiss_hides_the_note_and_connecting_a_file_clears_it(self):
        panel = self.app.window.panel
        panel.show_closed("plants.xlsx")
        panel.dismiss_closed_button.click()
        self.assertTrue(panel.closed_note.isHidden())
        panel.show_closed("plants.xlsx")
        self.app.connect_workbook(str(self.plants))                              # a file is connected again
        self.assertTrue(self.app.connected)
        self.assertTrue(panel.closed_note.isHidden())

    def test_start_with_the_window_open_goes_ahead(self):
        self.hosts.files = [OpenFile("plants.xlsx", str(self.plants), "Numbers")]
        self.app.toggle_listening(True)
        self.assertTrue(self.app.controller.session.listening)

    def test_stop_never_waits_for_a_look(self):
        self.hosts.files = [OpenFile("plants.xlsx", str(self.plants), "Numbers")]
        self.app.toggle_listening(True)
        calls = []
        self.app.run_in_background = lambda work, done: calls.append(1)
        self.app.toggle_listening(False)
        self.assertEqual(calls, [])
        self.assertFalse(self.app.controller.session.listening)


class TestNothingGrows(PanelApp):
    def test_many_ticks_with_real_helper_threads_leave_no_threads_and_no_growth(self):
        del self.app.run_in_background                                           # the real helper threads
        self.hosts.files = [OpenFile("plants.xlsx", str(self.plants), "Numbers")]
        base = threading.active_count()
        done = threading.Event()
        original = self.app._looked

        def finished(*args, **kwargs):
            original(*args, **kwargs)
            done.set()

        self.app._looked = finished
        for _ in range(40):
            done.clear()
            self.app.refresh_open_files()
            deadline = time.monotonic() + 5
            while not done.is_set() and time.monotonic() < deadline:
                self.app.qapp.processEvents()
                time.sleep(0.005)
            self.assertTrue(done.is_set())
        deadline = time.monotonic() + 3
        while self.app._open_files_busy and time.monotonic() < deadline:        # (a look that was already under way finishes)
            self.app.qapp.processEvents()
            time.sleep(0.005)
        time.sleep(0.1)
        self.assertLessEqual(threading.active_count(), base + 1)
        self.assertEqual(len(self.app._open_files), 1)
        self.assertFalse(self.app._open_files_busy)

    def test_remembered_launches_and_names_are_bounded(self):
        self.app._launched_at = {f"/old/{i}.xlsx": time.monotonic() - 1000 for i in range(500)}
        self.app.hosts.launch = lambda path, program="auto": True
        self.app._launch(self.plants)
        self.assertEqual(len(self.app._launched_at), 1)
        h = SpreadsheetHosts("darwin", FakeRunner())
        for i in range(500):
            h._remember_name(f"doc{i}", pathlib.Path(f"/x/doc{i}.xlsx"))
        self.assertLessEqual(len(h._found_by_name), h.MAX_REMEMBERED_NAMES)


class TestEveryCommandIsBounded(unittest.TestCase):
    """Static checks over every source file that starts a process."""

    def calls(self):
        for path in ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    yield path, node

    @staticmethod
    def dotted(node):
        func = node.func
        parts = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
        return ".".join(reversed(parts))

    def test_no_command_goes_through_a_shell(self):
        for path, node in self.calls():
            name = self.dotted(node)
            self.assertNotIn(name, ("os.system", "os.popen"), f"{path}")
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    self.assertFalse(getattr(keyword.value, "value", True) is True, f"shell=True in {path}")

    def test_every_subprocess_run_has_a_time_limit_and_no_process_is_left_unwaited(self):
        for path, node in self.calls():
            name = self.dotted(node)
            if name == "subprocess.run":
                self.assertIn("timeout", {k.arg for k in node.keywords}, f"no timeout in {path}:{node.lineno}")
            if name in ("subprocess.Popen", "subprocess.call", "subprocess.check_output"):
                # the only allowed one is the fire-and-forget xdg-open on Linux (its pipes go to DEVNULL)
                self.assertTrue(path.name == "hosts.py", f"{name} in {path}:{node.lineno}")


class TestATimedOutCommandIsKilledAndReaped(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict("os.environ")
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("QUILL_NO_HOSTS", None)                                   # these run real (harmless) commands

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
            time.sleep(0.2)
            with self.assertRaises(ProcessLookupError):                          # not running and not a zombie
                os.kill(pid, 0)

    def test_a_command_that_exits_badly_is_a_failure_too(self):
        failed = []
        hosts_module._run([sys.executable, "-c", "raise SystemExit(3)"], failed)
        self.assertEqual(len(failed), 1)

    def test_a_missing_program_is_a_failure_not_a_crash(self):
        failed = []
        self.assertEqual(hosts_module._run(["/no/such/program-xyz"], failed), "")
        self.assertEqual(len(failed), 1)

    def test_an_incomplete_look_is_reported(self):
        def runner(args):
            return ""
        h = SpreadsheetHosts("darwin", runner)
        h._failed.append("osascript")                                            # (what a time-out inside a look leaves)
        h.open_files(running=[])
        self.assertTrue(h.last_look_complete)                                    # a new look starts clean
        h._run = lambda args: (h._failed.append("osascript"), "")[1]
        h.open_files(running=[NUMBERS])
        self.assertFalse(h.last_look_complete)


class TestNamesNeverBecomeCommands(unittest.TestCase):
    NASTY = ['/a/"; do shell script "touch /tmp/pwned"; "b.xlsx', "/a/'; rm -rf ~; '.xlsx", "/a/$(touch pwned)`x`.xlsx",
             "/a/new\nline\ttab.xlsx", "/a/\\\\back.xlsx"]

    def test_reload_passes_the_path_as_an_argument_to_a_fixed_script(self):
        for path in self.NASTY:
            runner = FakeRunner({"osascript": "ok"})
            SpreadsheetHosts("darwin", runner).reload(NUMBERS, path)
            command = runner.calls[0]
            self.assertEqual(command[:3], ["osascript", "-e", hosts_module._RELOAD_NUMBERS])
            self.assertEqual(command[3:], [path])

    def test_a_spotlight_name_cannot_close_its_quote(self):
        for name in ("x'c || kMDItemFSName == '*", "y\\'", "z'"):
            runner = FakeRunner({"osascript": f"{name}\t\t\n", "ps": "/Applications/Numbers.app/Contents/MacOS/Numbers\n", "mdfind": ""})
            runner.answers["comm="] = ""
            h = SpreadsheetHosts("darwin", runner)
            h.find_by_name(name)
            for call in runner.calls:
                if call[0] == "mdfind":
                    query = call[1]
                    body = query[len("kMDItemFSName == '"):query.rindex("'c")]
                    self.assertNotIn("'", body.replace("\\'", ""), query)         # every quote inside is escaped

    def test_the_numbers_scripts_are_fixed_text_and_names_arrive_as_arguments(self):
        runner_calls = []

        def runner(args):
            runner_calls.append(args)
            return 0, "ok", ""
        mirror = NumbersMirror(runner)
        for path in self.NASTY:
            mirror.has_document(path)
            mirror.active_sheet(path)
            mirror.push(path, [("S", 1, 1, "v")])
        from quill.bridge import numbers_mirror as nm
        for args in runner_calls:
            self.assertIn(args[2], (nm.PROBE, nm.ACTIVE_SHEET, nm.SCRIPT))
            self.assertNotIn("pwned", args[2])

    def test_the_libreoffice_job_is_data_in_a_file_never_part_of_a_command(self):
        with tempfile.TemporaryDirectory() as folder:
            commands = []
            mirror = LibreOfficeMirror(runner=lambda args: commands.append(list(args)) or 0, base=pathlib.Path(folder),
                                       running=lambda: True, soffice="/x/soffice", wait_s=0.1,
                                       scripts_dir=pathlib.Path(folder) / "scripts")
            (pathlib.Path(folder) / "user").mkdir()
            for path in self.NASTY:
                mirror.active_sheet(path)
            for command in commands:
                self.assertEqual(command[0], "/x/soffice")
                self.assertEqual(len(command), 2)
                self.assertTrue(command[1].startswith("vnd.sun.star.script:"))
                for path in self.NASTY:
                    self.assertNotIn(path, command[1])
            self.assertFalse((pathlib.Path(folder) / "in.json").exists())          # the job file is not kept
            self.assertFalse((pathlib.Path(folder) / "out.json").exists())
            self.assertFalse((pathlib.Path(folder) / "in.json.tmp").exists())


class TestTheNativeProcessList(unittest.TestCase):
    def test_it_starts_no_process_and_answers_fast_on_a_mac(self):
        if sys.platform != "darwin":
            self.skipTest("macOS only")
        from quill.bridge.processes import running_executables
        with mock.patch.dict("os.environ"):
            os.environ.pop("QUILL_NO_HOSTS", None)
            running_executables()                                                # (the first call loads the framework)
            with mock.patch("subprocess.run") as run, mock.patch("subprocess.Popen") as popen:
                started = time.perf_counter()
                names = running_executables()
                took = time.perf_counter() - started
            run.assert_not_called()
            popen.assert_not_called()
            self.assertIsNotNone(names)
            self.assertLess(took, 0.2)

    def test_the_tests_never_ask_the_system(self):
        from quill.bridge.processes import running_executables
        with mock.patch.dict("os.environ", {"QUILL_NO_HOSTS": "1"}):
            self.assertIsNone(running_executables())


if __name__ == "__main__":
    unittest.main()


class TestSheetNotSavedYet(PanelApp):
    """A sheet that the program shows but the saved file does not have: the folder icon gets a red dot, the Files panel a
    red dot on the Sheet label (nothing moves), and Quill stays on its last sheet; both go when the file and the program agree
    again."""

    def setUp(self):
        super().setUp()
        self.app.connect_to_file(self.plants) if hasattr(self.app, "connect_to_file") else None
        self.logged = []
        self.app.window.append_log = lambda text, level="info", **kw: self.logged.append((level, text))

    def test_the_two_dots_and_one_log_line_appear_once(self):
        self.app._apply_sheet("Sheet Nine", quiet=True)
        self.app._apply_sheet("Sheet Nine", quiet=True)
        window = self.app.window
        self.assertIn("Sheet Nine", window.file_alert)
        label, _ = window.panel.fact_rows["Sheet"]
        self.assertTrue(label._dot)
        self.assertIn("Sheet Nine is open in", label.toolTip())
        self.assertEqual([lvl for lvl, _ in self.logged].count("warning"), 1)

    def test_opening_the_file_panel_puts_the_folder_dot_away_but_the_sheet_dot_stays(self):
        self.app._apply_sheet("Sheet Nine", quiet=True)
        self.app.window.open_panel(FILE_PAGE)
        self.assertEqual(self.app.window.file_alert, "")
        self.assertTrue(self.app.window.panel.fact_rows["Sheet"][0]._dot)

    def test_everything_goes_when_the_file_has_the_sheet(self):
        self.app._apply_sheet("Sheet Nine", quiet=True)
        self.app._apply_sheet(self.app.controller.bridge.active_sheet_name(), quiet=True)
        self.assertEqual(self.app.window.file_alert, "")
        self.assertFalse(self.app.window.panel.fact_rows["Sheet"][0]._dot)
