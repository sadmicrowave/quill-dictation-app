"""The Windows installer and the app folder it installs (what is checked here is the recipe; the workflows install it for real on a Windows runner
and run the installed program's self-check, then uninstall it).

A one-file exe unpacks itself to a temporary folder on every start; the app is a folder that an installer puts on the PC once.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SPEC = (ROOT / "packaging" / "quill_win.spec").read_text(encoding="utf-8")
ISS = (ROOT / "packaging" / "quill_win.iss").read_text(encoding="utf-8")
DEV = (ROOT / ".github" / "workflows" / "dev-build.yml").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def setup_section():
    body = ISS.split("[Setup]", 1)[1].split("\n[", 1)[0]
    return dict(line.split("=", 1) for line in body.splitlines() if "=" in line and not line.lstrip().startswith(";"))


class TestTheAppFolder(unittest.TestCase):
    def test_the_spec_builds_a_folder_not_one_self_extracting_file(self):
        self.assertIn("exclude_binaries=True", SPEC)
        self.assertRegex(SPEC, r"COLLECT\(exe, a\.binaries, a\.datas, name=\"Quill\"\)")
        self.assertNotRegex(SPEC, r"EXE\(pyz, a\.scripts, a\.binaries")                  # (the one-file form)

    def test_the_version_resource_is_still_written(self):
        self.assertIn("version=version_file", SPEC)


class TestTheInstallerScript(unittest.TestCase):
    def test_it_installs_for_the_current_user_without_administrator_rights(self):
        s = setup_section()
        self.assertEqual(s["PrivilegesRequired"], "lowest")
        self.assertTrue(s["DefaultDirName"].startswith("{localappdata}"), s["DefaultDirName"])

    def test_it_has_a_fixed_app_id_so_a_newer_one_replaces_an_older_install(self):
        self.assertRegex(setup_section()["AppId"], r"^\{\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")
        self.assertIn("33741EDA-7E33-45C3-8003-3839F089C0DE", ISS)                      # (never change it: it is how Windows knows it is the same program)

    def test_it_takes_the_folder_the_spec_makes_and_makes_the_file_the_site_names(self):
        self.assertIn(r'Source: "..\dist\Quill\*"', ISS)
        s = setup_section()
        self.assertEqual(s["OutputBaseFilename"], "Quill-Setup")
        self.assertEqual(s["OutputDir"], r"..\dist\installer")

    def test_the_version_comes_from_the_command_line_and_has_a_default(self):
        self.assertIn("#ifndef AppVersion", ISS)
        self.assertEqual(setup_section()["AppVersion"], "{#AppVersion}")

    def test_it_makes_the_start_menu_entry_and_offers_a_desktop_one(self):
        self.assertIn(r'Name: "{autoprograms}\Quill"; Filename: "{app}\Quill.exe"', ISS)
        self.assertRegex(ISS, r'Name: "desktopicon".*Flags: unchecked')

    def test_it_closes_a_running_quill_before_replacing_it(self):
        self.assertEqual(setup_section()["CloseApplications"], "yes")

    def test_it_is_64_bit_only_like_the_build(self):
        self.assertIn("x64compatible", setup_section()["ArchitecturesAllowed"])

    def test_the_users_own_data_is_not_removed_by_an_uninstall(self):
        self.assertNotIn("[UninstallDelete]", ISS)


class TestTheWorkflows(unittest.TestCase):
    def test_both_build_the_installer_with_the_apps_version(self):
        for name, text in (("dev-build", DEV), ("release", RELEASE)):
            with self.subTest(name):
                self.assertIn("ISCC.exe", text)
                self.assertIn("/DAppVersion=", text)
                self.assertIn("packaging/quill_win.iss", text)

    def test_both_install_it_silently_check_the_installed_program_and_uninstall_it(self):
        for name, text in (("dev-build", DEV), ("release", RELEASE)):
            with self.subTest(name):
                self.assertIn("/VERYSILENT", text)
                self.assertIn("unins000.exe", text)
                self.assertRegex(text, r'"--selftest", "--out", "selfcheck')
                self.assertIn("left Quill.exe behind", text)

    def test_the_release_attaches_both_downloads_and_says_which_is_which(self):
        self.assertIn('extra: "Quill-Setup.exe"', RELEASE)
        self.assertIn("Windows: Quill-Setup.exe", RELEASE)
        self.assertIn("Quill-windows.zip", RELEASE)

    def test_nothing_still_expects_the_one_file_exe(self):
        offenders = []
        for path in list(ROOT.glob("*.md")) + list((ROOT / "docs").glob("*.md")) + list((ROOT / "packaging").glob("*")) + list(
                (ROOT / ".github" / "workflows").glob("*.yml")) + list((ROOT / "tools").glob("*.bat")):
            if path.name in ("development-history.md", "quill_win.iss") or not path.is_file():
                continue
            if re.search(r"dist[\\/]Quill\.exe", path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_the_version_the_workflow_reads_is_the_one_the_spec_reads(self):
        init = (ROOT / "quill" / "__init__.py").read_text(encoding="utf-8")
        self.assertRegex(init, r'__version__ = "[^"]+"')
        self.assertIn("quill/__init__.py", DEV)
        self.assertIn('__version__ = "([^"]+)"', DEV)


if __name__ == "__main__":
    unittest.main()
