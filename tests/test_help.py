"""The help system: Markdown pages, the sidebar-and-reader window, and every ? icon opening the right page."""
import pathlib
import re
import unittest

from PySide6.QtWidgets import QApplication

from quill import helpdocs
from quill.ui.help_window import HelpWindow
from quill.ui.main_window import HELP_TOPIC as MAIN_TOPIC, MainWindow
from quill.ui.sorting_window import HELP_TOPIC as SORTING_TOPIC
from quill.ui.hints import plain

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
                stem = name[:-len(".png")]                          # each picture comes in a light and a dark version
                for theme in ("light", "dark"):
                    self.assertTrue((helpdocs.help_dir() / f"{stem}-{theme}.png").exists(), f"{topic.slug}: {name} ({theme})")

    def test_pages_are_found_by_file_name_order_and_slug(self):
        self.assertEqual(self.topics[0].slug, "welcome")

    def test_a_new_page_is_just_a_new_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "01-first.md").write_text("# 😀 First\n\n## One\n\ntext\n\n## Two\n", encoding="utf-8")
            pathlib.Path(tmp, "02-second.md").write_text("# Second\n", encoding="utf-8")
            topics = helpdocs.load_topics(pathlib.Path(tmp))
        self.assertEqual([(t.slug, t.title, t.sections) for t in topics],
                         [("first", "😀 First", ["One", "Two"]), ("second", "Second", [])])

    def test_search_matches_titles_and_text(self):
        topic = self.topics[0]
        self.assertTrue(topic.matches(""))
        self.assertTrue(topic.matches(topic.title.split()[-1].lower()))
        self.assertFalse(topic.matches("zzzz-not-in-the-help"))


EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200D]")


class TestThePagesFollowTheRules(unittest.TestCase):
    """The rules of docs/help-redesign/outline.md, checked on every page: organised by what the reader does, plain, with pictures."""

    def setUp(self):
        self.topics = helpdocs.load_topics()
        self.slugs = {t.slug for t in self.topics}

    def test_no_emoji_anywhere(self):
        for topic in self.topics:
            self.assertNotRegex(topic.text, EMOJI, topic.slug)

    def test_every_link_to_another_page_goes_to_a_page(self):
        for topic in self.topics:
            for target in re.findall(r"\]\(help:([\w-]+)\)", topic.text):
                self.assertIn(target, self.slugs, f"{topic.slug} links to {target}")

    def test_every_page_but_the_last_ends_with_where_to_go_next(self):
        for topic in self.topics[:-1]:
            if topic.slug in ("troubleshooting",):
                continue
            self.assertRegex(topic.text.strip().splitlines()[-1], r"^\*\*Next:\*\* \[[^\]]+\]\(help:[\w-]+\)$", topic.slug)

    def test_no_bullet_lists_inside_bullet_lists_and_no_long_ones(self):
        for topic in self.topics:
            bullets = [line for line in topic.text.splitlines() if re.match(r"^\s*[-*] ", line)]
            self.assertFalse([b for b in bullets if b.startswith(" ")], f"{topic.slug}: a nested bullet")
            self.assertLessEqual(len(bullets), 4, f"{topic.slug}: too many bullets (use steps or a table)")

    def test_a_task_page_numbers_its_steps_and_says_what_you_will_see(self):
        for slug in ("quick-start", "use-a-file-directly", "first-row", "notes", "ids", "term-helper", "mini-view"):
            text = next(t.text for t in self.topics if t.slug == slug)
            self.assertRegex(text, r"(?m)^\*\*1\. ", slug)
            self.assertIn("*You'll see:*", text, slug)

    def test_every_icon_a_page_names_has_a_picture_in_both_themes(self):
        for topic in self.topics:
            for name in re.findall(r"\(images/(icon-[\w-]+)\.png\)", topic.text):
                for theme in ("light", "dark"):
                    self.assertTrue((helpdocs.help_dir() / "images" / f"{name}-{theme}.png").exists(), f"{topic.slug}: {name}")

    def test_the_pages_are_grouped_in_the_order_a_person_meets_them(self):
        order = [t.group for t in self.topics]
        seen = []
        for group in order:
            if not seen or seen[-1] != group:
                seen.append(group)
        self.assertEqual(seen, [name for name, _ in helpdocs.GROUPS], "one stretch per group, in order")
        self.assertNotIn("More", order, "every page belongs to a group")

    def test_the_pages_the_app_opens_exist(self):
        for wanted in ("welcome", "term-helper", "settings", "privacy", "troubleshooting"):
            self.assertIn(wanted, self.slugs)


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
        self.assertEqual(self.help.nav.currentItem().text(0), plain(self.help.topic("troubleshooting").sections[-1]))
        self.assertGreater(self.help.page.verticalScrollBar().value(), 0)

    def test_the_sidebar_shows_plain_words_while_the_pages_keep_their_headings(self):
        for topic in self.help.topics:
            item = self.help._items[topic.slug]
            self.assertEqual(item.text(0), plain(topic.title))
            self.assertEqual(plain(item.text(0)), item.text(0), "no emoji in the sidebar")
            for i, section in enumerate(topic.sections):
                self.assertEqual(item.child(i).text(0), plain(section))
        self.assertNotRegex("".join(self.help.nav.topLevelItem(i).text(0) for i in range(self.help.nav.topLevelItemCount())), "[\U0001F000-\U0001FFFF]")

    def test_a_section_can_be_asked_for_with_or_without_its_emoji(self):
        raw = self.help.topic("troubleshooting").sections[-1]
        for asked in (raw, plain(raw)):
            self.help.show("welcome")
            self.help.goto("troubleshooting", asked)
            self.assertEqual(self.help.nav.currentItem().text(0), plain(raw))

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
        self.assertIn("main-window-", doc.toHtml())

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


class TestThemedPictures(unittest.TestCase):
    def test_the_page_shows_the_picture_for_the_current_theme(self):
        from PySide6.QtWidgets import QApplication
        from quill.ui.help_window import HelpWindow
        from quill.ui.theme import apply_theme
        app = QApplication.instance() or QApplication([])
        window = HelpWindow()
        window.setup()
        for theme in ("light", "dark"):
            apply_theme(app, theme, "violet", "compact")
            window.show()
            window._render(window.current)
            html = window.page.document().toHtml()
            self.assertIn(f"-{theme}.png", html)
            other = "dark" if theme == "light" else "light"
            self.assertNotIn(f"-{other}.png", html)
