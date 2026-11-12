"""The window as Windows (and any system without a native title-bar toolbar) shows it.

macOS puts the chrome icons (help, undo, files, turns, settings, resize) in the title bar and the menus at the top of the screen. Everywhere
else the window draws them itself: the icons in a **ribbon above** the Start button, the menus in a bar inside the window. These tests build
the window the way such a system gets it (no native buttons), so they run on every machine; the ones that ask Windows itself are marked.
"""
import ast
import os
import pathlib
import sys
import unittest
from unittest import mock

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from quill import platforms
from quill.ui.icons import make_icon
from quill.ui.main_window import MainWindow
from quill.ui.theme import apply_theme

_app = QApplication.instance() or QApplication([])

QUILL = pathlib.Path(__file__).resolve().parent.parent.parent / "quill"


def build(width=520, height=600):
    apply_theme(_app, "light")
    MainWindow.animation_ms = 0
    window = MainWindow()
    window.setup()
    window.widget.resize(width, height)
    window.widget.show()
    QTest.qWait(50)
    return window


def top_left(window, widget):
    return widget.mapTo(window.widget, QPoint(0, 0))


class Case(unittest.TestCase):
    def tearDown(self):
        MainWindow.animation_ms = 240


class TestTheRibbon(Case):
    """The icons sit in their own row above Start, so Start keeps the whole width."""

    def icons(self, w):
        return [w.help_button, w.undo_button, w.open_file_button, w.turn_button, w.settings_button, w.mini_button]

    def test_every_icon_is_above_the_start_button_not_beside_it(self):
        w = build()
        start = top_left(w, w.toggle_button).y()
        for button in self.icons(w):
            self.assertTrue(button.isVisible(), button.accessibleName() or button.toolTip())
            self.assertLessEqual(top_left(w, button).y() + button.height(), start, f"{button.toolTip()} is not above Start")

    def test_the_icons_are_one_row_in_the_titlebar_order_at_the_right(self):
        w = build()
        xs = [top_left(w, b).x() for b in self.icons(w)]
        ys = {top_left(w, b).y() for b in self.icons(w)}
        self.assertEqual(xs, sorted(xs), "help, undo, files, turns, settings, resize: left to right")
        self.assertEqual(len(ys), 1, "one row")
        last = self.icons(w)[-1]
        self.assertGreater(top_left(w, last).x() + last.width(), w.widget.width() * 0.85, "right-aligned")

    def test_start_keeps_the_width_of_the_window(self):
        w = build()
        self.assertGreaterEqual(w.toggle_button.width(), w.widget.width() * 0.7)
        w.set_listening_indicator(True)                                    # (the Next Row button joins it while listening)
        QTest.qWait(50)
        self.assertGreaterEqual(w.toggle_button.width(), w.widget.width() * 0.6)

    def test_a_window_with_native_title_bar_icons_has_no_ribbon(self):
        apply_theme(_app, "light")
        w = MainWindow()
        w.setup()
        for setter in (w.set_native_help_button, w.set_native_undo_button, w.set_native_file_button, w.set_native_turn_button,
                       w.set_native_settings_button, w.set_native_mini_button):
            setter(True)
        w.widget.resize(520, 600)
        w.widget.show()
        QTest.qWait(50)
        self.assertFalse(w.ribbon.isVisible(), "nothing to put in it: no empty bar above Start")

    def test_the_mini_view_keeps_the_same_toolbar_with_all_six_icons(self):
        w = build(520, 200)
        w.set_mini(True)
        QTest.qWait(50)
        self.assertTrue(w.ribbon.isVisible())
        start = top_left(w, w.toggle_button).y()
        half = w.widget.width() / 2
        for button in self.icons(w):
            self.assertTrue(button.isVisible(), button.toolTip())
            self.assertLessEqual(top_left(w, button).y() + button.height(), start, f"{button.toolTip()} is not above Start")
        for button in (w.help_button, w.undo_button):
            self.assertLess(top_left(w, button).x(), half)
        for button in (w.open_file_button, w.turn_button, w.settings_button, w.mini_button):
            self.assertGreater(top_left(w, button).x(), half)

    def test_the_toolbar_is_where_it_was_when_the_window_gets_small_and_comes_back(self):
        w = build()
        before = {b.toolTip(): (top_left(w, b).x() - 0, top_left(w, b).y()) for b in self.icons(w)}
        w.set_mini(True)
        QTest.qWait(50)
        mini_y = {top_left(w, b).y() for b in self.icons(w)}
        self.assertEqual(len(mini_y), 1, "one row in the mini view too")
        self.assertLessEqual(abs(next(iter(mini_y)) - before[w.help_button.toolTip()][1]), 2, "at the same height (the mini view's margin is a pixel less)")
        w.set_mini(False)
        QTest.qWait(50)
        start = top_left(w, w.toggle_button).y()
        self.assertTrue(all(top_left(w, b).y() + b.height() <= start for b in self.icons(w)))

    def test_the_mini_view_is_tall_enough_for_the_toolbar_and_start(self):
        w = build(520, 500)
        w.set_mini(True)
        QTest.qWait(50)
        bar = w.widget.menuBar()
        need = (bar.height() if bar.isVisible() else 0) + w.ribbon.height() + w.toggle_button.minimumSizeHint().height()
        self.assertGreaterEqual(w.widget.height(), need)
        self.assertGreaterEqual(w.toggle_button.height(), w.toggle_button.minimumSizeHint().height())
        central = w.widget.centralWidget()
        corner = w.toggle_button.mapTo(central, QPoint(w.toggle_button.width() - 1, w.toggle_button.height() - 1))
        self.assertLessEqual(corner.y(), central.height())

    def test_the_icons_come_back_with_the_full_window(self):
        w = build()
        w.set_mini(True)
        QTest.qWait(50)
        w.set_mini(False)
        QTest.qWait(50)
        start = top_left(w, w.toggle_button).y()
        self.assertTrue(all(top_left(w, b).y() + b.height() <= start for b in self.icons(w)))


class TestTheToolbarLook(Case):
    """The ribbon is a toolbar as the macOS title bar is: help and undo at the left, the rest at the right, no border round an icon until the
    pointer is on it, and a thin rule under the row that separates it from Start. Measured on the painted window."""

    @staticmethod
    def pixel(w, point):
        return w.widget.grab().toImage().pixelColor(point)

    @staticmethod
    def close(a, b, delta=6):
        return all(abs(x - y) <= delta for x, y in ((a.red(), b.red()), (a.green(), b.green()), (a.blue(), b.blue())))

    def settled(self, width=520):
        w = build(width, 600)
        QTest.qWait(1300)                                                # (the columns ease in: wait until they are drawn)
        return w

    def test_help_and_undo_are_at_the_left_and_the_other_icons_at_the_right(self):
        w = self.settled()
        half = w.widget.width() / 2
        for button in (w.help_button, w.undo_button):
            self.assertLess(top_left(w, button).x() + button.width(), half, button.toolTip())
        for button in (w.open_file_button, w.turn_button, w.settings_button, w.mini_button):
            self.assertGreater(top_left(w, button).x(), half, button.toolTip())
        self.assertLess(top_left(w, w.help_button).x(), 25)
        self.assertGreater(top_left(w, w.mini_button).x() + w.mini_button.width(), w.widget.width() - 25)

    def test_the_six_icons_are_one_size_in_one_row(self):
        w = self.settled()
        buttons = [w.help_button, w.undo_button, w.open_file_button, w.turn_button, w.settings_button, w.mini_button]
        self.assertEqual({(b.width(), b.height()) for b in buttons}, {(32, 28)})
        self.assertEqual({top_left(w, b).y() for b in buttons}, {top_left(w, buttons[0]).y()})

    def test_an_icon_has_no_border_or_fill_until_the_pointer_is_on_it(self):
        w = self.settled()
        for button in (w.help_button, w.open_file_button, w.settings_button, w.mini_button):
            with self.subTest(button.toolTip()):
                origin = top_left(w, button)
                outside = self.pixel(w, QPoint(origin.x() - 4, origin.y() + button.height() // 2))
                for dx, dy in ((1, button.height() // 2), (button.width() - 2, button.height() // 2), (button.width() // 2, 1)):
                    self.assertTrue(self.close(self.pixel(w, QPoint(origin.x() + dx, origin.y() + dy)), outside),
                                    f"{button.toolTip()}: the edge of the icon is drawn")

    def test_the_icon_under_the_pointer_gets_a_soft_fill(self):
        w = self.settled()
        button = w.settings_button
        origin = top_left(w, button)
        edge = QPoint(origin.x() + 3, origin.y() + button.height() // 2)
        before = self.pixel(w, edge)
        QTest.mouseMove(button, QPoint(button.width() // 2, button.height() // 2))
        QTest.qWait(150)
        after = self.pixel(w, edge)
        self.assertFalse(self.close(before, after, 3), "no fill under the pointer")
        QTest.mouseMove(w.widget.centralWidget(), QPoint(w.widget.width() // 2, 400))
        QTest.qWait(150)
        self.assertTrue(self.close(self.pixel(w, edge), before), "the fill goes when the pointer leaves")

    def test_a_thin_rule_under_the_row_separates_it_from_start(self):
        from quill.ui.theme import colors_for
        w = self.settled()
        ribbon = w.ribbon
        bottom = top_left(w, ribbon).y() + ribbon.height() - 1
        middle = top_left(w, ribbon).x() + ribbon.width() // 2
        rule = QColor(colors_for(False)["border"])
        self.assertTrue(self.close(self.pixel(w, QPoint(middle, bottom)), rule), "the rule is the theme's border colour")
        self.assertFalse(self.close(self.pixel(w, QPoint(middle, bottom - 4)), rule), "and only one pixel thick")
        self.assertLess(bottom, top_left(w, w.toggle_button).y(), "Start is below the rule")

    def test_the_rule_is_also_there_in_the_dark_theme(self):
        from quill.ui.theme import colors_for
        apply_theme(_app, "dark")
        w = MainWindow()
        w.setup()
        w.widget.resize(520, 600)
        w.widget.show()
        QTest.qWait(1300)
        ribbon = w.ribbon
        bottom = top_left(w, ribbon).y() + ribbon.height() - 1
        middle = top_left(w, ribbon).x() + ribbon.width() // 2
        self.assertTrue(self.close(self.pixel(w, QPoint(middle, bottom)), QColor(colors_for(True)["border"])))


class TestTheMiniView(Case):
    """The window is the content plus the menu bar drawn inside it: the mini view's size counted only the content."""

    def test_start_is_whole_and_clickable_in_the_mini_view(self):
        w = build(560, 500)
        w.set_mini(True)
        QTest.qWait(50)
        central = w.widget.centralWidget()
        button = w.toggle_button
        self.assertTrue(button.isVisible())
        self.assertGreaterEqual(button.height(), button.minimumSizeHint().height(), "Start is cut short")
        self.assertGreaterEqual(button.width(), 120)
        corner = button.mapTo(central, QPoint(button.width() - 1, button.height() - 1))
        self.assertLessEqual(corner.y(), central.height(), "Start's lower edge is below the window")
        self.assertLessEqual(corner.x(), central.width())

    def test_the_window_is_at_least_the_menu_bar_plus_the_content(self):
        w = build(560, 500)
        w.set_mini(True)
        QTest.qWait(50)
        bar = w.widget.menuBar()
        content = w._layout.sizeHint().height()
        self.assertGreaterEqual(w.widget.height(), (bar.height() if bar.isVisible() else 0) + content - 2)

    def test_the_least_size_the_user_can_drag_it_to_still_holds_start(self):
        w = build(560, 500)
        w.set_mini(True)
        QTest.qWait(50)
        bar = w.widget.menuBar()
        least = w.widget.minimumHeight()
        self.assertGreaterEqual(least, (bar.height() if bar.isVisible() else 0) + w.toggle_button.minimumSizeHint().height())

    def test_the_full_window_cannot_be_dragged_smaller_than_its_content_and_menu_bar(self):
        w = build(560, 600)
        w._keep_minimum()                                                   # (what the window does whenever its content changes)
        bar = w.widget.menuBar()
        extra = bar.height() if bar.isVisible() else 0
        self.assertGreaterEqual(w.widget.minimumHeight(), w._layout.minimumSize().height() + extra - 2)


class TestTheMenuBarText(Case):
    """File, Listening, View, Window, Help: the size of the system's own title-bar text, not the size of Quill's controls."""

    def test_the_menu_bar_is_in_the_system_title_font_size(self):
        w = build()
        bar = w.widget.menuBar()
        system = QFontDatabase.systemFont(QFontDatabase.SystemFont.TitleFont).pointSizeF()
        self.assertGreater(system, 0)
        self.assertAlmostEqual(bar.font().pointSizeF(), system, delta=0.6)

    def test_it_stays_that_size_when_the_text_size_setting_grows(self):
        apply_theme(_app, "light", font_size=16)
        w = MainWindow()
        w.setup()
        w.widget.show()
        QTest.qWait(50)
        system = QFontDatabase.systemFont(QFontDatabase.SystemFont.TitleFont).pointSizeF()
        self.assertAlmostEqual(w.widget.menuBar().font().pointSizeF(), system, delta=0.6)
        self.assertGreater(w.help_button.font().pointSizeF(), system)             # (the rest of the window still follows the setting)


class TestTheFolderIcon(Case):
    """The File icon is muted while no file is open: that must still be drawn (a colour with an alpha part was drawn as nothing)."""

    @staticmethod
    def drawn(icon, size=18):
        image = icon.pixmap(size, size).toImage()
        return sum(1 for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x, y).alpha() > 0)

    def test_the_icon_with_no_file_open_has_pixels(self):
        w = build()
        self.assertFalse(w.open_file_button.icon().isNull())
        self.assertGreater(self.drawn(w.open_file_button.icon()), 30)

    def test_the_icon_with_a_file_open_has_pixels_too(self):
        w = build()
        w.update_workbooks(["Stock.xlsx"], "Stock.xlsx")
        self.assertGreater(self.drawn(w.open_file_button.icon()), 30)

    def test_muted_is_fainter_than_solid_and_both_are_visible(self):
        solid = make_icon("folder", "#202020", 18)
        faint = make_icon("folder", "#202020", 18, alpha=0.43)
        a, b = solid.pixmap(18, 18).toImage(), faint.pixmap(18, 18).toImage()
        peak = lambda image: max(image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height()))
        self.assertGreater(peak(b), 60)
        self.assertLess(peak(b), peak(a))

    def test_no_icon_is_drawn_from_a_colour_with_an_alpha_part(self):
        for path in (QUILL / "ui").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "make_icon" and len(node.args) > 1:
                    colour = ast.unparse(node.args[1])
                    self.assertNotIn("HexArgb", colour, f"{path.name}: make_icon is given an ARGB colour")


class TestNoConsoleWindow(Case):
    """Asking Windows for the process list (every few seconds) opened a console for a moment: every child process must be started without one."""

    def test_the_helper_asks_windows_for_no_console_and_other_systems_for_nothing(self):
        self.assertEqual(platforms.no_console("win32"), {"creationflags": 0x08000000})
        self.assertEqual(platforms.no_console("darwin"), {})
        self.assertEqual(platforms.no_console("linux"), {})

    def test_the_process_list_question_is_asked_without_a_console(self):
        from quill.bridge import hosts
        seen = {}

        def fake_run(args, **kwargs):
            seen.update(kwargs)
            return mock.Mock(stdout="", returncode=0)
        with mock.patch.dict(os.environ), mock.patch.object(sys, "platform", "win32"), mock.patch.object(hosts.subprocess, "run", fake_run):
            os.environ.pop("QUILL_NO_HOSTS", None)                          # (the tests set it so that nothing asks the system by accident)
            hosts._run(["tasklist"])
        self.assertEqual(seen.get("creationflags"), 0x08000000)

    def test_every_child_process_outside_the_mac_code_is_started_without_a_console(self):
        """A new call that forgets it would flash a window on Windows: check them all, as the test of time limits does."""
        offenders = []
        for path in QUILL.rglob("*.py"):
            if "macos" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "subprocess" and node.func.attr in ("run", "Popen", "check_output", "call")):
                    command = ast.unparse(node.args[0]) if node.args else ""
                    if "xdg-open" in command:                                    # (a Linux command: never run on Windows)
                        continue
                    if not any(k.arg is None or k.arg == "creationflags" for k in node.keywords):
                        offenders.append(f"{path.relative_to(QUILL.parent)}:{node.lineno}")
        self.assertEqual(offenders, [], "child processes that would open a console window on Windows")

    @unittest.skipUnless(sys.platform == "win32", "a real console")
    def test_a_real_child_process_makes_no_console_window(self):
        from quill.bridge import hosts
        os.environ.pop("QUILL_NO_HOSTS", None)
        import ctypes
        before = ctypes.windll.kernel32.GetConsoleWindow()
        out = hosts._run(["tasklist", "/fo", "csv", "/nh"])
        self.assertIn(".exe", out.lower())
        self.assertEqual(ctypes.windll.kernel32.GetConsoleWindow(), before)


if __name__ == "__main__":
    unittest.main()
