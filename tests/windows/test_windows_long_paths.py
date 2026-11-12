"""Paths over 260 characters on Windows: the packaged program is built to use them (when Windows' own setting is on), and when a file cannot be reached
the message says why, instead of "not found" for a file that is there."""
import pathlib
import sys
import unittest
from unittest import mock

from quill.bridge.base import WINDOWS_PATH_LIMIT, BridgeError, long_path_hint
from quill.bridge.xlsx_bridge import XlsxBridge


class TestTheHint(unittest.TestCase):
    def test_a_path_inside_the_limit_gets_no_hint(self):
        self.assertEqual(long_path_hint("C:\\Users\\me\\Stock.xlsx", "win32"), "")
        self.assertEqual(long_path_hint("C:\\" + "a" * 250, "win32"), "")

    def test_a_path_at_or_over_the_limit_gets_one_that_says_how_long_and_what_to_do(self):
        path = "C:\\" + "a" * 300 + "\\Stock.xlsx"
        hint = long_path_hint(path, "win32")
        self.assertIn(str(len(path)), hint)
        self.assertIn("259", hint)
        self.assertIn("shorter path", hint)
        self.assertIn("long paths", hint)

    def test_only_windows_has_the_limit(self):
        self.assertEqual(long_path_hint("/" + "a" * 400, "darwin"), "")
        self.assertEqual(long_path_hint("/" + "a" * 400, "linux"), "")

    def test_the_limit_is_the_one_windows_has(self):
        self.assertEqual(WINDOWS_PATH_LIMIT, 260)


class TestTheMessages(unittest.TestCase):
    def test_a_workbook_that_is_not_there_names_the_path_length_when_it_is_over_the_limit(self):
        path = "C:\\" + "\\".join(["folder with a long name"] * 12) + "\\Stock.xlsx"
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(pathlib.Path, "exists", return_value=False):     # (as Windows says)
            with self.assertRaises(BridgeError) as caught:
                XlsxBridge(path).connect()
        self.assertIn("Workbook not found", str(caught.exception))
        self.assertIn("characters long", str(caught.exception))

    def test_a_short_path_keeps_the_plain_message(self):
        with mock.patch.object(sys, "platform", "win32"):
            with self.assertRaises(BridgeError) as caught:
                XlsxBridge("C:\\nowhere\\Stock.xlsx").connect()
        self.assertEqual(str(caught.exception), "Workbook not found: C:\\nowhere\\Stock.xlsx")


class TestThePackagedProgramIsBuiltForLongPaths(unittest.TestCase):
    """PyInstaller writes the program's manifest. Its default says the program is long-path aware; a spec that gave its own manifest, or a PyInstaller that
    changed the default, would quietly lose that."""

    def test_the_default_manifest_declares_long_path_awareness(self):
        from PyInstaller.utils.win32 import winmanifest
        text = winmanifest._DEFAULT_MANIFEST_XML.decode("utf-8")
        self.assertRegex(text, r"<longPathAware[^>]*>true</longPathAware>")

    def test_the_spec_does_not_replace_the_manifest(self):
        spec = (pathlib.Path(__file__).resolve().parent.parent.parent / "packaging" / "quill_win.spec").read_text(encoding="utf-8")
        self.assertNotIn("manifest=", spec.replace("version_file", ""), "a custom manifest must say longPathAware itself")


if __name__ == "__main__":
    unittest.main()
