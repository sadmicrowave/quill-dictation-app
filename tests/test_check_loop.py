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
from quill.platforms.macos import hosts as mac_hosts
from quill.platforms.macos.numbers_mirror import NumbersMirror
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
        self.assertTrue(self.app.window.toggle_button.alerting)  # Start blinked red
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
            h._os._remember_name(f"doc{i}", pathlib.Path(f"/x/doc{i}.xlsx"))
        self.assertLessEqual(len(h._os._found_by_name), h._os.MAX_REMEMBERED_NAMES)


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
                # the allowed ones: the fire-and-forget xdg-open on Linux (its pipes go to DEVNULL), and the one kept process that
                # asks Numbers things (ScriptWorker: every read has a time limit after which it is killed and waited for, it is
                # let go of when idle and ends when Quill's end of its pipe closes; tests/macos/test_numbers_live.py proves each)
                self.assertTrue(path.name in ("hosts.py", "numbers_live.py"), f"{name} in {path}:{node.lineno}")


class TestATimedOutCommandIsKilledAndReaped(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict("os.environ")
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("QUILL_NO_HOSTS", None)                                   # these run real (harmless) commands

    @unittest.skipIf(sys.platform == "win32", "checks a POSIX child process with os.kill")

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

    def test_reload_never_puts_a_path_in_a_script(self):
        from tests.fake_numbers import FakeNumbers
        for path in self.NASTY:
            numbers = FakeNumbers()
            numbers.import_xlsx(path)
            SpreadsheetHosts("darwin", numbers).reload(NUMBERS, path)
            for command in numbers.calls:
                if command[0] == "osascript":
                    self.assertIn(command[4], (mac_hosts._LIST_NUMBERS_FOR_RELOAD, mac_hosts._CLOSE_NUMBERS, mac_hosts.NUMBERS_BUNDLE_JS))      # fixed scripts
                    self.assertNotIn(path, command[4])
                    self.assertTrue(all(arg.isdigit() for arg in command[5:]))                                        # only positions
                elif command[0] == "mdfind":                                                                           # which Numbers is installed
                    self.assertNotIn(path, " ".join(command))
                    self.assertIn(command[1], [f"kMDItemCFBundleIdentifier == '{b}'" for b in ("com.apple.Numbers", "com.apple.iWork.Numbers")])
                else:
                    self.assertEqual(command[-1], path)                                                                # one argument, never a shell line

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
        from quill.platforms.macos import numbers_mirror as nm
        for args in runner_calls:
            self.assertIn(args[2], (nm.PROBE, nm.ACTIVE_SHEET, nm.SCRIPT))
            self.assertNotIn("pwned", args[2])

    def test_the_libreoffice_job_is_data_in_a_file_never_part_of_a_command(self):
        with tempfile.TemporaryDirectory() as folder:
            commands = []
            mirror = LibreOfficeMirror(runner=lambda args: commands.append(list(args)) or 0, base=pathlib.Path(folder),
                                       running=lambda: True, soffice="/x/soffice", wait_s=0.1, use_live=False,
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

    def test_start_does_not_listen_while_the_dot_shows_and_shakes(self):
        self.app._apply_sheet("Sheet Nine", quiet=True)
        shaken = []
        self.app.window.toggle_button.alert = lambda: shaken.append(1)
        self.app.toggle_listening(True)
        self.assertFalse(self.app.controller.session.listening)
        self.assertEqual(shaken, [1])
        self.assertEqual(self.app.window.panel_page, "file")

    def test_the_refresh_icon_saves_in_libreoffice_then_follows(self):
        self.app._apply_sheet("Sheet Nine", quiet=True)
        saved, looks = [], []
        self.app._program_holding = lambda path: "libreoffice"
        self.app.lo_mirror = type("M", (), {"save": lambda s, path: saved.append(path) or True})()
        self.app.run_in_background = lambda work, done: done(work())
        self.app.refresh_open_files = lambda **kw: looks.append(kw)
        self.app.refresh_active_sheet()
        self.assertEqual(len(saved), 1)
        self.assertEqual(looks, [{"manual": True, "announce": True}])

    def test_a_failed_save_says_so_and_changes_nothing(self):
        self.app._apply_sheet("Sheet Nine", quiet=True)
        self.app._program_holding = lambda path: "libreoffice"
        self.app.lo_mirror = type("M", (), {"save": lambda s, path: False})()
        self.app.run_in_background = lambda work, done: done(work())
        self.logged.clear()
        self.app.refresh_active_sheet()
        self.assertTrue(any("did not save" in text for _, text in self.logged))
        self.assertTrue(self.app.window.panel.fact_rows["Sheet"][0]._dot)

    # --- LibreOffice: saved and followed with no click -------------------------------------------------------------

    def libreoffice_holds_the_file(self, saves):
        self.app._program_holding = lambda path: "libreoffice"
        self.app.lo_mirror = type("M", (), {"save": lambda s, path: saves.append(path) or True})()
        self.looks = []
        self.app.refresh_open_files = lambda **kw: self.looks.append(kw)
        self.app.controller.refresh = lambda: self.looks.append("reread")

    def test_a_new_sheet_in_libreoffice_is_saved_and_followed_without_any_click_or_alert(self):
        saves = []
        self.libreoffice_holds_the_file(saves)
        self.app.run_in_background = lambda work, done: done(work())
        self.app._apply_sheet("Sheet Nine", quiet=True)
        self.assertEqual(len(saves), 1)
        self.assertEqual(self.looks, ["reread", {"manual": False, "announce": False}])
        self.assertEqual(self.app.window.file_alert, "")                  # no red dot: nothing asked of the user
        self.assertFalse(self.app.window.panel.fact_rows["Sheet"][0]._dot)
        self.assertEqual([lvl for lvl, _ in self.logged if lvl == "warning"], [])
        self.assertTrue(any("saved so Quill could follow" in text for _, text in self.logged))

    def test_every_look_while_it_saves_waits_instead_of_saving_again_or_alerting(self):
        saves, pending = [], []
        self.libreoffice_holds_the_file(saves)
        self.app.run_in_background = lambda work, done: pending.append((work, done))
        for _ in range(3):
            self.app._apply_sheet("Sheet Nine", quiet=True)
        self.assertEqual(len(pending), 1)
        self.assertEqual(self.app.window.file_alert, "")
        work, done = pending[0]
        done(work())
        self.assertEqual(len(saves), 1)

    def test_when_libreoffice_will_not_save_the_red_dot_asks_once_and_nothing_loops(self):
        calls = []
        self.app._program_holding = lambda path: "libreoffice"
        self.app.lo_mirror = type("M", (), {"save": lambda s, path: calls.append(path) or False})()
        self.app.run_in_background = lambda work, done: done(work())
        self.app._apply_sheet("Sheet Nine", quiet=True)
        self.app._apply_sheet("Sheet Nine", quiet=True)
        self.app._apply_sheet("Sheet Nine", quiet=True)
        self.assertEqual(len(calls), 1)                                   # it did not try again at every look
        self.assertIn("Sheet Nine", self.app.window.file_alert)
        self.assertTrue(self.app.window.panel.fact_rows["Sheet"][0]._dot)

    def test_other_programs_still_ask_for_the_click(self):
        saves = []
        self.libreoffice_holds_the_file(saves)
        self.app._program_holding = lambda path: "numbers"
        self.app._apply_sheet("Sheet Nine", quiet=True)
        self.assertEqual(saves, [])
        self.assertIn("Sheet Nine", self.app.window.file_alert)

    def test_libreoffice_telling_quill_makes_a_look_at_once(self):
        looks = []
        self.app.refresh_open_files = lambda **kw: looks.append(kw)
        for kind in ("sheet", "opened", "closed"):
            self.app._lo_event(kind, "file:///x.xlsx", "Sheet2")
        self.assertEqual(len(looks), 3)
        self.app._lo_event("lost", "", "")                                  # a dropped link is not news about a document
        self.assertEqual(len(looks), 3)

    def test_the_events_come_from_the_mirror_through_the_windows_own_thread(self):
        from quill.bridge.libreoffice_mirror import LibreOfficeMirror
        got = []
        self.app.lo_mirror = LibreOfficeMirror(use_live=False)
        self.app._wire_lo_events()
        self.app.relay.lo_event.disconnect()
        self.app.relay.lo_event.connect(lambda *a: got.append(a))
        self.app.lo_mirror.on_event("sheet", "file:///x.xlsx", "Sheet2")            # (as the link's thread calls it)
        self.assertEqual(got, [("sheet", "file:///x.xlsx", "Sheet2")])

    def test_following_the_program_to_another_sheet_puts_the_dot_on_the_folder_icon(self):
        answers = [True]
        self.app.controller.follow_sheet = lambda: answers.pop() if answers else False      # (one change, as a program gives)
        self.app._apply_sheet(None, quiet=True)
        self.assertIn("Now on sheet", self.app.window.file_alert)
        self.app.window.open_panel(FILE_PAGE)
        self.assertEqual(self.app.window.file_alert, "")

    def test_a_shake_while_listening_also_plays_the_error_cue_but_a_click_does_not(self):
        cues, shakes = [], []
        self.app.feedback.cue = lambda name, *a, **k: cues.append(name)
        self.app.window.toggle_button.alert = lambda: shakes.append(1)
        self.app._alert_start(False)
        self.assertEqual((cues, len(shakes)), ([], 1))
        self.app._alert_start(True)
        self.assertEqual((cues, len(shakes)), (["error"], 2))


class TestWorkingInTheOpenLibreOfficeDocument(PanelApp):
    """A file that LibreOffice has open and tells Quill about is worked on in the open document (the live bridge), the way a file
    open in live Excel is; a lost link puts Quill back on the file."""

    class FakeLink:
        connected = True

        def __init__(self, urls): self.urls = urls
        def find(self, urls): return {"sheet": "Sheet1"} if any(u in self.urls for u in urls) else None

    def setUp(self):
        super().setUp()
        from quill.bridge.libreoffice_mirror import file_addresses
        global file_addresses_for_fake
        file_addresses_for_fake = file_addresses
        self.link = self.FakeLink(file_addresses(self.plants))
        self.app.lo_mirror = type("M", (), {"live_link": self.link, "on_event": None})()
        self.app._program_holding = lambda path: "libreoffice"
        self.logged = []
        self.app.window.append_log = lambda text, level="info", **kw: self.logged.append((level, text))
        self.made = []
        self.will_not_answer = False
        outer = self

        class FakeLiveBridge(type(self.app.controller.bridge)):
            def __init__(self, path, link):
                super().__init__(path)
                outer.made.append(path)

            def connect(self, workbook=None):
                if outer.will_not_answer:
                    from quill.bridge.base import BridgeError
                    raise BridgeError("LibreOffice is not answering.")
                super().connect(workbook)                       # (reads the file: enough for the app's flows)

            addresses = property(lambda s: file_addresses_for_fake(s._path))
            stamp = 0
            change_stamp = property(lambda s: FakeLiveBridge.stamp)

            def touch(self): FakeLiveBridge.stamp += 1

        patcher = mock.patch("quill.app.LibreOfficeBridge", FakeLiveBridge)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.FakeLiveBridge = FakeLiveBridge

    def test_the_file_is_taken_over_in_the_open_document_and_the_log_says_where_rows_go(self):
        self.assertTrue(self.app._attach_live_if_open_in_libreoffice())
        self.assertIsInstance(self.app.controller.bridge, self.FakeLiveBridge)
        self.assertTrue(self.app.connected)
        self.assertTrue(any("works in it directly" in text and "unsaved" in text for _, text in self.logged))

    def test_not_while_listening_it_waits_for_the_next_look(self):
        self.app.controller.session.listening = True
        self.assertFalse(self.app._attach_live_if_open_in_libreoffice())
        self.assertEqual(self.made, [])

    def test_only_for_a_file_libreoffice_holds_and_the_link_knows(self):
        self.app._program_holding = lambda path: "numbers"
        self.assertFalse(self.app._attach_live_if_open_in_libreoffice())
        self.app._program_holding = lambda path: "libreoffice"
        self.link.urls = []                                       # the link does not know the document
        self.assertFalse(self.app._attach_live_if_open_in_libreoffice())
        self.app.lo_mirror = type("M", (), {"live_link": None})()   # no link at all
        self.assertFalse(self.app._attach_live_if_open_in_libreoffice())
        self.assertEqual(self.made, [])

    def test_a_document_that_will_not_answer_leaves_the_file_as_it_was(self):
        before = self.app.controller.bridge
        self.will_not_answer = True
        self.assertFalse(self.app._attach_live_if_open_in_libreoffice())
        self.assertIs(self.app.controller.bridge, before)
        self.assertTrue(self.app.connected)

    def test_it_is_taken_over_once_not_at_every_look(self):
        self.assertTrue(self.app._attach_live_if_open_in_libreoffice())
        self.assertFalse(self.app._attach_live_if_open_in_libreoffice())
        self.assertEqual(len(self.made), 1)

    def test_an_edit_in_libreoffice_re_reads_the_lists_at_once(self):
        from quill.bridge.libreoffice_mirror import file_addresses
        self.app._attach_live_if_open_in_libreoffice()
        refreshed = []
        self.app.controller.refresh = lambda: refreshed.append(1)
        self.app._remember_mtime()
        for _ in range(4):                                                  # a burst of edits
            self.app._lo_event("changed", file_addresses(self.plants)[0], "")
        self.assertEqual(refreshed, [])                                      # not at each one ...
        self.assertTrue(self.app._lo_changed_timer.isActive())
        self.app._lo_changed_timer.stop()
        self.app._check_workbook_changes()                                   # ... once, when the timer runs out
        self.assertEqual(refreshed, [1])
        self.assertTrue(any("lists and columns re-read" in text for _, text in self.logged))

    def test_an_edit_in_some_other_document_changes_nothing(self):
        self.app._attach_live_if_open_in_libreoffice()
        refreshed = []
        self.app.controller.refresh = lambda: refreshed.append(1)
        self.app._lo_event("changed", "file:///elsewhere.xlsx", "")
        self.assertEqual(refreshed, [])

    def test_the_watcher_asks_the_live_bridge_not_the_file_whether_anything_changed(self):
        self.app._attach_live_if_open_in_libreoffice()
        before = self.app._workbook_mtime()
        self.app.controller.bridge.touch()
        self.assertEqual(self.app._workbook_mtime(), before + 1)

    def test_a_lost_link_puts_quill_back_on_the_saved_file_and_says_so(self):
        self.app._attach_live_if_open_in_libreoffice()
        self.app._back_to_the_file()
        self.assertNotIsInstance(self.app.controller.bridge, self.FakeLiveBridge)
        self.assertEqual(os.path.realpath(self.app.controller.bridge.workbook_path), os.path.realpath(self.plants))
        self.assertTrue(any("link to LibreOffice was lost" in text for _, text in self.logged))


class TestWhatLibreOfficeHasOpenComesFromItsLink(PanelApp):
    def test_the_link_names_the_files_and_sheets_and_no_link_means_ask_the_old_way(self):
        link = type("L", (), {"docs": {"file:///Users/me/My%20Plants.xlsx": {"sheet": "Data"}, "private:factory/scalc": {"sheet": "S"}}})()
        self.app.lo_mirror = type("M", (), {"live_link": link})()
        self.assertEqual(self.app._libreoffice_documents(), [(pathlib.Path("/Users/me/My Plants.xlsx"), "Data")])    # (an unsaved one has no file)
        self.app.lo_mirror = type("M", (), {"live_link": None})()
        self.assertIsNone(self.app._libreoffice_documents())
        self.assertIn("libreoffice", self.app.hosts.live_documents)
