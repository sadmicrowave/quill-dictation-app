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


class FakeTitlebar:
    def __init__(self): self.calls = []
    def set_extra_image(self, index, png, tip, muted, template=True): self.calls.append(("image", index, template, tip)); return True
    def reset_extra_symbol(self, index): self.calls.append(("reset", index)); return True


class TestInTheApp(PanelApp):
    def setUp(self):
        super().setUp()
        self.logged, self.shown = [], []
        self.app.window.append_log = lambda text, level="info", **kw: self.logged.append(text)
        self.titlebar = FakeTitlebar()
        self.app._titlebar = self.titlebar
        patches = [mock.patch("quill.app.info", lambda *a, **k: self.shown.append(("info", a))),
                   mock.patch("quill.app.confirm", lambda parent, title, message, action, *a, **k: self.shown.append(("confirm", title, message)) or False)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def check_with(self, result):
        with mock.patch("quill.updates.check", lambda *a, **k: result):
            self.app.check_for_updates(manual=False)

    def test_a_newer_version_puts_a_red_dot_on_the_settings_icon_and_says_so_once_in_the_log(self):
        newer = UpdateResult("available", latest="9.9.9")
        self.check_with(newer)
        self.check_with(newer)
        self.assertEqual(sum("9.9.9" in line for line in self.logged), 1)
        self.assertTrue(self.app._update_unseen)
        self.assertTrue(self.app.window._update_alert)
        self.assertEqual(self.titlebar.calls[-1][:3], ("image", 2, False))                  # (the title bar's own icon, with the dot)
        self.assertEqual(self.shown, [])                                                     # (nothing pops up)

    def test_an_up_to_date_check_is_silent_and_wears_no_dot(self):
        self.check_with(UpdateResult("current"))
        self.check_with(UpdateResult("unknown", error="offline"))
        self.assertEqual((self.logged, self.shown), ([], []))
        self.assertFalse(self.app._update_unseen)
        self.assertFalse(self.app.window._update_alert)
        self.assertEqual(self.titlebar.calls[-1], ("reset", 2))

    def test_looking_at_about_takes_the_dots_away_and_the_same_version_does_not_bring_them_back(self):
        self.check_with(UpdateResult("available", latest="9.9.9"))
        self.app._about_seen()
        self.assertFalse(self.app._update_unseen)
        self.assertFalse(self.app.window._update_alert)
        self.assertEqual(self.titlebar.calls[-1], ("reset", 2))
        self.check_with(UpdateResult("available", latest="9.9.9"))                           # the next start finds the same one
        self.assertFalse(self.app._update_unseen)
        self.check_with(UpdateResult("available", latest="9.9.10"))                          # a newer one is new news
        self.assertTrue(self.app._update_unseen)

    def test_the_state_the_about_page_shows(self):
        self.assertEqual(self.app.update_state()["available"], False)
        self.check_with(UpdateResult("available", latest="9.9.9"))
        self.assertEqual(self.app.update_state(), {"available": True, "checking": False, "message": "Version 9.9.9 is available."})
        self.check_with(UpdateResult("current"))
        self.assertIn("newest", self.app.update_state()["message"])
        self.check_with(UpdateResult("unknown", error="Couldn't reach the update service."))
        self.assertEqual(self.app.update_state()["message"], "Couldn't reach the update service.")

    def test_settings_opens_on_about_while_an_update_has_not_been_looked_at(self):
        self.check_with(UpdateResult("available", latest="9.9.9"))
        self.app.open_settings()
        try:
            dialog = self.app._settings_dialog
            self.assertEqual(dialog.nav.currentItem().text(), "About")
            self.assertFalse(self.app._update_unseen)                                        # (opening the page was the looking)
            self.assertEqual(dialog.update_button.text(), "Update")
        finally:
            self.app._settings_dialog._dialog.close()

    def test_the_update_button_offers_the_download_and_the_other_button_checks(self):
        self.check_with(UpdateResult("available", latest="9.9.9", notes="Fixes"))
        self.app.update_now()
        self.assertEqual(self.shown[-1][0], "confirm")
        self.assertIn("Fixes", self.shown[-1][2])
        asked = []
        self.app.check_for_updates = lambda manual=True: asked.append(manual)
        self.check_with = None
        self.app._update_result = UpdateResult("current")
        self.app.open_settings("About")
        try:
            self.app._settings_dialog.update_button.click()
            self.assertEqual(asked, [True])
        finally:
            self.app._settings_dialog._dialog.close()

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

    def test_about_quill_in_the_menu_opens_the_about_page_and_there_is_no_popup(self):
        self.app._about()
        try:
            self.assertEqual(self.app._settings_dialog.nav.currentItem().text(), "About")
            self.assertEqual(self.shown, [])
        finally:
            self.app._settings_dialog._dialog.close()


if __name__ == "__main__":
    unittest.main()
