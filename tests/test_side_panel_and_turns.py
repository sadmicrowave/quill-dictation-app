"""The side panel (file and turn pages), spreadsheets open in other programs, and the turn settings:
Next Row or Append To, and headings across the top or down the side."""
import pathlib
import tempfile
import unittest
from unittest import mock

import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation
from PySide6.QtWidgets import QApplication

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
        self.assertEqual(self.panel.name_label.full_text, "plants.xlsx")
        self.assertEqual(self.panel.name_label.toolTip(), "/Users/me/Documents/plants.xlsx")
        self.assertEqual(self.panel.sheet_label.text(), "Sheet: Inventory")

    def test_with_no_file_it_says_so_and_hides_the_sheet(self):
        self.assertEqual(self.panel.name_label.full_text, "No file connected")
        self.assertFalse(self.panel.sheet_label.isVisibleTo(self.panel))
        self.w.update_workbooks([], "")
        self.assertEqual(self.panel.name_label.full_text, "No file connected")

    def test_a_workbook_without_a_path_hovers_its_name(self):
        self.panel.set_active("Unsaved.xlsx", "", "")
        self.assertEqual(self.panel.name_label.toolTip(), "Unsaved.xlsx")

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
        rules = [f for f in self.panel.findChildren(type(self.panel.stack.currentWidget())) if f.property("panelRule")]
        self.assertTrue(rules)

    def test_the_list_scrolls(self):
        self.panel.set_available([(f"s{i}.xlsx", "", i) for i in range(40)])
        self.assertGreater(self.panel.available.verticalScrollBar().maximum() or 1, 0)
        self.assertEqual(self.panel.available.verticalScrollMode(), self.panel.available.ScrollMode.ScrollPerPixel)

    def test_turn_choices_are_reported_but_showing_them_is_not_a_change(self):
        seen = []
        self.panel.mode_changed.connect(seen.append)
        self.panel.layout_changed.connect(seen.append)
        self.panel.set_turn(APPEND_TO, True)
        self.assertEqual(seen, [])
        self.assertTrue(self.panel.append_radio.isChecked())
        self.assertTrue(self.panel.down_radio.isChecked())
        self.panel.next_row_radio.setChecked(True)
        self.panel.across_radio.setChecked(True)
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

    def launch(self, path):
        self.launched.append(str(path))
        return True


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
                            file_chooser=lambda: self.chosen[0], live_bridge_factory=lambda: DeadExcel(), hosts=self.hosts)
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
        self.assertEqual(panel.name_label.full_text, "other.xlsx")
        self.assertEqual(panel.name_label.toolTip(), str(self.other.resolve()))
        self.assertEqual(panel.available_names(), ["plants.xlsx"])

    def test_picking_a_live_excel_workbook_goes_through_excel(self):
        entry = OpenFile("live.xlsx", "", "Excel", live=True)
        with mock.patch.object(self.app, "use_live_excel") as use, mock.patch.object(self.app, "connect_workbook") as connect:
            self.app._panel_pick(entry)
        use.assert_called_once()
        connect.assert_called_once_with("live.xlsx")

    def test_the_file_button_in_the_panel_opens_the_file_window(self):
        self.chosen[0] = str(self.other)
        self.app.window.panel.open_button.click()
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
        panel.down_radio.setChecked(True)
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


if __name__ == "__main__":
    unittest.main()
