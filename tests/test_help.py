"""The help system: Markdown pages, the sidebar-and-reader window, and every ? icon opening the right page."""
import pathlib
import re
import unittest

from PySide6.QtWidgets import QApplication

from quill import helpdocs
from quill.ui.help_window import HelpWindow
from quill.ui.main_window import HELP_TOPIC as MAIN_TOPIC, MainWindow
from quill.ui.sorting_window import HELP_TOPIC as SORTING_TOPIC

_app = QApplication.instance() or QApplication([])


class TestPages(unittest.TestCase):
    def setUp(self):
        self.topics = helpdocs.load_topics()

    def test_there_are_pages_with_titles_and_sections(self):
        self.assertGreaterEqual(len(self.topics), 6)
        for topic in self.topics:
            self.assertTrue(topic.title, topic.slug)
            self.assertTrue(topic.sections, topic.slug)

    def test_every_icon_has_a_page_to_open(self):
        slugs = {t.slug for t in self.topics}
        for wanted in (MAIN_TOPIC, SORTING_TOPIC, "settings"):
            self.assertIn(wanted, slugs)

    def test_pictures_named_in_the_pages_exist(self):
        for topic in self.topics:
            for name in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", topic.text):
                self.assertTrue((helpdocs.help_dir() / name).exists(), f"{topic.slug}: {name}")

    def test_pages_are_found_by_file_name_order_and_slug(self):
        self.assertEqual(self.topics[0].slug, "welcome")

    def test_a_new_page_is_just_a_new_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "01-first.md").write_text("# 😀 First\n\n## One\n\ntext\n\n## Two\n")
            pathlib.Path(tmp, "02-second.md").write_text("# Second\n")
            topics = helpdocs.load_topics(pathlib.Path(tmp))
        self.assertEqual([(t.slug, t.title, t.sections) for t in topics],
                         [("first", "😀 First", ["One", "Two"]), ("second", "Second", [])])

    def test_search_matches_titles_and_text(self):
        topic = self.topics[0]
        self.assertTrue(topic.matches(""))
        self.assertTrue(topic.matches(topic.title.split()[-1].lower()))
        self.assertFalse(topic.matches("zzzz-not-in-the-help"))


class TestWindow(unittest.TestCase):
    def setUp(self):
        self.help = HelpWindow()
        self.help.setup()

    def tearDown(self):
        self.help.widget.close()

    def test_it_lands_on_the_page_it_is_asked_for_not_the_top(self):
        self.help.show("term-helper")
        self.assertEqual(self.help.current.slug, "term-helper")
        self.assertEqual(self.help.nav.currentItem().data(0, 0x100)[0], "term-helper")

    def test_a_section_is_selected_and_scrolled_to(self):
        self.help.widget.resize(900, 400)
        self.help.show("troubleshooting", self.help.topic("troubleshooting").sections[-1])
        _app.processEvents()
        _app.processEvents()
        self.assertEqual(self.help.nav.currentItem().text(0), self.help.topic("troubleshooting").sections[-1])
        self.assertGreater(self.help.page.verticalScrollBar().value(), 0)

    def test_an_unknown_or_missing_topic_opens_the_first_page(self):
        self.help.show("nope")
        self.assertEqual(self.help.current, self.help.topics[0])
        self.help.show()
        self.assertEqual(self.help.current, self.help.topics[0])

    def test_the_page_is_rendered_markdown_with_styled_headings_and_a_picture(self):
        self.help.show("welcome")
        doc = self.help.page.document()
        levels = []
        block = doc.begin()
        while block.isValid():
            if block.blockFormat().headingLevel():
                levels.append(block.blockFormat().headingLevel())
            block = block.next()
        self.assertIn(1, levels)
        self.assertIn(2, levels)
        self.assertIn("main-window.png", doc.toHtml())

    def test_only_the_open_page_lists_its_sections(self):
        self.help.show("welcome")
        self.assertTrue(self.help._items["welcome"].isExpanded())
        self.assertFalse(self.help._items["settings"].isExpanded())

    def test_search_hides_pages_that_do_not_match_and_reopening_clears_it(self):
        self.help.show("welcome")
        self.help.search.setText("zzzz-not-in-the-help")
        self.assertTrue(all(i.isHidden() for i in self.help._items.values()))
        self.assertTrue(self.help.empty_label.isVisibleTo(self.help.widget))
        self.help.show("settings")
        self.assertEqual(self.help.search.text(), "")
        self.assertFalse(self.help._items["settings"].isHidden())

    def test_help_links_jump_between_pages(self):
        from PySide6.QtCore import QUrl
        self.help.show("welcome")
        self.help._link_clicked(QUrl("help:settings"))
        self.assertEqual(self.help.current.slug, "settings")


class TestIconsOpenTheRightPage(unittest.TestCase):
    def test_the_main_windows_icon_asks_for_the_welcome_page(self):
        asked = []
        w = MainWindow(on_help=asked.append)
        w.setup()
        w.help_button.click()
        self.assertEqual(asked, [MAIN_TOPIC])

    def test_the_settings_icon_opens_the_settings_page(self):
        from quill.config.settings import Settings
        from quill.ui.settings_dialog import SettingsDialog
        asked = []
        dialog = SettingsDialog(Settings.defaults(), None, on_help=asked.append)
        dialog.build()
        dialog.open_help()
        self.assertEqual(asked, ["settings"])

    def test_the_apps_help_window_is_created_on_first_use_and_reused(self):
        from tests.test_sorting import DemoCase
        from quill.app import QuillApp
        from quill.bridge.xlsx_bridge import XlsxBridge

        class Case(DemoCase):
            def runTest(self): pass
        case = Case()
        case.setUp()
        try:
            app = QuillApp(_app, case.settings, XlsxBridge(case.path), listener_factory=lambda *a: None,
                           model_finder=lambda c: None)
            app.start()
            self.assertIsNone(app.help)
            app.sorting.help_button.click()
            first = app.help
            self.assertEqual(first.current.slug, "term-helper")
            app.window.help_button.click()
            self.assertIs(app.help, first)
            self.assertEqual(first.current.slug, "welcome")
            first.widget.close()
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
