"""macOS App Nap stretches the timers of an app whose windows are covered (a 2-second timer fired every 21 seconds while Quill sat behind
Numbers). Quill takes an 'activity' only while its quick look at Numbers is wanted, and gives it back when it is not."""
import os
import unittest
from unittest import mock

from quill.platforms.macos import chrome as mac
from quill.ui import chrome as neutral
from tests.macos.test_titlebar_and_refresh import native, restore


class FakeFoundation:
    NSActivityUserInitiatedAllowingIdleSystemSleep = 0x00FFFFFF & ~(1 << 20)

    class _Info:
        def __init__(self):
            self.begun, self.ended = [], []

        def beginActivityWithOptions_reason_(self, options, reason):
            self.begun.append((options, reason))
            return f"token-{len(self.begun)}"

        def endActivity_(self, token):
            self.ended.append(token)

    info = _Info()

    class NSProcessInfo:
        @staticmethod
        def processInfo():
            return FakeFoundation.info


class TestTheActivity(unittest.TestCase):
    def setUp(self):
        FakeFoundation.info = FakeFoundation._Info()

    def tearDown(self):
        restore()

    def test_begin_takes_a_user_initiated_activity_that_still_lets_the_mac_sleep_when_idle(self):
        native()
        token = mac.begin_activity("why", platform="darwin", foundation=FakeFoundation)
        self.assertEqual(token, "token-1")
        options, reason = FakeFoundation.info.begun[0]
        self.assertEqual(reason, "why")
        self.assertFalse(options & (1 << 20), "idle system sleep is not disabled (NSActivityIdleSystemSleepDisabled)")

    def test_end_gives_it_back(self):
        native()
        mac.end_activity("token-1", platform="darwin", foundation=FakeFoundation)
        self.assertEqual(FakeFoundation.info.ended, ["token-1"])

    def test_ending_nothing_does_nothing(self):
        native()
        mac.end_activity(None, platform="darwin", foundation=FakeFoundation)
        self.assertEqual(FakeFoundation.info.ended, [])

    def test_other_systems_and_headless_runs_take_nothing(self):
        self.assertIsNone(mac.begin_activity("why"))                           # (headless: not the real window system)
        native()
        self.assertIsNone(mac.begin_activity("why", platform="win32", foundation=FakeFoundation))
        self.assertEqual(FakeFoundation.info.begun, [])

    def test_a_failing_system_call_is_never_an_error(self):
        native()

        class Broken:
            NSActivityUserInitiatedAllowingIdleSystemSleep = 1

            class NSProcessInfo:
                @staticmethod
                def processInfo():
                    raise RuntimeError("no")
        self.assertIsNone(mac.begin_activity("why", platform="darwin", foundation=Broken))
        mac.end_activity("t", platform="darwin", foundation=Broken)

    def test_the_neutral_wrappers_forward_to_the_provider_and_do_nothing_elsewhere(self):
        self.assertIsNone(neutral.begin_activity("why", platform="linux"))
        neutral.end_activity("t", platform="linux")


if __name__ == "__main__":
    unittest.main()
