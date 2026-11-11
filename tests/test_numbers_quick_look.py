"""Numbers cannot say that its open sheet changed, so Quill asks. A quicker look than the general check loop runs only while it is worth its
cost (about 0.1 s and 17 ms of CPU per look): while listening (every second), and while a connected file held by Numbers is on a window that
is showing (every two seconds). It stops by itself when none of that is true, and it is never started where hosts are off (the tests)."""
import os
from unittest import mock

from quill.bridge.hosts import OpenFile
from tests.test_app import AppCase


class FakeLink:
    """What the app needs of the live link to Numbers: it is looked at, and it is closed."""

    def __init__(self):
        self.looks = []
        self.sheet_looks = []

    def look(self, deep=True):
        self.looks.append(deep)

    def look_sheet(self, urls):
        self.sheet_looks.append(list(urls))

    def close(self):
        pass


class QuickLookCase(AppCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("QUILL_NO_HOSTS", None)
        self.link = FakeLink()
        self.quill.numbers_link = self.link
        self.quill.run_in_background = lambda work, done: done(work())
        self.path = str(self.quill.controller.bridge.workbook_path)
        self.quill.window.widget.show()
        self.hold_in("Numbers")

    def hold_in(self, program):
        self.quill._open_files = [OpenFile("plants.xlsx", self.path, program)] if program else []
        self.quill._sync_numbers_timer()

    @property
    def timer(self):
        return self.quill._numbers_timer


class TestWhenTheQuickLookRuns(QuickLookCase):
    def test_idle_with_a_file_held_by_numbers_on_a_showing_window_it_looks_every_two_seconds(self):
        self.assertTrue(self.timer.isActive())
        self.assertEqual(self.timer.interval(), self.quill.NUMBERS_IDLE_LOOK_MS)
        self.assertEqual(self.quill.NUMBERS_IDLE_LOOK_MS, 2000)

    def test_listening_it_looks_every_second_and_goes_back_when_listening_stops(self):
        self.hear("start listening")
        self.assertEqual((self.timer.isActive(), self.timer.interval()), (True, self.quill.NUMBERS_LOOK_MS))
        self.hear("stop listening")
        self.assertEqual((self.timer.isActive(), self.timer.interval()), (True, self.quill.NUMBERS_IDLE_LOOK_MS))

    def test_a_look_at_a_file_numbers_merely_holds_asks_the_quick_question(self):
        self.quill._look_at_numbers()
        self.assertEqual(self.link.looks, [False])
        self.assertEqual(self.link.sheet_looks, [])

    def test_working_in_numbers_own_document_asks_only_which_sheet_it_shows(self):
        from quill.platforms.macos.numbers_live import document_names
        self.quill.controller.bridge.PROGRAM = "Numbers"
        self.quill._look_at_numbers()
        self.assertEqual(self.link.sheet_looks, [document_names(self.path)])
        self.assertEqual(self.link.looks, [])


class TestWhenItStops(QuickLookCase):
    def test_working_in_numbers_own_document_keeps_it_going_even_when_the_last_look_lost_the_name(self):
        """Found by watching the ticks: it was gated on the last full look matching the file by name, which flickers (two documents with one
        name, say), so the quick look switched itself off for ten seconds at a time."""
        self.quill.controller.bridge.PROGRAM = "Numbers"
        self.hold_in(None)
        self.assertTrue(self.timer.isActive())
        self.hold_in("LibreOffice")
        self.assertTrue(self.timer.isActive())

    def test_a_file_numbers_does_not_hold_is_not_looked_at_quickly(self):
        self.hold_in("LibreOffice")
        self.assertFalse(self.timer.isActive())
        self.hold_in(None)
        self.assertFalse(self.timer.isActive())

    def test_a_hidden_window_stops_it(self):
        self.quill.window.widget.hide()
        self.quill._sync_numbers_timer()
        self.assertFalse(self.timer.isActive())

    def test_a_minimised_window_stops_it(self):
        self.quill.window.widget.showMinimized()
        self.quill._sync_numbers_timer()
        self.assertFalse(self.timer.isActive())

    def test_no_file_connected_stops_it(self):
        self.quill.controller.detach()
        self.quill.connected = False
        self.quill._sync_numbers_timer()
        self.assertFalse(self.timer.isActive())

    def test_a_tick_that_is_no_longer_wanted_ends_it_without_asking_numbers(self):
        self.hold_in("LibreOffice")
        self.timer.start()                                          # (a tick already queued when the file moved to another program)
        self.quill._look_at_numbers()
        self.assertFalse(self.timer.isActive())
        self.assertEqual(self.link.looks, [])

    def test_never_where_hosts_are_off(self):
        os.environ["QUILL_NO_HOSTS"] = "1"
        self.quill._sync_numbers_timer()
        self.assertFalse(self.timer.isActive())
        self.hear("start listening")
        self.assertFalse(self.timer.isActive())

    def test_without_a_link_there_is_nothing_to_look_with(self):
        self.quill.numbers_link = None
        self.quill._sync_numbers_timer()
        self.assertFalse(self.timer.isActive())

    def test_quitting_stops_it(self):
        self.quill.shutdown()
        self.assertFalse(self.timer.isActive())


class TestItDoesNotChangeWhatListeningDid(QuickLookCase):
    def test_listening_without_numbers_holding_the_file_still_looks_every_second_as_before(self):
        self.hold_in(None)
        self.hear("start listening")
        self.assertEqual((self.timer.isActive(), self.timer.interval()), (True, self.quill.NUMBERS_LOOK_MS))
        self.hear("stop listening")
        self.assertFalse(self.timer.isActive())


class TestASheetChangeIsFollowedAtOnce(QuickLookCase):
    """Found by timing the real thing: the quick look saw a sheet change within two seconds, but it was applied only after the full look at
    every spreadsheet program (a second or two more). The event already says which sheet: apply it directly."""

    def setUp(self):
        super().setUp()
        self.bridge = self.quill.controller.bridge
        self.bridge.PROGRAM = "Numbers"                              # (this bridge now stands for Numbers' open document)
        self.followed, self.looked = [], []
        self.quill._apply_sheet = lambda sheet, quiet: self.followed.append((sheet, quiet))
        self.quill.refresh_open_files = lambda manual=False, announce=False, then=None: self.looked.append("full look")
        self.stem = os.path.splitext(os.path.basename(self.path))[0]

    def test_the_sheet_of_the_document_in_use_is_applied_directly_without_the_full_look(self):
        self.quill._lo_event("sheet", self.stem, "Config")
        self.assertEqual(self.followed, [("Config", True)])
        self.assertEqual(self.looked, [])

    def test_the_name_with_numbers_own_extension_is_the_same_document(self):
        self.quill._lo_event("sheet", self.stem, "Inventory")
        self.assertEqual(self.followed, [("Inventory", True)])

    def test_another_document_takes_the_full_look(self):
        self.quill._lo_event("sheet", "Some other book", "Config")
        self.assertEqual(self.followed, [])
        self.assertEqual(self.looked, ["full look"])

    def test_documents_opening_or_closing_still_take_the_full_look(self):
        for kind in ("opened", "closed"):
            self.quill._lo_event(kind, self.stem, "Inventory")
        self.assertEqual(self.looked, ["full look", "full look"])
        self.assertEqual(self.followed, [])

    def test_a_bridge_that_is_not_numbers_takes_the_full_look(self):
        self.bridge.PROGRAM = "LibreOffice"
        self.quill._lo_event("sheet", self.stem, "Config")
        self.assertEqual((self.followed, self.looked), ([], ["full look"]))

    def test_with_no_file_connected_or_no_sheet_named_it_takes_the_full_look(self):
        self.quill._lo_event("sheet", self.stem, "")
        self.quill.connected = False
        self.quill._lo_event("sheet", self.stem, "Config")
        self.assertEqual((self.followed, self.looked), ([], ["full look", "full look"]))


class TestItIsNotNapped(QuickLookCase):
    """Found by timing: with Quill behind Numbers, macOS App Nap turned the 2-second look into one every 21 s. The quick look holds an activity
    for exactly as long as it runs."""

    def setUp(self):
        super().setUp()
        self.begun, self.ended = [], []
        for name, fn in (("begin_activity", lambda reason: self.begun.append(reason) or f"hold-{len(self.begun)}"),
                         ("end_activity", lambda token: self.ended.append(token))):
            patch = mock.patch(f"quill.app.{name}", fn)
            patch.start()
            self.addCleanup(patch.stop)
        self.quill._release_nap()                                   # (start from a clean slate: setUp of the base already started the look)
        self.begun.clear()
        self.ended.clear()
        self.quill._numbers_timer.stop()

    def test_it_is_held_while_the_quick_look_runs_once_and_not_per_tick(self):
        self.quill._sync_numbers_timer()
        self.quill._sync_numbers_timer()
        self.quill._look_at_numbers()
        self.assertEqual(len(self.begun), 1)
        self.assertEqual(self.ended, [])

    def test_it_is_given_back_when_the_look_stops(self):
        self.quill._sync_numbers_timer()
        self.hold_in(None)                                          # (Numbers no longer holds the file)
        self.assertEqual(self.ended, ["hold-1"])
        self.assertIsNone(self.quill._nap_hold)

    def test_it_is_given_back_when_the_window_is_hidden(self):
        self.quill._sync_numbers_timer()
        self.quill.window.widget.hide()
        self.quill._sync_numbers_timer()
        self.assertEqual(self.ended, ["hold-1"])

    def test_a_tick_that_is_no_longer_wanted_gives_it_back(self):
        self.quill._sync_numbers_timer()
        self.quill.window.widget.hide()
        self.quill._look_at_numbers()
        self.assertEqual(self.ended, ["hold-1"])

    def test_quitting_gives_it_back(self):
        self.quill._sync_numbers_timer()
        self.quill.shutdown()
        self.assertEqual(self.ended, ["hold-1"])

    def test_nothing_is_held_where_the_look_is_not_wanted(self):
        self.hold_in(None)
        self.quill._sync_numbers_timer()
        self.assertEqual(self.begun, [])
