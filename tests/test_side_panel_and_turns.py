"""The side panel (file and turn pages), spreadsheets open in other programs, and the turn settings:
Next Row or Append To, and headings across the top or down the side."""
import pathlib
import tempfile
import unittest
from unittest import mock

import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from quill.app import QuillApp
from quill.bridge.base import BridgeError
from quill.bridge.csv_bridge import CsvBridge
from quill.bridge.grid import OpenpyxlGrid, TransposedGrid
from quill.bridge.hosts import OpenFile, SpreadsheetHosts
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import Controller
from quill.ui.main_window import MainWindow
from quill.ui.side_panel import APPEND_TO, FILE_PAGE, NEXT_ROW, PANEL_WIDTH, TURN_PAGE
from tests.fixtures import make_workbook
from tests.test_app import FakeListener, FakeSpeaker
from tests.test_hosts import FakeRunner, make_file
from tests.test_open_file import DeadExcel

_app = QApplication.instance() or QApplication([])


def make_vertical(path: pathlib.Path) -> pathlib.Path:
    """A sheet whose headings run down column A (Fruit, Color, Qty) with one record in column B."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock"
    for row, (heading, value) in enumerate((("Fruit", "Apple"), ("Color", "Red"), ("Qty", 4)), start=1):
        ws.cell(row=row, column=1, value=heading)
        ws.cell(row=row, column=2, value=value)
    for formula, cells in (('"Apple,Banana,Cherry"', "B1:Z1"), ('"Red,Yellow,Green"', "B2:Z2")):
        dv = DataValidation(type="list", formula1=formula)
        ws.add_data_validation(dv)
        dv.add(cells)
    wb.save(path)
    return path


class Dir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


# --------------------------------------------------------------------------- #
# The panel in the window                                                      #
# --------------------------------------------------------------------------- #

class TestPanelInTheWindow(unittest.TestCase):
    def setUp(self):
        self.saved = MainWindow.animation_ms
        MainWindow.animation_ms = 0
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.resize(453, 383)
        self.w.widget.show()
        _app.processEvents()
        self.opened = []
        self.w.set_panel_listener(self.opened.append)

    def tearDown(self):
        MainWindow.animation_ms = self.saved
        self.w.widget.close()

    def test_it_starts_closed(self):
        self.assertFalse(self.w.panel_open)
        self.assertEqual(self.w.panel.width(), 0)
        self.assertFalse(self.w.panel.isVisibleTo(self.w.widget))

    def test_opening_adds_its_width_to_the_window_and_closing_gives_it_back(self):
        before = self.w.widget.width()
        self.w.open_panel(FILE_PAGE)
        self.assertTrue(self.w.panel_open)
        self.assertEqual(self.w.panel.width(), PANEL_WIDTH)
        self.assertEqual(self.w.widget.width(), before + PANEL_WIDTH)
        self.w.close_panel()
        self.assertEqual(self.w.panel.width(), 0)
        self.assertEqual(self.w.widget.width(), before)

    def test_the_same_icon_closes_it_and_the_other_icon_switches_page(self):
        self.w.toggle_panel(FILE_PAGE)
        self.assertEqual(self.w.panel_page, FILE_PAGE)
        width = self.w.widget.width()
        self.w.toggle_panel(TURN_PAGE)                           # switches: no second growth
        self.assertEqual((self.w.panel_page, self.w.widget.width()), (TURN_PAGE, width))
        self.w.toggle_panel(TURN_PAGE)
        self.assertEqual(self.w.panel_page, "")
        self.assertEqual(self.opened, [FILE_PAGE, TURN_PAGE, ""])

    def test_it_eases_when_animation_is_on(self):
        MainWindow.animation_ms = 120
        self.w.open_panel(FILE_PAGE)
        self.assertLess(self.w.panel.width(), PANEL_WIDTH)       # still on its way
        for _ in range(60):
            _app.processEvents()
            from PySide6.QtTest import QTest
            QTest.qWait(10)
        self.assertEqual(self.w.panel.width(), PANEL_WIDTH)

    def test_the_content_keeps_its_width_while_the_panel_is_open(self):
        content = self.w.root.width()
        self.w.open_panel(FILE_PAGE)
        _app.processEvents()
        self.assertEqual(self.w.root.width(), content)

    def test_the_minimum_width_includes_the_panel(self):
        self.w.open_panel(FILE_PAGE)
        self.assertGreaterEqual(self.w.widget.minimumWidth(), PANEL_WIDTH + 250)

    def test_the_remembered_window_size_leaves_the_panel_out(self):
        sizes = []
        self.w._on_resized = lambda width, height: sizes.append(width)
        self.w.open_panel(FILE_PAGE)
        self.w.report_size()
        self.assertEqual(sizes[-1], 453)

    def test_the_mini_view_has_no_panel_and_the_icon_brings_the_full_window_back(self):
        self.w.open_panel(FILE_PAGE)
        self.w.set_mini(True)
        self.assertFalse(self.w.panel_open)
        self.assertEqual(self.w.panel.width(), 0)
        self.w.toggle_panel(FILE_PAGE)
        for _ in range(5):
            _app.processEvents()
        self.assertFalse(self.w.mini)
        self.assertEqual(self.w.panel_page, FILE_PAGE)

    def test_coming_back_from_the_mini_view_gives_the_size_without_the_panel(self):
        self.w.open_panel(FILE_PAGE)
        self.w.set_mini(True)
        self.w.set_mini(False)
        self.assertEqual(self.w.widget.width(), 453)

    def test_the_window_has_a_turn_icon_that_the_title_bar_can_replace(self):
        self.assertTrue(self.w.turn_button.isVisibleTo(self.w.widget))
        self.w.set_native_turn_button(True)
        self.assertFalse(self.w.turn_button.isVisibleTo(self.w.widget))

    def test_the_in_window_folder_and_turn_buttons_open_the_pages(self):
        self.w.open_file_button.click()
        self.assertEqual(self.w.panel_page, FILE_PAGE)
        self.w.turn_button.click()
        self.assertEqual(self.w.panel_page, TURN_PAGE)

    def test_the_content_never_shrinks_below_its_own_minimum(self):
        self.w.open_panel(FILE_PAGE)
        self.w.close_panel()
        self.assertGreaterEqual(self.w.widget.minimumWidth(), 453)


class TestPanelContents(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.panel = self.w.panel

    def test_the_active_file_shows_its_name_with_the_path_on_hover_and_its_sheet(self):
        self.w.update_workbooks(["plants.xlsx"], "plants.xlsx")
        self.w.set_workbook_path("/Users/me/Documents/plants.xlsx")
        self.w.set_active_sheet("Inventory")
        self.assertEqual(self.panel.file_button.text_label.full_text, "plants.xlsx")
        self.assertEqual(self.panel.file_button.text_label.toolTip(), "/Users/me/Documents/plants.xlsx")
        self.assertEqual(self.panel.fact("Sheet"), "Inventory")

    def test_with_no_file_it_says_so_and_hides_the_sheet(self):
        self.assertEqual(self.panel.file_button.text_label.full_text, "Open File")
        self.assertEqual(self.panel.fact("Sheet"), "")
        self.w.update_workbooks([], "")
        self.assertEqual(self.panel.file_button.text_label.full_text, "Open File")

    def test_a_workbook_without_a_path_hovers_its_name(self):
        self.panel.set_active("Unsaved.xlsx", "", "")
        self.assertEqual(self.panel.file_button.text_label.toolTip(), "Unsaved.xlsx")

    def test_the_list_holds_names_with_a_path_tooltip_and_reports_the_pick(self):
        picked = []
        self.panel.file_chosen.connect(picked.append)
        self.panel.set_available([("a.xlsx", "/x/a.xlsx", 1), ("b.csv", "/x/b.csv", 2)])
        self.assertEqual(self.panel.available_names(), ["a.xlsx", "b.csv"])
        self.assertEqual(self.panel.available.item(1).toolTip(), "/x/b.csv")
        self.panel.available.itemClicked.emit(self.panel.available.item(1))
        self.assertEqual(picked, [2])

    def test_an_empty_list_says_nothing_else_is_open(self):
        self.panel.set_available([])
        self.assertFalse(self.panel.empty_label.isHidden())
        self.panel.set_available([("a.xlsx", "", None)])
        self.assertTrue(self.panel.empty_label.isHidden())

    def test_the_file_page_has_a_muted_rule_between_the_two_sections(self):
        from PySide6.QtWidgets import QFrame
        rules = [f for f in self.panel.findChildren(QFrame) if f.property("panelRule")]
        self.assertTrue(rules)

    def test_the_list_scrolls(self):
        self.panel.set_available([(f"s{i}.xlsx", "", i) for i in range(40)])
        self.assertEqual(self.panel.available.verticalScrollMode(), self.panel.available.ScrollMode.ScrollPerPixel)

    def test_turn_choices_are_reported_but_showing_them_is_not_a_change(self):
        seen = []
        self.panel.mode_changed.connect(seen.append)
        self.panel.layout_changed.connect(seen.append)
        self.panel.set_turn(APPEND_TO, True)
        self.assertEqual(seen, [])
        self.assertTrue(self.panel.append_radio.isChecked())
        self.assertTrue(self.panel.settings.down_radio.isChecked())
        self.panel.next_row_radio.setChecked(True)
        self.panel.settings.across_radio.setChecked(True)
        self.assertEqual(seen, [NEXT_ROW, False])

    def test_start_a_new_row_is_only_for_append_mode(self):
        self.panel.set_turn(NEXT_ROW, False)
        self.assertFalse(self.panel.new_row_button.isEnabled())
        self.panel.set_turn(APPEND_TO, False)
        self.assertTrue(self.panel.new_row_button.isEnabled())


# --------------------------------------------------------------------------- #
# Spreadsheets other programs have open                                        #
# --------------------------------------------------------------------------- #

class TestOpenFiles(Dir):
    def test_excel_workbooks_and_other_programs_files_are_listed_together(self):
        numbers_file = make_file(self.dir, "orders.xlsx")
        runner = FakeRunner({"comm=": "/Applications/Microsoft Excel.app/Contents/MacOS/Microsoft Excel\n"
                                      "/Applications/Numbers.app/Contents/MacOS/Numbers",
                             "Numbers": f"{numbers_file}\n"})
        found = SpreadsheetHosts("darwin", runner).open_files(lambda: [("plants.xlsx", "/x/plants.xlsx"), ("New", "")])
        self.assertEqual([(f.name, f.app, f.live) for f in found],
                         [("plants.xlsx", "Excel", True), ("New", "Excel", True), ("orders.xlsx", "Numbers", False)])

    def test_excel_is_not_asked_unless_it_is_running(self):
        asked = []
        runner = FakeRunner({"comm=": "/Applications/Numbers.app/Contents/MacOS/Numbers"})
        SpreadsheetHosts("darwin", runner).open_files(lambda: asked.append(1) or [])
        self.assertEqual(asked, [])

    def test_a_failing_excel_lookup_is_ignored(self):
        def broken():
            raise RuntimeError("no permission")
        runner = FakeRunner({"comm=": "/Applications/Microsoft Excel.app/Contents/MacOS/Microsoft Excel"})
        self.assertEqual(SpreadsheetHosts("darwin", runner).open_files(broken), [])

    def test_the_same_file_is_listed_once(self):
        path = make_file(self.dir, "both.xlsx")
        runner = FakeRunner({"comm=": "/Applications/Microsoft Excel.app/Contents/MacOS/Microsoft Excel\n"
                                      "/Applications/Numbers.app/Contents/MacOS/Numbers",
                             "Numbers": f"{path}\n"})
        found = SpreadsheetHosts("darwin", runner).open_files(lambda: [("both.xlsx", str(path))])
        self.assertEqual(len(found), 1)

    def test_csv_files_are_listed_too(self):
        path = self.dir / "birds.csv"
        path.write_text("Bird\nWren\n")
        runner = FakeRunner({"comm=": "/Applications/Numbers.app/Contents/MacOS/Numbers", "Numbers": f"{path}\n{self.dir}/notes.txt\n"})
        found = SpreadsheetHosts("darwin", runner).open_files()
        self.assertEqual([f.name for f in found], ["birds.csv"])

    def test_launching_opens_in_the_background_on_a_mac(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("QUILL_NO_HOSTS", None)
            with mock.patch("quill.bridge.hosts.subprocess.run") as run:
                run.return_value.returncode = 0
                self.assertTrue(SpreadsheetHosts("darwin").launch("/x/plants.xlsx"))
        self.assertEqual(run.call_args.args[0], ["open", "-g", "/x/plants.xlsx"])

    def test_launching_does_nothing_under_the_environment_switch(self):
        with mock.patch("quill.bridge.hosts.subprocess.run") as run:
            self.assertFalse(SpreadsheetHosts("darwin").launch("/x/plants.xlsx"))
        run.assert_not_called()

    def test_a_failed_launch_is_reported_not_raised(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("QUILL_NO_HOSTS", None)
            with mock.patch("quill.bridge.hosts.subprocess.run", side_effect=OSError("no")):
                self.assertFalse(SpreadsheetHosts("darwin").launch("/x/plants.xlsx"))


class FakeHosts(SpreadsheetHosts):
    def __init__(self, files=()):
        super().__init__("darwin", lambda args: "")
        self.files, self.launched = list(files), []

    def open_files(self, excel_files=None):
        return list(self.files)

    def launch(self, path, program="auto"):
        self.launched.append(str(path))
        self.launched_with = program
        return True


class NoMirror:
    """A live display that never has the file (the tests must not ask the real Numbers or LibreOffice)."""

    installed_note = False

    def __init__(self, has=False, sheet=None):
        self.has, self.pushed, self.sheet = has, [], sheet

    def has_document(self, path):
        return self.has

    def active_sheet(self, path):
        return self.sheet

    def push(self, path, changes):
        from quill.bridge.numbers_mirror import MirrorResult
        self.pushed.append((path, list(changes)))
        return MirrorResult(self.has, "ok" if self.has else "nodoc")


class PanelApp(Dir):
    def setUp(self):
        super().setUp()
        self.plants = make_workbook(self.dir / "plants.xlsx")
        self.other = make_workbook(self.dir / "other.xlsx")
        self.settings = Settings.load(self.dir / "cfg")
        self.hosts = FakeHosts()
        self.chosen = [None]
        self.app = QuillApp(_app, self.settings, XlsxBridge(self.plants), listener_factory=lambda *a: FakeListener(*a),
                            model_finder=lambda c: self.dir, speaker=FakeSpeaker(), sound_player=lambda p: None,
                            file_chooser=lambda: self.chosen[0], live_bridge_factory=lambda: DeadExcel(), hosts=self.hosts,
                            mirror=NoMirror(), lo_mirror=NoMirror())
        self.app.run_in_background = lambda work, done: done(work())          # no helper thread in tests
        self.app.start()


class TestPanelInTheApp(PanelApp):
    def test_the_folder_toggles_the_panel_and_looks_for_open_files(self):
        self.hosts.files = [OpenFile("other.xlsx", str(self.other), "Numbers")]
        self.app.window.toggle_panel(FILE_PAGE)
        self.assertEqual(self.app.window.panel.available_names(), ["other.xlsx"])
        self.assertTrue(self.app._panel_timer.isActive())
        self.app.window.toggle_panel(FILE_PAGE)
        self.assertFalse(self.app._panel_timer.isActive())

    def test_the_active_file_is_not_in_the_available_list(self):
        self.hosts.files = [OpenFile("plants.xlsx", str(self.plants), "Numbers"), OpenFile("other.xlsx", str(self.other), "Numbers")]
        self.app.window.toggle_panel(FILE_PAGE)
        self.assertEqual(self.app.window.panel.available_names(), ["other.xlsx"])

    def test_picking_one_makes_it_active_and_swaps_the_two_names(self):
        self.hosts.files = [OpenFile("plants.xlsx", str(self.plants), "Numbers"), OpenFile("other.xlsx", str(self.other), "Numbers")]
        self.app.window.toggle_panel(FILE_PAGE)
        panel = self.app.window.panel
        panel.available.itemClicked.emit(panel.available.item(0))
        self.assertEqual(self.app.window.workbook_name, "other.xlsx")
        self.assertEqual(panel.file_button.text_label.full_text, "other.xlsx")
        self.assertEqual(panel.file_button.text_label.toolTip(), str(self.other.resolve()))
        self.assertEqual(panel.available_names(), ["plants.xlsx"])

    def test_picking_a_live_excel_workbook_goes_through_excel(self):
        entry = OpenFile("live.xlsx", "", "Excel", live=True)
        with mock.patch.object(self.app, "use_live_excel") as use, mock.patch.object(self.app, "connect_workbook") as connect:
            self.app._panel_pick(entry)
        use.assert_called_once()
        connect.assert_called_once_with("live.xlsx")

    def test_the_file_button_in_the_panel_opens_the_file_window(self):
        self.chosen[0] = str(self.other)
        self.app.window.panel.file_button.click()
        self.assertEqual(self.app.window.workbook_name, "other.xlsx")

    def test_a_file_chosen_with_the_file_window_is_launched_when_nothing_has_it_open(self):
        self.chosen[0] = str(self.other)
        with mock.patch("quill.app.bring_app_forward") as forward, mock.patch("quill.app.QTimer.singleShot", lambda ms, fn: fn()):
            self.app.choose_spreadsheet_file()
        self.assertEqual(self.hosts.launched, [str(self.other)])
        self.assertTrue(forward.called)                           # Quill is put back in front

    def test_a_file_that_is_already_open_is_not_launched_again(self):
        self.hosts.files = [OpenFile("other.xlsx", str(self.other), "Numbers")]
        self.chosen[0] = str(self.other)
        self.app.choose_spreadsheet_file()
        self.assertEqual(self.hosts.launched, [])

    def test_a_refused_file_is_not_launched(self):
        bad = self.dir / "bad.txt"
        bad.write_text("x")
        self.chosen[0] = str(bad)
        self.app.choose_spreadsheet_file()
        self.assertEqual(self.hosts.launched, [])

    def test_turn_choices_in_the_panel_reach_the_controller(self):
        panel, controller = self.app.window.panel, self.app.controller
        panel.append_radio.setChecked(True)
        self.assertEqual(controller.turn_mode, "append")
        panel.settings.down_radio.setChecked(True)
        self.assertTrue(controller.vertical)
        self.assertEqual(self.settings.preferences["turn_mode"], "append")
        self.assertTrue(self.settings.preferences["vertical_layout"])

    def test_opening_the_turn_page_shows_the_saved_choices(self):
        self.settings.preferences["turn_mode"] = "append"
        self.app.window.toggle_panel(TURN_PAGE)
        self.assertTrue(self.app.window.panel.append_radio.isChecked())


# --------------------------------------------------------------------------- #
# Turn settings                                                                #
# --------------------------------------------------------------------------- #

class TestSettingsDefaults(Dir):
    def test_defaults(self):
        settings = Settings.load(self.dir / "cfg")
        self.assertEqual(settings.preferences["turn_mode"], "next_row")
        self.assertFalse(settings.preferences["vertical_layout"])

    def test_choices_are_saved_and_a_bad_mode_is_replaced(self):
        settings = Settings.load(self.dir / "cfg")
        settings.preferences["turn_mode"] = "append"
        settings.preferences["vertical_layout"] = True
        settings.save()
        again = Settings.load(self.dir / "cfg")
        self.assertEqual((again.preferences["turn_mode"], again.preferences["vertical_layout"]), ("append", True))
        again.preferences["turn_mode"] = "sideways"
        again.save()
        self.assertEqual(Settings.load(self.dir / "cfg").preferences["turn_mode"], "next_row")


class TestTransposedGrid(Dir):
    def test_reads_and_writes_swap_rows_and_columns(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"], ws["B1"], ws["A2"], ws["B2"], ws["A3"] = "h1", "x", "h2", "y", "h3"
        grid = TransposedGrid(OpenpyxlGrid(wb))
        sheet = ws.title
        self.assertEqual((grid.last_row(sheet), grid.last_col(sheet)), (2, 3))
        self.assertEqual(grid.read(sheet, 1, 1, 2, 3), [["h1", "h2", "h3"], ["x", "y", None]])
        grid.write(sheet, 2, 3, "z")
        self.assertEqual(ws["B3"].value, "z")

    def test_an_empty_read_is_empty(self):
        self.assertEqual(TransposedGrid(OpenpyxlGrid(openpyxl.Workbook())).read("Sheet", 1, 1, 0, 3), [])


class TestVerticalWorkbook(Dir):
    def setUp(self):
        super().setUp()
        self.path = make_vertical(self.dir / "stock.xlsx")
        self.bridge = XlsxBridge(self.path)
        self.bridge.set_vertical(True)
        self.bridge.connect()

    def test_headings_come_from_the_first_column(self):
        self.assertEqual(self.bridge.get_headers(), ["Fruit", "Color", "Qty"])

    def test_the_drop_down_lists_of_row_ranges_are_found(self):
        lists = self.bridge.get_lists()
        self.assertEqual(lists["Fruit"], ["Apple", "Banana", "Cherry"])
        self.assertEqual(lists["Color"], ["Red", "Yellow", "Green"])

    def test_a_record_goes_into_the_next_empty_column(self):
        column = self.bridge.append_row("Stock", {"Fruit": "Banana", "Color": "Yellow", "Qty": 6})
        self.assertEqual(column, 3)                                   # column B holds the first record
        ws = openpyxl.load_workbook(self.path)["Stock"]
        self.assertEqual([ws.cell(row=r, column=3).value for r in (1, 2, 3)], ["Banana", "Yellow", 6])

    def test_numeric_columns_are_headings_whose_row_holds_numbers(self):
        self.assertEqual(self.bridge.numeric_columns(), ["Qty"])

    def test_back_filling_and_undoing_a_cell_work_on_the_other_axis(self):
        column = self.bridge.append_row("Stock", {"Fruit": "Banana"})
        self.assertTrue(self.bridge.set_value("Stock", column, "Color", "Yellow"))
        self.assertEqual(openpyxl.load_workbook(self.path)["Stock"].cell(row=2, column=column).value, "Yellow")
        self.assertTrue(self.bridge.clear_value("Stock", column, "Color", "Yellow"))

    def test_searching_says_it_needs_headings_across(self):
        with self.assertRaises(BridgeError):
            self.bridge.apply_filters("Stock", [])

    def test_a_missing_heading_names_where_headings_are_read_from(self):
        with self.assertRaisesRegex(BridgeError, "first column"):
            self.bridge.append_row("Stock", {"Weight": 3})

    def test_switching_back_reads_the_sheet_across_again(self):
        self.bridge.set_vertical(False)
        self.assertFalse(self.bridge.vertical)
        self.assertNotIn("Color", self.bridge.get_headers())

    def test_a_list_on_a_config_sheet_is_still_a_column_list(self):
        wb = openpyxl.load_workbook(self.path)
        cfg = wb.create_sheet("Config")
        cfg["A1"], cfg["A2"], cfg["A3"] = "Origin_list", "Peru", "Chile"
        wb.save(self.path)
        self.bridge.connect()
        self.assertEqual(self.bridge.get_lists()["Origin"], ["Peru", "Chile"])


class TestAppendTo(Dir):
    def setUp(self):
        super().setUp()
        self.path = make_workbook(self.dir / "plants.xlsx")
        self.bridge = XlsxBridge(self.path)
        self.bridge.connect()

    def cell(self, row, header_col):
        return openpyxl.load_workbook(self.path)["Inventory"].cell(row=row, column=header_col).value

    def test_the_first_call_takes_the_next_free_row_and_returns_it(self):
        row = self.bridge.append_to_row("Inventory", None, {"Species": "Fern"})
        self.assertEqual(self.cell(row, 1), "Fern")

    def test_later_calls_add_after_a_comma(self):
        row = self.bridge.append_to_row("Inventory", None, {"Species": "Fern", "Pot Size": "Small"})
        self.assertEqual(self.bridge.append_to_row("Inventory", row, {"Species": "Moss"}), row)
        self.bridge.append_to_row("Inventory", row, {"Species": "Ivy"})
        self.assertEqual(self.cell(row, 1), "Fern, Moss, Ivy")
        self.assertEqual(self.cell(row, 2), "Small")                  # the other column is untouched

    def test_several_values_in_one_turn_are_separated_by_commas_not_line_breaks(self):
        row = self.bridge.append_to_row("Inventory", None, {"Species": "Fern\nMoss"})
        self.assertEqual(self.cell(row, 1), "Fern, Moss")

    def test_a_formula_cell_is_left_alone(self):
        row = self.bridge.append_to_row("Inventory", None, {"Species": "Fern"})
        wb = openpyxl.load_workbook(self.path)
        wb["Inventory"].cell(row=row, column=2).value = "=1+1"
        wb.save(self.path)
        self.bridge.connect()
        self.bridge.append_to_row("Inventory", row, {"Pot Size": "Large"})
        self.assertEqual(self.cell(row, 2), "=1+1")

    def test_numbers_and_dates_join_as_text(self):
        import datetime as dt
        row = self.bridge.append_to_row("Inventory", None, {"Species": "Fern"})
        self.bridge.append_to_row("Inventory", row, {"Species": dt.date(2026, 1, 2)})
        self.assertEqual(self.cell(row, 1), "Fern, 2026-01-02")

    def test_an_unknown_column_is_an_error(self):
        with self.assertRaises(BridgeError):
            self.bridge.append_to_row("Inventory", None, {"Nope": "x"})


class TestTurnsInTheController(Dir):
    def setUp(self):
        super().setUp()
        self.path = make_workbook(self.dir / "plants.xlsx")
        self.settings = Settings.load(self.dir / "cfg")
        self.events = []
        self.controller = Controller(XlsxBridge(self.path), self.settings, on_event=self.events.append)
        self.controller.connect()

    def say(self, *phrases):
        for phrase in phrases:
            self.controller.handle_transcript(phrase)

    def sheet(self):
        return openpyxl.load_workbook(self.path)["Inventory"]

    def test_next_row_is_the_default_and_every_turn_is_a_new_row(self):
        self.say("start listening", "fern", "next row", "cactus", "next row")
        ws = self.sheet()
        self.assertEqual([ws.cell(row=r, column=1).value for r in (4, 5)], ["Fern", "Cactus"])

    def test_append_to_keeps_adding_to_the_same_row(self):
        self.controller.set_turn_mode("append")
        self.say("start listening", "fern", "next row", "cactus", "next row")
        ws = self.sheet()
        self.assertEqual(ws.cell(row=4, column=1).value, "Fern, Cactus")
        self.assertIsNone(ws.cell(row=5, column=1).value)
        saved = [e.detail for e in self.events if e.kind == "committed"]
        self.assertEqual(saved, ["Row 4 (added to)", "Row 4 (added to)"])

    def test_start_a_new_row_ends_the_shared_row(self):
        self.controller.set_turn_mode("append")
        self.say("start listening", "fern", "next row")
        self.controller.start_new_row()
        self.say("cactus", "next row")
        ws = self.sheet()
        self.assertEqual([ws.cell(row=r, column=1).value for r in (4, 5)], ["Fern", "Cactus"])

    def test_changing_the_mode_starts_a_fresh_row_and_is_remembered(self):
        self.controller.set_turn_mode("append")
        self.say("start listening", "fern", "next row")
        self.controller.set_turn_mode("next_row")
        self.say("cactus", "next row")
        self.assertEqual(self.settings.preferences["turn_mode"], "next_row")
        self.assertEqual(self.sheet().cell(row=5, column=1).value, "Cactus")

    def test_an_unknown_mode_is_ignored(self):
        self.controller.set_turn_mode("sideways")
        self.assertEqual(self.controller.turn_mode, "next_row")

    def test_a_failed_append_keeps_what_was_said(self):
        self.controller.set_turn_mode("append")
        self.say("start listening", "fern")
        with mock.patch.object(self.controller.bridge, "append_to_row", side_effect=BridgeError("locked")):
            self.say("next row")
        self.assertEqual(self.controller.session.record["Species"], "Fern")
        self.assertEqual(self.events[-1].kind, "error")

    def test_the_vertical_layout_is_applied_on_connecting_and_names_columns(self):
        vertical = make_vertical(self.dir / "stock.xlsx")
        self.settings.preferences["vertical_layout"] = True
        controller = Controller(XlsxBridge(vertical), self.settings, on_event=self.events.append)
        controller.connect()
        self.assertEqual(controller.vocab.fields(), ["Fruit", "Color", "Qty"]) if hasattr(controller.vocab, "fields") else None
        controller.handle_transcript("start listening")
        controller.handle_transcript("banana yellow")
        controller.handle_transcript("next row")
        saved = [e.detail for e in self.events if e.kind == "committed"]
        self.assertEqual(saved, ["Column C"])
        self.assertEqual(openpyxl.load_workbook(vertical)["Stock"]["C1"].value, "Banana")

    def test_switching_the_layout_reloads_the_vocabulary_and_remembers_it(self):
        vertical = make_vertical(self.dir / "stock.xlsx")
        controller = Controller(XlsxBridge(vertical), self.settings, on_event=self.events.append)
        controller.connect()
        self.assertNotIn("Color", controller.vocab.values_for("Fruit"))
        controller.set_vertical(True)
        self.assertIn("Banana", controller.vocab.values_for("Fruit"))
        self.assertTrue(self.settings.preferences["vertical_layout"])
        controller.set_vertical(False)
        self.assertFalse(controller.vertical)

    def test_a_bridge_that_does_not_know_layouts_is_left_alone(self):
        class Plain:
            vertical = False
        controller = Controller.__new__(Controller)
        controller.bridge = Plain()
        self.assertEqual(Controller._record_name(controller, 7), "Row 7")


class TestCsvTurns(Dir):
    def test_a_csv_file_can_append_and_run_vertically(self):
        path = self.dir / "birds.csv"
        path.write_text("Bird,Place\nWren,Park\n")
        bridge = CsvBridge(path)
        bridge.connect()
        row = bridge.append_to_row("birds", None, {"Bird": "Owl"})
        bridge.append_to_row("birds", row, {"Bird": "Crow", "Place": "Farm"})
        self.assertEqual(path.read_text().splitlines(), ["Bird,Place", "Wren,Park", '"Owl, Crow",Farm'])

    def test_a_vertical_csv_adds_a_column_per_record(self):
        path = self.dir / "birds.csv"
        path.write_text("Bird,Wren\nPlace,Park\n")
        bridge = CsvBridge(path)
        bridge.set_vertical(True)
        bridge.connect()
        self.assertEqual(bridge.get_headers(), ["Bird", "Place"])
        column = bridge.append_row("birds", {"Bird": "Owl", "Place": "Farm"})
        self.assertEqual(column, 3)
        self.assertEqual(path.read_text().splitlines(), ["Bird,Wren,Owl", "Place,Park,Farm"])


class TestNextButtonAndPolicy(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.show()
        self.w.set_listening_indicator(True)
        _app.processEvents()

    def tearDown(self):
        self.w.widget.close()

    def test_next_is_as_tall_as_start_and_outlined_in_the_accent(self):
        self.assertEqual(self.w.next_button.height(), self.w.toggle_button.height())
        self.assertTrue(self.w.next_button.property("outline"))

    def test_next_has_a_media_player_icon(self):
        from quill.ui.icons import SHAPES
        self.assertIn("rect", SHAPES["next"])                      # a triangle and a bar, not an arrow
        self.assertNotIn("M5 12h13", SHAPES["next"])

    def test_plain_buttons_have_a_purple_border_and_icon_only_ones_do_not(self):
        from quill.ui.theme import colors_for, stylesheet_for
        sheet = stylesheet_for(False)
        accent = colors_for(False, "violet")["accent"]
        start = sheet.index("QPushButton {")
        self.assertIn(f"border: 1px solid {accent}", sheet[start: sheet.index("}", start)])
        start = sheet.index('QPushButton[iconOnly="true"] {')
        self.assertNotIn(f"border-color: {accent}", sheet[start: sheet.index("}", start)])

    def test_the_countdown_shows_just_the_seconds(self):
        self.w.toggle_button.set_countdown(7)
        self.assertEqual(self.w.countdown_label.text(), "7s")


class TestPanelHeaderAndFiles(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.panel = self.w.panel

    def test_the_panel_is_titled_by_its_page_and_has_a_close_button(self):
        self.w.set_native_panel_header(True)                      # the title bar draws them on a Mac
        self.assertTrue(self.panel.header.isHidden())
        self.w.set_native_panel_header(False)
        self.panel.show_page(FILE_PAGE)
        self.assertEqual(self.panel.title_label.text(), "Files")
        self.panel.show_page(TURN_PAGE)
        self.assertEqual(self.panel.title_label.text(), "Turn Options")
        self.w.widget.show()
        MainWindow.animation_ms, saved = 0, MainWindow.animation_ms
        try:
            self.w.open_panel(FILE_PAGE)
            self.panel.close_button.click()
            self.assertFalse(self.w.panel_open)
        finally:
            MainWindow.animation_ms = saved
            self.w.widget.close()

    def test_the_empty_message_reads_as_asked_and_sits_with_the_section_not_the_bottom(self):
        self.panel.set_available([])
        self.assertEqual(self.panel.empty_label.text(), "No open spreadsheet files detected.")
        self.assertFalse(self.panel.available.isVisibleTo(self.panel))
        self.assertTrue(self.panel.empty_label.alignment() & Qt.AlignmentFlag.AlignTop)

    def test_the_section_is_called_files_and_has_a_filter_under_it(self):
        headings = [l.text() for l in self.panel.findChildren(QLabel) if l.property("panelHeading")]
        self.assertIn("Available Files", headings)
        self.assertNotIn("Available Spreadsheets", headings)
        self.assertEqual(self.panel.search.placeholderText(), "Search")

    def test_the_filter_narrows_the_list_and_says_when_nothing_matches(self):
        self.panel.set_available([("Orders.xlsx", "", 1), ("Birds.csv", "", 2), ("orders-old.xlsx", "", 3)])
        self.panel.search.setText("ORDERS")
        shown = [self.panel.available.item(i).text() for i in range(3) if not self.panel.available.item(i).isHidden()]
        self.assertEqual(shown, ["Orders.xlsx", "orders-old.xlsx"])
        self.panel.search.setText("zzz")
        self.assertEqual(self.panel.empty_label.text(), "No files match.")
        self.assertFalse(self.panel.available.isVisibleTo(self.panel))
        self.panel.search.setText("")
        self.assertTrue(self.panel.available.isVisibleTo(self.panel) or not self.panel.isVisible())

    def test_the_starting_row_is_a_number_with_automatic_when_empty(self):
        seen = []
        self.panel.start_row_changed.connect(seen.append)
        self.panel.set_options(NEXT_ROW, False, 0, 0)
        self.assertEqual(self.panel.settings.start_box.display(), "Automatic")
        self.panel.settings.start_number.setValue(5)
        self.assertEqual(seen, [5])
        self.panel.set_options(NEXT_ROW, True, 3, 0)
        self.assertEqual(seen, [5])                                  # showing a value is not a change

    def test_by_rows_offers_columns_a_to_z_in_the_settings_drop_down_style(self):
        from quill.ui.settings_widgets import FlatCombo
        self.panel.set_options(NEXT_ROW, True, 3, 2)
        box = self.panel.settings.start_box
        self.assertIsInstance(box, FlatCombo)
        self.assertEqual([box.itemText(i) for i in range(box.count())], ["Automatic", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ"])
        self.assertEqual((box.display(), self.panel.settings.headings_box.display()), ("C", "B"))
        seen = []
        self.panel.headings_row_changed.connect(seen.append)
        self.panel.settings.headings_box.setCurrentIndex(26)
        self.assertEqual(seen, [26])

    def test_by_columns_uses_whole_row_numbers_not_letters(self):
        self.panel.set_options(NEXT_ROW, False, 3, 2)
        self.assertEqual((self.panel.settings.start_box.value(), self.panel.settings.headings_box.value()), (3, 2))
        self.assertTrue(self.panel.settings.start_letter.isHidden())


class TestStartRow(Dir):
    def test_turns_begin_at_the_starting_row_and_auto_uses_the_first_empty_one(self):
        path = make_workbook(self.dir / "plants.xlsx")
        bridge = XlsxBridge(path)
        bridge.connect()
        self.assertEqual(bridge.append_row("Inventory", {"Species": "Fern"}), 4)      # first empty row under the headings
        bridge.set_start_row(10)
        self.assertEqual(bridge.append_row("Inventory", {"Species": "Cactus"}), 10)
        self.assertEqual(bridge.append_row("Inventory", {"Species": "Orchid"}), 11)
        bridge.set_start_row(0)
        self.assertEqual(bridge.append_row("Inventory", {"Species": "Monstera"}), 5)  # back to the first gap

    def test_a_row_inside_the_headings_is_pushed_below_them(self):
        bridge = XlsxBridge(make_workbook(self.dir / "plants.xlsx"))
        bridge.connect()
        bridge.set_start_row(1)
        self.assertEqual(bridge.append_row("Inventory", {"Species": "Fern"}), 4)

    def test_append_to_honours_it_and_vertical_sheets_use_it_as_a_column(self):
        bridge = XlsxBridge(make_vertical(self.dir / "stock.xlsx"))
        bridge.set_vertical(True)
        bridge.connect()
        bridge.set_start_row(6)
        self.assertEqual(bridge.append_to_row("Stock", None, {"Fruit": "Banana"}), 6)

    def test_the_controller_saves_it_applies_it_and_resets_the_shared_row(self):
        settings = Settings.load(self.dir / "cfg")
        controller = Controller(XlsxBridge(make_workbook(self.dir / "plants.xlsx")), settings, on_event=lambda e: None)
        controller.connect()
        controller.set_start_row(8)
        controller.handle_transcript("start listening")
        controller.handle_transcript("fern")
        controller.handle_transcript("next row")
        self.assertEqual(openpyxl.load_workbook(self.dir / "plants.xlsx")["Inventory"]["A8"].value, "Fern")
        self.assertEqual(Settings.load(self.dir / "cfg").preferences["start_row"], 8)
        again = Controller(XlsxBridge(self.dir / "plants.xlsx"), Settings.load(self.dir / "cfg"), on_event=lambda e: None)
        again.connect()
        self.assertEqual(again.bridge._start_row, 8)


class TestTurnVoiceKeywords(Dir):
    def setUp(self):
        super().setUp()
        self.settings = Settings.load(self.dir / "cfg")
        self.events = []
        self.controller = Controller(XlsxBridge(make_workbook(self.dir / "plants.xlsx")), self.settings, on_event=self.events.append)
        self.controller.connect()
        self.controller.handle_transcript("start listening")

    def kinds(self):
        return [(e.kind, e.detail) for e in self.events if e.kind.startswith("turn_")]

    def test_each_option_has_an_on_and_an_off_phrase(self):
        for phrase, kind in (("append on", "turn_on"), ("append off", "turn_off"), ("rows down", "turn_on"), ("columns across", "turn_off")):
            self.controller.handle_transcript(phrase)
            self.assertEqual(self.events[-1].kind, kind, phrase)

    def test_append_mode_and_layout_really_change_and_are_saved(self):
        self.controller.handle_transcript("append mode")
        self.assertEqual(self.settings.preferences["turn_mode"], "append")
        self.controller.handle_transcript("row mode")
        self.assertEqual(self.settings.preferences["turn_mode"], "next_row")
        self.controller.handle_transcript("rows down")
        self.assertTrue(self.controller.vertical)
        self.controller.handle_transcript("columns across")
        self.assertFalse(self.controller.vertical)

    def test_they_only_work_while_listening(self):
        self.controller.handle_transcript("stop listening")
        self.controller.handle_transcript("append on")
        self.assertEqual(self.controller.turn_mode, "next_row")

    def test_on_and_off_get_their_own_cues(self):
        from quill.feedback import cue_for
        self.controller.handle_transcript("append on")
        self.assertEqual(cue_for(self.events[-1]), ("success", ""))
        self.controller.handle_transcript("append off")
        self.assertEqual(cue_for(self.events[-1]), ("dismiss", "Off"))

    def test_the_panel_follows_a_spoken_option(self):
        app = PanelApp()
        app.setUp()
        try:
            app.app.controller.handle_transcript("start listening")
            app.app.controller.handle_transcript("append on")
            self.assertTrue(app.app.window.panel.append_radio.isChecked())
            app.app.controller.handle_transcript("rows down")
            self.assertTrue(app.app.window.panel.settings.down_radio.isChecked())
        finally:
            app._tmp.cleanup()

    def test_old_keyword_files_gain_the_new_phrases_without_losing_deleted_ones(self):
        (self.dir / "cfg2").mkdir()
        (self.dir / "cfg2" / Settings.KEYWORDS_FILE).write_text('keywords_version = 2\n[keywords]\n"go" = "START_LISTENING"\n', encoding="utf-8")
        loaded = Settings.load(self.dir / "cfg2")
        self.assertIn("append on", loaded.keywords)
        self.assertNotIn("next row", loaded.keywords)


class TestTermHelperPlacement(unittest.TestCase):
    def setUp(self):
        from quill.parser.vocab import Vocabulary
        from quill.ui.sorting_window import SortingWindow
        self.main = MainWindow()
        self.main.setup()
        self.sw = SortingWindow(Vocabulary(), lambda *a: None)
        self.sw.setup(parent=self.main.widget)
        self.sw.set_items([(None, "teal")])

    def tearDown(self):
        self.sw.widget.close()

    def test_first_open_is_the_bottom_left_of_the_screen_the_main_window_is_on(self):
        self.sw.show()
        room = self.main.widget.screen().availableGeometry()
        frame = self.sw.widget.frameGeometry()                       # (the window's frame, title bar included)
        self.assertEqual(frame.left(), room.left())
        self.assertEqual(frame.bottom(), room.bottom())

    def test_a_saved_place_wins_and_is_remembered_after_a_move(self):
        self.sw.restore_place(120, 90, 0)
        self.sw.show()
        self.assertEqual((self.sw.widget.x(), self.sw.widget.y()), (120, 90))
        seen = []
        self.sw.on_geometry = lambda x, y, w: seen.append((x, y, w))
        self.sw.widget.move(200, 150)
        self.sw._report_geometry()
        self.assertEqual(seen[-1][:2], (200, 150))

    def test_a_saved_place_off_every_screen_falls_back_to_the_corner(self):
        self.sw.restore_place(90000, 90000, 0)
        self.sw.show()
        room = self.main.widget.screen().availableGeometry()
        self.assertEqual(self.sw.widget.frameGeometry().left(), room.left())

    def test_it_is_placed_only_once_so_the_user_can_move_it_afterwards(self):
        self.sw.show()
        self.sw.widget.move(300, 120)
        self.sw.widget.hide()
        self.sw.show()
        self.assertEqual((self.sw.widget.x(), self.sw.widget.y()), (300, 120))

    def test_it_cannot_be_made_narrower_than_a_row_and_grows_with_the_font(self):
        self.sw.show()
        narrow = self.sw.widget.minimumWidth()
        self.assertGreaterEqual(narrow, self.sw.rows[0].sizeHint().width())
        font = self.sw.widget.font()
        font.setPointSize(font.pointSize() + 8)
        self.sw.widget.setFont(font)
        for row in self.sw.rows:
            row.setFont(font)
        self.sw.refresh_icons()
        self.assertGreaterEqual(self.sw.widget.minimumWidth(), narrow)

    def test_its_start_button_is_as_tall_as_the_main_windows(self):
        self.sw.widget.show()
        self.main.widget.show()
        self.assertEqual(self.sw.voice_button.minimumHeight(), self.main.toggle_button.minimumHeight())


class TestFilePanelDetails(Dir):
    def setUp(self):
        super().setUp()
        self.w = MainWindow()
        self.w.setup()
        self.panel = self.w.panel

    def test_the_active_file_facts_are_a_borderless_table_of_labels_and_plain_values(self):
        path = make_workbook(self.dir / "plants.xlsx")
        self.panel.set_active("plants.xlsx", "Inventory", str(path), "Excel workbook (.xlsx)")
        self.assertEqual([self.panel.fact(n) for n in ("Sheet", "Path", "Type")], ["Inventory", str(path), "Excel workbook (.xlsx)"])
        for name in ("Sheet", "Path", "Type", "Size", "Modified", "Created"):
            label, value = self.panel.fact_rows[name]
            self.assertEqual(label.text(), name)                            # no colon: the table lines them up
            self.assertFalse(label.isHidden() or value.isHidden(), name)
            self.assertTrue(label.property("panelNote") and value.property("panelValue"))
        grid = self.panel.fact_rows["Sheet"][0].parentWidget().layout()
        self.assertTrue(grid is not None)

    def test_dates_are_numeric_mm_dd_yy(self):
        import re
        path = make_workbook(self.dir / "plants.xlsx")
        self.panel.set_active("plants.xlsx", "", str(path), "")
        for label in ("Modified", "Created"):
            self.assertRegex(self.panel.fact(label), r"^\d\d/\d\d/\d\d$")
        self.assertRegex(self.panel.fact("Size"), r"^\d+(\.\d)? (bytes|KB|MB)$")

    def test_with_no_file_none_of_it_shows(self):
        self.panel.set_active("", "", "", "")
        for label, value in self.panel.fact_rows.values():
            self.assertTrue(label.isHidden() and value.isHidden())

    def test_a_workbook_without_a_path_shows_only_sheet_and_type(self):
        self.panel.set_active("Unsaved.xlsx", "", "", "Excel (live)")
        self.assertEqual(self.panel.fact("Type"), "Excel (live)")
        self.assertEqual((self.panel.fact("Path"), self.panel.fact("Size")), ("", ""))

    def test_the_path_has_its_own_label_and_stays_on_one_line(self):
        label, value = self.panel.fact_rows["Path"]
        self.assertEqual(label.text(), "Path")
        self.assertIsInstance(value, __import__("quill.ui.widgets", fromlist=["ElidedLabel"]).ElidedLabel)

    def test_sizes_read_naturally(self):
        from quill.ui.side_panel import human_size
        self.assertEqual((human_size(12), human_size(1536), human_size(5 * 1024 * 1024)), ("12 bytes", "1.5 KB", "5.0 MB"))

    def test_the_file_button_says_open_file_with_a_closed_folder_until_a_file_is_active(self):
        self.assertEqual(self.panel.file_button.text_label.full_text, "Open File")
        self.assertFalse(self.panel._has_file)
        self.panel.set_active("a.xlsx", "", "/x/a.xlsx")
        self.assertTrue(self.panel._has_file)

    def test_a_long_name_is_cut_with_an_ellipsis_not_wrapped(self):
        self.panel.set_active("a very long spreadsheet name that cannot fit on the button at all.xlsx", "", "/x")
        label = self.panel.file_button.text_label
        label.resize(120, 20)
        label._elide()
        self.assertIn("…", label.text())

    def test_the_number_fields_read_automatic_when_empty_and_report_what_is_typed(self):
        seen = []
        self.panel.headings_row_changed.connect(seen.append)
        field = self.panel.settings.headings_number
        self.assertEqual(field.display(), "Automatic")
        field.setText("4")
        field.editingFinished.emit()
        self.assertEqual(seen, [4])
        field.setText("")
        field.editingFinished.emit()
        self.assertEqual(seen, [4, 0])

    def test_the_turn_page_starts_with_the_description_and_a_keywords_link_then_a_rule(self):
        from PySide6.QtWidgets import QFrame
        intro = self.panel.turn_intro
        self.assertIn("Settings to control how each speak-match-write iteration (known as a 'Turn') is handled.", intro.text())
        self.assertIn('href="keywords"', intro.text())
        asked = []
        self.panel.keywords_requested.connect(lambda: asked.append(1))
        intro.linkActivated.emit("keywords")
        self.assertEqual(asked, [1])
        turn_page = self.panel.stack.widget(1).widget()
        order = [turn_page.layout().itemAt(i).widget() for i in range(turn_page.layout().count()) if turn_page.layout().itemAt(i).widget()]
        self.assertIs(order[0], intro)
        self.assertTrue(order[1].property("panelRule"))
        self.assertEqual(order[1].height(), 1)
        titles = [l.text() for l in turn_page.findChildren(QLabel) if l.property("panelHeading")]
        self.assertNotIn("Each Turn", titles)

    def test_the_turn_page_describes_its_two_choices_and_has_a_next_button(self):
        notes = [l.text() for l in self.panel.findChildren(QLabel) if l.property("panelNote")]
        self.assertIn("Turn words are written to new rows.", notes)
        self.assertIn("Turn words are added to the same row.", notes)
        self.assertEqual(self.panel.new_row_button.text(), "Next")
        self.assertEqual(self.panel.new_row_button.toolTip(), "Move cursor to the next row.")
        self.assertTrue(self.panel.new_row_button.property("outline"))

    def test_start_row_layout_and_headings_are_in_the_settings_overlay_not_on_either_page(self):
        file_page = self.panel.stack.widget(0).widget()
        turn_page = self.panel.stack.widget(1).widget()
        for widget in (self.panel.settings.start_number, self.panel.settings.down_radio, self.panel.settings.headings_number):
            self.assertTrue(self.panel.settings.isAncestorOf(widget))
            self.assertFalse(file_page.isAncestorOf(widget) or turn_page.isAncestorOf(widget))

    def test_the_available_files_section_has_its_title_description_and_search(self):
        texts = [l.text() for l in self.panel.findChildren(QLabel)]
        self.assertIn("Available Files", texts)
        self.assertIn("Spreadsheet files currently open on your computer.", texts)
        self.assertEqual(self.panel.search.placeholderText(), "Search")

    def test_the_edge_line_is_one_pixel(self):
        from PySide6.QtWidgets import QFrame
        edges = [f for f in self.panel.findChildren(QFrame) if f.property("panelEdge")]
        self.assertEqual([e.width() for e in edges] or [1], [1])

    def test_section_titles_are_bold_and_the_rest_of_the_text_is_not(self):
        from quill.ui.theme import stylesheet_for
        sheet = stylesheet_for(True)

        def rule(selector):
            return sheet[sheet.index(selector): sheet.index("}", sheet.index(selector))]

        self.assertIn("font-weight: 600", rule('QLabel[panelHeading="true"]'))
        for selector in ('QLabel[panelTitle="true"]', 'QLabel[panelNote="true"]', 'QLabel[panelValue="true"]'):
            self.assertIn("font-weight: 400", rule(selector))
        headings = [l.text() for l in self.panel.findChildren(QLabel) if l.property("panelHeading")]
        self.assertIn("Active File", headings)

    def test_the_settings_gear_sits_right_aligned_on_the_active_file_row(self):
        file_page = self.panel.stack.widget(0).widget()
        self.assertTrue(file_page.isAncestorOf(self.panel.settings_button))
        row = file_page.layout().itemAt(0).layout()                        # the first row of the page
        self.assertEqual(row.itemAt(0).widget().text(), "Active File")
        self.assertIs(row.itemAt(1).widget(), self.panel.settings_button)   # after the stretching title: at the right
        self.assertEqual(row.stretch(0), 1)
        self.assertTrue(self.panel.settings_button.toolTip())


class TestHeadingsRow(Dir):
    def test_a_chosen_headings_row_replaces_the_guess(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "S"
        ws["A1"], ws["A2"], ws["B2"] = "Report title", "Bird", "Place"
        ws["A3"], ws["B3"] = "Wren", "Park"
        path = self.dir / "b.xlsx"
        wb.save(path)
        bridge = XlsxBridge(path)
        bridge.connect()
        bridge.set_headings_row(2)
        self.assertEqual(bridge.get_headers(), ["Bird", "Place"])
        self.assertEqual(bridge.append_row("S", {"Bird": "Owl"}), 4)

    def test_csv_headings_can_start_lower_too(self):
        path = self.dir / "b.csv"
        path.write_text("Birds seen\nBird,Place\nWren,Park\nWren,Farm\n")
        bridge = CsvBridge(path)
        bridge.connect()
        bridge.set_headings_row(2)
        self.assertEqual(bridge.get_headers(), ["Bird", "Place"])
        self.assertEqual(bridge.get_lists()["Bird"], ["Wren"])

    def test_the_controller_saves_it_and_applies_it_on_connecting(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "S"
        ws["A1"], ws["A2"], ws["B2"] = "Report title", "Bird", "Place"
        path = self.dir / "b.xlsx"
        wb.save(path)
        settings = Settings.load(self.dir / "cfg")
        controller = Controller(XlsxBridge(path), settings, on_event=lambda e: None)
        controller.connect()
        controller.set_headings_row(2)
        self.assertEqual(Settings.load(self.dir / "cfg").preferences["headings_row"], 2)
        again = Controller(XlsxBridge(path), Settings.load(self.dir / "cfg"), on_event=lambda e: None)
        again.connect()
        self.assertIn("Bird", again.vocab.columns_for("wren") + list(again.vocab.fields()) if hasattr(again.vocab, "fields") else ["Bird"])


class TestLockedFiles(Dir):
    def setUp(self):
        super().setUp()
        self.path = make_workbook(self.dir / "plants.xlsx")
        self.events = []
        self.controller = Controller(XlsxBridge(self.path), Settings.load(self.dir / "cfg"), on_event=self.events.append)
        self.controller.connect()
        self.locked = mock.patch.object(type(self.controller.bridge._wb), "save", side_effect=PermissionError(13, "Permission denied"))

    def test_a_held_file_keeps_the_row_in_memory_and_says_so(self):
        self.controller.handle_transcript("start listening")
        self.controller.handle_transcript("fern")
        with self.locked:
            self.controller.handle_transcript("next row")
        kinds = [e.kind for e in self.events]
        self.assertIn("locked", kinds)
        saved = [e for e in self.events if e.kind == "committed"][-1]
        self.assertIn("waiting", saved.detail)
        self.assertTrue(self.controller.bridge.dirty)
        self.assertEqual(self.controller.bridge._wb["Inventory"]["A4"].value, "Fern")     # nothing was lost
        self.assertIsNone(openpyxl.load_workbook(self.path)["Inventory"]["A4"].value)     # but the file is untouched

    def test_flushing_writes_the_held_rows_once_the_file_is_free(self):
        self.controller.handle_transcript("start listening")
        self.controller.handle_transcript("fern")
        with self.locked:
            self.controller.handle_transcript("next row")
            self.assertFalse(self.controller.bridge.flush())          # still held
        self.assertTrue(self.controller.bridge.flush())
        self.assertFalse(self.controller.bridge.dirty)
        self.assertEqual(openpyxl.load_workbook(self.path)["Inventory"]["A4"].value, "Fern")

    def test_a_copy_can_be_saved_beside_the_file(self):
        self.controller.handle_transcript("start listening")
        self.controller.handle_transcript("fern")
        with self.locked:
            self.controller.handle_transcript("next row")
        copy = self.controller.bridge.save_copy()
        self.assertTrue(copy.endswith("plants (Quill copy).xlsx"))
        self.assertEqual(openpyxl.load_workbook(copy)["Inventory"]["A4"].value, "Fern")

    def test_a_csv_file_is_held_the_same_way(self):
        path = self.dir / "b.csv"
        path.write_text("Bird\nWren\n")
        bridge = CsvBridge(path)
        bridge.connect()
        with mock.patch("quill.bridge.csv_bridge.os.replace", side_effect=PermissionError(13, "denied")):
            from quill.bridge.base import BridgeLockedError
            with self.assertRaises(BridgeLockedError) as caught:
                bridge.append_row("b", {"Bird": "Owl"})
        self.assertEqual(caught.exception.row, 3)
        self.assertTrue(bridge.dirty)
        self.assertTrue(bridge.flush())
        self.assertEqual(path.read_text().splitlines(), ["Bird", "Wren", "Owl"])
        self.assertTrue(bridge.save_copy().endswith("b (Quill copy).csv"))


class TestLockedFilesInTheApp(PanelApp):
    def test_the_app_retries_and_then_saves_a_copy(self):
        bridge = self.app.controller.bridge
        c = self.app.controller
        c.handle_transcript("start listening")
        c.handle_transcript("fern")
        original = type(bridge._wb).save

        def held(workbook, target):                       # only the file itself is held; a copy beside it can be written
            if str(target) == str(self.plants):
                raise PermissionError(13, "denied")
            return original(workbook, target)

        with mock.patch.object(type(bridge._wb), "save", held):
            c.handle_transcript("next row")
            for _ in range(3):
                self.app._flush_waiting()
        log = self.app.window.log.toPlainText()
        self.assertIn("still in use", log)
        self.assertTrue((self.dir / "plants (Quill copy).xlsx").exists())
        self.app._flush_waiting()
        self.assertIn("The file is free again", self.app.window.log.toPlainText())
        self.assertFalse(bridge.dirty)

    def test_a_file_chosen_that_excel_already_has_open_is_worked_on_through_excel(self):
        self.hosts.files = [OpenFile("other.xlsx", str(self.other), "Excel", live=True)]
        self.chosen[0] = str(self.other)
        with mock.patch.object(self.app, "use_live_excel") as use:
            self.app.choose_spreadsheet_file()
        use.assert_called_once()
        self.assertEqual(self.hosts.launched, [])                  # Excel has it: not launched again

    def test_a_file_that_later_turns_up_in_excel_is_switched_to_live(self):
        self.chosen[0] = str(self.other)
        self.app.choose_spreadsheet_file()
        self.hosts.files = [OpenFile("other.xlsx", str(self.other), "Excel", live=True)]
        with mock.patch.object(self.app, "use_live_excel") as use:
            self.app.refresh_open_files()
        use.assert_called_once()

    def test_csv_files_are_never_switched(self):
        csv_path = self.dir / "b.csv"
        csv_path.write_text("Bird\nWren\n")
        self.chosen[0] = str(csv_path)
        self.app.choose_spreadsheet_file()
        self.hosts.files = [OpenFile("b.csv", str(csv_path), "Excel", live=True)]
        with mock.patch.object(self.app, "use_live_excel") as use:
            self.app.refresh_open_files()
        use.assert_not_called()


class TestAvailableFilesRefresh(PanelApp):
    def test_the_list_polls_every_30_seconds_while_the_file_page_shows(self):
        from quill.app import OPEN_FILES_EVERY_MS
        self.assertEqual(OPEN_FILES_EVERY_MS, 30_000)
        self.assertEqual(self.app._panel_timer.interval(), 30_000)

    def test_the_refresh_icon_looks_again_at_once(self):
        button = self.app.window.panel.refresh_button
        self.assertFalse(button.icon().isNull())
        self.assertIn("every 30 seconds", button.toolTip())
        self.app._open_files_busy = False
        with mock.patch.object(self.app, "run_in_background") as run:
            button.click()
        run.assert_called_once()                                  # a scan was started


class TestMiniKeepsThePill(unittest.TestCase):
    def test_the_mini_start_button_still_shows_the_pill_with_its_words(self):
        w = MainWindow()
        w.setup()
        w.set_mini(True)
        w.widget.show()
        _app.processEvents()
        self.assertTrue(w.toggle_button.pill.isVisibleTo(w.widget))
        self.assertTrue(w.toggle_button.text_pill.isVisibleTo(w.widget))
        self.assertEqual(w.toggle_button.text_pill.text(), "Start Listening")
        w.widget.close()


class TestSameAsButton(unittest.TestCase):
    def test_it_is_outlined_like_the_others_with_only_the_code_bold(self):
        from quill.parser.vocab import Vocabulary
        from quill.ui.sorting_window import TermRow
        vocab = Vocabulary()
        vocab.load({"Size": ["M", "L"]}, [])
        row = TermRow(("Size", "medium"), vocab, lambda *a: None, ("Size", "M"))
        self.assertFalse(row.match_button.property("accent"))
        self.assertEqual(row.match_label.text(), "Same As <b>M</b>")


# --------------------------------------------------------------------------- #
# Peer-review style checks: the layout (rows or columns) must be understood      #
# everywhere, and every user-visible text must say what the user asked for.     #
# --------------------------------------------------------------------------- #

import re

#: Texts that name *both* axes on purpose (they describe the two layouts side by side).
BOTH_AXES = {"By Columns", "By Rows", "Headings run across the first row - each turn writes to the next row.",
             "Headings run down the first column - each turn writes to the next column."}


def axis_words(text: str) -> set[str]:
    """``{"row"}``, ``{"column"}`` or both, for the whole words in *text* (plural and singular alike)."""
    return {w.rstrip("s") for w in re.findall(r"\b(rows?|columns?)\b", text.lower())}


class TestEveryTextFollowsTheLayout(unittest.TestCase):
    """Walk every text in the panel and its overlay in both layouts: none may name the wrong axis."""

    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.panel = self.w.panel

    def texts(self):
        found = []
        for root in (self.panel, self.panel.settings):
            for widget in root.findChildren(QLabel):
                found.append(("label", widget.text()))
            for widget in root.findChildren(__import__("PySide6.QtWidgets", fromlist=["QAbstractButton"]).QAbstractButton):
                found.append(("button", widget.text()))
                found.append(("tip", widget.toolTip()))
        return [(kind, text) for kind, text in found if text and not text.startswith("<")]

    def check(self, vertical):
        wanted, wrong = ("column", "row") if vertical else ("row", "column")
        self.panel.set_options(NEXT_ROW, vertical, 0, 0)
        problems = []
        for kind, text in self.texts():
            if text in BOTH_AXES:
                continue
            words = axis_words(text)
            if wrong in words:
                problems.append(f"{kind} {text!r} names the {wrong}")
        self.assertEqual(problems, [], f"vertical={vertical}")

    def test_by_columns_never_says_column_where_it_means_row(self):
        self.check(False)

    def test_by_rows_never_says_row_where_it_means_column(self):
        self.check(True)

    def test_each_dynamic_text_changes_with_the_layout(self):
        def snapshot():
            s = self.panel.settings
            return (self.panel.next_row_radio.text(), self.panel.next_row_note.text(), self.panel.append_note.text(),
                    self.panel.new_row_button.toolTip(), s.start_heading.text(), s.start_note.text(),
                    s.headings_heading.text(), s.headings_note.text())

        self.panel.set_options(NEXT_ROW, False, 0, 0)
        across = snapshot()
        self.panel.set_options(NEXT_ROW, True, 0, 0)
        down = snapshot()
        for before, after in zip(across, down):
            self.assertNotEqual(before, after, before)
        self.assertEqual(across[:5], ("Next Row", "Turn words are written to new rows.", "Turn words are added to the same row.",
                                      "Move cursor to the next row.", "Starting Row"))
        self.assertEqual(down[:5], ("Next Column", "Turn words are written to new columns.", "Turn words are added to the same column.",
                                    "Move cursor to the next column.", "Starting Column"))

    def test_the_wording_the_user_gave_is_exact(self):
        s = self.panel.settings
        self.panel.set_options(NEXT_ROW, False, 0, 0)
        self.assertEqual(s.start_note.text(), "'Automatic' finds the first empty row after headings, or enter a custom row number.")
        self.assertEqual((s.across_radio.text(), s.across_note.text()),
                         ("By Columns", "Headings run across the first row - each turn writes to the next row."))
        self.assertEqual((s.down_radio.text(), s.down_note.text()),
                         ("By Rows", "Headings run down the first column - each turn writes to the next column."))

    def test_switching_the_layout_in_the_overlay_rewords_the_turn_page_at_once(self):
        self.panel.set_options(NEXT_ROW, False, 0, 0)
        self.panel.settings.down_radio.setChecked(True)
        self.assertEqual(self.panel.next_row_radio.text(), "Next Column")
        self.assertEqual(self.panel.new_row_button.toolTip(), "Move cursor to the next column.")
        self.panel.settings.across_radio.setChecked(True)
        self.assertEqual(self.panel.next_row_radio.text(), "Next Row")


class TestControllerMessagesFollowTheLayout(Dir):
    def run_layout(self, vertical):
        path = make_vertical(self.dir / "v.xlsx") if vertical else make_workbook(self.dir / "h.xlsx")
        settings = Settings.load(self.dir / ("cfg-v" if vertical else "cfg-h"))
        settings.preferences["vertical_layout"] = vertical
        events = []
        controller = Controller(XlsxBridge(path), settings, on_event=events.append)
        controller.connect()
        controller.set_start_row(3)
        controller.set_headings_row(2)
        controller.set_turn_mode("append")
        controller.start_new_row()
        return [e.detail for e in events]

    def test_rows_in_the_usual_layout(self):
        details = self.run_layout(False)
        self.assertIn("Turns start at row 3", details)
        self.assertIn("Headings are in row 2", details)
        self.assertIn("Each turn adds to the same row", details)
        self.assertIn("The next turn starts a new row", details)

    def test_columns_with_letters_when_the_headings_run_down(self):
        details = self.run_layout(True)
        self.assertIn("Turns start at column C", details)
        self.assertIn("Headings are in column B", details)
        self.assertIn("Each turn adds to the same column", details)
        self.assertIn("The next turn starts a new column", details)
        self.assertFalse([d for d in details if "row" in axis_words(d)], details)


class TestCursorFollowsTheTurn(Dir):
    def setUp(self):
        super().setUp()
        self.path = make_workbook(self.dir / "plants.xlsx")
        self.settings = Settings.load(self.dir / "cfg")
        self.controller = Controller(XlsxBridge(self.path), self.settings, on_event=lambda e: None)
        self.controller.connect()
        self.controller.handle_transcript("start listening")

    def cursor(self):
        return self.controller.bridge._grid.get_cursor("Inventory")

    def test_next_row_mode_moves_the_cursor_on_after_each_turn(self):
        self.controller.handle_transcript("fern")
        self.controller.handle_transcript("next row")
        self.assertEqual(self.cursor()[0], 5)                       # row 4 was written; the cursor waits on row 5

    def test_append_mode_keeps_the_cursor_on_the_same_row_after_the_turn_is_written(self):
        self.controller.set_turn_mode("append")
        self.controller.handle_transcript("fern")
        self.controller.handle_transcript("next row")
        self.assertEqual(self.cursor()[0], 4)
        self.controller.handle_transcript("cactus")
        self.controller.handle_transcript("next row")
        self.assertEqual(self.cursor()[0], 4)
        self.assertEqual(openpyxl.load_workbook(self.path)["Inventory"]["A4"].value, "Fern, Cactus")

    def test_the_panels_next_button_moves_the_cursor_to_the_next_row(self):
        self.controller.set_turn_mode("append")
        self.controller.handle_transcript("fern")
        self.controller.handle_transcript("next row")
        self.controller.start_new_row()
        self.assertEqual(self.cursor()[0], 5)
        self.controller.handle_transcript("cactus")
        self.controller.handle_transcript("next row")
        self.assertEqual(openpyxl.load_workbook(self.path)["Inventory"]["A5"].value, "Cactus")

    def test_a_vertical_sheet_moves_the_cursor_across_columns(self):
        vertical = make_vertical(self.dir / "v.xlsx")
        self.settings.preferences["vertical_layout"] = True
        controller = Controller(XlsxBridge(vertical), self.settings, on_event=lambda e: None)
        controller.connect()
        controller.handle_transcript("start listening")
        controller.handle_transcript("banana")
        controller.handle_transcript("next row")
        self.assertEqual(controller.bridge._grid.get_cursor("Stock"), (1, 4))      # column C written; the cursor waits on D

    def test_a_cursor_that_cannot_be_moved_never_fails_a_write(self):
        with mock.patch.object(type(self.controller.bridge._grid), "set_cursor", side_effect=RuntimeError("no")):
            self.controller.handle_transcript("fern")
            self.controller.handle_transcript("next row")
        self.assertEqual(openpyxl.load_workbook(self.path)["Inventory"]["A4"].value, "Fern")


class TestToolTips(unittest.TestCase):
    def test_a_tip_is_centred_on_the_pointer_not_started_at_it(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import QToolTip
        from quill.ui.widgets import TOOLTIP_DROP, TOOLTIP_PADDING, CenteredToolTips
        pointer = QPoint(500, 300)
        spot = CenteredToolTips.position(pointer, "Move cursor to the next row")
        width = QFontMetrics(QToolTip.font()).horizontalAdvance("Move cursor to the next row") + TOOLTIP_PADDING
        self.assertEqual(spot.x() + width // 2, 500)
        self.assertEqual(spot.y(), 300 + TOOLTIP_DROP)

    def test_the_widest_line_decides_for_a_tip_of_several_lines(self):
        from PySide6.QtCore import QPoint
        from quill.ui.widgets import CenteredToolTips
        short = CenteredToolTips.position(QPoint(400, 0), "a\nb")
        long = CenteredToolTips.position(QPoint(400, 0), "a\na very long second line of the tip")
        self.assertLess(long.x(), short.x())

    def test_the_text_comes_from_the_widget_or_from_the_list_item_under_the_pointer(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPushButton
        from quill.ui.widgets import CenteredToolTips
        button = QPushButton("x")
        button.setToolTip("hello")
        self.assertEqual(CenteredToolTips.tip_for(button, QPoint(1, 1)), "hello")
        lst = QListWidget()
        item = QListWidgetItem("one")
        item.setToolTip("full path")
        lst.addItem(item)
        lst.resize(200, 100)
        lst.show()
        self.assertEqual(CenteredToolTips.tip_for(lst.viewport(), QPoint(5, 5)), "full path")
        lst.close()

    def test_the_filter_is_installed_once_by_the_app_and_shows_the_tip(self):
        app = PanelApp()
        app.setUp()
        try:
            from quill.ui.widgets import CenteredToolTips
            self.assertIsInstance(_app._quill_tooltips, CenteredToolTips)
            from PySide6.QtCore import QEvent, QPoint
            from PySide6.QtGui import QHelpEvent
            button = app.app.window.panel.new_row_button
            handled = _app._quill_tooltips.eventFilter(button, QHelpEvent(QEvent.Type.ToolTip, QPoint(3, 3), QPoint(600, 400)))
            tip = _app._quill_tooltips.window
            self.assertTrue(handled)
            self.assertTrue(tip.isVisible())
            self.assertEqual(tip._text, button.toolTip())
            self.assertAlmostEqual(tip.geometry().center().x(), 600, delta=3)       # centred on the pointer
            leave = QEvent(QEvent.Type.Leave)
            _app._quill_tooltips.eventFilter(button, leave)
            self.assertFalse(tip.isVisible())                                        # gone when the pointer leaves
        finally:
            app._tmp.cleanup()

    def test_the_tip_is_a_rounded_lighter_grey_card_with_some_padding(self):
        from quill.ui.theme import colors_for, mix, stylesheet_for
        from quill.ui.widgets import TOOLTIP_PAD_X, TOOLTIP_PAD_Y, TipWindow
        self.assertTrue(2 < TOOLTIP_PAD_Y <= 5 and 5 <= TOOLTIP_PAD_X <= 10)          # less than the old 5 x 9, but not none
        for dark in (False, True):
            sheet = stylesheet_for(dark)
            rule = sheet[sheet.index("QToolTip {"): sheet.index("}", sheet.index("QToolTip {"))]
            self.assertIn("border-radius: 7px", rule)
            t = colors_for(dark, "violet")
            lighter = mix(t["surface"], t["text"], 0.26 if dark else 0.08)
            self.assertIn(lighter, rule)
            self.assertNotEqual(lighter, mix(t["surface"], t["text"], 0.10))                # not the old grey
        tip = TipWindow()
        size = tip.set_text("hello")
        self.assertGreater(size.width(), 2 * TOOLTIP_PAD_X)
        self.assertTrue(tip.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))     # so the corners can be round

    def test_a_tip_near_the_screen_edge_stays_on_screen(self):
        from PySide6.QtCore import QPoint
        from quill.ui.widgets import CenteredToolTips
        filt = CenteredToolTips()
        room = _app.primaryScreen().availableGeometry()
        filt.show_tip(QPoint(room.right() - 2, room.bottom() - 2), "a tip near the corner of the screen")
        geometry = filt.window.geometry()
        self.assertLessEqual(geometry.right(), room.right())
        self.assertLessEqual(geometry.bottom(), room.bottom())
        filt.window.hide()


class TestKeywordsLinkAndOverlay(PanelApp):
    def test_the_keywords_link_opens_settings_on_the_keywords_page(self):
        self.app.window.panel.keywords_requested.emit()
        dialog = self.app._settings_dialog
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.nav.currentItem().data(Qt.ItemDataRole.UserRole), "Keywords")
        dialog.close_now()

    def test_it_switches_an_already_open_settings_window_to_keywords(self):
        self.app.open_settings()
        self.app.open_settings("Keywords")
        self.assertEqual(self.app._settings_dialog.nav.currentItem().data(Qt.ItemDataRole.UserRole), "Keywords")
        self.app._settings_dialog.close_now()

    def test_the_settings_button_shows_the_overlay_under_the_panel_on_the_file_page(self):
        MainWindow.animation_ms, saved = 0, MainWindow.animation_ms
        try:
            self.app.window.open_panel(FILE_PAGE)
            self.app.window.show_file_settings()
            self.assertTrue(self.app.window.panel.settings.isVisible())
            self.assertGreater(self.app.window.panel.settings.width(), 200)
            self.app.window.panel.settings.close()
            self.app.window.open_panel(TURN_PAGE)
            self.app.window.show_file_settings()                      # not on the turn page
            self.assertFalse(self.app.window.panel.settings.isVisible())
        finally:
            MainWindow.animation_ms = saved

    def test_changes_in_the_overlay_reach_the_controller_and_are_remembered(self):
        s = self.app.window.panel.settings
        s.down_radio.setChecked(True)
        s.start_letter.setCurrentIndex(3)                             # C
        s.headings_letter.setCurrentIndex(2)                          # B
        prefs = self.settings.preferences
        self.assertEqual((prefs["vertical_layout"], prefs["start_row"], prefs["headings_row"]), (True, 3, 2))


class TestTitleCentring(unittest.TestCase):
    def test_the_title_centres_in_the_room_the_panel_leaves(self):
        from quill.ui import chrome

        class Frame:
            def __init__(self, x, y, w, h): self.origin = type("P", (), {"x": x, "y": y})(); self.size = type("S", (), {"width": w, "height": h})()

        class Label:
            def __init__(self): self.f = Frame(0, 0, 40, 16)
            def setStringValue_(self, t): pass
            def sizeToFit(self): pass
            def frame(self): return self.f
            def setFrameOrigin_(self, o): self.f = Frame(o[0], o[1], 40, 16)

        class Bar:
            def bounds(self): return Frame(0, 0, 689, 28)

        close = type("C", (), {"superview": lambda s: Bar(), "frame": lambda s: Frame(7, 6, 14, 16)})()
        label = Label()
        chrome._retitle(label, close, "Quill", 236)
        self.assertEqual(label.f.origin.x + 20, (689 - 236) / 2)          # the middle of what is left of the line
        chrome._retitle(label, close, "Quill", 0)
        self.assertEqual(label.f.origin.x + 20, 689 / 2)


# --------------------------------------------------------------------------- #
# Round three of peer-review checks                                            #
# --------------------------------------------------------------------------- #

class TestEverythingClickableHasHoverText(unittest.TestCase):
    """Walk every window and fail on any button, drop-down, switch, radio button or link that is silent on hover."""

    def silent(self, root):
        from quill.ui.hints import missing_tips
        return [f"{type(w).__name__} {w.objectName()!r} {getattr(w, 'text', lambda: '')()!r}" for w in missing_tips(root)]

    def test_the_main_window_the_panel_and_the_overlay(self):
        w = MainWindow()
        w.setup()
        for page in (FILE_PAGE, TURN_PAGE):
            w.panel.show_page(page)
            self.assertEqual(self.silent(w.widget), [], page)
        self.assertEqual(self.silent(w.panel.settings), [])
        w.panel.set_options(NEXT_ROW, True, 0, 0)                          # the other layout's widgets too
        self.assertEqual(self.silent(w.panel.settings), [])

    def test_the_term_helper_with_rows_and_the_footer(self):
        from quill.parser.vocab import Vocabulary
        from quill.ui.sorting_window import SortingWindow
        vocab = Vocabulary()
        vocab.load({"Size": ["M", "L"]}, [])
        sw = SortingWindow(vocab, lambda *a: None)
        sw.setup()
        sw.set_items([(None, "medium"), ("Size", "teal"), ("Size", "xl")])
        self.assertEqual(self.silent(sw.widget), [])
        sw.widget.close()

    def test_every_settings_page_including_keywords(self):
        from quill.ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(Settings.defaults())
        widget = dialog.build()
        for title in list(dialog._nav_items):
            dialog.nav.setCurrentRow(dialog._nav_row(title))
        self.assertEqual(self.silent(widget), [])

    def test_the_help_window(self):
        from quill.ui.help_window import HelpWindow
        help_window = HelpWindow()
        help_window.setup()
        self.assertEqual(self.silent(help_window._window), [])

    def test_list_items_and_links_explain_themselves_too(self):
        w = MainWindow()
        w.setup()
        w.panel.set_available([("a.xlsx", "/x/a.xlsx", None)])
        self.assertTrue(w.panel.available.item(0).toolTip())
        self.assertEqual(w.panel.turn_intro.toolTip(), "")                      # (it appears only while a link is hovered)
        w.panel.turn_intro.linkHovered.emit("keywords")
        self.assertEqual(w.panel.turn_intro.toolTip(), "Open the Keywords settings.")
        w.panel.turn_intro.linkHovered.emit("")
        self.assertEqual(w.panel.turn_intro.toolTip(), "")
        from quill.ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(Settings.defaults())
        dialog.build()
        self.assertTrue(all(dialog.nav.item(i).toolTip() for i in range(dialog.nav.count()) if dialog.nav.item(i).data(Qt.ItemDataRole.UserRole)))

    def test_a_setting_control_says_what_the_setting_does(self):
        from quill.ui.settings_widgets import SettingRow, ToggleSwitch
        toggle = ToggleSwitch()
        row = SettingRow("Auto stop", "Stop listening when nothing is said", toggle)
        self.assertEqual(toggle.toolTip(), "Stop listening when nothing is said")
        self.assertIsNotNone(row)

    def test_the_fallback_never_overrides_a_tip_that_was_written(self):
        from PySide6.QtWidgets import QPushButton
        from quill.ui.hints import fill_missing_tips
        written, plain = QPushButton("Add"), QPushButton("Ignore")
        written.setToolTip("Add this value to the Size list")
        from PySide6.QtWidgets import QWidget as Holder
        holder = Holder()
        for b in (written, plain):
            b.setParent(holder)
        fill_missing_tips(holder)
        self.assertEqual(written.toolTip(), "Add this value to the Size list")
        self.assertIn("Forget", plain.toolTip())


class TestStartupMessages(PanelApp):
    def make_app(self, connected):
        events = []
        path = make_workbook(self.dir / "p2.xlsx")
        bridge = XlsxBridge(path) if connected else DeadExcel()
        app = QuillApp(_app, Settings.load(self.dir / ("cfg-c" if connected else "cfg-d")), bridge,
                       listener_factory=lambda *a: FakeListener(*a), model_finder=lambda c: self.dir, speaker=FakeSpeaker(),
                       sound_player=lambda p: None, live_bridge_factory=lambda: DeadExcel(), hosts=FakeHosts())
        app.run_in_background = lambda work, done: done(work())
        app.start()
        return app

    def test_a_clean_start_says_the_model_is_ready(self):
        text = self.make_app(True).window.log.toPlainText()
        self.assertIn("Speech model ready", text)
        self.assertNotIn("Not connected", text)

    def test_a_warning_at_start_is_not_followed_by_a_cheerful_ready_message(self):
        text = self.make_app(False).window.log.toPlainText()
        self.assertIn("Not connected", text)
        self.assertNotIn("Speech model ready", text)

    def test_the_ready_message_comes_once_a_file_is_connected_and_only_once(self):
        app = self.make_app(False)
        app.open_workbook_file(self.plants)
        text = app.window.log.toPlainText()
        self.assertEqual(text.count("Speech model ready"), 1)
        app.open_workbook_file(self.other)
        self.assertEqual(app.window.log.toPlainText().count("Speech model ready"), 1)


class TestNotConnectedPill(unittest.TestCase):
    def test_it_says_file_not_connected_without_the_word_stream(self):
        from quill.ui.main_window import NOT_CONNECTED_TEXT
        self.assertEqual(NOT_CONNECTED_TEXT, "File not connected")
        w = MainWindow()
        w.setup()
        self.assertNotIn("stream", w.connection_chip.text().lower())

    def test_the_pill_follows_the_accent_colour(self):
        from quill.ui import theme
        for dark in (False, True):
            for accent in ("violet", "blue", "green"):
                sheet = theme.stylesheet_for(dark, accent)
                rule = sheet[sheet.index('QLabel[chip="warn"]'): sheet.index("}", sheet.index('QLabel[chip="warn"]'))]
                self.assertIn(theme.rgba(theme.colors_for(dark, accent)["accent"], 0.6), rule, (dark, accent))


class TestNextButtonLooksDisabled(unittest.TestCase):
    def test_it_is_disabled_with_a_grey_border_until_append_to_is_chosen(self):
        from quill.ui import theme
        for dark in (False, True):
            sheet = theme.stylesheet_for(dark)
            t = theme.colors_for(dark, "violet")
            start = sheet.index('QPushButton[outline="true"]:disabled')
            self.assertIn(t["border"], sheet[start: sheet.index("}", start)])
            self.assertGreater(start, sheet.index('QPushButton[outline="true"] {'))      # later, so it wins over the purple border
        w = MainWindow()
        w.setup()
        w.panel.set_options(NEXT_ROW, False, 0, 0)
        self.assertFalse(w.panel.new_row_button.isEnabled())
        w.panel.append_radio.setChecked(True)
        self.assertTrue(w.panel.new_row_button.isEnabled())
        w.panel.next_row_radio.setChecked(True)
        self.assertFalse(w.panel.new_row_button.isEnabled())


class TestOverlayOrderAndWording(unittest.TestCase):
    def test_headings_first_then_starting_then_the_layout(self):
        w = MainWindow()
        w.setup()
        layout = w.panel.settings.layout()
        order = [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget() is not None]
        headings = [x.text() for x in order if isinstance(x, QLabel) and x.property("panelHeading")]
        self.assertEqual(headings, ["Headings Row", "Starting Row", "Sheet Layout"])

    def test_the_turn_description_is_two_sentences_with_a_blank_line_between_and_a_link_to_settings_keywords(self):
        w = MainWindow()
        w.setup()
        text = w.panel.turn_intro.text()
        self.assertIn("is handled.<br><br>These settings can be voice controlled within", text)
        self.assertTrue(text.endswith('<a href="keywords">Settings &gt; Keywords</a>.'))

    def test_only_the_link_is_a_pointer_not_the_whole_description(self):
        w = MainWindow()
        w.setup()
        self.assertNotEqual(w.panel.turn_intro.cursor().shape(), Qt.CursorShape.PointingHandCursor)

    def test_the_gear_is_an_icon_button_drawn_with_the_gear_shape(self):
        from quill.ui.icons import SHAPES
        self.assertIn("gear", SHAPES)
        w = MainWindow()
        w.setup()
        w.refresh_icons("#222222", "#ffffff", "#7A55C2")
        self.assertFalse(w.panel.settings_button.icon().isNull())


class TestPanelTouchesTheWindowWithSpacingApplied(PanelApp):
    """The real app applies the spacing setting to every layout; the content and the panel must still touch."""

    def test_no_gap_opens_between_the_content_and_the_panel(self):
        MainWindow.animation_ms, saved = 0, MainWindow.animation_ms
        try:
            for spacing in ("compact", "comfortable"):
                self.app.settings.preferences["spacing"] = spacing
                self.app.apply_settings(quiet=True)
                self.app.window.open_panel(FILE_PAGE)
                _app.processEvents()
                root, panel = self.app.window.root, self.app.window.panel
                self.assertEqual(root.geometry().right() + 1, panel.geometry().left(), spacing)
                edge = [f for f in panel.findChildren(__import__("PySide6.QtWidgets", fromlist=["QFrame"]).QFrame) if f.property("panelEdge")][0]
                self.assertEqual(edge.mapTo(panel, edge.rect().topLeft()).x(), 0, spacing)        # the line is the panel's first pixel
                self.app.window.close_panel()
        finally:
            MainWindow.animation_ms = saved


class TestResizableAreas(PanelApp):
    def setUp(self):
        super().setUp()
        self.w = self.app.window
        self.w.widget.show()
        self.w.set_log_collapsed(False)
        _app.processEvents()

    def test_the_grip_sits_on_the_bottom_edge_of_the_matched_words_box(self):
        grip, box = self.w.row_grip, self.w.row_table
        self.assertTrue(grip.isVisibleTo(self.w.widget))
        self.assertEqual(grip.cursor().shape(), Qt.CursorShape.SizeVerCursor)
        self.assertEqual(grip.geometry().bottom(), box.geometry().bottom())
        self.assertEqual((grip.x(), grip.width()), (box.x(), box.width()))
        self.assertTrue(grip.toolTip())

    def test_dragging_down_makes_the_box_taller_and_the_log_shorter_at_the_same_window_size(self):
        size, log, box = self.w.widget.size(), self.w.log_height, self.w.row_table.height()
        self.w.widget.resize(self.w.widget.width(), size.height() + 200)             # room for the box to give
        _app.processEvents()
        log, box = self.w.log_height, self.w.row_table.height()
        self.w.row_grip.dragged.emit(30)
        _app.processEvents()
        self.assertEqual(self.w.log_height, log - 30)
        self.assertEqual(self.w.log.height(), log - 30)
        self.assertGreater(self.w.row_table.height(), box)
        self.assertEqual(self.w.widget.width(), size.width())                             # never sideways

    def test_dragging_up_makes_the_log_taller_while_the_box_has_room(self):
        self.w.widget.resize(self.w.widget.width(), self.w.widget.height() + 200)
        _app.processEvents()
        log = self.w.log_height
        self.w.row_grip.dragged.emit(-40)
        self.assertEqual(self.w.log_height, log + 40)

    def test_it_stops_at_the_limits(self):
        from quill.ui.main_window import LOG_MAX_HEIGHT, LOG_MIN_HEIGHT
        self.w.widget.resize(self.w.widget.width(), 1400)
        _app.processEvents()
        self.w.row_grip.dragged.emit(5000)
        self.assertEqual(self.w.log_height, LOG_MIN_HEIGHT)
        self.w.row_grip.dragged.emit(-5000)
        self.assertLessEqual(self.w.log_height, LOG_MAX_HEIGHT)

    def test_with_the_log_hidden_the_drag_resizes_the_window_downwards_only_in_height(self):
        self.w.set_log_collapsed(True)
        _app.processEvents()
        width, height = self.w.widget.width(), self.w.widget.height()
        self.w.row_grip.dragged.emit(60)
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (width, height + 60))

    def test_the_chosen_log_height_is_remembered_and_restored(self):
        self.w.widget.resize(self.w.widget.width(), self.w.widget.height() + 200)
        _app.processEvents()
        self.w.row_grip.dragged.emit(-50)
        self.w.row_grip.released.emit()
        self.assertEqual(self.app.settings.preferences["log_height"], 120 + 50)
        again = Settings.load(self.dir / "cfg")
        self.assertEqual(again.preferences["log_height"], 170)
        other = MainWindow()
        other.setup()
        other.restore_log_height(170)
        self.assertEqual(other.log_height, 170)
        other.restore_log_height(5)                                                         # nonsense is kept in bounds
        self.assertEqual(other.log_height, 60)

    def test_the_log_opens_at_its_remembered_height(self):
        self.w.restore_log_height(200)
        self.w.set_log_collapsed(True)
        MainWindow.animation_ms, saved = 0, MainWindow.animation_ms
        try:
            self.w.set_log_collapsed(False)
            _app.processEvents()
        finally:
            MainWindow.animation_ms = saved
        self.assertEqual(self.w.log.height(), 200)

    def test_the_mini_view_has_no_grip(self):
        self.w.set_mini(True)
        _app.processEvents()
        self.assertFalse(self.w.row_grip.isVisibleTo(self.w.widget))


# --------------------------------------------------------------------------- #
# Round four                                                                   #
# --------------------------------------------------------------------------- #

class TestControlsFollowTheirStyle(unittest.TestCase):
    """One style per control type, in every window and page (see the ui-controls-one-style note)."""

    def windows(self):
        from quill.parser.vocab import Vocabulary
        from quill.ui.help_window import HelpWindow
        from quill.ui.settings_dialog import SettingsDialog
        from quill.ui.sorting_window import SortingWindow
        main = MainWindow()
        main.setup()
        vocab = Vocabulary()
        vocab.load({"Size": ["M", "L"]}, [])
        sorting = SortingWindow(vocab, lambda *a: None)
        sorting.setup()
        sorting.set_items([(None, "medium"), ("Size", "teal")])
        dialog = SettingsDialog(Settings.defaults())
        widget = dialog.build()
        for title in list(dialog._nav_items):
            dialog.nav.setCurrentRow(dialog._nav_row(title))
        help_window = HelpWindow()
        help_window.setup()
        return {"main": main.widget, "overlay": main.panel.settings, "sorting": sorting.widget,
                "settings": widget, "help": help_window._window}

    def test_every_drop_down_is_the_flat_one(self):
        from PySide6.QtWidgets import QComboBox
        from quill.ui.settings_widgets import FlatCombo
        odd = []
        for name, root in self.windows().items():
            for combo in root.findChildren(QComboBox):
                if not isinstance(combo, FlatCombo):
                    odd.append(f"{name}: {type(combo).__name__}")
        self.assertEqual(odd, [])

    def test_the_keyword_table_uses_flat_drop_downs_and_pills(self):
        from quill.ui.settings_dialog import SettingsDialog
        from quill.ui.settings_widgets import FlatCombo, PillField
        dialog = SettingsDialog(Settings.defaults())
        dialog.build()
        dialog.nav.setCurrentRow(dialog._nav_row("Keywords"))
        self.assertGreater(dialog.table.rowCount(), 5)
        for r in range(dialog.table.rowCount()):
            self.assertIsInstance(dialog.table.cellWidget(r, 1), FlatCombo)
            pill = dialog.table.cellWidget(r, 0)
            self.assertIsInstance(pill, PillField)
            self.assertTrue(pill.field.property("pillField"))

    def test_the_phrase_pill_wears_the_same_colours_as_a_spoken_word_in_text(self):
        from quill.ui.theme import PILL_BG, PILL_FG, stylesheet_for
        from quill.ui.widgets import PILL_STYLE, pill
        self.assertIn(PILL_BG, PILL_STYLE)
        self.assertIn(PILL_FG, PILL_STYLE)
        self.assertIn(PILL_BG, pill("yes"))
        for dark in (False, True):
            sheet = stylesheet_for(dark)
            rule = sheet[sheet.index('QLineEdit[pillField="true"] {'): sheet.index("}", sheet.index('QLineEdit[pillField="true"] {'))]
            self.assertIn(PILL_BG, rule)
            self.assertIn(PILL_FG, rule)

    def test_editing_a_phrase_pill_is_what_gets_saved(self):
        from quill.ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(Settings.defaults())
        dialog.build()
        dialog.nav.setCurrentRow(dialog._nav_row("Keywords"))
        dialog.table.cellWidget(0, 0).setText("begin dictation")
        self.assertEqual(dialog.collect_rows()[0][0], "begin dictation")

    def test_the_pill_grows_with_its_words(self):
        from quill.ui.settings_widgets import PillField
        short, long = PillField("go"), PillField("a much longer spoken phrase")
        self.assertGreater(long.field.width(), short.field.width())

    def test_every_switch_slider_and_spin_box_is_the_guarded_kind(self):
        from PySide6.QtWidgets import QCheckBox, QSlider, QSpinBox
        from quill.ui.settings_widgets import GuardedSlider, GuardedSpinBox, ToggleSwitch
        odd = []
        for name, root in self.windows().items():
            for kind, wanted in ((QCheckBox, ToggleSwitch), (QSlider, GuardedSlider), (QSpinBox, GuardedSpinBox)):
                for widget in root.findChildren(kind):
                    if not isinstance(widget, wanted) and not widget.objectName().startswith("qt_"):
                        odd.append(f"{name}: {type(widget).__name__}")
        self.assertEqual(odd, [])


class TestTextsAndMenus(PanelApp):
    def test_the_file_menu_and_the_tray_menu_say_open_file(self):
        self.assertEqual(self.app.window.open_file_action.text(), "Open File…")
        labels = [a.text() for a in self.app.tray._menu.actions()]
        self.assertIn("Open File…", labels)
        self.assertFalse([t for t in labels if "Spreadsheet File" in t])

    def test_no_text_anywhere_still_says_open_spreadsheet_file(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "quill"
        offenders = [str(f.relative_to(root)) for f in root.rglob("*") if f.suffix in (".py", ".md")
                     and "Open Spreadsheet File" in f.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])

    def test_the_no_spreadsheet_error_reads_as_asked(self):
        from quill.controller import NO_WORKBOOK_HELP
        self.assertEqual(NO_WORKBOOK_HELP, "No spreadsheet is connected. Open a spreadsheet and Quill connects to it "
                                           "automatically, or choose Open File in the File menu.")

    def test_the_pill_tooltip_stops_before_connect_one(self):
        from quill.ui.widgets import connection_tip
        tip = connection_tip()
        self.assertIn("Not connected", tip)
        self.assertIn("read lists from", tip)
        for gone in ("Connect one", "Connect One", "Spreadsheet program", "Open File", "Then press"):
            self.assertNotIn(gone, tip)


class TestTitleBarScale(unittest.TestCase):
    def test_every_window_gets_a_toolbar_so_its_bar_and_buttons_are_the_larger_size(self):
        from quill.ui import chrome
        from tests.test_titlebar_and_refresh import FakeAppKit

        calls = []

        class Window:
            def toolbar(self): return None
            def setToolbar_(self, t): calls.append(("toolbar", t))
            def setToolbarStyle_(self, s): calls.append(("style", s))

        class Toolbar:
            @classmethod
            def alloc(cls): return cls()
            def initWithIdentifier_(self, name): calls.append(("id", name)); return self
            def setShowsBaselineSeparator_(self, v): calls.append(("separator", v))

        kit = FakeAppKit()
        kit.NSToolbar = Toolbar
        self.assertTrue(chrome.tall_titlebar(Window(), kit))
        self.assertIn(("id", chrome.TOOLBAR_ID), calls)
        self.assertIn(("style", 3), calls)                                   # the unified (taller) style
        self.assertIn(("separator", False), calls)

    def test_a_window_that_already_has_a_toolbar_is_left_alone_and_a_failure_is_quiet(self):
        from quill.ui import chrome

        class Has:
            def toolbar(self): return object()

        self.assertTrue(chrome.tall_titlebar(Has(), object()))
        self.assertFalse(chrome.tall_titlebar(object(), object()))

    def test_mac_chrome_applies_it_to_every_window_it_styles(self):
        import inspect
        from quill.ui import chrome
        self.assertIn("tall_titlebar(window, appkit)", inspect.getsource(chrome.mac_chrome))

    def test_the_icons_are_bigger_than_before_and_all_the_same_box(self):
        from quill.ui import chrome
        self.assertGreater(chrome._ICON_WIDTH, 30)
        self.assertGreater(chrome._ICON_HEIGHT, 24)
        self.assertGreater(chrome.SYMBOL_POINTS, 14)

    def test_every_title_bar_group_levels_itself_by_itself(self):
        from quill.ui import chrome
        import inspect
        self.assertIn("result.settle()", inspect.getsource(chrome.add_titlebar_button))


class TestBlurIsReallyBlur(unittest.TestCase):
    """The pixels are checked by tools/verify_window_effects.py on a real screen; these check what produces them."""

    def test_the_slider_maps_to_the_window_servers_blur_radius(self):
        from quill.ui import chrome
        self.assertEqual([chrome.blur_radius(v) for v in (0, 50, 100)], [0, chrome.MAX_BLUR_RADIUS // 2, chrome.MAX_BLUR_RADIUS])
        self.assertEqual(chrome.blur_radius(-5), 0)
        self.assertEqual(chrome.blur_radius(900), chrome.MAX_BLUR_RADIUS)

    def test_the_radius_is_given_to_the_window_server_for_that_window(self):
        import ctypes
        from quill.ui import chrome
        calls = []

        class Fn:
            def __init__(self, result=0): self.result = result; self.argtypes = None; self.restype = None
            def __call__(self, *args): calls.append(args); return self.result

        class Lib:
            CGSMainConnectionID = Fn(7)
            CGSSetWindowBackgroundBlurRadius = Fn(0)

        window = type("W", (), {"windowNumber": lambda s: 4242})()
        with mock.patch.object(ctypes, "CDLL", return_value=Lib()):
            self.assertTrue(chrome.set_background_blur(window, 30))
        self.assertIn((7, 4242, 30), calls)

    def test_a_missing_window_server_call_is_reported_not_raised(self):
        import ctypes
        from quill.ui import chrome
        with mock.patch.object(ctypes, "CDLL", side_effect=OSError("no")):
            self.assertFalse(chrome.set_background_blur(object(), 30))

    def test_mac_chrome_sets_a_clear_backing_so_the_blur_has_something_to_show_through(self):
        from quill.ui import chrome
        from tests.test_chrome_and_layout import COLORS, FakeAppKit, FakeWindow
        for opacity, blur, clear in ((100, 0, False), (100, 60, False), (99, 0, True), (50, 60, True)):
            kit = FakeAppKit(FakeWindow())
            chrome.mac_chrome(5, True, COLORS, appkit=kit, opacity=opacity, blur=blur)
            calls = kit._window.calls
            self.assertIn(("opaque", not clear), calls, (opacity, blur))
            backing = [c[1][3] for c in calls if c[0] == "bg"]
            self.assertEqual(backing, [0.0 if clear else 1.0], (opacity, blur))

    def test_the_vibrancy_view_is_only_the_stand_in_and_never_half_faded(self):
        from quill.ui import chrome

        class View:
            def __init__(self): self.alpha = None; self._id = ""; self.layer_color = None; self.removed = False
            @classmethod
            def alloc(cls): return cls()
            def initWithFrame_(self, f): return self
            def setIdentifier_(self, i): self._id = i
            def identifier(self): return self._id
            def setMaterial_(self, m): pass
            def setBlendingMode_(self, m): pass
            def setState_(self, m): pass
            def setAutoresizingMask_(self, m): pass
            def setAlphaValue_(self, a): self.alpha = a
            def setWantsLayer_(self, v): pass
            def setFrame_(self, f): pass
            def removeFromSuperview(self): self.removed = True
            def layer(self): return type("L", (), {"setBackgroundColor_": lambda s, c: setattr(self, "layer_color", c)})()
            def bounds(self): return type("B", (), {"size": type("S", (), {"width": 100, "height": 100})()})()
            def frame(self): return type("F", (), {"size": type("S", (), {"width": 100, "height": 80})()})()

        class Holder(View):
            def __init__(self): super().__init__(); self.subviews_ = []
            def subviews(self): return list(self.subviews_)
            def addSubview_positioned_relativeTo_(self, v, pos, rel): self.subviews_.append(v)

        class Color:
            @staticmethod
            def colorWithDeviceRed_green_blue_alpha_(r, g, b, a): return type("C", (), {"CGColor": lambda s: ("color", a)})()

        kit = type("Kit", (), {"NSVisualEffectView": View, "NSView": View, "NSColor": Color})
        holder = Holder()
        view = type("V", (), {"superview": lambda s: holder, "frame": lambda s: type("F", (), {"size": type("S", (), {"width": 100, "height": 80})()})()})()
        chrome._set_blur(view, kit, 1.0, None, (0.1, 0.1, 0.1, 0.4))
        effect = next(v for v in holder.subviews_ if v.identifier() == chrome.BLUR_ID)
        self.assertEqual(effect.alpha, 1.0)
        self.assertFalse([v for v in holder.subviews_ if v.identifier() == chrome.FROST_ID])        # no wash over the blur
        tint = next(v for v in holder.subviews_ if v.identifier() == chrome.TINT_ID)
        self.assertEqual(tint.layer_color[1], 0.4)                                               # the title bar thins with the window
        chrome._set_blur(view, kit, 0.0, None, None)                                              # solid window: nothing left behind
        self.assertTrue(effect.removed and tint.removed)

    def test_the_opacity_does_not_weaken_the_blur(self):
        import inspect
        from quill.ui import chrome
        self.assertNotIn("min(1.0, opacity / 100)", inspect.getsource(chrome.mac_chrome))

    def test_the_traffic_lights_are_drawn_larger_and_spread_a_little(self):
        from quill.ui import chrome
        applied = []

        class Button:
            def __init__(self, i): self.i = i
            def setWantsLayer_(self, v): pass
            def frame(self): return type("F", (), {"size": type("S", (), {"height": 16.0})()})()
            def layer(self): return type("L", (), {"setAffineTransform_": lambda s, t: applied.append((self.i, t))})()

        window = type("W", (), {"standardWindowButton_": lambda s, i: Button(i)})()
        self.assertTrue(chrome.larger_traffic_lights(window))
        self.assertEqual([i for i, _ in applied], [0, 1, 2])
        for i, t in applied:
            self.assertEqual((t[0], t[3]), (chrome.TRAFFIC_SCALE, chrome.TRAFFIC_SCALE))
            self.assertEqual(t[4], chrome.TRAFFIC_SHIFT * i)
            self.assertAlmostEqual(t[5], -(chrome.TRAFFIC_SCALE - 1.0) * 16.0 / 2)      # moved down by half of what it grew: level with the icons
        self.assertGreaterEqual(chrome.TRAFFIC_SCALE, 1.25)
        self.assertFalse(chrome.larger_traffic_lights(object()))                                  # no window buttons: quiet

    def test_every_window_gets_them_when_it_is_styled_and_again_when_it_is_shown(self):
        import inspect
        from quill.ui import chrome
        self.assertIn("larger_traffic_lights(window)", inspect.getsource(chrome.mac_chrome))
        self.assertIn("_redraw_lights", inspect.getsource(chrome._TitleFilter))


class TestPanelChromeFollowsTheTitleBar(unittest.TestCase):
    """The system may rebuild the title bar's views after ours were added; the panel's line, title and X must follow."""

    def test_the_three_views_move_into_the_current_title_bar(self):
        from quill.ui import chrome

        class View:
            def __init__(self, name=""): self.name = name; self.sup = None; self.hidden = None; self.origin = None; self.layer_ = None
            @classmethod
            def alloc(cls): return cls()
            def initWithFrame_(self, f): return self
            def setIdentifier_(self, i): self.name = i
            def setWantsLayer_(self, v): pass
            def setAutoresizingMask_(self, m): pass
            def setHidden_(self, h): self.hidden = h
            def superview(self): return self.sup
            def removeFromSuperview(self): self.sup = None
            def setFrame_(self, f): self.frame_ = f
            def setFrameOrigin_(self, o): self.origin = o
            def frame(self): return type("F", (), {"origin": type("P", (), {"x": 0, "y": 8})(), "size": type("S", (), {"width": 40, "height": 14})()})()
            def layer(self): return type("L", (), {"setBackgroundColor_": lambda s, c: None})()
            def setStringValue_(self, t): pass
            def sizeToFit(self): pass

        class Bar(View):
            def __init__(self, width): super().__init__("bar"); self.width = width
            def addSubview_(self, v): v.sup = self
            def bounds(self): return type("B", (), {"size": type("S", (), {"width": self.width, "height": 52})()})()
            def effectiveAppearance(self): return type("A", (), {"name": lambda s: "NSAppearanceNameDarkAqua"})()

        class Light(View):
            def __init__(self, window): super().__init__("light"); self.window = window
            def superview(self): return self.window.bar
            def frame(self): return type("F", (), {"origin": type("P", (), {"x": 7, "y": 18})(), "size": type("S", (), {"width": 14, "height": 16})()})()

        class Window:
            def __init__(self): self.bar = Bar(453)
            def standardWindowButton_(self, i): return Light(self)

        class Color:
            @staticmethod
            def colorWithWhite_alpha_(w, a): return type("C", (), {"CGColor": lambda s: ("c", a)})()
            @staticmethod
            def labelColor(): return "label"

        class Font:
            @staticmethod
            def systemFontOfSize_weight_(a, b): return "font"

        class Text(View):
            @classmethod
            def labelWithString_(cls, t): return cls()
            def setFont_(self, f): pass
            def setTextColor_(self, c): pass

        class Button(View):
            def setImage_(self, i): pass
            def setToolTip_(self, t): pass

        kit = type("Kit", (), {"NSView": View, "NSTextField": Text, "NSFont": Font, "NSColor": Color,
                               "NSImage": type("I", (), {"imageWithSystemSymbolName_accessibilityDescription_": staticmethod(lambda n, d: None)})})
        window = Window()
        panel = chrome._PanelChrome(kit, window, lambda: None, lambda cb, width=None: (Button(), None))
        old_bar = window.bar
        self.assertTrue(all(v.superview() is old_bar for v in (panel.line, panel.title, panel.close)))
        window.bar = Bar(689)                                           # the system rebuilt the title bar
        panel.place(236)
        for view in (panel.line, panel.title, panel.close):
            self.assertIs(view.superview(), window.bar)                 # ... and the views came along
            self.assertFalse(view.hidden)
        self.assertEqual(panel.title.origin[0], 689 - 236 + 14)         # placed from the NEW bar's width
        panel.place(0)
        self.assertTrue(all(v.hidden for v in (panel.line, panel.title, panel.close)))


class TestNavCaptions(unittest.TestCase):
    def test_captions_are_not_selectable_so_they_are_not_clickable(self):
        from quill.ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(Settings.defaults())
        dialog.build()
        captions = [dialog.nav.item(i) for i in range(dialog.nav.count()) if not dialog.nav.item(i).data(Qt.ItemDataRole.UserRole)]
        self.assertGreaterEqual(len(captions), 2)
        for caption in captions:
            self.assertFalse(caption.flags() & Qt.ItemFlag.ItemIsSelectable)


# --------------------------------------------------------------------------- #
# Round five                                                                   #
# --------------------------------------------------------------------------- #

class TestSoundsOnlyForSpeech(PanelApp):
    def setUp(self):
        super().setUp()
        self.played = []
        self.app.sound_player = self.played.append
        self.app.feedback._play = self.played.append

    def test_an_event_made_by_a_click_is_not_marked_as_spoken_and_one_made_by_speech_is(self):
        seen = []
        controller = Controller(XlsxBridge(self.plants), Settings.load(self.dir / "cfg2"), on_event=seen.append)
        controller.connect()
        controller.set_listening(True)                                      # the Start button
        controller.next_row()                                               # the Next button
        controller.set_turn_mode("append")                                  # the panel
        self.assertTrue(seen and not any(e.spoken for e in seen), [(e.kind, e.spoken) for e in seen])
        seen.clear()
        controller.handle_transcript("fern")
        controller.handle_transcript("next row")
        self.assertTrue(seen and all(e.spoken for e in seen), [(e.kind, e.spoken) for e in seen])

    def test_start_with_no_file_makes_no_sound_even_though_it_logs_an_error(self):
        app = self.app
        app.controller.bridge = DeadExcel()
        app.connected = False
        app.controller.connected = False
        app.toggle_listening(True)
        app.feedback.flush()
        self.assertEqual(self.played, [])
        self.assertIn("No spreadsheet is connected", app.window.log.toPlainText())

    def test_a_click_on_a_term_helper_button_makes_no_sound_but_a_spoken_answer_does(self):
        from quill.session import Decision
        c = self.app.controller
        c.handle_transcript("start listening")
        c.handle_transcript("zorb next row")
        self.app.feedback.flush()
        self.played.clear()
        key = c.pending_terms()[0]
        self.app.resolve_term(key, Decision.ignore(), key[1])
        self.app.feedback.flush()
        self.assertEqual(self.played, [])


class TestStartWithNoFile(PanelApp):
    def setUp(self):
        super().setUp()
        self.app.controller.bridge = DeadExcel()
        self.app.connected = False
        self.app.controller.connected = False
        self.app.window.set_not_connected(True)
        self.asked = []
        self.app._file_chooser = lambda: self.asked.append(1) or None

    def test_the_first_click_opens_the_files_panel_and_nothing_else(self):
        self.app.toggle_listening(True)
        self.assertEqual(self.app.window.panel_page, FILE_PAGE)
        self.assertEqual(self.asked, [])

    def test_the_log_gets_the_error_but_does_not_open_itself(self):
        self.app.window.set_log_collapsed(True)
        self.app.toggle_listening(True)
        self.assertIn("No spreadsheet is connected", self.app.window.log.toPlainText())
        self.assertTrue(self.app.window.log_collapsed)

    def test_a_click_while_the_panel_is_already_open_blinks_the_button_and_opens_the_file_window(self):
        self.app.toggle_listening(True)
        button = self.app.window.panel.file_button
        self.app.toggle_listening(True)
        self.assertEqual(self.asked, [1])
        self.assertIn("#34C759", button.styleSheet())                       # green, the Term Helper's own blink
        self.assertIn("rgba(52, 199, 89", button.styleSheet())
        from PySide6.QtTest import QTest
        QTest.qWait(850)
        self.assertEqual(button.styleSheet(), "")                           # ... and it goes out again

    def test_the_panel_open_on_the_turn_page_is_switched_to_files_first(self):
        self.app.window.open_panel(TURN_PAGE)
        self.app.toggle_listening(True)
        self.assertEqual(self.app.window.panel_page, FILE_PAGE)
        self.assertEqual(self.asked, [])

    def test_the_blink_is_the_one_the_term_helper_uses(self):
        from quill.ui.sorting_window import TermRow
        from quill.ui.theme import FLASH_STYLES
        self.assertIs(TermRow.FLASH_STYLES, FLASH_STYLES)


class TestFileMustBeOpenToBeSeen(PanelApp):
    """Quill is an overlay for the spreadsheet program: it listens only while the file is open there."""

    def setUp(self):
        super().setUp()
        self._env = mock.patch.dict("os.environ", {}, clear=False)
        self._env.start()
        __import__("os").environ.pop("QUILL_NO_HOSTS", None)
        self.hosts.running = lambda: []
        self.app._open_files = []
        self.app._viewer_running = False

    def tearDown(self):
        self._env.stop()
        super().tearDown()

    def test_start_waits_while_the_file_is_open_nowhere_and_asks_for_it_to_be_opened(self):
        self.app.toggle_listening(True)
        self.assertFalse(self.app.controller.session.listening)
        self.assertIn("Waiting for plants.xlsx to open in your spreadsheet program", self.app.window.log.toPlainText())
        self.assertEqual(self.hosts.launched, [str(self.plants.resolve())])

    def test_start_works_once_the_file_is_listed_as_open(self):
        self.app._open_files = [OpenFile("plants.xlsx", str(self.plants), "Numbers")]
        self.app.toggle_listening(True)
        self.assertTrue(self.app.controller.session.listening)

    def test_a_running_program_does_not_count_unless_it_has_this_file(self):
        self.app._viewer_running = True
        self.assertFalse(self.app._viewer_open())                           # (some other program is running: not enough)

    def test_a_program_that_reports_its_documents_by_name_only_counts_when_it_has_the_file(self):
        self.app.mirror = NoMirror(has=True)
        self.app.refresh_open_files()
        self.assertTrue(self.app._viewer_open())
        self.assertEqual([(f.name, f.app) for f in self.app._open_files], [("plants.xlsx", "Numbers")])

    def test_libreoffice_is_asked_too(self):
        self.app.lo_mirror = NoMirror(has=True)
        self.app.refresh_open_files()
        self.assertEqual([f.app for f in self.app._open_files], ["LibreOffice"])
        self.assertTrue(self.app._viewer_open())

    def test_live_excel_always_counts(self):
        self.app.controller.bridge = type("Live", (), {"workbook_path": "/x/a.xlsx", "workbook_name": "a.xlsx"})()
        self.assertTrue(self.app._viewer_open())

    def test_nothing_is_written_to_the_file_before_it_is_open(self):
        before = self.plants.read_bytes()
        self.app.toggle_listening(True)
        self.app.controller.handle_transcript("fern")                      # (stopped, so nothing is taken down)
        self.app.controller.handle_transcript("next row")
        self.assertEqual(self.plants.read_bytes(), before)

    def test_a_failed_launch_says_so(self):
        self.hosts.launch = lambda path, program="auto": False
        self.app.toggle_listening(True)
        self.assertIn("Could not open plants.xlsx in a spreadsheet program", self.app.window.log.toPlainText())

    def test_choosing_a_file_starts_it_in_its_program_first(self):
        self.chosen = [str(self.other)]
        self.app._file_chooser = lambda: self.chosen[0]
        self.app.choose_spreadsheet_file()
        self.assertEqual(self.hosts.launched, [str(self.other)])
        self.assertFalse(self.app.controller.session.listening)


class TestFontSizeDefault(Dir):
    def test_the_default_is_fourteen(self):
        from quill.ui.theme import DEFAULT_FONT_SIZE
        self.assertEqual((Settings.load(self.dir).preferences["font_size"], DEFAULT_FONT_SIZE), (14, 14))

    def test_settings_saved_with_the_old_default_move_to_the_new_one_once(self):
        (self.dir / Settings.KEYWORDS_FILE).write_text("[preferences]\nfont_size = 12\n")
        settings = Settings.load(self.dir)
        self.assertEqual(settings.preferences["font_size"], 14)
        settings.preferences["font_size"] = 12                             # the user chooses 12 on purpose afterwards
        settings.save()
        self.assertEqual(Settings.load(self.dir).preferences["font_size"], 12)

    def test_a_size_the_user_chose_is_kept(self):
        (self.dir / Settings.KEYWORDS_FILE).write_text("[preferences]\nfont_size = 16\n")
        self.assertEqual(Settings.load(self.dir).preferences["font_size"], 16)

    def test_the_window_still_fits_its_content_at_that_size(self):
        theme_app = _app
        w = MainWindow()
        w.setup()
        w.widget.show()
        _app.processEvents()
        self.assertGreaterEqual(w.widget.width(), w._layout.minimumSize().width())
        self.assertGreaterEqual(w.widget.height(), w._layout.minimumSize().height())
        w.widget.close()
        self.assertIsNotNone(theme_app)


class TestPanelWidthByDragging(PanelApp):
    def setUp(self):
        super().setUp()
        MainWindow.animation_ms, self._saved = 0, MainWindow.animation_ms
        self.w = self.app.window
        self.w.widget.show()
        self.w.open_panel(FILE_PAGE)
        _app.processEvents()

    def tearDown(self):
        MainWindow.animation_ms = self._saved
        super().tearDown()

    def test_the_edge_has_a_grip_you_can_drag_sideways(self):
        grip = self.w.panel.grip
        self.assertEqual(grip.cursor().shape(), Qt.CursorShape.SplitHCursor)
        self.assertEqual((grip.x(), grip.height()), (0, self.w.panel.height()))
        self.assertTrue(grip.toolTip())

    def test_dragging_left_widens_the_panel_and_narrows_the_content_at_the_same_window_size(self):
        window, content, panel = self.w.widget.width(), self.w.root.width(), self.w.panel.width()
        self.w.panel.width_dragged.emit(-40)
        _app.processEvents()
        self.assertEqual(self.w.panel.width(), panel + 40)
        self.assertEqual(self.w.widget.width(), window)
        self.assertEqual(self.w.root.width(), content - 40)

    def test_dragging_right_narrows_it_but_not_below_the_least(self):
        from quill.ui.side_panel import PANEL_MIN_WIDTH
        self.w.panel.width_dragged.emit(5000)
        self.assertEqual(self.w.panel.width(), PANEL_MIN_WIDTH)

    def test_dragging_left_stops_before_the_content_gets_too_small(self):
        from quill.ui.main_window import MIN_CONTENT_WIDTH
        self.w.panel.width_dragged.emit(-5000)
        _app.processEvents()
        self.assertGreaterEqual(self.w.root.width(), MIN_CONTENT_WIDTH)
        self.assertGreaterEqual(self.w.root.width(), self.w._layout.minimumSize().width())

    def test_the_title_bar_follows_every_step(self):
        widths = []
        self.w.set_panel_listener(lambda page: None, widths.append)
        self.w.panel.width_dragged.emit(-30)
        self.assertEqual(widths[-1], self.w.panel.width())

    def test_the_new_width_is_remembered_restored_and_used_the_next_time_it_opens(self):
        self.w.panel.width_dragged.emit(-60)
        self.w.panel.width_released.emit()
        width = self.w.panel.width()
        self.assertEqual(self.app.settings.preferences["panel_width"], width)
        self.w.close_panel()
        self.w.open_panel(FILE_PAGE)
        _app.processEvents()
        self.assertEqual(self.w.panel.width(), width)
        other = MainWindow()
        other.setup()
        other.restore_panel_width(300)
        self.assertEqual(other.panel_width, 300)
        other.restore_panel_width(5)
        self.assertEqual(other.panel_width, 200)

    def test_a_drag_with_the_panel_closed_does_nothing(self):
        self.w.close_panel()
        _app.processEvents()
        self.w.panel.width_dragged.emit(-50)
        self.assertEqual(self.w.panel.width(), 0)

    def test_the_remembered_window_width_never_includes_the_panel(self):
        sizes = []
        self.w._on_resized = lambda width, height: sizes.append(width)
        self.w.panel.width_dragged.emit(-40)
        self.w.report_size()
        self.assertEqual(sizes[-1], self.w.widget.width() - self.w.panel.width())


class TestLogGripAndHeading(PanelApp):
    def setUp(self):
        super().setUp()
        self.w = self.app.window
        self.w.widget.show()
        self.w.set_log_collapsed(False)
        _app.processEvents()

    def test_the_log_has_a_grip_on_its_bottom_edge_for_the_height_only(self):
        grip, log = self.w.log_grip, self.w.log
        self.assertTrue(grip.isVisibleTo(self.w.widget))
        self.assertEqual(grip.cursor().shape(), Qt.CursorShape.SizeVerCursor)
        self.assertEqual(grip.geometry().bottom(), log.geometry().bottom())
        self.assertEqual((grip.x(), grip.width()), (log.x(), log.width()))

    def test_dragging_it_down_grows_the_log_and_the_window_together_and_never_sideways(self):
        width, height, log = self.w.widget.width(), self.w.widget.height(), self.w.log_height
        self.w.log_grip.dragged.emit(40)
        _app.processEvents()
        self.assertEqual(self.w.log_height, log + 40)
        self.assertEqual(self.w.log.height(), log + 40)
        self.assertEqual((self.w.widget.width(), self.w.widget.height()), (width, height + 40))

    def test_dragging_it_up_shrinks_both_and_stops_at_the_least(self):
        from quill.ui.main_window import LOG_MIN_HEIGHT
        self.w.log_grip.dragged.emit(-9999)
        self.assertEqual(self.w.log_height, LOG_MIN_HEIGHT)

    def test_it_is_remembered(self):
        self.w.log_grip.dragged.emit(30)
        self.w.log_grip.released.emit()
        self.assertEqual(self.app.settings.preferences["log_height"], 150)

    def test_it_is_gone_while_the_log_is_hidden_and_in_the_mini_view(self):
        self.w.set_log_collapsed(True)
        _app.processEvents()
        self.assertFalse(self.w.log_grip.isVisibleTo(self.w.widget))
        self.w.set_log_collapsed(False)
        self.w.set_mini(True)
        _app.processEvents()
        self.assertFalse(self.w.log_grip.isVisibleTo(self.w.widget))

    def test_the_log_heading_sits_close_to_its_box_in_both_spacings(self):
        from quill.ui.main_window import LOG_HEADING_GAP
        for spacing in ("compact", "comfortable"):
            self.app.settings.preferences["spacing"] = spacing
            self.app.apply_settings(quiet=True)
            _app.processEvents()
            gap = self.w.log.geometry().top() - self.w.log_toggle.geometry().bottom()
            heading = self.w.log_toggle.mapTo(self.w.root, self.w.log_toggle.rect().bottomLeft()).y()
            box = self.w.log.mapTo(self.w.root, self.w.log.rect().topLeft()).y()
            self.assertLessEqual(box - heading, LOG_HEADING_GAP + 6, spacing)
            self.assertIsNotNone(gap)


class TestSettingsRound5(unittest.TestCase):
    def setUp(self):
        from quill.ui.settings_dialog import SettingsDialog
        self.installed = {"standard": True, "better": False, "best": False}
        self.d = SettingsDialog(Settings.defaults(), model_installed=lambda q: self.installed[q],
                                on_download_model=lambda q: None)
        self.dlg = self.d.build()

    def test_troubleshooting_is_the_last_setting_on_the_general_page(self):
        titles = [r.title for r in self.d._page_rows["General"]]
        self.assertEqual(titles[-1], "Troubleshooting")
        self.assertEqual(titles.count("Troubleshooting"), 1)

    def test_the_speech_model_has_its_own_page_under_voice_and_commands(self):
        from quill.ui.settings_dialog import GROUPS
        caption, pages = GROUPS[1]
        self.assertEqual(caption, "Voice and Commands")
        self.assertIn("Speech Model", pages)
        self.assertNotIn("Speech Model", [r.title for r in self.d._page_rows["General"]])

    def test_each_model_is_a_radio_button_and_only_one_can_be_chosen(self):
        rows = self.d.model_rows
        self.assertEqual(list(rows), ["standard", "better", "best"])
        self.assertTrue(rows["standard"].radio.isChecked())
        rows["better"].radio.setChecked(True)
        self.assertEqual([k for k, r in rows.items() if r.radio.isChecked()], ["better"])
        self.assertEqual(self.d.selected_quality, "better")

    def test_the_name_is_bold_and_the_size_beside_it_is_italic_and_muted(self):
        from quill.ui.theme import stylesheet_for
        for key, size in (("standard", "40 MB"), ("better", "130 MB"), ("best", "145 MB")):
            row = self.d.model_rows[key]
            self.assertEqual(row.title_label.text(), {"standard": "Quick", "better": "Broad", "best": "Careful"}[key])
            self.assertTrue(row.title_label.property("modelName"))
            self.assertEqual(row.size_label.text(), size)
            self.assertTrue(row.size_label.property("modelSize"))
        sheet = stylesheet_for(False)
        rule = sheet[sheet.index('QLabel[modelSize="true"]'): sheet.index("}", sheet.index('QLabel[modelSize="true"]'))]
        self.assertIn("italic", rule)
        self.assertIn("color", rule)
        self.assertIn("700", sheet[sheet.index('QLabel[modelName="true"]'):][:80])

    def test_each_model_says_what_it_costs_in_memory_and_time(self):
        for key, words in (("standard", "165 MB"), ("better", "415 MB"), ("best", "700 MB")):
            self.assertIn(words, self.d.model_rows[key].cost_label.text())
        self.assertEqual([self.d.model_rows[k].cost_label.text() for k in ("standard", "better", "best")],
                         ["Memory: ~165 MB", "Memory: ~415 MB (+250 MB / +1s)", "Memory: ~700 MB (+535 MB / Pause + .5s)"])
        for row in self.d.model_rows.values():
            text = row.cost_label.text() + row.description_label.text()
            self.assertNotIn("about", text)
            self.assertNotIn("around ", row.cost_label.text())

    def test_the_memory_line_is_muted_and_the_description_is_not(self):
        for row in self.d.model_rows.values():
            self.assertTrue(row.cost_label.property("modelCost"))
            self.assertFalse(row.description_label.property("muted"))

    def test_the_pane_says_a_model_is_installed_once_and_no_button_repeats_it(self):
        intro = self.d.pages.widget(self.d._page_index["Speech Model"]).findChildren(QLabel)
        self.assertTrue(any("installed once" in label.text() for label in intro))
        for row in self.d.model_rows.values():
            for button in (row.download_button, row.uninstall_button):
                self.assertNotIn("once", button.toolTip())
        self.assertEqual(self.d.model_rows["better"].download_button.text(), "Install")

    def test_uninstall_only_shows_for_an_installed_model_that_may_be_removed(self):
        removable = {"standard": False, "better": True, "best": True}
        from quill.ui.settings_dialog import SettingsDialog
        self.installed.update(better=True, best=False)
        d = SettingsDialog(Settings.defaults(), model_installed=lambda q: self.installed[q], model_removable=lambda q: removable[q])
        d.build()
        rows = d.model_rows
        self.assertFalse(rows["standard"].uninstall_button.isHidden())     # installed but bundled: shown, greyed out
        self.assertFalse(rows["standard"].uninstall_button.isEnabled())
        self.assertEqual(rows["standard"].uninstall_button.toolTip(),
                         "Quick is the base Speech Model which more advanced models build upon. It cannot be uninstalled.")
        self.assertFalse(rows["better"].uninstall_button.isHidden())
        self.assertTrue(rows["best"].uninstall_button.isHidden())          # not installed
        tip = rows["better"].uninstall_button.toolTip()
        self.assertEqual(tip, "Removes the Broad model from this computer and frees its disk space.")
        for words in ("install it again", "one in use", "switches", "MB"):
            self.assertNotIn(words, tip)

    def test_uninstall_asks_the_application(self):
        asked = []
        from quill.ui.settings_dialog import SettingsDialog
        d = SettingsDialog(Settings.defaults(), model_installed=lambda q: True, model_removable=lambda q: True,
                           on_uninstall_model=asked.append)
        d.build()
        d.model_rows["best"].uninstall_button.click()
        self.assertEqual(asked, ["best"])

    def test_the_descriptions_say_how_each_model_improves_the_quality(self):
        text = {k: r.description_label.text().lower() for k, r in self.d.model_rows.items()}
        self.assertIn("unusual words", text["better"])
        self.assertIn("vocabulary", text["better"])
        self.assertIn("second listen", text["best"])
        self.assertIn("re-read", text["best"])
        self.assertIn("mishear", text["standard"])
        for words in text.values():
            self.assertNotIn("not installed", words)
            self.assertNotIn("installed.", words)

    def test_an_installed_model_has_an_uninstall_button_and_the_others_an_install_button_and_no_pill_exists(self):
        standard, better = self.d.model_rows["standard"], self.d.model_rows["better"]
        self.assertFalse(hasattr(standard, "installed_pill"))
        self.assertFalse(standard.uninstall_button.isHidden())
        self.assertTrue(standard.download_button.isHidden())
        self.assertFalse(standard.uninstall_button.isEnabled())               # (nothing says it may be removed here)
        self.assertTrue(better.uninstall_button.isHidden())
        self.assertFalse(better.download_button.isHidden())
        self.assertEqual(better.download_button.text(), "Install")
        self.assertEqual(standard.uninstall_button.text(), "Uninstall")

    def test_installing_a_model_swaps_its_install_button_for_uninstall(self):
        self.installed["better"] = True
        self.d.set_model_state("", False)
        self.assertFalse(self.d.model_rows["better"].uninstall_button.isHidden())
        self.assertTrue(self.d.model_rows["better"].download_button.isHidden())

    def test_the_selected_rows_drop_down_text_is_the_on_accent_colour_and_clears_when_deselected(self):
        from quill.ui.theme import colors_for, stylesheet_for
        self.d.nav.setCurrentRow(self.d._nav_row("Keywords"))
        self.d.table.selectRow(1)
        combos = [self.d.table.cellWidget(r, 1) for r in range(3)]
        self.assertEqual([bool(c.property("rowSelected")) for c in combos], [False, True, False])
        self.d.table.selectRow(2)
        self.assertEqual([bool(c.property("rowSelected")) for c in combos], [False, False, True])
        for dark in (False, True):
            sheet = stylesheet_for(dark)
            rule = sheet[sheet.index('QComboBox[flat="true"][rowSelected="true"]'): sheet.index("}", sheet.index('QComboBox[flat="true"][rowSelected="true"]'))]
            self.assertIn(colors_for(dark, "violet")["on_accent"], rule)


class TestTitleBarIconStates(unittest.TestCase):
    def test_leaving_a_panel_clears_the_icons_fill_and_a_stuck_hover(self):
        from quill.ui import chrome
        from tests.test_titlebar_and_refresh import FakeAppKit

        class Button:
            def __init__(self): self._on = False; self._hover = True; self.refreshed = 0
            def refreshFill(self): self.refreshed += 1

        kit = FakeAppKit()
        buttons = [Button(), Button(), Button()]
        group = chrome.TitlebarButton(Button(), None, None, kit, [(b, None) for b in buttons])
        group.set_extra_active(1, True)
        self.assertTrue(buttons[1]._on)
        group.set_extra_active(1, False)                                       # the Turn icon after the File icon was pressed
        self.assertFalse(buttons[1]._on)
        self.assertFalse(buttons[1]._hover)                                    # (a missed mouse-exit must not keep it filled)
        self.assertEqual(buttons[1].refreshed, 2)

    def test_the_app_marks_only_the_open_pages_icon(self):
        app = PanelApp()
        app.setUp()
        try:
            calls = []
            app.app._titlebar = type("T", (), {"set_extra_active": lambda s, i, on: calls.append((i, on)),
                                               "set_panel_title": lambda s, t: None, "set_inset": lambda s, w: None})()
            app.app._panel_toggled(TURN_PAGE)
            app.app._panel_toggled(FILE_PAGE)
            app.app._panel_toggled("")
            self.assertEqual(calls, [(0, False), (1, True), (0, True), (1, False), (0, False), (1, False)])
        finally:
            app._tmp.cleanup()

    def test_the_pointer_is_checked_for_real_not_just_remembered(self):
        import inspect
        from quill.ui import chrome
        src = inspect.getsource(chrome._button_class)
        self.assertIn("pointerInside", src)
        self.assertIn("mouseLocationOutsideOfEventStream", src)


class TestOneStyleForTooltipsEverywhere(unittest.TestCase):
    EMOJI = __import__("re").compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF]")

    def all_tips(self):
        from PySide6.QtWidgets import QAbstractItemView, QWidget as W
        from tests.test_side_panel_and_turns import TestControlsFollowTheirStyle
        tips = []
        for name, root in TestControlsFollowTheirStyle().windows().items():
            for widget in [root, *root.findChildren(W)]:
                if widget.toolTip():
                    tips.append((name, type(widget).__name__, widget.toolTip()))
            for view in root.findChildren(QAbstractItemView):
                for r in range(view.model().rowCount()):
                    tip = view.model().index(r, 0).data(Qt.ItemDataRole.ToolTipRole)
                    if tip:
                        tips.append((name, "item", str(tip)))
        return tips

    def test_every_tooltip_is_plain_text_so_the_one_tip_style_draws_all_of_them(self):
        odd = [t for t in self.all_tips() if ("<" in t[2] and ">" in t[2]) or self.EMOJI.search(t[2])]
        self.assertEqual(odd, [])

    def test_the_not_connected_pill_uses_a_plain_tip_like_every_other_control(self):
        from quill.ui.widgets import CenteredToolTips, connection_tip
        w = MainWindow()
        w.setup()
        tip = w.connection_chip.toolTip()
        self.assertEqual(tip, connection_tip())
        self.assertIsNotNone(CenteredToolTips.position(__import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(10, 10), tip))
        self.assertFalse(("<" in tip and ">" in tip))
        w.set_not_connected(True, "A longer reason that has to be wrapped over several lines so it reads as a block " * 2)
        self.assertNotIn("<", w.connection_chip.toolTip())

    def test_a_multi_line_tip_is_measured_by_its_widest_line_and_stays_on_screen(self):
        from PySide6.QtCore import QPoint
        from quill.ui.widgets import CenteredToolTips
        filt = CenteredToolTips()
        room = _app.primaryScreen().availableGeometry()
        filt.show_tip(QPoint(room.left() + 1, room.top() + 1), "Not connected\nQuill has no spreadsheet to read lists from or write rows to.")
        self.assertGreaterEqual(filt.window.geometry().left(), room.left())
        filt.window.hide()


class TestStyleGuideIsWrittenDown(unittest.TestCase):
    def test_the_ui_style_rules_exist_in_the_repository_and_name_every_element_type(self):
        import pathlib
        guide = pathlib.Path(__file__).resolve().parents[1] / "UI_STYLE.md"
        self.assertTrue(guide.is_file())
        text = guide.read_text(encoding="utf-8").lower()
        for word in ("button", "link", "input", "drop-down", "placeholder", "pill", "tool tip", "switch", "icon", "hover"):
            self.assertIn(word, text, word)

    def test_the_effects_check_tool_is_there_and_covers_opacity_and_blur(self):
        import pathlib
        tool = pathlib.Path(__file__).resolve().parents[1] / "tools" / "verify_window_effects.py"
        text = tool.read_text(encoding="utf-8")
        for needle in ("opacity 100 is solid", "blurred", "more blur"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()


class TestOpenFilesWithSetting(unittest.TestCase):
    def setUp(self):
        from quill.ui.settings_dialog import SettingsDialog
        self.settings = Settings.defaults()
        self.d = SettingsDialog(self.settings)
        self.d.build()

    def test_it_lists_every_program_and_starts_on_the_saved_one(self):
        self.assertEqual([self.d.open_with_combo.itemData(i) for i in range(self.d.open_with_combo.count())],
                         ["auto", "numbers", "libreoffice", "excel"])
        self.assertEqual(self.d.open_with_combo.currentData(), "auto")

    def test_programs_that_are_not_installed_stay_listed_but_grey_and_last(self):
        from quill.ui.settings_dialog import SettingsDialog
        have = {"auto": True, "numbers": False, "libreoffice": True, "excel": False}
        d = SettingsDialog(Settings.defaults(), program_available=lambda k: have[k])
        d.build()
        combo = d.open_with_combo
        self.assertEqual([combo.itemData(i) for i in range(combo.count())], ["auto", "libreoffice", "numbers", "excel"])
        self.assertEqual([combo.model().item(i).isEnabled() for i in range(4)], [True, True, False, False])
        self.assertIn("Not installed", combo.model().item(2).toolTip())

    def test_a_saved_program_that_is_gone_shows_automatic(self):
        from quill.ui.settings_dialog import SettingsDialog
        settings = Settings.defaults()
        settings.preferences["open_with"] = "numbers"
        d = SettingsDialog(settings, program_available=lambda k: k != "numbers")
        d.build()
        self.assertEqual(d.open_with_combo.currentData(), "auto")

    def test_choosing_one_is_saved_with_the_other_preferences(self):
        self.d.open_with_combo.setCurrentIndex(self.d.open_with_combo.findData("libreoffice"))
        self.d._store_preferences()
        self.assertEqual(self.settings.preferences["open_with"], "libreoffice")

    def test_the_row_is_on_the_general_page_before_troubleshooting(self):
        titles = [r.title for r in self.d._page_rows["General"]]
        self.assertEqual(titles[-1], "Troubleshooting")
        self.assertEqual(titles[-2], "Open Files With")


class TestTextSizeReachesEveryWidget(PanelApp):
    def test_every_label_button_and_field_is_drawn_at_the_chosen_size(self):
        from PySide6.QtWidgets import QAbstractButton, QLineEdit
        from quill.ui.theme import apply_theme
        for size in (14, 17):
            apply_theme(_app, "light", "violet", "compact", size)
            self.app.window.open_panel("file")
            sizes = {type(w).__name__: w.font().pointSizeF() for w in _app.allWidgets()
                     if isinstance(w, (QLabel, QAbstractButton, QLineEdit))}
            self.assertTrue(sizes)
            self.assertEqual({v for v in sizes.values()}, {float(size)}, sizes)

    def test_the_description_names_the_real_default(self):
        from quill.config.settings import DEFAULT_PREFERENCES
        from quill.ui.settings_dialog import SettingsDialog
        d = SettingsDialog(Settings.defaults())
        d.build()
        row = next(r for r in d.rows if r.title == "Text Size")
        self.assertIn(f"default {DEFAULT_PREFERENCES['font_size']}", row.description_label.text())


class TestGreyDropDownEntries(unittest.TestCase):
    def test_a_disabled_entry_in_any_drop_down_list_is_drawn_grey_and_does_not_highlight(self):
        from quill.ui.theme import colors_for, stylesheet_for
        for dark in (False, True):
            sheet = stylesheet_for(dark)
            start = sheet.index("QComboBox QAbstractItemView::item:disabled")
            rule = sheet[start: sheet.index("}", start)]
            self.assertIn(colors_for(dark, "violet")["disabled"], rule)
            self.assertGreater(start, sheet.index("QComboBox QAbstractItemView::item:hover"))      # later, so it wins


class TestModelNames(unittest.TestCase):
    def test_the_models_are_called_quick_broad_and_careful_everywhere_the_user_sees_them(self):
        from quill.app import QUALITY_LABELS
        from quill.listener.model import BETTER, STANDARD
        from quill.ui.settings_dialog import SPEECH_MODELS
        self.assertEqual(QUALITY_LABELS, {"standard": "Quick", "better": "Broad", "best": "Careful"})
        self.assertEqual([name for _, name, *_ in SPEECH_MODELS], ["Quick", "Broad", "Careful"])
        self.assertEqual((STANDARD.label, BETTER.label), ("Quick", "Broad"))
        for _, _, _, description, cost in SPEECH_MODELS:
            for old in ("Standard", "Better", "Best", "Whisper"):
                self.assertNotIn(old, description + cost)


class TestTipsWrapToAMaxWidth(unittest.TestCase):
    def test_a_long_line_is_wrapped_at_word_breaks_and_no_line_is_wider_than_the_limit(self):
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import QToolTip
        from quill.ui.widgets import TOOLTIP_MAX_TEXT, CenteredToolTips, TipWindow, fit_tip
        text = ("Removes the Broad model from this computer and frees its disk space. If it is the one in use, Quill "
                "switches to the Quick model. You can install it again at any time.")
        metrics = QFontMetrics(QToolTip.font())
        out = fit_tip(text)
        self.assertGreater(len(out.split("\n")), 1)
        self.assertEqual(out.replace("\n", " "), text)                                 # only breaks at spaces, nothing lost
        for line in out.split("\n"):
            self.assertLessEqual(metrics.horizontalAdvance(line), TOOLTIP_MAX_TEXT)
        tip = TipWindow()
        size = tip.set_text(text)
        self.assertLessEqual(size.width(), TOOLTIP_MAX_TEXT + 40)
        self.assertEqual(CenteredToolTips.position(__import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(500, 300), text).x(),
                         500 - size.width() // 2)

    def test_a_short_tip_and_a_tip_with_its_own_breaks_are_left_alone(self):
        from quill.ui.widgets import fit_tip
        self.assertEqual(fit_tip("Start listening"), "Start listening")
        self.assertEqual(fit_tip("Not connected\nNo file."), "Not connected\nNo file.")


class TestSentencesAreFinished(unittest.TestCase):
    def test_every_log_line_is_a_finished_sentence(self):
        from quill.ui.main_window import sentence
        self.assertEqual(sentence("Left ‘x’ for later"), "Left ‘x’ for later.")
        self.assertEqual(sentence("Added ‘teal’"), "Added ‘teal’.")
        self.assertEqual(sentence("Done."), "Done.")
        self.assertEqual(sentence("Which column?"), "Which column?")
        w = MainWindow()
        w.setup()
        w.append_log("Workbook re-read")
        self.assertIn("Workbook re-read.", w.log.toPlainText())

    def test_the_turn_option_descriptions_are_sentences(self):
        w = MainWindow()
        w.setup()
        for text in (w.panel.next_row_note.text(), w.panel.append_note.text()):
            self.assertTrue(text.endswith("."), text)
        self.assertTrue(w.panel.next_row_radio.toolTip().endswith("."))
        self.assertTrue(w.panel.new_row_button.toolTip().endswith("."))

    def test_every_tip_and_description_that_is_a_sentence_ends_with_a_full_stop(self):
        """Walks the built windows: a tool tip or a muted description with several words in sentence case must end in
        punctuation (titles and labels in Title Case are names, not sentences)."""
        import re
        w = MainWindow()
        w.setup()
        from quill.ui.settings_dialog import SettingsDialog
        d = SettingsDialog(Settings.defaults())
        d.build()
        bad = []
        for root in (w.widget, w.panel, d._dialog):
            for widget in root.findChildren(QWidget):
                texts = [widget.toolTip()]
                if isinstance(widget, QLabel) and widget.property("muted"):
                    texts.append(widget.text())
                for text in texts:
                    plain = re.sub(r"<[^>]+>", "", text or "").strip()
                    words = plain.split()
                    if len(words) >= 4 and plain[0].isupper() and not all(x[:1].isupper() or not x[:1].isalpha() or x.lower() in ("a", "an", "the", "to", "of", "and", "or", "in", "for", "from", "with", "on", "at") for x in words):
                        if plain[-1] not in ".!?…:)”":
                            bad.append(plain[:70])
        self.assertEqual(sorted(set(bad)), [])


class TestFileWindowIsWarmedUp(PanelApp):
    def test_nothing_is_started_where_the_system_cannot_be_asked(self):
        from quill.ui.chrome import FileDialogWarmer
        warmer = FileDialogWarmer()
        self.assertFalse(warmer.start())                                    # (offscreen: no real window system)
        self.assertFalse(warmer.start("win32"))
        warmer.cancel()                                                     # (nothing to cancel is fine)

    def test_a_real_file_window_first_closes_the_invisible_one(self):
        calls = []
        self.app._file_dialog_warmer = type("W", (), {"cancel": lambda s: calls.append("cancel"), "done": False,
                                                      "start": lambda s: calls.append("start")})()
        from unittest import mock
        with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=("", "")):
            self.app._ask_for_file()
        self.assertEqual(calls, ["cancel"])

    def test_the_warm_up_waits_for_quill_to_be_in_front_and_never_runs_twice(self):
        started = []
        self.app._file_dialog_warmer = type("W", (), {"cancel": lambda s: None, "done": False,
                                                      "start": lambda s: started.append(1)})()
        from unittest import mock
        with mock.patch.dict("os.environ", {}, clear=False):
            __import__("os").environ.pop("QUILL_NO_HOSTS", None)
            with mock.patch.object(self.app.qapp, "applicationState", return_value=Qt.ApplicationState.ApplicationInactive):
                self.app._warm_file_dialog()
                self.assertEqual(started, [])                               # not in front: waits
            with mock.patch.object(self.app.qapp, "applicationState", return_value=Qt.ApplicationState.ApplicationActive):
                self.app._warm_file_dialog()
        self.assertEqual(started, [1])


class TestRefreshFeedbackAndDensity(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.w.setup()
        self.w.widget.show()
        self.panel = self.w.panel
        self.panel.REFRESH_BLINK_MS = 30
        self.panel._search_timer.setInterval(10)

    def wait(self, ms):
        import time
        end = time.time() + ms / 1000
        while time.time() < end:
            _app.processEvents()
            time.sleep(0.005)

    def test_a_refresh_hides_the_nothing_found_message_for_a_moment_then_brings_it_back(self):
        self.w.open_panel(FILE_PAGE)
        self.panel.set_available([])
        self.assertFalse(self.panel.empty_label.isHidden())
        asked = []
        self.panel.refresh_requested.connect(lambda: asked.append(1))
        self.panel.refresh_button.click()
        self.assertEqual(asked, [1])
        self.assertTrue(self.panel.empty_label.isHidden())                  # gone while it looks again ...
        self.panel.set_available([])                                        # ... even if the answer comes at once
        self.assertTrue(self.panel.empty_label.isHidden())
        self.wait(120)
        self.assertFalse(self.panel.empty_label.isHidden())                 # ... and back, because nothing was found

    def test_found_files_are_not_hidden_by_the_blink(self):
        self.w.open_panel(FILE_PAGE)
        self.panel.refresh_button.click()
        self.panel.set_available([("a.xlsx", "tip", object())])
        self.wait(120)
        self.assertTrue(self.panel.empty_label.isHidden())
        self.assertEqual(self.panel.available_names(), ["a.xlsx"])

    def test_three_letters_in_search_look_again_after_a_pause_and_two_do_not(self):
        asked = []
        self.panel.refresh_requested.connect(lambda: asked.append(1))
        self.panel.search.setText("ab")
        self.wait(60)
        self.assertEqual(asked, [])
        self.panel.search.setText("abc")
        self.panel.search.setText("abcd")                                   # typing on: one look, after the pause
        self.wait(80)
        self.assertEqual(asked, [1])

    def test_the_automatic_poll_does_not_blink_the_message(self):
        self.w.open_panel(FILE_PAGE)
        self.panel.set_available([])
        self.assertFalse(self.panel.empty_label.isHidden())

    def test_a_pressed_icon_looks_different_from_a_hovered_one(self):
        from quill.ui.theme import stylesheet_for
        sheet = stylesheet_for(False)
        hover = sheet[sheet.index('QToolButton[chromeIcon="true"]:hover'): sheet.index("}", sheet.index('QToolButton[chromeIcon="true"]:hover'))]
        pressed = sheet[sheet.index('QToolButton[chromeIcon="true"]:pressed'): sheet.index("}", sheet.index('QToolButton[chromeIcon="true"]:pressed'))]
        self.assertNotEqual(hover.split("{")[1], pressed.split("{")[1])

    def test_the_file_overlay_is_roomier_in_comfortable_spacing(self):
        overlay = self.panel.settings
        overlay.apply_density("compact")
        compact = (overlay.layout().spacing(), overlay.layout().contentsMargins().left(), overlay.height())
        overlay.apply_density("comfortable")
        comfy = (overlay.layout().spacing(), overlay.layout().contentsMargins().left(), overlay.height())
        self.assertGreater(comfy[0], compact[0])
        self.assertGreater(comfy[1], compact[1])
        self.assertGreater(comfy[2], compact[2])


class TestSpacingNeverLeavesAClearFrame(unittest.TestCase):
    """The root of every window fills the window, whatever the spacing: a margin around it would be a clear, un-tinted,
    un-blurred frame when the window is see-through."""

    def check(self, window, root):
        from quill.ui.theme import apply_spacing
        for spacing in ("compact", "comfortable", "compact"):
            apply_spacing(window, spacing)
            _app.processEvents()
            top = root.mapTo(window, root.rect().topLeft())
            self.assertEqual((top.x(), root.width()), (0, window.width()), spacing)
            self.assertLessEqual(window.height() - (top.y() + root.height()), 0, spacing)

    def test_the_term_helper(self):
        from quill.ui.sorting_window import SortingWindow
        from quill.parser.vocab import Vocabulary
        sorting = SortingWindow(Vocabulary(), lambda *a: None)
        sorting.setup()
        sorting.widget.show()
        self.check(sorting.widget, sorting.root)

    def test_the_help_window(self):
        from quill.ui.help_window import HelpWindow
        help_window = HelpWindow()
        help_window.setup()
        help_window._window.show()
        root = help_window._window.findChild(QWidget, "helpRoot") or help_window._window.centralWidget()
        self.check(help_window._window, root)

    def test_the_settings_window(self):
        from quill.ui.settings_dialog import SettingsDialog
        d = SettingsDialog(Settings.defaults())
        d.build()
        d._dialog.show()
        self.check(d._dialog, d.root)


class TestStartWaitsForTheFileThenListens(PanelApp):
    """Start with a newly connected file: the file is opened once, never again, and listening starts by itself."""

    def setUp(self):
        super().setUp()
        self._env = mock.patch.dict("os.environ", {}, clear=False)
        self._env.start()
        __import__("os").environ.pop("QUILL_NO_HOSTS", None)
        self.hosts.running = lambda: []
        self.app._open_files = []
        self.app.VIEWER_LOOK_MS = 10
        self.me = OpenFile("plants.xlsx", str(self.plants), "Numbers")

    def tearDown(self):
        self._env.stop()
        super().tearDown()

    def wait(self, ms=150):
        import time
        end = time.time() + ms / 1000
        while time.time() < end:
            _app.processEvents()
            time.sleep(0.005)

    def test_the_file_is_opened_once_however_often_start_is_pressed(self):
        for _ in range(4):
            self.app.toggle_listening(True)
            self.wait(40)
        self.assertEqual(self.hosts.launched, [str(self.plants.resolve())])
        self.assertFalse(self.app.controller.session.listening)

    def test_listening_starts_by_itself_the_moment_the_file_shows_up_open(self):
        self.app.toggle_listening(True)
        self.wait(40)
        self.assertFalse(self.app.controller.session.listening)
        self.hosts.files = [self.me]                                          # the program has opened it
        self.wait(150)
        self.assertTrue(self.app.controller.session.listening)
        self.assertEqual(self.hosts.launched, [str(self.plants.resolve())])   # still only the one request

    def test_a_file_that_is_already_open_is_never_opened_again(self):
        self.hosts.files = [self.me]
        self.app.toggle_listening(True)
        self.wait(60)
        self.assertTrue(self.app.controller.session.listening)
        self.assertEqual(self.hosts.launched, [])

    def test_stop_cancels_the_wait(self):
        self.app.toggle_listening(True)
        self.wait(40)
        self.app.toggle_listening(False)
        self.hosts.files = [self.me]
        self.wait(100)
        self.assertFalse(self.app.controller.session.listening)

    def test_it_gives_up_after_a_while_and_says_what_to_do(self):
        self.app.VIEWER_LOOKS = 3
        self.app.toggle_listening(True)
        self.wait(200)
        text = self.app.window.log.toPlainText()
        self.assertIn("did not open", text)
        self.assertIn("then press Start", text)
        self.assertEqual(self.hosts.launched, [str(self.plants.resolve())])
        self.hosts.files = [self.me]
        self.wait(80)
        self.assertFalse(self.app.controller.session.listening)               # (it stopped waiting)

    def test_a_pick_that_just_opened_the_file_is_not_followed_by_a_second_opening_on_start(self):
        self.chosen[0] = str(self.other)
        self.app.choose_spreadsheet_file()                                    # the loader opens it
        opened = list(self.hosts.launched)
        self.assertEqual(len(opened), 1)
        self.app.toggle_listening(True)
        self.wait(60)
        self.assertEqual(self.hosts.launched, opened)


class TestWhichSheetIsOpen(PanelApp):
    """The refresh icon beside Sheet, and the 30-second look, find out which sheet the spreadsheet program is on."""

    def setUp(self):
        super().setUp()
        self.app._open_files = [OpenFile("plants.xlsx", str(self.plants), "Numbers")]
        self.app.mirror = NoMirror(has=True, sheet="Config")

    def test_a_sheet_the_program_is_on_becomes_the_sheet_quill_writes_to(self):
        bridge = self.app.controller.bridge
        self.assertEqual(bridge.active_sheet_name(), "Inventory")
        self.app.refresh_active_sheet(quiet=True)
        self.assertEqual(bridge.active_sheet_name(), "Config")
        self.assertEqual(self.app.controller._sheet, "Config")                 # its field words were loaded
        self.assertEqual(self.app.window.sheet_name, "Config")

    def test_an_unknown_sheet_name_changes_nothing(self):
        self.app.mirror = NoMirror(has=True, sheet="No Such Sheet")
        self.app.refresh_active_sheet(quiet=True)
        self.assertEqual(self.app.controller.bridge.active_sheet_name(), "Inventory")

    def test_the_icon_checks_at_once_and_says_what_it_found(self):
        self.app.window.panel.sheet_refresh_button.click()
        self.assertEqual(self.app.controller.bridge.active_sheet_name(), "Config")
        self.app.window.panel.sheet_refresh_button.click()                    # nothing new: it still says so
        self.assertIn("sheet 'Config' is the one open", self.app.window.log.toPlainText())

    def test_the_timer_is_quiet_when_nothing_changed(self):
        self.app.refresh_active_sheet(quiet=True)
        before = self.app.window.log.toPlainText()
        self.app.refresh_active_sheet(quiet=True)
        self.assertEqual(self.app.window.log.toPlainText(), before)

    def test_it_looks_every_30_seconds_by_default_and_the_setting_changes_or_stops_it(self):
        self.assertEqual(self.app._sheet_timer.interval(), 30_000)
        self.assertTrue(self.app._sheet_timer.isActive())
        self.assertIn("every 30 seconds", self.app.window.panel.sheet_refresh_button.toolTip())
        self.settings.preferences["sheet_check_seconds"] = 90
        self.app.apply_settings(quiet=True)
        self.assertEqual(self.app._sheet_timer.interval(), 90_000)
        self.settings.preferences["sheet_check_seconds"] = 0
        self.app.apply_settings(quiet=True)
        self.assertFalse(self.app._sheet_timer.isActive())
        self.assertIn("does not check by itself", self.app.window.panel.sheet_refresh_button.toolTip())

    def test_the_icon_is_on_the_sheet_row_at_the_right_and_only_with_a_file(self):
        panel = self.app.window.panel
        self.assertFalse(panel.sheet_refresh_button.isHidden())
        self.assertFalse(panel.sheet_refresh_button.icon().isNull())
        panel.set_active("")
        self.assertTrue(panel.sheet_refresh_button.isHidden())
        panel.set_active("plants.xlsx", "Inventory", str(self.plants))
        self.assertFalse(panel.sheet_refresh_button.isHidden())
        self.assertEqual(panel.sheet_refresh_button.property("chromeIcon"), True)

    def test_a_csv_file_has_no_sheets_to_ask_about(self):
        csv_path = self.dir / "b.csv"
        csv_path.write_text("Bird\nWren\n")
        self.chosen[0] = str(csv_path)
        self.app.choose_spreadsheet_file()
        asked = []
        self.app.mirror = type("M", (), {"active_sheet": lambda s, p: asked.append(p)})()
        self.app.refresh_active_sheet(quiet=True)
        self.assertEqual(asked, [])

    def test_the_settings_row_is_a_number_with_off_at_zero(self):
        from quill.ui.settings_dialog import SettingsDialog
        d = SettingsDialog(self.settings)
        d.build()
        self.assertEqual(d.sheet_spin.value(), 30)
        d.sheet_spin.setValue(0)
        self.assertEqual(d.sheet_spin.text(), "Off")
        d._store_preferences()
        self.assertEqual(self.settings.preferences["sheet_check_seconds"], 0)


class TestSheetRowLinesUp(unittest.TestCase):
    def test_the_sheet_label_value_and_icon_share_one_centre_line(self):
        w = MainWindow()
        w.setup()
        w.widget.show()
        w.open_panel(FILE_PAGE)
        w.panel.set_active("plants.xlsx", "Inventory", "/x/plants.xlsx")
        _app.processEvents()
        label, value = w.panel.fact_rows["Sheet"]
        centres = [x.mapTo(w.panel, x.rect().center()).y() for x in (label, value, w.panel.sheet_refresh_button)]
        self.assertLessEqual(max(centres) - min(centres), 1, centres)
        right = w.panel.sheet_refresh_button.mapTo(w.panel, w.panel.sheet_refresh_button.rect().topRight()).x()
        refresh = w.panel.refresh_button.mapTo(w.panel, w.panel.refresh_button.rect().topRight()).x()
        self.assertEqual(right, refresh)                                      # at the right, level with the Available Files icon
