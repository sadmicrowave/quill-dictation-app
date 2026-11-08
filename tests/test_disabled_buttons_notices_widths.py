"""One look for every disabled button, the green and red notices, and no page that needs a sideways scroll bar."""

import pathlib
import tempfile
import unittest

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QWidget, QVBoxLayout

from quill.config.settings import Settings
from quill.ui import theme
from quill.ui.notice import Notice
from quill.ui.settings_dialog import SettingsDialog

APP = QApplication.instance() or QApplication([])


def painted(button: QPushButton) -> QColor:
    """The fill colour at the button's left edge (inside the border)."""
    button.resize(140, 36)
    image = button.grab().toImage()
    return image.pixelColor(10, 18)


class TestDisabledButtons(unittest.TestCase):
    def test_a_disabled_primary_button_is_not_the_accent_colour(self):
        for dark in (False, True):
            theme.apply_theme(APP, "dark" if dark else "light", "violet", "compact")
            t = theme.colors_for(dark, "violet")
            for prop in ("accent", "danger"):
                holder = QWidget()
                QVBoxLayout(holder)
                button = QPushButton("Send Report")
                button.setProperty(prop, True)
                holder.layout().addWidget(button)
                holder.show()
                enabled = painted(button)
                button.setEnabled(False)
                button.style().unpolish(button)
                button.style().polish(button)
                disabled = painted(button)
                self.assertNotEqual(disabled.name().upper(), enabled.name().upper(), (dark, prop))
                self.assertEqual(disabled.name().upper(), t["off_fill"].upper(), (dark, prop))
                self.assertNotEqual(disabled.name().upper(), t["accent"].upper())
                holder.close()

    def test_every_disabled_button_kind_is_listed_after_the_accent_rule_so_it_wins(self):
        for dark in (False, True):
            sheet = theme.stylesheet_for(dark)
            accent = sheet.index('QPushButton[accent="true"] {')
            disabled = sheet.index('QPushButton[accent="true"]:disabled')
            self.assertGreater(disabled, accent)
            self.assertIn(theme.colors_for(dark)["off_fill"], sheet[disabled:disabled + 400])


class TestNotice(unittest.TestCase):
    def test_it_is_hidden_until_it_has_something_to_say(self):
        notice = Notice()
        self.assertTrue(notice.isHidden())
        self.assertEqual(notice.kind, "")

    def test_ok_is_green_and_error_is_red_and_clear_hides_it(self):
        theme.apply_theme(APP, "light", "violet", "compact")
        holder = QWidget()
        QVBoxLayout(holder)
        notice = Notice()
        holder.layout().addWidget(notice)
        holder.resize(360, 100)
        holder.show()
        notice.show_ok("Thank you")
        self.assertEqual((notice.kind, notice.label.text()), ("ok", "Thank you"))
        green = notice.grab().toImage().pixelColor(4, notice.height() // 2)
        notice.show_error("Couldn't reach")
        red = notice.grab().toImage().pixelColor(4, notice.height() // 2)
        self.assertGreater(green.green(), green.red())              # a green tint
        self.assertGreater(red.red(), red.green())                  # a red tint
        notice.clear()
        self.assertTrue(notice.isHidden())
        holder.close()


class TestSettingsNeverScrollSideways(unittest.TestCase):
    def pages_at(self, width):
        settings = Settings.load(pathlib.Path(tempfile.mkdtemp()))
        controller = SettingsDialog(settings)
        dialog = controller.build()
        dialog.show()
        dialog.resize(width, 740)
        APP.processEvents()
        result = {}
        for name in ("General", "Appearance", "Sounds", "Keywords", "Speech Model", "Learned Words"):
            controller.show_page_named(name)
            APP.processEvents()
            page = next(s for s in dialog.findChildren(QScrollArea) if s.isVisible() and s.objectName() == "settingsPage")
            result[name] = page.horizontalScrollBar().maximum()
        dialog.close()
        return result

    def test_no_page_scrolls_sideways_at_the_default_size_or_the_smallest(self):
        for width in (920, 720):                       # 720 is below the window's real minimum: it is raised to fit
            self.assertEqual({k: v for k, v in self.pages_at(width).items() if v}, {}, width)


if __name__ == "__main__":
    unittest.main()
