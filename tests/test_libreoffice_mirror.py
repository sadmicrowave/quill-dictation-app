"""Live rows in LibreOffice: the cells Quill writes are also set in the open LibreOffice document."""
import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from quill.bridge import libreoffice_mirror as L
from quill.bridge.libreoffice_mirror import LibreOfficeMirror, change_fields, file_addresses, profile_scripts_dir


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.profile = self.dir / "LibreOffice" / "4" / "user"
        self.profile.mkdir(parents=True)
        self.scripts = self.profile / "Scripts" / "python"
        self.base = self.dir / "mirror"
        self.calls = []
        self.answer = "ok"
        env = mock.patch.dict("os.environ", {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        __import__("os").environ.pop("QUILL_NO_HOSTS", None)

    def runner(self, args):
        self.calls.append(args)
        self.job = json.loads((self.base / "in.json").read_text())
        if self.answer is not None:
            (self.base / "out.json").write_text(self.answer)
        return 0

    def mirror(self, **kw):
        defaults = dict(runner=self.runner, scripts_dir=self.scripts, base=self.base, running=lambda: True,
                        soffice="/x/soffice", wait_s=1)
        defaults.update(kw)
        return LibreOfficeMirror(**defaults)


class TestPushing(Case):
    def test_the_cells_go_to_the_running_program_through_its_user_script(self):
        m = self.mirror()
        result = m.push(self.dir / "a.xlsx", [("Sheet1", 4, 2, "teal"), ("Sheet1", 4, 3, 3.5)])
        self.assertTrue(result.ok)
        self.assertEqual(self.calls[0][0], "/x/soffice")
        self.assertIn("--headless", self.calls[0])                   # (else each call shows a Dock icon for a moment)
        self.assertIn("quill_mirror.py$apply", self.calls[0][-1])
        self.assertEqual(self.job["changes"], [["Sheet1", 4, 2, "s", "teal"], ["Sheet1", 4, 3, "n", "3.5"]])
        self.assertTrue(any(u.endswith("a.xlsx") for u in self.job["urls"]))

    def test_the_cells_are_not_left_on_disk(self):
        self.mirror().push(self.dir / "a.xlsx", [("S", 1, 1, "secret")])
        self.assertFalse((self.base / "in.json").exists())
        self.assertFalse((self.base / "out.json").exists())

    def test_nothing_to_show_does_nothing(self):
        m = self.mirror()
        self.assertTrue(m.push(self.dir / "a.xlsx", []).ok)
        self.assertEqual(self.calls, [])

    def test_it_never_starts_libreoffice(self):
        result = self.mirror(running=lambda: False).push(self.dir / "a.xlsx", [("S", 1, 1, "x")])
        self.assertEqual((result.ok, result.reason), (False, "notrunning"))
        self.assertEqual(self.calls, [])

    def test_not_installed(self):
        with mock.patch.object(L, "find_soffice", return_value=None):
            result = self.mirror(soffice=None).push(self.dir / "a.xlsx", [("S", 1, 1, "x")])
        self.assertEqual(result.reason, "notinstalled")

    def test_the_document_not_being_open_in_it_is_reported(self):
        self.answer = "nodoc"
        self.assertEqual(self.mirror().push(self.dir / "a.xlsx", [("S", 1, 1, "x")]).reason, "nodoc")

    def test_an_error_inside_libreoffice_is_reported(self):
        self.answer = "error boom"
        result = self.mirror().push(self.dir / "a.xlsx", [("S", 1, 1, "x")])
        self.assertEqual((result.ok, result.reason), (False, "error"))

    def test_no_answer_in_time_is_an_error(self):
        self.answer = None
        result = self.mirror(wait_s=0.2).push(self.dir / "a.xlsx", [("S", 1, 1, "x")])
        self.assertEqual(result.reason, "error")

    def test_the_hosts_switch_turns_it_off(self):
        with mock.patch.dict("os.environ", {"QUILL_NO_HOSTS": "1"}):
            self.assertEqual(self.mirror().push(self.dir / "a.xlsx", [("S", 1, 1, "x")]).reason, "disabled")


class TestInstallingTheScript(Case):
    def test_it_is_written_once_and_rewritten_only_when_it_changes(self):
        m = self.mirror()
        self.assertTrue(m.install())
        target = self.scripts / "quill_mirror.py"
        self.assertIn(repr(str(self.base)), target.read_text())
        self.assertTrue(m.installed_note)
        m.installed_note = False
        self.assertTrue(m.install())
        self.assertFalse(m.installed_note)                               # unchanged: not written again
        target.write_text("old")
        self.assertTrue(m.install())
        self.assertIn("Quill live-rows helper", target.read_text())

    def test_without_a_profile_nothing_is_written(self):
        m = self.mirror(scripts_dir=self.dir / "nowhere" / "4" / "user" / "Scripts" / "python")
        self.assertFalse(m.install())
        result = m.push(self.dir / "a.xlsx", [("S", 1, 1, "x")])
        self.assertEqual(result.reason, "noprofile")
        self.assertFalse((self.dir / "nowhere").exists())

    def test_the_script_is_valid_python(self):
        compile(self.mirror().script_text(), "quill_mirror.py", "exec")


class TestHelpers(unittest.TestCase):
    def test_cell_kinds(self):
        self.assertEqual(change_fields("S", 1, 2, None)[3:], ["e", ""])
        self.assertEqual(change_fields("S", 1, 2, "")[3:], ["e", ""])
        self.assertEqual(change_fields("S", 1, 2, 3)[3:], ["n", "3.0"])
        self.assertEqual(change_fields("S", 1, 2, dt.date(2026, 11, 2))[3:], ["d", "2026-11-02"])
        self.assertEqual(change_fields("S", 1, 2, True)[3:], ["s", "True"])
        self.assertEqual(change_fields("S", 1, 2, "a'b\"c")[3:], ["s", "a'b\"c"])           # text is data, never code

    def test_addresses_are_file_uris(self):
        self.assertTrue(all(a.startswith("file:///") for a in file_addresses("/tmp/a b.xlsx")))

    def test_the_profile_folder_per_system(self):
        home = pathlib.Path("/h")
        self.assertEqual(profile_scripts_dir("darwin", home),
                         home / "Library/Application Support/LibreOffice/4/user/Scripts/python")
        self.assertEqual(profile_scripts_dir("linux", home), home / ".config/libreoffice/4/user/Scripts/python")


if __name__ == "__main__":
    unittest.main()
