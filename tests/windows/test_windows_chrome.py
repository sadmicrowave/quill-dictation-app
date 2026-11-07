"""Windows 11 window look: DWM attributes, acrylic blur, always-on-top."""
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication, QWidget

from quill.platforms.windows import chrome as wchrome
from quill.ui import chrome

_app = QApplication.instance() or QApplication([])

COLORS = {"bg": "#FAF9F5", "text": "#1F1E1D", "border": "#E3E0D6"}


class TestWindowsChrome(unittest.TestCase):
    def test_colorref_is_blue_green_red(self):
        self.assertEqual(wchrome.colorref("#112233"), 0x332211)

    def test_dark_mode_colours_and_rounding_are_set(self):
        calls = []
        self.assertTrue(wchrome.windows_chrome(77, True, COLORS, lambda h, a, v: calls.append((h, a, v))))
        self.assertEqual(calls[0], (77, wchrome.DWMWA_USE_IMMERSIVE_DARK_MODE, 1))
        attrs = {a: v for _, a, v in calls}
        self.assertEqual(attrs[wchrome.DWMWA_CAPTION_COLOR], wchrome.colorref("#FAF9F5"))
        self.assertEqual(attrs[wchrome.DWMWA_TEXT_COLOR], wchrome.colorref("#1F1E1D"))
        self.assertEqual(attrs[wchrome.DWMWA_BORDER_COLOR], wchrome.colorref("#E3E0D6"))
        self.assertEqual(attrs[wchrome.DWMWA_WINDOW_CORNER_PREFERENCE], wchrome.DWMWCP_ROUND)

    def test_light_mode_turns_dark_title_bar_off(self):
        calls = []
        wchrome.windows_chrome(1, False, COLORS, lambda h, a, v: calls.append((a, v)))
        self.assertIn((wchrome.DWMWA_USE_IMMERSIVE_DARK_MODE, 0), calls)

    def test_attributes_an_older_windows_rejects_are_skipped(self):
        def picky(hwnd, attribute, value):
            if attribute != wchrome.DWMWA_USE_IMMERSIVE_DARK_MODE:
                raise OSError("not on this build")
        self.assertTrue(wchrome.windows_chrome(1, True, COLORS, picky))

    def test_without_dwm_nothing_happens(self):
        with mock.patch.object(wchrome, "_dwm_setter", lambda: None):      # (on a real Windows the call would exist)
            self.assertFalse(wchrome.windows_chrome(1, True, COLORS))

class TestWindowsBlur(unittest.TestCase):
    def test_acrylic_backdrop_and_extended_frame_when_blurred(self):
        calls, extended = [], []
        wchrome.windows_chrome(9, False, COLORS, lambda h, a, v: calls.append((a, v)), blur=40,
                              extend_frame=extended.append)
        self.assertIn((wchrome.DWMWA_SYSTEMBACKDROP_TYPE, wchrome.BACKDROP_ACRYLIC), calls)
        self.assertEqual(extended, [9])

    def test_no_backdrop_when_not_blurred(self):
        calls, extended = [], []
        wchrome.windows_chrome(9, False, COLORS, lambda h, a, v: calls.append((a, v)), blur=0,
                              extend_frame=extended.append)
        self.assertIn((wchrome.DWMWA_SYSTEMBACKDROP_TYPE, wchrome.BACKDROP_NONE), calls)
        self.assertEqual(extended, [])

    def test_older_windows_without_the_backdrop_attribute_still_works(self):
        def picky(hwnd, attribute, value):
            if attribute == wchrome.DWMWA_SYSTEMBACKDROP_TYPE:
                raise OSError("unknown attribute")
        self.assertTrue(wchrome.windows_chrome(1, True, COLORS, picky, blur=50, extend_frame=lambda h: None))


class TestWindowsTopmost(unittest.TestCase):
    def test_windows_uses_setwindowpos_topmost_and_notopmost(self):
        calls = []
        user32 = type("U", (), {"SetWindowPos": lambda s, *a: calls.append(a)})()
        with mock.patch.object(wchrome, "_native", lambda: True):
            self.assertTrue(chrome.set_always_on_top(QWidget(), True, platform="win32", user32=user32))
            self.assertTrue(chrome.set_always_on_top(QWidget(), False, platform="win32", user32=user32))
        import ctypes
        self.assertEqual(calls[0][1].value, ctypes.c_void_p(-1).value)      # HWND_TOPMOST
        self.assertEqual(calls[1][1].value, ctypes.c_void_p(-2).value)      # HWND_NOTOPMOST
        self.assertEqual(calls[0][6], 0x1 | 0x2 | 0x10)               # no size, no move, no activate

    def test_nothing_is_applied_under_the_offscreen_plugin(self):
        self.assertIsNone(chrome.apply_chrome(QWidget(), True, COLORS, platform="win32"))
        self.assertFalse(chrome.set_always_on_top(QWidget(), True, platform="win32"))
