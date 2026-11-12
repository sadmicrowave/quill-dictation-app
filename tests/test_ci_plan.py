"""Which runners the CI uses (tools/ci_plan.py) and what starts a run (the workflow files): checked here so that the rules cannot drift."""
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ci_plan", ROOT / "tools" / "ci_plan.py")
ci_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_plan)

TESTS = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
DEV = (ROOT / ".github" / "workflows" / "dev-build.yml").read_text(encoding="utf-8")


def systems(matrix):
    return [r["os"] for r in matrix["include"]]


class TestWhichRunners(unittest.TestCase):
    def test_a_pull_request_into_develop_runs_the_quick_pair(self):
        self.assertEqual(systems(ci_plan.plan("pull_request", "develop", ["quill/session.py"])), ["macos-26", "windows-2025"])

    def test_a_change_to_only_windows_files_needs_only_windows(self):
        changed = ["quill/platforms/windows/hosts.py", "packaging/quill_win.iss"]
        self.assertEqual(systems(ci_plan.plan("pull_request", "develop", changed)), ["windows-2025"])

    def test_a_change_to_only_mac_files_needs_only_the_mac(self):
        changed = ["quill/platforms/macos/chrome.py", "tests/macos/test_window_polish.py"]
        self.assertEqual(systems(ci_plan.plan("pull_request", "develop", changed)), ["macos-26"])

    def test_one_shared_file_among_them_brings_back_the_pair(self):
        changed = ["quill/platforms/windows/hosts.py", "quill/session.py"]
        self.assertEqual(systems(ci_plan.plan("pull_request", "develop", changed)), ["macos-26", "windows-2025"])

    def test_the_windows_tests_run_on_both_systems_so_they_are_not_windows_only(self):
        """tests/windows holds tests that run everywhere (fake runners): a change to one still gets the Mac."""
        self.assertEqual(systems(ci_plan.plan("pull_request", "develop", ["tests/windows/test_windows_hosts.py"])), ["macos-26", "windows-2025"])

    def test_nothing_known_about_the_changes_means_both(self):
        self.assertEqual(systems(ci_plan.plan("pull_request", "develop", [])), ["macos-26", "windows-2025"])
        self.assertEqual(systems(ci_plan.plan("pull_request", "develop", ["", "  "])), ["macos-26", "windows-2025"])

    def test_everything_else_uses_every_runner(self):
        every = systems(ci_plan.plan("push"))
        self.assertEqual(len(every), 6)
        for event, base in (("pull_request", "main"), ("push", ""), ("schedule", ""), ("workflow_dispatch", "")):
            self.assertEqual(systems(ci_plan.plan(event, base, ["quill/platforms/windows/x.py"])), every, event)

    def test_the_arm_runner_may_fail(self):
        arm = [r for r in ci_plan.plan("push")["include"] if r["os"] == "windows-11-arm"][0]
        self.assertTrue(arm["experimental"])

    def test_the_script_prints_the_line_the_workflow_appends_to_its_output(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ci_plan.main(["--event", "pull_request", "--base", "develop"])
        self.assertRegex(out.getvalue(), r'^matrix=\{"include":\[.*\]\}\n$')


class TestWhatStartsARun(unittest.TestCase):
    def section(self, text, name):
        match = re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  \w|\Z)", text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0])
        return match.group(1) if match else ""

    def test_a_push_to_a_feature_branch_or_to_develop_starts_no_tests(self):
        self.assertRegex(self.section(TESTS, "push"), r"branches: \[main\]")
        self.assertNotIn('"**"]', self.section(TESTS, "push").split("paths:")[0])

    def test_a_pull_request_into_develop_or_main_does(self):
        pr = self.section(TESTS, "pull_request")
        self.assertIn("branches: [develop, main]", pr)
        self.assertIn("ready_for_review", pr)

    def test_a_draft_pull_request_is_skipped(self):
        self.assertIn("!github.event.pull_request.draft", TESTS)

    def test_the_plan_is_made_by_the_script(self):
        self.assertIn("tools/ci_plan.py", TESTS)
        self.assertIn("fetch-depth: 0", TESTS)

    def test_documentation_still_starts_nothing(self):
        for path in ("!README.md", "!**/README.md", "!docs/**"):
            self.assertGreaterEqual(TESTS.count(path), 2, path)

    def test_the_weekly_full_run_and_the_manual_one_remain(self):
        self.assertIn("cron:", TESTS)
        self.assertIn("workflow_dispatch:", TESTS)

    def test_the_dev_build_starts_only_when_packaging_changes_or_when_asked(self):
        on = DEV.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("branches: [develop]", on)
        self.assertIn('"packaging/**"', on)
        self.assertIn('"requirements*.txt"', on)
        self.assertIn("workflow_dispatch:", on)


if __name__ == "__main__":
    unittest.main()
