"""Title-bar resize icon, in-place always-on-top, the two-phase mini animation, and auto-refresh."""
import os
import pathlib
import tempfile
import unittest

import openpyxl
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

import quill.app as app_module
from quill.app import QuillApp
from quill.bridge.base import BridgeError
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.platforms.macos import chrome
from quill.ui.main_window import MainWindow
from tests.fixtures import make_workbook
from tests.test_app import FakeListener, FakeSpeaker
from tests.test_sorting import DemoCase

_app = QApplication.instance() or QApplication([])


# ---- fakes for AppKit ----------------------------------------------------------------------

class FakeNSWindow:
    def __init__(self):
        self.level, self.accessories = 0, []

    def setLevel_(self, level): self.level = level
    def addTitlebarAccessoryViewController_(self, vc): self.accessories.append(vc)
    def titlebarAccessoryViewControllers(self): return list(self.accessories)
    def removeTitlebarAccessoryViewControllerAtIndex_(self, index): del self.accessories[index]


class FakeButton:
    def __init__(self):
        self.image, self.tip, self.target, self.action, self.bordered = None, "", None, None, True

    @classmethod
    def alloc(cls): return cls()
    def initWithFrame_(self, frame): self.frame = frame; return self
    def setBordered_(self, v): self.bordered = v
    def setFrame_(self, frame): self.frame = frame
    def setTarget_(self, t): self.target = t
    def setAction_(self, a): self.action = a
    def setImage_(self, image): self.image = image
    def setToolTip_(self, tip): self.tip = tip
    def performClick_(self, sender): self.target.toggle_(self)


class FakeHolderView:
    """A plain view the icons' row sits in (it is what the title bar gets)."""
    def __init__(self): self.subviews = []

    @classmethod
    def alloc(cls): return cls()
    def initWithFrame_(self, frame): self.frame = frame; return self
    def addSubview_(self, view): self.subviews.append(view)
    def setFrame_(self, frame): self.frame = frame
    def setFrameOrigin_(self, origin): self.origin = origin
    def setFrameSize_(self, size): self.size = size


class FakeController:
    def __init__(self): self.view, self.layout, self.removed, self.identifier_ = None, None, False, ""

    @classmethod
    def alloc(cls): return cls()
    def init(self): return self
    def setView_(self, v): self.view = v
    def setLayoutAttribute_(self, a): self.layout = a
    def setIdentifier_(self, name): self.identifier_ = name
    def identifier(self): return self.identifier_
    def removeFromParentViewController(self): self.removed = True


class FakeTarget:
    @classmethod
    def alloc(cls): return cls()
    def initWithCallback_(self, cb): self.cb = cb; return self
    def toggle_(self, sender): self.cb()


class FakeAppKit:
    TargetClass = FakeTarget
    NSButton = FakeButton
    NSTitlebarAccessoryViewController = FakeController
    NSView = FakeHolderView

    def __init__(self, window=None):
        self.window = window or FakeNSWindow()
        self.NSImage = type("I", (), {"imageWithSystemSymbolName_accessibilityDescription_":
                                      staticmethod(lambda name, text: f"image:{name}")})

    def view_for(self, view_id):
        window = self.window
        return type("V", (), {"window": lambda s: window})()


def native(monkey=True):
    """Pretend Qt is running on the real window system (the offscreen guard is bypassed)."""
    chrome._native_platform = lambda platform: True


def restore():
    chrome.__dict__.pop("_native_platform", None)


class TestAlwaysOnTop(unittest.TestCase):
    def tearDown(self):
        restore()

    def test_headless_falls_back_to_the_qt_flag(self):
        self.assertFalse(chrome.set_always_on_top(QWidget(), True))

    def test_macos_sets_the_window_level_in_place(self):
        native()
        kit = FakeAppKit()
        self.assertTrue(chrome.set_always_on_top(QWidget(), True, platform="darwin", appkit=kit))
        self.assertEqual(kit.window.level, 3)
        self.assertTrue(chrome.set_always_on_top(QWidget(), False, platform="darwin", appkit=kit))
        self.assertEqual(kit.window.level, 0)


    def test_errors_fall_back_quietly(self):
        native()
        class Boom:
            def view_for(self, i): raise RuntimeError("no")
        self.assertFalse(chrome.set_always_on_top(QWidget(), True, platform="darwin", appkit=Boom()))

    def test_a_view_without_a_window_falls_back(self):
        native()
        kit = FakeAppKit()
        kit.view_for = lambda i: type("V", (), {"window": lambda s: None})()
        self.assertFalse(chrome.set_always_on_top(QWidget(), True, platform="darwin", appkit=kit))


class TestTitlebarButton(unittest.TestCase):
    def tearDown(self):
        restore()

    def test_not_available_headless_or_off_macos(self):
        self.assertIsNone(chrome.add_titlebar_button(QWidget(), lambda: None))
        native()
        self.assertIsNone(chrome.add_titlebar_button(QWidget(), lambda: None, platform="win32"))

    def test_adds_a_borderless_icon_at_the_right_of_the_title_bar(self):
        native()
        kit = FakeAppKit()
        button = chrome.add_titlebar_button(QWidget(), lambda: None, platform="darwin", appkit=kit)
        self.assertIsNotNone(button)
        controller = kit.window.accessories[0]
        self.assertEqual(controller.layout, 2)                         # NSLayoutAttributeRight
        self.assertFalse(button._button.bordered)                      # just the icon, no box
        self.assertEqual(button._button.action, "toggle:")

    def test_asking_again_for_the_same_side_never_leaves_two_rows_on_the_window(self):
        """Found on screen: the main window showed two rows of icons drawn over each other, because the system keeps every row it is given."""
        native()
        kit = FakeAppKit()
        widget = QWidget()
        for _ in range(3):
            chrome.add_titlebar_button(widget, lambda: None, platform="darwin", appkit=kit)
            chrome.add_titlebar_button(widget, lambda: None, symbol="undo", side="left", platform="darwin", appkit=kit)
        self.assertEqual(sorted(c.layout for c in kit.window.accessories), [1, 2])      # one left row and one right row, nothing more
        self.assertEqual(sorted(c.identifier() for c in kit.window.accessories),
                         ["quillTitlebarIcons-left", "quillTitlebarIcons-right"])

    def test_a_row_another_part_of_the_app_put_on_is_not_removed(self):
        native()
        kit = FakeAppKit()
        other = FakeController()
        other.setIdentifier_("somethingElse")
        kit.window.addTitlebarAccessoryViewController_(other)
        chrome.add_titlebar_button(QWidget(), lambda: None, platform="darwin", appkit=kit)
        self.assertIn(other, kit.window.accessories)

    def test_clicking_it_calls_back(self):
        native()
        calls = []
        button = chrome.add_titlebar_button(QWidget(), lambda: calls.append(1), platform="darwin", appkit=FakeAppKit())
        button.click()
        button.click()
        self.assertEqual(calls, [1, 1])

    def test_the_icon_follows_the_view(self):
        native()
        button = chrome.add_titlebar_button(QWidget(), lambda: None, mini=False, platform="darwin", appkit=FakeAppKit())
        self.assertEqual(button._button.image, f"image:{chrome.SYMBOL_MINI}")
        self.assertEqual(button._button.tip, "Mini View")
        button.set_mini(True)
        self.assertEqual(button._button.image, f"image:{chrome.SYMBOL_FULL}")
        self.assertEqual(button._button.tip, "Back to the Full Window")

    def test_starting_in_mini_shows_the_back_icon(self):
        native()
        button = chrome.add_titlebar_button(QWidget(), lambda: None, mini=True, platform="darwin", appkit=FakeAppKit())
        self.assertEqual(button._button.image, f"image:{chrome.SYMBOL_FULL}")

    def test_can_be_removed(self):
        native()
        kit = FakeAppKit()
        button = chrome.add_titlebar_button(QWidget(), lambda: None, platform="darwin", appkit=kit)
        button.remove()
        self.assertTrue(kit.window.accessories[0].removed)

    def test_errors_return_none(self):
        native()
        class Boom:
            def view_for(self, i): raise RuntimeError("no")
            TargetClass = FakeTarget
        self.assertIsNone(chrome.add_titlebar_button(QWidget(), lambda: None, platform="darwin", appkit=Boom()))


class TestTwoPhaseAnimation(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.resize(460, 620)
        self.w.widget.show()
        _app.processEvents()
        MainWindow.animation_ms = 150

    def tearDown(self):
        MainWindow.animation_ms = 0

    def wait(self):
        QTest.qWait(330)

    def test_entering_keeps_the_full_contents_while_the_window_shrinks_then_swaps(self):
        self.w.set_mini(True)
        self.assertFalse(self.w._view_mini, "the full contents stay until the window has shrunk")
        self.assertTrue(self.w.log_toggle.isVisibleTo(self.w.widget))
        self.assertTrue(self.w.mini)
        self.wait()
        self.assertTrue(self.w._view_mini)
        self.assertFalse(self.w.log_toggle.isVisibleTo(self.w.widget))
        self.assertEqual(self.w.widget.width(), MainWindow.MINI_WIDTH)

    def test_leaving_grows_the_window_first_then_swaps_to_the_full_contents(self):
        self.w.set_mini(True)
        self.wait()
        self.w.set_mini(False)
        self.assertTrue(self.w._view_mini, "the mini contents stay while the window grows")
        self.wait()
        self.assertFalse(self.w._view_mini)
        self.assertTrue(self.w.log_toggle.isVisibleTo(self.w.widget))
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (460, 620))

    def test_the_height_passes_through_in_between_values(self):
        seen = []
        self.w.set_mini(True)
        for _ in range(12):
            QTest.qWait(15)
            seen.append(self.w.widget.height())
        self.assertGreater(len(set(seen)), 4, seen)
        self.assertTrue(any(300 < h < 600 for h in seen), seen)
        self.assertEqual(seen, sorted(seen, reverse=True))                 # it only ever shrinks

    def test_toggling_again_mid_animation_settles_and_continues(self):
        self.w.set_mini(True)
        QTest.qWait(40)
        self.w.set_mini(False)
        self.wait()
        self.assertFalse(self.w._view_mini)
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (460, 620))

    def test_the_wanted_state_is_known_immediately(self):
        self.w.set_mini(True)
        self.assertTrue(self.w.mini)

    def test_no_stay_on_top_window_recreation_while_animating(self):
        self.w.set_mini_on_top(True)
        self.w.set_mini(True)
        self.assertTrue(self.w.native_window_recreated, "(headless falls back to the Qt flag, and says so)")

    def test_native_button_hides_the_one_in_the_window(self):
        self.assertTrue(self.w.mini_button.isVisibleTo(self.w.widget))
        self.w.set_native_mini_button(True)
        self.assertFalse(self.w.mini_button.isVisibleTo(self.w.widget))
        self.w.set_mini(True)
        self.w.set_native_mini_button(False)
        _app.processEvents()
        self.assertTrue(self.w.mini_button.isVisibleTo(self.w.widget))


class TitlebarCase(DemoCase):
    def setUp(self):
        super().setUp()
        self.fake_button = type("B", (), {"mini": None, "set_mini": lambda s, m: setattr(s, "mini", m),
                                          "set_extra_enabled": lambda s, i, f: None, "set_inset": lambda s, w: setattr(s, "inset", w),
                                          "set_extra_active": lambda s, i, on: None, "align": lambda s: 0.0, "set_panel_title": lambda s, t, tip="": None,
                                          "set_extra_image": lambda s, i, png, tip, muted, template=True: setattr(s, "file", (tip, muted)) or True,
                                          "set_enabled": lambda s, f: None})()
        self.made = []
        original = app_module.add_titlebar_button
        app_module.add_titlebar_button = lambda widget, callback, mini=False, **kw: (
            self.made.append((widget, callback)) or self.fake_button)
        self.addCleanup(lambda: setattr(app_module, "add_titlebar_button", original))
        self.app = QuillApp(_app, self.settings, XlsxBridge(self.path), listener_factory=lambda *a: FakeListener(*a),
                            model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None)
        self.app.start()


class TestTitlebarInTheApp(TitlebarCase):
    def test_the_title_bar_icon_replaces_the_in_window_one(self):
        self.assertEqual(len(self.made), 2)       # resize + Settings on the right, Help + Undo on the left
        self.assertFalse(self.app.window.mini_button.isVisibleTo(self.app.window.widget))

    def test_its_callback_toggles_the_mini_view_and_remembers_it(self):
        _, callback = self.made[0]
        callback()
        self.assertTrue(self.app.window.mini)
        self.assertTrue(Settings.load(self.dir / "cfg").preferences["mini_mode"])
        self.assertTrue(self.fake_button.mini)
        callback()
        self.assertFalse(self.app.window.mini)
        self.assertFalse(self.fake_button.mini)

    def test_where_there_is_no_title_bar_icon_the_window_keeps_its_own_button(self):
        app_module.add_titlebar_button = lambda *a, **k: None
        app = QuillApp(_app, self.settings, XlsxBridge(self.path), listener_factory=lambda *a: FakeListener(*a),
                       model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None)
        app.start()
        self.assertTrue(app.window.mini_button.isVisibleTo(app.window.widget))

    def test_a_recreated_window_is_restyled_and_gets_its_icon_back(self):
        calls = []
        self.app._apply_look = lambda: calls.append("look")
        self.app.window.native_window_recreated = True
        self.app._mini_toggled(True)
        self.assertEqual(calls, ["look"])
        self.assertEqual(len(self.made), 4)
        self.assertFalse(self.app.window.native_window_recreated)

    def test_a_native_level_change_needs_no_restyling(self):
        calls = []
        self.app._apply_look = lambda: calls.append("look")
        self.app.window.native_window_recreated = False
        self.app._mini_toggled(True)
        self.assertEqual(calls, [])


# ---- auto refresh --------------------------------------------------------------------------

class RefreshCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.path = make_workbook(self.dir / "plants.xlsx")
        self.settings = Settings.load(self.dir / "cfg")
        self.app = QuillApp(_app, self.settings, XlsxBridge(self.path), listener_factory=lambda *a: FakeListener(*a),
                            model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None)
        self.app.run_in_background = lambda work, done: done(work())      # a tick's look runs at once here (no helper thread)
        self.app.start()
        self.log = self.app.window.log

    def tearDown(self):
        self._tmp.cleanup()

    def edit_file(self, value="Palm", slot="A6"):
        wb = openpyxl.load_workbook(self.path)
        wb["Config"][slot] = value
        wb.save(self.path)
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))   # certainly a new mtime

    def values(self):
        return self.app.controller.vocab.values_for("Species")


class TestAutoRefresh(RefreshCase):
    def test_there_is_no_refresh_button_any_more(self):
        texts = [b.text() for b in self.app.window.widget.findChildren(QPushButton)]
        self.assertNotIn("Refresh", texts)

    def test_a_change_saved_in_excel_is_picked_up_on_the_next_tick(self):
        self.assertNotIn("Palm", self.values())
        self.edit_file()
        self.app.poll_workbooks()
        self.assertIn("Palm", self.values())
        self.assertIn("Workbook changed: lists and columns re-read", self.log.toPlainText())

    def test_nothing_happens_when_the_file_is_unchanged(self):
        before = self.log.toPlainText()
        for _ in range(3):
            self.app.poll_workbooks()
        self.assertEqual(self.log.toPlainText(), before)

    def test_the_same_change_is_read_only_once(self):
        self.edit_file()
        self.app.poll_workbooks()
        self.app.poll_workbooks()
        self.assertEqual(self.log.toPlainText().count("Workbook changed"), 1)

    def test_a_second_change_is_read_too(self):
        self.edit_file("Palm", "A6")
        self.app.poll_workbooks()
        self.edit_file("Orchid", "A7")
        self.app.poll_workbooks()
        self.assertTrue({"Palm", "Orchid"} <= set(self.values()))

    def test_quills_own_writes_do_not_trigger_a_refresh(self):
        c = self.app.controller
        c.handle_transcript("start listening")
        c.handle_transcript("fern small bright")
        c.handle_transcript("next row")                 # writes a row and saves the file
        self.app.poll_workbooks()
        self.assertNotIn("Workbook changed", self.log.toPlainText())

    def test_teaching_a_value_does_not_trigger_one_either(self):
        c = self.app.controller
        c.handle_transcript("start listening")
        c.handle_transcript("species snake plant")
        c.handle_transcript("next row")
        c.handle_transcript("yes")                      # adds to the Config list and saves
        self.app.poll_workbooks()
        self.assertNotIn("Workbook changed", self.log.toPlainText())

    def test_an_outside_change_after_quills_own_write_is_still_noticed(self):
        c = self.app.controller
        c.handle_transcript("start listening")
        c.handle_transcript("fern next row")
        self.app.poll_workbooks()
        self.edit_file("Cactus Jack", "A7")
        self.app.poll_workbooks()
        self.assertIn("Cactus Jack", self.values())

    def test_a_file_caught_mid_save_is_retried_on_the_next_tick(self):
        self.edit_file()
        real = self.app.controller.refresh
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) == 1:
                raise BridgeError("being saved")
            real()

        self.app.controller.refresh = flaky
        self.app.poll_workbooks()
        self.assertNotIn("Palm", self.values())
        self.assertNotIn("Workbook changed", self.log.toPlainText())
        self.app.poll_workbooks()
        self.assertIn("Palm", self.values())
        self.assertEqual(len(attempts), 2)

    def test_an_unsaved_or_unreadable_workbook_is_ignored(self):
        self.app.controller.bridge._path = None
        self.app._seen_mtime = None
        self.app.poll_workbooks()                       # must not raise
        self.app._check_workbook_changes()

    def test_connecting_starts_from_the_file_as_it_is(self):
        self.assertEqual(self.app._seen_mtime, os.stat(self.path).st_mtime_ns)



if __name__ == "__main__":
    unittest.main()
