"""Checking whether a newer Quill has been released: the comparison, the relay's answer, and what the app does with it."""
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from quill import updates
from quill.updates import UpdateResult, check, is_newer, version_tuple
from tests.test_side_panel_and_turns import PanelApp


class Reply:
    def __init__(self, body): self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
    def read(self): return self._body
    def __enter__(self): return self
    def __exit__(self, *a): return False


def opener_for(body):
    seen = []

    def opener(request, timeout=None):
        seen.append(request)
        if isinstance(body, Exception):
            raise body
        return Reply(body)
    opener.seen = seen
    return opener


class TestVersions(unittest.TestCase):
    def test_versions_read_by_their_numbers(self):
        self.assertEqual(version_tuple("v0.2.10-beta"), (0, 2, 10))
        self.assertEqual(version_tuple("1.4"), (1, 4))
        self.assertEqual(version_tuple("nonsense"), ())

    def test_only_a_newer_release_is_an_update(self):
        self.assertTrue(is_newer("0.2.0", "0.1.0"))
        self.assertTrue(is_newer("0.10.0", "0.9.9"))             # (numbers, not text: 10 > 9)
        self.assertTrue(is_newer("1.0", "0.9.9"))
        self.assertFalse(is_newer("0.1.0", "0.1.0"))
        self.assertFalse(is_newer("1.2", "1.2.0"))
        self.assertFalse(is_newer("0.1.0", "0.2.0"))             # a copy built from newer sources is not told to go back
        self.assertFalse(is_newer("", "0.1.0"))
        self.assertFalse(is_newer("0.2.0", "dev"))


class TestTheCheck(unittest.TestCase):
    URL = "https://relay.example/latest"

    def ask(self, body, current="0.1.0"):
        opener = opener_for(body)
        return check(current, self.URL, opener), opener

    def test_a_newer_release_is_available_with_its_page_and_notes(self):
        result, opener = self.ask({"ok": True, "version": "0.2.0", "url": "https://github.com/o/r/releases/tag/v0.2.0", "notes": "Fixes"})
        self.assertEqual((result.status, result.latest, result.notes), ("available", "0.2.0", "Fixes"))
        self.assertEqual(result.url, "https://github.com/o/r/releases/tag/v0.2.0")
        self.assertEqual(opener.seen[0].get_method(), "GET")
        self.assertEqual(opener.seen[0].get_header("User-agent"), "Quill/0.1.0")        # the only thing sent besides the request itself

    def test_the_same_or_an_older_release_is_current(self):
        self.assertEqual(self.ask({"ok": True, "version": "0.1.0"})[0].status, "current")
        self.assertEqual(self.ask({"ok": True, "version": "0.0.9"})[0].status, "current")

    def test_nothing_published_yet_is_current(self):
        self.assertEqual(self.ask({"ok": True, "version": None})[0].status, "current")

    def test_a_page_that_is_not_on_github_is_not_followed(self):
        result, _ = self.ask({"ok": True, "version": "0.2.0", "url": "https://evil.example/download"})
        self.assertEqual(result.url, updates.RELEASES_URL)

    def test_every_failure_is_unknown_with_a_sentence_and_never_raises(self):
        cases = [urllib.error.HTTPError(self.URL, 502, "bad", {}, io.BytesIO(b"")), OSError("offline"), b"not json", {"ok": False}, ["x"]]
        for body in cases:
            result, _ = self.ask(body)
            self.assertEqual(result.status, "unknown", body)
            self.assertTrue(result.error)

    def test_only_https_is_used(self):
        self.assertEqual(check("0.1.0", "http://relay.example/latest", opener_for({"ok": True, "version": "9"})).status, "unknown")
        self.assertEqual(check("0.1.0", "", opener_for({})).status, "unknown")


class TestInTheApp(PanelApp):
    def setUp(self):
        super().setUp()
        self.logged, self.shown = [], []
        self.app.window.append_log = lambda text, level="info", **kw: self.logged.append(text)
        patches = [mock.patch("quill.app.info", lambda parent, title, message, *a, **k: self.shown.append(("info", title, message))),
                   mock.patch("quill.app.confirm", lambda parent, title, message, action, *a, **k: self.shown.append(("confirm", title, message)) or False)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def check_with(self, result, manual):
        with mock.patch("quill.updates.check", lambda *a, **k: result):
            self.app.check_for_updates(manual=manual)

    def test_a_newer_version_says_so_once_in_the_log_and_in_the_help_menu(self):
        newer = UpdateResult("available", latest="9.9.9")
        self.check_with(newer, manual=False)
        self.check_with(newer, manual=False)
        self.assertEqual(sum("9.9.9" in line for line in self.logged), 1)
        self.assertEqual(self.app.menus.state.update_version, "9.9.9")
        self.assertIn("Update Available: Quill 9.9.9", self.app.menus.actions()["check_updates"].text())
        self.assertEqual(self.shown, [])                                    # (the start-up check never interrupts)

    def test_an_up_to_date_start_check_is_silent(self):
        self.check_with(UpdateResult("current"), manual=False)
        self.check_with(UpdateResult("unknown", error="offline"), manual=False)
        self.assertEqual((self.logged, self.shown), ([], []))
        self.assertEqual(self.app.menus.actions()["check_updates"].text(), "Check for Updates…")

    def test_a_check_the_person_asked_for_always_answers(self):
        self.check_with(UpdateResult("current"), manual=True)
        self.check_with(UpdateResult("unknown", error="offline"), manual=True)
        self.check_with(UpdateResult("available", latest="9.9.9", notes="Fixes"), manual=True)
        self.assertEqual([kind for kind, *_ in self.shown], ["info", "info", "confirm"])
        self.assertIn("offline", self.shown[1][2])
        self.assertIn("Fixes", self.shown[2][2])

    def test_the_menu_entry_offers_a_known_update_without_asking_again(self):
        self.check_with(UpdateResult("available", latest="9.9.9"), manual=False)
        asked = []
        self.app.check_for_updates = lambda manual=True: asked.append(manual)
        self.app.check_updates_from_menu()
        self.assertEqual(asked, [])
        self.assertEqual(self.shown[-1][0], "confirm")

    def test_the_start_check_obeys_the_setting_and_the_tests_own_switch(self):
        calls = []
        self.app.check_for_updates = lambda manual=True: calls.append(manual)
        with mock.patch.dict(os.environ):
            os.environ.pop("QUILL_NO_HOSTS", None)
            self.app.settings.preferences["check_for_updates"] = False
            self.app._check_at_start()
            self.assertEqual(calls, [])
            self.app.settings.preferences["check_for_updates"] = True
            self.app._check_at_start()
            self.assertEqual(calls, [False])
            os.environ["QUILL_NO_HOSTS"] = "1"
            self.app._check_at_start()
            self.assertEqual(calls, [False])


if __name__ == "__main__":
    unittest.main()
