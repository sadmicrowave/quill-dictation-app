"""Open Spreadsheet File: working on an .xlsx directly, without Excel."""
import pathlib
import tempfile
import unittest

import openpyxl
from PySide6.QtWidgets import QApplication, QPushButton

from quill.app import QuillApp
from quill.bridge.factory import startup_bridge
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import NO_WORKBOOK_HELP
from quill.ui.main_window import MainWindow
from tests.fixtures import make_workbook
from tests.test_app import FakeListener, FakeSpeaker

_app = QApplication.instance() or QApplication([])


class DeadExcel:
    """Stands in for live Excel on a machine that has none."""
    workbook_name = ""
    workbook_path = ""

    def open_workbooks(self): return []
    def connect(self, workbook=None): from quill.bridge.base import BridgeError; raise BridgeError("No workbook is open in Excel.")
    def disconnect(self): pass
    def active_sheet_name(self, *a): return ""


class FileCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.plants = make_workbook(self.dir / "plants.xlsx")
        self.other = make_workbook(self.dir / "other.xlsx")
        self.settings = Settings.load(self.dir / "cfg")
        self.chosen = [None]
        self.live = DeadExcel()
        self.app = QuillApp(_app, self.settings, self.live, listener_factory=lambda *a: FakeListener(*a),
                            model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None,
                            file_chooser=lambda: self.chosen[0], live_bridge_factory=lambda: DeadExcel())
        self.app.start()
        self.log = self.app.window.log

    def tearDown(self):
        self._tmp.cleanup()

    def sheet(self, path=None):
        return openpyxl.load_workbook(path or self.plants)["Inventory"]


class TestOpeningAFile(FileCase):
    def test_starts_without_a_workbook_when_there_is_no_excel(self):
        self.assertFalse(self.app.connected)
        self.assertTrue(self.app.window.connection_chip.isVisibleTo(self.app.window.widget))

    def test_the_help_text_points_at_the_file_menu(self):
        self.assertIn("Open Spreadsheet File", NO_WORKBOOK_HELP)

    def test_choosing_a_file_connects_to_it_without_excel(self):
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        self.assertTrue(self.app.connected)
        self.assertIsInstance(self.app.controller.bridge, XlsxBridge)
        self.assertEqual(self.app.window.workbook_name, "plants.xlsx")
        self.assertIn("Working directly on the file plants.xlsx", self.log.toPlainText())

    def test_its_lists_are_learned(self):
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        self.assertIn("Fern", self.app.controller.vocab.values_for("Species"))

    def test_dictation_writes_into_the_file(self):
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        c = self.app.controller
        c.handle_transcript("start listening")
        c.handle_transcript("fern small bright")
        c.handle_transcript("next row")
        self.assertEqual(self.sheet()["A4"].value, "Fern")

    def test_the_choice_is_remembered_for_next_time(self):
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        self.assertEqual(Settings.load(self.dir / "cfg").preferences["workbook_file"], str(self.plants))

    def test_cancelling_the_picker_changes_nothing(self):
        self.chosen[0] = None
        self.app.choose_spreadsheet_file()
        self.assertFalse(self.app.connected)
        self.assertEqual(self.settings.preferences["workbook_file"], "")

    def test_switching_to_another_file_closes_listening_and_moves_over(self):
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        self.app.controller.set_listening(True)
        self.chosen[0] = str(self.other)
        self.app.choose_spreadsheet_file()
        self.assertFalse(self.app.controller.session.listening)
        self.assertEqual(self.app.window.workbook_name, "other.xlsx")
        self.app.controller.handle_transcript("start listening")
        self.app.controller.handle_transcript("cactus next row")
        self.assertEqual(self.sheet(self.other)["A4"].value, "Cactus")
        self.assertIsNone(self.sheet(self.plants)["A4"].value)

    def test_a_macro_enabled_or_wrong_file_is_refused_and_the_old_one_kept(self):
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        bad = self.dir / "macros.xlsm"
        bad.write_bytes(b"x")
        self.assertFalse(self.app.open_workbook_file(bad))
        self.assertIn("choose a spreadsheet file", self.log.toPlainText())
        self.assertEqual(self.app.window.workbook_name, "plants.xlsx")
        self.assertTrue(self.app.connected)

    def test_a_missing_file_is_refused(self):
        self.assertFalse(self.app.open_workbook_file(self.dir / "gone.xlsx"))
        self.assertFalse(self.app.connected)

    def test_a_corrupt_file_leaves_the_previous_workbook_working(self):
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        corrupt = self.dir / "broken.xlsx"
        corrupt.write_text("this is not a workbook")
        self.assertFalse(self.app.open_workbook_file(corrupt))
        self.assertTrue(self.app.connected)
        self.assertEqual(self.app.window.workbook_name, "plants.xlsx")
        self.assertEqual(self.settings.preferences["workbook_file"], str(self.plants))

    def test_a_corrupt_first_file_goes_back_to_no_workbook(self):
        corrupt = self.dir / "broken.xlsx"
        corrupt.write_text("this is not a workbook")
        self.assertFalse(self.app.open_workbook_file(corrupt))
        self.assertFalse(self.app.connected)
        self.assertIs(self.app.controller.bridge, self.live)
        self.assertEqual(self.settings.preferences["workbook_file"], "")


class TestGoingBackToExcel(FileCase):
    def test_use_open_excel_workbook_leaves_file_mode_and_forgets_the_file(self):
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        self.app.window.use_excel_action.trigger()
        self.assertNotIsInstance(self.app.controller.bridge, XlsxBridge)
        self.assertEqual(self.settings.preferences["workbook_file"], "")
        self.assertIn("Using the workbook open in your spreadsheet program", self.log.toPlainText())
        self.assertFalse(self.app.window.use_excel_action.isEnabled())

    def test_the_menu_item_is_only_enabled_while_working_on_a_file(self):
        self.assertFalse(self.app.window.use_excel_action.isEnabled())
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        self.assertTrue(self.app.window.use_excel_action.isEnabled())

    def test_an_unsupported_platform_is_reported_not_raised(self):
        def boom():
            raise NotImplementedError("Quill does not support platform 'linux'.")
        self.app._live_bridge_factory = boom
        self.app.use_live_excel()
        self.assertIn("does not support", self.log.toPlainText())


class TestWhereItIsOffered(FileCase):
    def test_a_file_menu_with_open_and_a_shortcut(self):
        window = self.app.window.widget
        titles = [a.text() for a in window.menuBar().actions()]
        self.assertIn("File", titles)
        self.assertEqual(self.app.window.open_file_action.text(), "Open Spreadsheet File…")
        self.assertEqual(self.app.window.open_file_action.shortcut().toString(), "Ctrl+O")

    def test_menu_item_opens_the_picker(self):
        self.chosen[0] = str(self.plants)
        self.app.window.open_file_action.trigger()
        self.assertTrue(self.app.connected)

    def test_a_visible_open_file_button_in_the_status_row(self):
        self.assertTrue(self.app.window.open_file_button.isVisibleTo(self.app.window.widget))
        self.chosen[0] = str(self.plants)
        self.app.window.panel.file_button.click()           # the folder opens the side panel, whose button opens the file window
        self.assertTrue(self.app.connected)

    def test_the_button_is_hidden_in_the_mini_view_with_the_rest_of_the_full_view(self):
        self.app.window.set_mini(True)
        self.assertFalse(self.app.window.open_file_button.isVisibleTo(self.app.window.widget))

    def test_the_menu_bar_icon_menu_offers_it_too(self):
        self.chosen[0] = str(self.plants)
        action = next(a for a in self.app.tray._menu.actions() if a.text() == "Open Spreadsheet File…")
        action.trigger()
        self.assertTrue(self.app.connected)


class TestFileWatching(FileCase):
    def test_changes_saved_elsewhere_are_picked_up_in_file_mode_too(self):
        import os
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        wb = openpyxl.load_workbook(self.plants)
        wb["Config"]["A6"] = "Palm"
        wb.save(self.plants)
        stat = os.stat(self.plants)
        os.utime(self.plants, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.app.poll_workbooks()
        self.assertIn("Palm", self.app.controller.vocab.values_for("Species"))

    def test_the_file_choice_sticks_even_if_excel_appears(self):
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        for _ in range(3):
            self.app.poll_workbooks()
        self.assertIsInstance(self.app.controller.bridge, XlsxBridge)
        self.assertEqual(self.app.window.workbook_name, "plants.xlsx")

    def test_a_deleted_file_is_reported_like_a_closed_workbook(self):
        self.chosen[0] = str(self.plants)
        self.app.choose_spreadsheet_file()
        self.plants.unlink()
        self.app.poll_workbooks()
        self.assertFalse(self.app.connected)
        self.assertIn("was closed", self.log.toPlainText())


class TestStartup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.settings = Settings.load(self.dir / "cfg")
        self.path = make_workbook(self.dir / "plants.xlsx")
        self.made = []
        self.factory = lambda p: self.made.append(p) or ("bridge", p)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_is_live_excel(self):
        startup_bridge(self.settings, None, self.factory)
        self.assertEqual(self.made, [None])

    def test_the_last_opened_file_is_used_when_it_is_still_there(self):
        self.settings.preferences["workbook_file"] = str(self.path)
        startup_bridge(self.settings, None, self.factory)
        self.assertEqual(self.made, [str(self.path)])

    def test_a_moved_or_deleted_file_falls_back_to_live_excel_and_is_forgotten(self):
        self.settings.preferences["workbook_file"] = str(self.dir / "gone.xlsx")
        startup_bridge(self.settings, None, self.factory)
        self.assertEqual(self.made, [None])
        self.assertEqual(self.settings.preferences["workbook_file"], "")

    def test_the_command_line_wins_but_is_not_remembered(self):
        self.settings.preferences["workbook_file"] = str(self.path)
        startup_bridge(self.settings, "/some/other.xlsx", self.factory)
        self.assertEqual(self.made, ["/some/other.xlsx"])
        self.assertEqual(self.settings.preferences["workbook_file"], str(self.path))

    def test_main_uses_the_startup_choice(self):
        text = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text()
        self.assertIn("startup_bridge(settings, args.workbook)", text)

    def test_the_app_starts_in_file_mode_when_the_file_was_remembered(self):
        self.settings.preferences["workbook_file"] = str(self.path)
        bridge = startup_bridge(self.settings)
        app = QuillApp(_app, self.settings, bridge, listener_factory=lambda *a: FakeListener(*a),
                       model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None)
        app.start()
        self.assertTrue(app.connected)
        self.assertTrue(app.window.use_excel_action.isEnabled())
        self.assertEqual(app.window.workbook_name, "plants.xlsx")


if __name__ == "__main__":
    unittest.main()


class FakeHosts:
    """A spreadsheet program other than Excel that has ``path`` open."""

    def __init__(self, app, path):
        self.app, self.path, self.reloaded = app, path, []

    def open_excel_files(self):
        return [(self.app, self.path)]

    def reload(self, app, path):
        self.reloaded.append((app.key, str(path)))
        return True


class TestOtherSpreadsheetPrograms(FileCase):
    def setUp(self):
        super().setUp()
        from quill.bridge.hosts import NUMBERS
        self.hosts = self.app.hosts = FakeHosts(NUMBERS, self.plants)
        self.app.run_in_background = lambda work, done: done(work())          # no helper thread in tests

    def test_a_file_open_in_another_program_is_picked_up_without_any_action(self):
        self.app.poll_workbooks()
        self.assertTrue(self.app.connected)
        self.assertEqual(self.app.controller.bridge.workbook_name, "plants.xlsx")
        self.assertIn("open in Numbers", self.log.toPlainText())
        self.assertEqual(self.settings.preferences["workbook_file"], "")      # found, not chosen: not remembered

    def test_a_program_chosen_in_the_settings_stops_the_search(self):
        self.settings.preferences["spreadsheet_app"] = "excel"
        self.app.poll_workbooks()
        self.assertFalse(self.app.connected)

    def test_the_program_is_asked_to_reload_after_quill_saved(self):
        self.app.poll_workbooks()
        self.app._reload_host()
        self.assertEqual(self.hosts.reloaded, [("numbers", str(self.plants.resolve()))])

    def test_a_program_that_cannot_reload_is_explained_once(self):
        from quill.bridge.hosts import LIBREOFFICE
        self.app.poll_workbooks()
        self.app._host = LIBREOFFICE
        self.app._reload_host()
        self.app._reload_host()
        self.assertEqual(self.log.toPlainText().count("File > Reload"), 1)
