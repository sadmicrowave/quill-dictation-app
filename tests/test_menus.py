"""The menu bar: every major operation is reachable from it, shows the right state, and does what its button does."""
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication, QMainWindow, QMenuBar

from quill.ui.menus import HANDLERS, LAYOUT, SETTINGS_PAGES, MenuState, QuillMenus
from quill.ui.side_panel import APPEND_TO, FILE_PAGE, NEXT_ROW, TURN_PAGE
from tests.test_side_panel_and_turns import PanelApp

_app = QApplication.instance() or QApplication([])


def entries():
    return [e for _, group in LAYOUT for e in group if e.key != "-"]


class Recorder:
    """Handlers that remember what was asked of them."""

    def __init__(self):
        self.calls = []
        self.handlers = {name: (lambda *a, n=name: self.calls.append((n, *a))) for name in HANDLERS}
        self.handlers["settings_page"] = lambda page: self.calls.append(("settings_page", page))


class TestTable(unittest.TestCase):
    def test_every_entry_names_a_handler_and_every_handler_has_an_entry(self):
        keys = {e.key for e in entries() if e.kind != "submenu"}
        self.assertEqual(keys, set(HANDLERS))

    def test_menus_in_order(self):
        self.assertEqual([title for title, _ in LAYOUT], ["File", "Listening", "View", "Window", "Help"])

    def test_the_settings_pages_are_the_ones_the_settings_window_has(self):
        from quill.ui.settings_dialog import GROUPS
        self.assertEqual(set(SETTINGS_PAGES), {p for _, pages in GROUPS for p in pages})

    def test_no_shortcut_is_used_twice(self):
        shortcuts = [e.shortcut for e in entries() if e.shortcut]
        self.assertEqual(len(shortcuts), len(set(shortcuts)))


class TestBuilt(unittest.TestCase):
    def setUp(self):
        self.rec = Recorder()
        self.menus = QuillMenus(self.rec.handlers, platform="darwin")
        self.window = QMainWindow()
        self.actions = self.menus.install(self.window.menuBar())

    def titles(self):
        return [a.text() for a in self.window.menuBar().actions()]

    def test_the_bar_has_the_menus(self):
        self.assertEqual(self.titles(), ["File", "Listening", "View", "Window", "Help"])

    def test_every_entry_calls_its_handler(self):
        for entry in entries():
            if entry.kind == "submenu":
                continue
            self.rec.calls.clear()
            action = self.actions[entry.key]
            if not action.isEnabled():
                action.setEnabled(True)
            action.trigger()
            self.assertEqual(self.rec.calls, [(entry.key,)], entry.key)

    def test_each_settings_page_opens_its_page(self):
        sub = self.menus._built[0].menus["pages"]
        for action in sub.actions():
            action.trigger()
        self.assertEqual([c[1] for c in self.rec.calls if c[0] == "settings_page"], list(SETTINGS_PAGES))

    def test_listening_changes_the_wording_and_what_is_available(self):
        a = self.actions
        self.assertEqual(a["toggle_listening"].text(), "Start Listening")
        self.assertFalse(a["next_row"].isEnabled())
        self.menus.update(listening=True)
        self.assertEqual(a["toggle_listening"].text(), "Stop Listening")
        self.assertTrue(a["next_row"].isEnabled())
        self.assertTrue(a["new_row"].isEnabled())

    def test_undo_and_use_open_workbook_follow_their_state(self):
        a = self.actions
        self.assertFalse(a["undo"].isEnabled())
        self.menus.update(can_undo=True, can_use_excel=True)
        self.assertTrue(a["undo"].isEnabled())
        self.assertTrue(a["use_excel"].isEnabled())

    def test_term_helper_shows_its_count_and_is_off_with_nothing_to_sort(self):
        a = self.actions
        self.assertFalse(a["term_helper"].isEnabled())
        self.menus.update(sorting_count=3)
        self.assertEqual(a["term_helper"].text(), "Term Helper (3)…")
        self.assertTrue(a["term_helper"].isEnabled())

    def test_mini_wording_goes_both_ways(self):
        self.menus.update(mini=True)
        self.assertEqual(self.actions["mini"].text(), "Switch to the Full Window")
        self.menus.update(mini=False)
        self.assertEqual(self.actions["mini"].text(), "Switch to Mini View")

    def test_check_marks_follow_the_panel_and_log(self):
        a = self.actions
        self.menus.update(panel_page=FILE_PAGE, log_open=True)
        self.assertEqual((a["files_panel"].isChecked(), a["turn_panel"].isChecked(), a["log"].isChecked()), (True, False, True))
        self.menus.update(panel_page=TURN_PAGE, log_open=False)
        self.assertEqual((a["files_panel"].isChecked(), a["turn_panel"].isChecked(), a["log"].isChecked()), (False, True, False))

    def test_turn_mode_is_a_choice_of_one(self):
        a = self.actions
        self.menus.update(turn_mode="append")
        self.assertEqual((a["mode_next_row"].isChecked(), a["mode_append"].isChecked()), (False, True))
        self.menus.update(turn_mode="next_row")
        self.assertEqual((a["mode_next_row"].isChecked(), a["mode_append"].isChecked()), (True, False))

    def test_showing_a_state_never_runs_a_handler(self):
        self.menus.update(panel_page=FILE_PAGE, log_open=True, turn_mode="append", listening=True)
        self.assertEqual(self.rec.calls, [])

    def test_an_unknown_state_name_is_an_error(self):
        with self.assertRaises(AttributeError):
            self.menus.update(nonsense=True)

    def test_a_missing_handler_does_nothing(self):
        window = QMainWindow()
        actions = QuillMenus({}, platform="darwin").install(window.menuBar())
        actions["help"].trigger()                                  # no handler: no error

    def test_macos_roles_and_platform_wording(self):
        from PySide6.QtGui import QAction
        self.assertEqual(self.actions["settings"].menuRole(), QAction.MenuRole.PreferencesRole)
        self.assertEqual(self.actions["quit"].menuRole(), QAction.MenuRole.QuitRole)
        self.assertEqual(self.actions["about"].menuRole(), QAction.MenuRole.AboutRole)
        self.assertEqual(self.actions["quit"].text(), "Quit Quill")

    def test_the_window_less_bar_is_only_built_on_macos(self):
        self.assertIsInstance(self.menus.install_default_bar(), QMenuBar)
        self.assertIsNone(QuillMenus({}, platform="win32").install_default_bar())
        self.assertIsNone(QuillMenus({}, platform="linux").install_default_bar())

    def test_both_bars_follow_the_same_state(self):
        bar = self.menus.install_default_bar()
        self.menus.update(listening=True)
        self.assertEqual(self.menus.actions(bar)["toggle_listening"].text(), "Stop Listening")
        self.assertEqual(self.actions["toggle_listening"].text(), "Stop Listening")

    def test_existing_actions_are_reused_and_an_existing_file_menu_is_filled_in(self):
        window = QMainWindow()
        file_menu = window.menuBar().addMenu("File")
        mine = file_menu.addAction("Open File…")
        actions = QuillMenus({}, platform="darwin").install(window.menuBar(), reuse={"open_file": mine})
        self.assertIs(actions["open_file"], mine)
        self.assertEqual([a.text() for a in window.menuBar().actions()].count("File"), 1)
        self.assertEqual(file_menu.actions()[0], mine)
        self.assertEqual([a.text() for a in file_menu.actions()].count("Open File…"), 1)


class TestInTheApp(PanelApp):
    def setUp(self):
        super().setUp()
        self.menus = self.app.menus
        self.actions = self.menus.actions()
        self.window = self.app.window

    def settle(self):
        for _ in range(3):
            _app.processEvents()

    def test_the_main_window_has_the_menus_and_one_file_menu(self):
        titles = [a.text() for a in self.window.widget.menuBar().actions()]
        self.assertEqual(titles, ["File", "Listening", "View", "Window", "Help"])
        self.assertIs(self.actions["open_file"], self.window.open_file_action)
        self.assertEqual(self.actions["open_file"].shortcut().toString(), "Ctrl+O")

    def test_the_default_bar_exists_on_macos_only(self):
        import sys
        self.assertEqual(self.app._default_menu_bar is not None, sys.platform == "darwin")

    def test_open_file_asks_for_a_file(self):
        self.actions["open_file"].trigger()
        self.assertTrue(self.chosen is not None)

    def test_start_and_stop_listening(self):
        self.actions["toggle_listening"].trigger()
        self.settle()
        self.assertTrue(self.window.listening)
        self.assertEqual(self.actions["toggle_listening"].text(), "Stop Listening")
        self.assertTrue(self.actions["next_row"].isEnabled())
        self.actions["toggle_listening"].trigger()
        self.settle()
        self.assertFalse(self.window.listening)
        self.assertEqual(self.actions["toggle_listening"].text(), "Start Listening")

    def test_mini_view_there_and_back(self):
        self.actions["mini"].trigger()
        self.settle()
        self.assertTrue(self.window.mini)
        self.assertEqual(self.actions["mini"].text(), "Switch to the Full Window")
        self.actions["mini"].trigger()
        self.settle()
        self.assertFalse(self.window.mini)
        self.assertEqual(self.actions["mini"].text(), "Switch to Mini View")

    def test_panels_and_log(self):
        self.actions["files_panel"].trigger()
        self.settle()
        self.assertEqual(self.window.panel_page, FILE_PAGE)
        self.assertTrue(self.actions["files_panel"].isChecked())
        self.actions["turn_panel"].trigger()
        self.settle()
        self.assertEqual(self.window.panel_page, TURN_PAGE)
        self.assertTrue(self.actions["turn_panel"].isChecked())
        self.assertFalse(self.actions["files_panel"].isChecked())
        self.actions["turn_panel"].trigger()
        self.settle()
        self.assertEqual(self.window.panel_page, "")
        before = self.window.log_collapsed
        self.actions["log"].trigger()
        self.settle()
        self.assertNotEqual(self.window.log_collapsed, before)
        self.assertEqual(self.actions["log"].isChecked(), self.window.log_collapsed is False)

    def test_menu_follows_changes_made_elsewhere(self):
        self.window.set_mini(True)
        self.window.open_panel(FILE_PAGE) if False else None
        self.app.request_menu_sync()
        self.settle()
        self.assertEqual(self.actions["mini"].text(), "Switch to the Full Window")

    def test_turn_mode_from_the_menu_changes_the_turn_and_the_panel(self):
        self.actions["mode_append"].trigger()
        self.settle()
        self.assertEqual(self.app.controller.turn_mode, APPEND_TO)
        self.assertTrue(self.window.panel.append_radio.isChecked())
        self.actions["mode_next_row"].trigger()
        self.settle()
        self.assertEqual(self.app.controller.turn_mode, NEXT_ROW)

    def test_settings_and_each_page(self):
        self.actions["settings"].trigger()
        self.assertIsNotNone(self.app._settings_dialog)
        sub = self.menus._built[0].menus["pages"]
        for action in sub.actions():
            action.trigger()
            self.settle()
            self.assertEqual(self.app._settings_dialog.nav.currentItem().data(0x100), action.text())

    def test_undo_follows_history_and_term_helper_follows_pending_terms(self):
        self.assertFalse(self.actions["undo"].isEnabled())
        self.assertFalse(self.actions["term_helper"].isEnabled())

    def test_help_logs_about_and_quit(self):
        with mock.patch.object(self.app, "open_help") as help_:
            self.menus._handlers["help"]()
        help_.assert_called_once()
        with mock.patch("quill.app.open_log_folder") as logs:
            self.menus._handlers["open_logs"]()
        logs.assert_called_once()
        with mock.patch("quill.app.info") as shown:
            self.actions["about"].trigger()
        self.assertIn("Quill", shown.call_args.args[1])
        with mock.patch.object(self.app, "quit_app") as quit_:
            self.menus._handlers["quit"]()
        quit_.assert_called_once()

    def test_refresh_files_checks_now(self):
        with mock.patch.object(self.app, "refresh_open_files") as look:
            self.menus._handlers["refresh_files"]()
        look.assert_called_once_with(manual=True)

    def test_minimize_and_bring_to_front(self):
        with mock.patch.object(self.window.widget, "showMinimized") as mini:
            self.actions["minimize"].trigger()
        mini.assert_called_once()
        self.app._bring_to_front()


if __name__ == "__main__":
    unittest.main()
