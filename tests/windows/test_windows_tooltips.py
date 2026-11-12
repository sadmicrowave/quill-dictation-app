"""Tooltips on Windows: a tip window shown again with other text kept square black corners behind its rounded border. The tip is now cut to a
rounded shape with a mask where the system needs it, and the grid asks for a fresh tip window whenever its text changes."""
import unittest
from unittest import mock

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from quill import platforms
from quill.ui.main_window import MainWindow
from quill.ui.theme import _TooltipRounder, apply_theme
from quill.ui.widgets import CenteredToolTips, fit_tip

_app = QApplication.instance() or QApplication([])


class TestTheRoundedMask(unittest.TestCase):
    def tip(self):
        tip = QWidget()
        tip.resize(220, 80)
        return tip

    def test_windows_asks_for_the_mask_and_the_others_do_not(self):
        self.assertTrue(platforms.offered("win32", "ROUND_POPUPS_WITH_MASK", False))
        self.assertFalse(platforms.offered("darwin", "ROUND_POPUPS_WITH_MASK", False))

    def test_the_corners_are_cut_and_the_rest_is_kept(self):
        tip = self.tip()
        with mock.patch.object(platforms, "offered", return_value=True):
            _TooltipRounder._round(tip, 7)
        mask = tip.mask()
        self.assertFalse(mask.contains(QPoint(0, 0)))
        self.assertFalse(mask.contains(QPoint(219, 0)))
        self.assertFalse(mask.contains(QPoint(0, 79)))
        self.assertFalse(mask.contains(QPoint(219, 79)))
        for kept in (QPoint(110, 40), QPoint(110, 0), QPoint(0, 40), QPoint(219, 40), QPoint(110, 79), QPoint(8, 8)):
            self.assertTrue(mask.contains(kept), kept)

    def test_the_cut_follows_the_size_the_tip_takes_when_it_is_shown_again(self):
        tip = self.tip()
        with mock.patch.object(platforms, "offered", return_value=True):
            _TooltipRounder._round(tip, 7)
            tip.resize(300, 120)
            _TooltipRounder._round(tip, 7)
        self.assertFalse(tip.mask().contains(QPoint(299, 119)))
        self.assertTrue(tip.mask().contains(QPoint(299, 60)))

    def test_nothing_is_masked_where_the_system_draws_it_rounded_already(self):
        tip = self.tip()
        with mock.patch.object(platforms, "offered", return_value=False):
            _TooltipRounder._round(tip, 7)
        self.assertTrue(tip.mask().isEmpty())

    def test_the_radius_is_the_style_sheets(self):
        from quill.ui import theme
        self.assertIn(f"border-radius: {_TooltipRounder.TIP_RADIUS}px", theme.stylesheet_for(False).split("QToolTip", 1)[1].split("}", 1)[0])


class TestTheGridAsksForAFreshTip(unittest.TestCase):
    def test_the_tip_window_is_closed_when_the_text_changes(self):
        apply_theme(_app, "light")
        MainWindow.animation_ms = 0
        w = MainWindow()
        w.setup()
        w.set_columns(["ID", "Notes"])
        w.set_column_tips({"Notes": "Say “notes” or “start note”."})
        w.widget.resize(520, 600)
        w.widget.show()
        QTest.qWait(1300)
        table = w.row_table
        row = next(r for r in range(table.rowCount()) if table.item(r, 0).text() == "Notes")
        icon = table.icon_rect(row).center()
        with mock.patch("quill.ui.main_widgets.QToolTip.hideText") as hide:
            QTest.mouseMove(table.viewport(), icon)
            self.assertEqual(hide.call_count, 1, "a new tip: close the old window first")
            QTest.mouseMove(table.viewport(), icon + QPoint(1, 0))
            self.assertEqual(hide.call_count, 1, "the same tip: left alone")
            QTest.mouseMove(table.viewport(), QPoint(table.columnWidth(0) + 40, icon.y()))
            self.assertEqual(hide.call_count, 2, "the tip goes when the pointer leaves the icon")
        MainWindow.animation_ms = 240


class TestTheGridUsesQuillsRoundedTip(unittest.TestCase):
    """The grid's information icons showed the system's square tip (black corners behind the rounded border on Windows) because the grid tips its whole
    viewport, and Quill's own rounded tip looked only at list items. Now the icon's tip is the same card as every other button's."""

    def setUp(self):
        apply_theme(_app, "light")
        MainWindow.animation_ms = 0
        self.tips = CenteredToolTips(_app)
        _app.installEventFilter(self.tips)
        self.addCleanup(_app.removeEventFilter, self.tips)
        self.addCleanup(setattr, MainWindow, "animation_ms", 240)
        self.w = MainWindow()
        self.w.setup()
        self.w.set_columns(["ID", "Notes"])
        self.text = "Say \u201cnotes\u201d or \u201cstart note\u201d, speak your note, then \u201cend note\u201d or \u201cnext row\u201d."
        self.w.set_column_tips({"Notes": self.text})
        self.w.widget.resize(520, 600)
        self.w.widget.show()
        QTest.qWait(1300)
        self.table = self.w.row_table
        self.row = next(r for r in range(self.table.rowCount()) if self.table.item(r, 0).text() == "Notes")
        self.icon = self.table.icon_rect(self.row).center()
        QTest.mouseMove(self.table.viewport(), QPoint(3, self.table.height() - 3))          # (the pointer starts elsewhere, so moving to the icon is a move)

    def ask(self, point):
        """The system asks the grid for a tip at *point* (the pointer has rested there)."""
        event = QHelpEvent(QEvent.Type.ToolTip, point, self.table.viewport().mapToGlobal(point))
        _app.sendEvent(self.table.viewport(), event)

    def test_resting_on_the_icon_shows_the_rounded_card_with_the_text(self):
        QTest.mouseMove(self.table.viewport(), self.icon)
        self.ask(self.icon)
        self.assertTrue(self.tips.window.isVisible())
        self.assertEqual(self.tips.window._text, fit_tip(self.table.viewport().toolTip()))
        self.assertIn("start note", self.tips.window._text.replace("\n", " "))

    def test_the_card_goes_when_the_pointer_rests_where_there_is_no_tip(self):
        QTest.mouseMove(self.table.viewport(), self.icon)
        self.ask(self.icon)
        self.assertTrue(self.tips.window.isVisible())
        away = QPoint(self.table.columnWidth(0) + 40, self.icon.y())
        QTest.mouseMove(self.table.viewport(), away)
        self.assertFalse(self.tips.window.isVisible(), "moving off the icon takes the old tip away")
        self.ask(away)
        self.assertFalse(self.tips.window.isVisible())

    def test_an_item_tip_still_wins_over_the_viewports(self):
        from PySide6.QtCore import Qt
        item = self.table.item(self.row, 1) or self.table.item(self.row, 0)
        item.setToolTip("An item's own tip")
        point = self.table.visualItemRect(item).center()
        self.assertEqual(CenteredToolTips.tip_for(self.table.viewport(), point), "An item's own tip")


if __name__ == "__main__":
    unittest.main()
