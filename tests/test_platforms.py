"""The seam between Quill and the operating systems (quill.platforms): what a missing provider means."""
import sys
import unittest
from unittest import mock

from quill import platforms
from quill.bridge.factory import get_bridge


class TestProvider(unittest.TestCase):
    def test_a_system_with_no_provider_offers_nothing(self):
        for system in ("darwin", "linux", "plan9"):
            self.assertIsNone(platforms.provider(system))
            self.assertEqual(platforms.offered(system, "QUIT_LABEL", "Quit Quill"), "Quit Quill")

    def test_a_provider_that_is_not_in_this_build_is_the_same_as_none(self):
        with mock.patch.dict(platforms.NAMES, {"sunos5": "missing_for_this_test"}):
            self.assertIsNone(platforms.provider("sunos5"))

    def test_without_a_live_bridge_for_the_system_the_error_says_to_open_a_file(self):
        with mock.patch.object(sys, "platform", "sunos5"):
            with self.assertRaises(NotImplementedError) as caught:
                get_bridge()
        self.assertIn("Open a spreadsheet file", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
