"""The job runner of the Windows test VM and the Mac's ``send_job``: jobs left in a shared folder are run once, oldest first, and answered with a
``result.json``. (The runner and the journey scripts are plain Python, so all of this is tried here on any machine; only the real Windows run is the VM's.)"""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner_module = load("quill_jobrunner", "tools/windows-vm/jobrunner.py")
send = load("quill_send_job", "tools/windows-vm/send_job.py")


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.share = pathlib.Path(self._tmp.name) / "share"
        self.work = pathlib.Path(self._tmp.name) / "work"
        self.runner = runner_module.Runner(self.share, self.work)

    def result(self, job_id):
        return json.loads((self.share / "out" / job_id / "result.json").read_text(encoding="utf-8"))


class TestSendingAJob(Case):
    def test_a_job_is_a_json_file_in_the_jobs_folder(self):
        job_id = send.submit(self.share, "ping", {"hello": 1})
        data = json.loads((self.share / "jobs" / f"{job_id}.json").read_text(encoding="utf-8"))
        self.assertEqual((data["id"], data["kind"], data["args"]), (job_id, "ping", {"hello": 1}))

    def test_two_jobs_of_one_kind_get_two_ids(self):
        a, b = send.submit(self.share, "ping"), send.submit(self.share, "ping")
        self.assertNotEqual(a, b)

    def test_no_half_written_file_is_ever_a_job(self):
        send.submit(self.share, "ping")
        self.assertEqual(list((self.share / "jobs").glob("*.tmp")), [])

    def test_the_runner_reads_only_finished_json_files(self):
        (self.share / "jobs" / "x.tmp").write_text("{", encoding="utf-8")
        self.assertFalse(self.runner.poll_once())

    def test_waiting_gives_up_after_the_time_it_was_given(self):
        job_id = send.submit(self.share, "ping")
        ticks = []
        self.assertIsNone(send.wait(self.share, job_id, timeout=0.05, poll=0.01, sleep=lambda s: ticks.append(s) or time.sleep(0.02)))

    def test_the_runners_pulse_says_whether_it_is_alive(self):
        self.assertIsNone(send.runner_age(self.share))
        self.runner.heartbeat()
        self.assertLess(send.runner_age(self.share), 5)


class TestRunningJobs(Case):
    def test_a_ping_is_answered_and_the_job_file_moves_to_done(self):
        job_id = send.submit(self.share, "ping", {"x": 1})
        self.assertTrue(self.runner.poll_once())
        outcome = self.result(job_id)
        self.assertEqual(outcome["status"], "passed")
        self.assertIn("runner is up", outcome["summary"])
        self.assertTrue((self.share / "jobs" / "done" / f"{job_id}.json").is_file())
        self.assertEqual(list((self.share / "jobs").glob("*.json")), [])

    def test_the_oldest_job_runs_first_and_each_runs_once(self):
        first = send.submit(self.share, "ping")
        time.sleep(0.02)
        second = send.submit(self.share, "ping")
        self.assertTrue(self.runner.poll_once())
        self.assertTrue((self.share / "out" / first / "result.json").is_file())
        self.assertFalse((self.share / "out" / second / "result.json").is_file())
        self.assertTrue(self.runner.poll_once())
        self.assertFalse(self.runner.poll_once())

    def test_an_unknown_kind_is_an_error_not_a_crash(self):
        job_id = send.submit(self.share, "make-coffee")
        self.runner.poll_once()
        outcome = self.result(job_id)
        self.assertEqual(outcome["status"], "error")
        self.assertIn("unknown job kind", outcome["summary"])

    def test_a_job_that_raises_is_reported_with_its_traceback_and_the_runner_goes_on(self):
        runner = runner_module.Runner(self.share, self.work, handlers={"boom": lambda r, j, f: 1 / 0, "ping": runner_module.handle_ping})
        bad = send.submit(self.share, "boom")
        good = send.submit(self.share, "ping")
        runner.poll_once()
        runner.poll_once()
        self.assertEqual(self.result(bad)["status"], "error")
        self.assertIn("ZeroDivisionError", json.dumps(self.result(bad)))
        self.assertEqual(self.result(good)["status"], "passed")

    def test_an_unreadable_job_file_is_an_error(self):
        (self.share / "jobs").mkdir(parents=True, exist_ok=True)
        (self.share / "jobs" / "broken.json").write_text("{not json", encoding="utf-8")
        self.runner.poll_once()
        self.assertEqual(self.result("broken")["status"], "error")

    def test_the_answer_says_when_and_how_long(self):
        job_id = send.submit(self.share, "ping")
        self.runner.poll_once()
        outcome = self.result(job_id)
        for key in ("id", "kind", "started", "finished", "seconds"):
            self.assertIn(key, outcome)


class TestTheKindsOfJob(Case):
    def test_sync_copies_the_code_the_mac_left(self):
        src = self.share / "src"
        (src / "quill").mkdir(parents=True)
        (src / "main.py").write_text("print('hi')", encoding="utf-8")
        (src / "quill" / "_build.py").write_text('BUILD = "abc123 on test"', encoding="utf-8")
        job_id = send.submit(self.share, "sync", {"no_install": True})
        self.runner.poll_once()
        outcome = self.result(job_id)
        self.assertEqual(outcome["status"], "passed", outcome)
        self.assertIn("abc123", outcome["summary"])
        self.assertTrue((self.work / "src" / "main.py").is_file())

    def test_sync_says_so_when_there_is_no_code(self):
        job_id = send.submit(self.share, "sync")
        self.runner.poll_once()
        self.assertEqual(self.result(job_id)["status"], "error")

    def test_pytest_runs_the_tests_it_is_asked_for_and_reports_the_summary(self):
        src = self.work / "src"
        src.mkdir(parents=True)
        (src / "test_probe.py").write_text("def test_a():\n    assert True\n\ndef test_b():\n    assert 1 + 1 == 2\n", encoding="utf-8")
        job_id = send.submit(self.share, "pytest", {"paths": ["test_probe.py"]})
        self.runner.poll_once()
        outcome = self.result(job_id)
        self.assertEqual(outcome["status"], "passed", outcome)
        self.assertIn("2 passed", outcome["summary"])
        self.assertTrue((self.share / "out" / job_id / "junit.xml").is_file())

    def test_a_failing_test_is_a_failed_job_with_the_failure_in_the_log(self):
        src = self.work / "src"
        src.mkdir(parents=True)
        (src / "test_probe.py").write_text("def test_a():\n    assert False, 'no luck'\n", encoding="utf-8")
        job_id = send.submit(self.share, "pytest", {"paths": ["test_probe.py"]})
        self.runner.poll_once()
        self.assertEqual(self.result(job_id)["status"], "failed")
        self.assertIn("no luck", (self.share / "out" / job_id / "log.txt").read_text(encoding="utf-8"))

    def test_a_journey_script_reports_its_checks(self):
        script = self.work / "src" / "tools" / "vm_journeys"
        script.mkdir(parents=True)
        (script / "looks.py").write_text(
            "import argparse, json, pathlib\np = argparse.ArgumentParser(); p.add_argument('--out'); a = p.parse_args()\n"
            "pathlib.Path(a.out, 'checks.json').write_text(json.dumps([{'name': 'one', 'ok': True}, {'name': 'two', 'ok': False, 'detail': 'broke'}]))\n", encoding="utf-8")
        job_id = send.submit(self.share, "looks")
        self.runner.poll_once()
        outcome = self.result(job_id)
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("1 of 2", outcome["summary"])
        self.assertIn("two", outcome["summary"])

    def test_a_journey_script_that_dies_before_its_checks_is_an_error(self):
        script = self.work / "src" / "tools" / "vm_journeys"
        script.mkdir(parents=True)
        (script / "looks.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        job_id = send.submit(self.share, "looks")
        self.runner.poll_once()
        self.assertEqual(self.result(job_id)["status"], "error")

    def test_a_missing_script_says_to_sync_first(self):
        job_id = send.submit(self.share, "dictation")
        self.runner.poll_once()
        self.assertIn("sync", self.result(job_id)["summary"])


class TestTheReport(Case):
    def test_a_failed_check_is_listed_with_its_detail(self):
        job_id = send.submit(self.share, "ping")
        self.runner.poll_once()
        outcome = self.result(job_id)
        outcome["checks"] = [{"name": "bad one", "ok": False, "detail": "why"}]
        text = send.report(self.share, outcome)
        self.assertIn("FAILED bad one: why", text)
        self.assertIn("PASSED", text)

    def test_the_main_function_waits_for_the_answer_a_runner_gives(self):
        import threading
        stop = []
        thread = threading.Thread(target=lambda: self.runner.serve(stop=lambda: bool(stop)), daemon=True)
        runner_module.POLL_SECONDS = 0.05
        thread.start()
        try:
            code = send.main(["ping", "--share", str(self.share), "--wait", "10"])
        finally:
            stop.append(1)
            thread.join(3)
        self.assertEqual(code, 0)


class TestStartingWithWindows(Case):
    def test_the_launcher_starts_the_runner_with_no_window_and_quotes_its_paths(self):
        text = runner_module.launcher_text(r"C:\QuillTest\venv\Scripts\python.exe", pathlib.Path(r"C:\QuillTest\jobrunner\jobrunner.py"),
                                           r"\\vmware-host\Shared Folders\QuillShare")
        self.assertIn("pythonw.exe", text)
        self.assertIn("Run", text)
        self.assertTrue(text.rstrip().endswith(", 0, False"))                 # window style 0: hidden; do not wait
        self.assertIn('Shared Folders', text)

    def test_install_and_uninstall_keep_a_launcher_in_the_startup_folder(self):
        import os
        with tempfile.TemporaryDirectory() as appdata:
            old = os.environ.get("APPDATA")
            os.environ["APPDATA"] = appdata
            old_work = runner_module.WORK
            runner_module.WORK = self.work
            try:
                launcher = runner_module.install(str(self.share))
                self.assertTrue(launcher.is_file())
                self.assertTrue((self.work / "jobrunner" / "jobrunner.py").is_file())
                self.assertTrue(runner_module.uninstall())
                self.assertFalse(launcher.exists())
                self.assertFalse(runner_module.uninstall())
            finally:
                runner_module.WORK = old_work
                if old is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old


class TestTheJourneyScripts(unittest.TestCase):
    """Each script is tried here with the headless display (its real run is on the VM's screen)."""

    def run_script(self, name: str):
        with tempfile.TemporaryDirectory() as out:
            done = subprocess.run([sys.executable, str(ROOT / "tools" / "vm_journeys" / f"{name}.py"), "--out", out, "--offscreen"],
                                  capture_output=True, text=True, timeout=300, check=False)
            checks_file = pathlib.Path(out) / "checks.json"
            checks = json.loads(checks_file.read_text(encoding="utf-8")) if checks_file.is_file() else []
            shots = sorted(p.name for p in pathlib.Path(out).glob("*.png"))
        return done, checks, shots

    def test_looks_runs_and_every_check_holds(self):
        done, checks, shots = self.run_script("looks")
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        self.assertGreaterEqual(len(checks), 15)
        self.assertEqual([c for c in checks if not c["ok"]], [])
        self.assertIn("main-light.png", shots)
        self.assertIn("mini-dark.png", shots)

    def test_dictation_runs_and_every_check_holds(self):
        done, checks, shots = self.run_script("dictation")
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        self.assertGreaterEqual(len(checks), 12)
        self.assertEqual([c for c in checks if not c["ok"]], [])
        self.assertIn("dictation-row-heard.png", shots)

    def test_libreoffice_says_it_is_for_windows_anywhere_else(self):
        if sys.platform == "win32":
            self.skipTest("this is the machine it is for")
        done, checks, _ = self.run_script("libreoffice")
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        self.assertTrue(all(c["ok"] and "skipped" in c["detail"] for c in checks))


if __name__ == "__main__":
    unittest.main()
