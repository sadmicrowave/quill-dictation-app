"""Tooltips on Windows: a tip window shown again with other text kept square black corners behind its rounded border. The tip is now cut to a
rounded shape with a mask where the system needs it, and the grid asks for a fresh tip window whenever its text changes."""
import unittest
from unittest import mock

from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from quill import platforms
from quill.ui.main_window import MainWindow
from quill.ui.theme import _TooltipRounder, apply_theme

_app = QApplication.instance() or QApplication([])


class TestTheRoundedMask(unittest.TestCase):
    def tip(self):
        tip = QWidget()
        tip.resize(220, 80)
        return tip

    def test_windows_asks_for_the_mask_and_the_others_do_not(self):
        self.assertTrue(platforms.offered("win32", "ROUND_TOOLTIPS_WITH_MASK", False))
        self.assertFalse(platforms.offered("darwin", "ROUND_TOOLTIPS_WITH_MASK", False))

    def test_the_corners_are_cut_and_the_rest_is_kept(self):
        tip = self.tip()
        with mock.patch.object(platforms, "offered", return_value=True):
            _TooltipRounder._round(tip)
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
            _TooltipRounder._round(tip)
            tip.resize(300, 120)
            _TooltipRounder._round(tip)
        self.assertFalse(tip.mask().contains(QPoint(299, 119)))
        self.assertTrue(tip.mask().contains(QPoint(299, 60)))

    def test_nothing_is_masked_where_the_system_draws_it_rounded_already(self):
        tip = self.tip()
        with mock.patch.object(platforms, "offered", return_value=False):
            _TooltipRounder._round(tip)
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


if __name__ == "__main__":
    unittest.main()
