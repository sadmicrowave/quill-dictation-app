"""The seam between Quill and the operating systems (quill.platforms): what a missing provider means."""
import sys
import unittest
from unittest import mock

from quill import platforms
from quill.bridge.factory import get_bridge


class TestProvider(unittest.TestCase):
    def test_a_system_with_no_provider_offers_nothing(self):
        for system in ("linux", "plan9"):
            self.assertIsNone(platforms.provider(system))
            self.assertEqual(platforms.offered(system, "QUIT_LABEL", "Quit Quill"), "Quit Quill")

    def test_macos_has_a_provider_with_a_chrome_module(self):
        self.assertTrue(hasattr(platforms.provider("darwin"), "chrome"))

    def test_a_provider_that_is_not_in_this_build_is_the_same_as_none(self):
        with mock.patch.dict(platforms.NAMES, {"sunos5": "missing_for_this_test"}):
            self.assertIsNone(platforms.provider("sunos5"))

    def test_without_a_live_bridge_for_the_system_the_error_says_to_open_a_file(self):
        with mock.patch.object(sys, "platform", "sunos5"):
            with self.assertRaises(NotImplementedError) as caught:
                get_bridge()
        self.assertIn("Open a spreadsheet file", str(caught.exception))


class TestPackagingKeepsTheProviders(unittest.TestCase):
    """The provider of a system is loaded by name at run time, so the build cannot see it: the specs must name it, and make
    ``collect_submodules("quill")`` able to import the package (a build once shipped without the macOS provider)."""

    def test_each_spec_adds_the_repo_to_the_path_and_names_its_provider(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "packaging"
        for spec, provider in (("quill_mac.spec", "quill.platforms.macos"), ("quill_win.spec", "quill.platforms.windows")):
            text = (root / spec).read_text(encoding="utf-8")
            self.assertIn("sys.path.insert(0, ROOT)", text, spec)
            self.assertIn(f'"{provider}"', text, spec)


if __name__ == "__main__":
    unittest.main()
