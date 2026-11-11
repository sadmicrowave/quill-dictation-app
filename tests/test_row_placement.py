"""Where a turn's words are written: every layout (headings across the top, or down the first column) with every turn mode (each turn a new
record, or each turn added to the same one), on sheets whose columns are filled to different heights (as lists are).

A *record* is a row when the headings run across the top and a column when they run down the first column. Whatever the combination,
all the values of one turn go into ONE record, each in the cell where its own heading crosses that record. They are never put in the next
open cell of each heading's own line (which, on a sheet whose columns have different heights, would scatter one turn over several
records). The tests check the exact cell of every value, and that no other cell was touched: positive cases (what must be written, and
where) and negative cases (what must not be).
"""
import pathlib
import tempfile
import unittest

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from quill.bridge.base import BridgeError
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import SheetLayout, Settings
from quill.controller import Controller
from tests.test_app import AppCase

HEADINGS = ["Category", "Gender", "Size", "Brand", "Color", "Era", "Condition"]
LISTS = {
    "Category": ["T-Shirt", "Jacket", "Sweater", "Dress"],
    "Gender": ["Men", "Women", "Unisex"],
    "Size": ["Small", "Medium", "Large"],
    "Brand": ["Nike", "Adidas"],
    "Color": ["Black", "Brown", "Gray"],
    "Era": ["Eighties", "Nineties"],
    "Condition": ["New", "Good", "Fair"],
}
LAYOUTS = ("columns", "rows")             # headings across the first row / down the first column
MODES = ("next_row", "append")
HEADINGS_AT = 3                           # (headings across: below a one-line title)


class Sheet:
    """A workbook with one sheet ``Stock``, its headings, drop-down lists and some existing records of different heights per heading."""

    def __init__(self, folder: pathlib.Path, layout: str, depths: dict[str, int] | None = None, name: str = "stock.xlsx") -> None:
        self.layout, self.depths = layout, dict(depths or {})
        self.path = folder / name
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Stock"
        if layout == "columns":
            ws.cell(row=1, column=1, value="Stock book")                      # a title above the headings
        for index, heading in enumerate(HEADINGS, start=1):
            depth = self.depths.get(heading, 0)
            if layout == "columns":
                ws.cell(row=HEADINGS_AT, column=index, value=heading)
                for k in range(1, depth + 1):
                    ws.cell(row=HEADINGS_AT + k, column=index, value=f"old {heading} {k}")
                cells = f"{get_column_letter(index)}{HEADINGS_AT + 1}:{get_column_letter(index)}200"
            else:
                ws.cell(row=index, column=1, value=heading)
                for k in range(1, depth + 1):
                    ws.cell(row=index, column=1 + k, value=f"old {heading} {k}")
                cells = f"B{index}:Z{index}"
            rule = DataValidation(type="list", formula1='"' + ",".join(LISTS[heading]) + '"')
            ws.add_data_validation(rule)
            rule.add(cells)
        wb.save(self.path)

    # -- where things are ------------------------------------------------------------------------------
    @property
    def vertical(self) -> bool:
        return self.layout == "rows"

    def first_free(self) -> int:
        """The record number (1 = the first record below / right of the headings) a new turn starts at: past the tallest heading."""
        return max(self.depths.values(), default=0) + 1

    def address(self, heading: str, record: int) -> str:
        """The cell where *heading* crosses record number *record*."""
        index = HEADINGS.index(heading) + 1
        if self.layout == "columns":
            return f"{get_column_letter(index)}{HEADINGS_AT + record}"
        return f"{get_column_letter(1 + record)}{index}"

    def own_next(self, heading: str) -> str:
        """The next open cell of the heading's own line (the 'bottom of its column'): where a value must NOT go unless it is the record's."""
        return self.address(heading, self.depths.get(heading, 0) + 1)

    def snapshot(self) -> dict[str, object]:
        ws = openpyxl.load_workbook(self.path)["Stock"]
        return {cell.coordinate: cell.value for row in ws.iter_rows() for cell in row if cell.value is not None}


class PlacementCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.events = []

    def open(self, layout, depths=None, mode="next_row", name="stock.xlsx", start_row=0, prepare=None):
        """A controller on a fresh sheet of the layout, listening, in the mode. *prepare(sheet, worksheet)* may change the file first (what is
        already on the sheet when Quill connects to it: Quill works from what it loaded, and patches only the cells it writes)."""
        sheet = Sheet(self.dir, layout, depths, name)
        if prepare is not None:
            wb = openpyxl.load_workbook(sheet.path)
            prepare(sheet, wb["Stock"])
            wb.save(sheet.path)
        settings = Settings.load(self.dir / f"cfg-{name}")
        bridge = XlsxBridge(sheet.path)
        settings.set_layout(str(bridge.workbook_path), "Stock", SheetLayout(0, start_row, sheet.vertical))
        controller = Controller(bridge, settings, on_event=self.events.append)
        controller.connect()
        if mode == "append":
            controller.set_turn_mode("append")
        controller.handle_transcript("start listening")
        self.assertEqual(controller.vertical, sheet.vertical, "the layout is in force")
        return sheet, controller

    def turn(self, controller, *phrases):
        """Say the phrases, then 'next row' (which is what writes the turn)."""
        for phrase in phrases:
            controller.handle_transcript(phrase)
        controller.handle_transcript("next row")

    def written(self, sheet, before):
        """The cells that differ from *before* (a snapshot), as {cell: value}."""
        now = sheet.snapshot()
        return {k: v for k, v in now.items() if before.get(k) != v}


class TestOneTurnGoesIntoOneRecord(PlacementCase):
    def test_every_value_of_a_turn_is_in_the_same_record_in_every_layout_and_mode(self):
        for layout in LAYOUTS:
            for mode in MODES:
                with self.subTest(layout=layout, mode=mode):
                    sheet, c = self.open(layout, mode=mode, name=f"one-{layout}-{mode}.xlsx")
                    before = sheet.snapshot()
                    self.turn(c, "dress good")
                    self.assertEqual(self.written(sheet, before),
                                     {sheet.address("Category", 1): "Dress", sheet.address("Condition", 1): "Good"})

    def test_three_values_across_far_apart_headings_still_make_one_record(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                sheet, c = self.open(layout, name=f"far-{layout}.xlsx")
                before = sheet.snapshot()
                self.turn(c, "jacket large fair")
                self.assertEqual(self.written(sheet, before),
                                 {sheet.address("Category", 1): "Jacket", sheet.address("Size", 1): "Large", sheet.address("Condition", 1): "Fair"})


class TestHeadingsOfDifferentHeights(PlacementCase):
    """The case in the field report: Category is filled to six, Condition to four. The turn's two values must share ONE record (the one past the
    tallest heading), not land at the bottom of their own columns (one at A7 and one at G5)."""
    DEPTHS = {"Category": 6, "Condition": 4}

    def test_the_record_is_past_the_tallest_heading_and_not_at_each_headings_own_bottom(self):
        for layout in LAYOUTS:
            for mode in MODES:
                with self.subTest(layout=layout, mode=mode):
                    sheet, c = self.open(layout, self.DEPTHS, mode, name=f"stagger-{layout}-{mode}.xlsx")
                    self.assertEqual(sheet.first_free(), 7)
                    before = sheet.snapshot()
                    self.turn(c, "dress good")
                    got = self.written(sheet, before)
                    self.assertEqual(got, {sheet.address("Category", 7): "Dress", sheet.address("Condition", 7): "Good"})
                    # the negative: the shorter heading's own next open cell was NOT used
                    self.assertNotIn(sheet.own_next("Condition"), got)
                    self.assertNotEqual(sheet.own_next("Condition"), sheet.address("Condition", 7))

    def test_a_second_turn_goes_to_the_next_record_when_each_turn_is_a_new_record(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                sheet, c = self.open(layout, self.DEPTHS, name=f"stagger2-{layout}.xlsx")
                self.turn(c, "dress good")
                before = sheet.snapshot()
                self.turn(c, "jacket fair")
                self.assertEqual(self.written(sheet, before), {sheet.address("Category", 8): "Jacket", sheet.address("Condition", 8): "Fair"})

    def test_a_record_with_a_gap_is_filled_first_and_never_splits_a_turn(self):
        """A record left empty in the middle is the first free one: both values of the turn go there, together."""
        def gap(sheet, ws):
            ws.cell(row=HEADINGS_AT + 2, column=1).value = None           # empty the 2nd record entirely
            ws.cell(row=HEADINGS_AT + 2, column=7).value = None
        sheet, c = self.open("columns", {"Category": 3, "Condition": 3}, name="gap.xlsx", prepare=gap)
        before = sheet.snapshot()
        self.turn(c, "dress good")
        self.assertEqual(self.written(sheet, before), {"A5": "Dress", "G5": "Good"})


class TestAppendTo(PlacementCase):
    def test_each_turn_adds_to_the_same_record(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                sheet, c = self.open(layout, {"Category": 2}, "append", name=f"app-{layout}.xlsx")
                self.turn(c, "dress")
                self.turn(c, "good")
                self.turn(c, "large")
                record = sheet.first_free()                         # 3: past the two old category entries
                snap = sheet.snapshot()
                self.assertEqual(snap[sheet.address("Category", record)], "Dress")
                self.assertEqual(snap[sheet.address("Condition", record)], "Good")
                self.assertEqual(snap[sheet.address("Size", record)], "Large")
                # nothing went into the record after it
                for heading in HEADINGS:
                    self.assertNotIn(sheet.address(heading, record + 1), snap, f"{heading} spilled into the next record")

    def test_the_same_heading_said_again_in_the_same_record_is_added_to_the_cell(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                sheet, c = self.open(layout, mode="append", name=f"same-{layout}.xlsx")
                self.turn(c, "dress")
                self.turn(c, "jacket")
                self.assertEqual(sheet.snapshot()[sheet.address("Category", 1)], "Dress, Jacket")
                self.assertNotIn(sheet.address("Category", 2), sheet.snapshot())

    def test_a_staggered_sheet_keeps_every_turn_in_one_record(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                sheet, c = self.open(layout, {"Category": 6, "Condition": 4}, "append", name=f"appstag-{layout}.xlsx")
                before = sheet.snapshot()
                self.turn(c, "dress")
                self.turn(c, "good")
                self.assertEqual(self.written(sheet, before), {sheet.address("Category", 7): "Dress", sheet.address("Condition", 7): "Good"})

    def test_start_a_new_row_ends_the_shared_record(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                sheet, c = self.open(layout, mode="append", name=f"new-{layout}.xlsx")
                self.turn(c, "dress")
                c.start_new_row()
                self.turn(c, "jacket")
                snap = sheet.snapshot()
                self.assertEqual((snap[sheet.address("Category", 1)], snap[sheet.address("Category", 2)]), ("Dress", "Jacket"))

    def test_switching_back_to_next_row_starts_a_fresh_record_and_stays_there(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                sheet, c = self.open(layout, mode="append", name=f"back-{layout}.xlsx")
                self.turn(c, "dress")
                c.set_turn_mode("next_row")
                self.turn(c, "jacket")
                self.turn(c, "sweater")
                snap = sheet.snapshot()
                self.assertEqual([snap[sheet.address("Category", k)] for k in (1, 2, 3)], ["Dress", "Jacket", "Sweater"])

    def test_the_mode_is_remembered_and_the_two_modes_really_differ(self):
        """Negative: with each turn a new record the same words would NOT share a record."""
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                sheet, c = self.open(layout, mode="next_row", name=f"differ-{layout}.xlsx")
                self.turn(c, "dress")
                self.turn(c, "good")
                snap = sheet.snapshot()
                self.assertEqual(snap[sheet.address("Category", 1)], "Dress")
                self.assertEqual(snap[sheet.address("Condition", 2)], "Good")
                self.assertNotIn(sheet.address("Condition", 1), snap)


class TestStartingPosition(PlacementCase):
    def test_a_starting_row_or_column_sets_the_first_record(self):
        for layout in LAYOUTS:
            for mode in MODES:
                with self.subTest(layout=layout, mode=mode):
                    sheet, c = self.open(layout, mode=mode, start_row=6, name=f"start-{layout}-{mode}.xlsx")
                    before = sheet.snapshot()
                    self.turn(c, "dress good")
                    start = 6 - HEADINGS_AT if layout == "columns" else 6 - 1          # (record number of row 6 / of column F)
                    self.assertEqual(self.written(sheet, before),
                                     {sheet.address("Category", start): "Dress", sheet.address("Condition", start): "Good"})

    def test_a_starting_position_inside_the_headings_is_pushed_past_them(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                sheet, c = self.open(layout, start_row=1, name=f"inside-{layout}.xlsx")
                before = sheet.snapshot()
                self.turn(c, "dress")
                self.assertEqual(self.written(sheet, before), {sheet.address("Category", 1): "Dress"})

    def test_the_title_row_above_the_headings_is_left_alone(self):
        sheet, c = self.open("columns", name="title.xlsx")
        self.turn(c, "dress good")
        self.assertEqual(sheet.snapshot()["A1"], "Stock book")


class TestNothingIsWrittenThatShouldNotBe(PlacementCase):
    def test_a_turn_with_nothing_understood_writes_nothing(self):
        for layout in LAYOUTS:
            for mode in MODES:
                with self.subTest(layout=layout, mode=mode):
                    sheet, c = self.open(layout, mode=mode, name=f"none-{layout}-{mode}.xlsx")
                    before = sheet.snapshot()
                    self.turn(c)                                           # just "next row"
                    self.assertEqual(sheet.snapshot(), before)

    def test_a_heard_value_for_a_heading_the_sheet_does_not_have_writes_nothing_and_loses_nothing(self):
        for layout in LAYOUTS:
            for mode in MODES:
                with self.subTest(layout=layout, mode=mode):
                    sheet, c = self.open(layout, mode=mode, name=f"ghost-{layout}-{mode}.xlsx")
                    before = sheet.snapshot()
                    c.handle_transcript("dress good")
                    c.session.record["Ghost"] = "boo"                      # (a value for a heading this sheet lacks: the vocabulary is workbook-wide)
                    c.handle_transcript("next row")
                    self.assertEqual(sheet.snapshot(), before, "a half-written record must never be left behind")
                    self.assertEqual(self.events[-1].kind, "error")
                    self.assertEqual(c.session.record.get("Category"), "Dress")      # what was said is kept to try again
                    self.assertEqual(c.session.record.get("Condition"), "Good")

    def test_a_computed_cell_is_never_overwritten_when_adding_to_a_record(self):
        """A formula column filled in advance (a total, a tag): it does not make a record 'taken', and Quill never writes over it."""
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                def formula(sheet, ws):
                    ws[sheet.address("Condition", 1)] = "=1+1"
                sheet, c = self.open(layout, mode="append", name=f"formula-{layout}.xlsx", prepare=formula)
                self.turn(c, "dress")                                         # (record 1 is still the first free one)
                self.turn(c, "good")                                          # (so this adds to it, but the formula stays)
                snap = sheet.snapshot()
                self.assertEqual(snap[sheet.address("Category", 1)], "Dress")
                self.assertEqual(snap[sheet.address("Condition", 1)], "=1+1")
                self.assertNotIn(sheet.address("Category", 2), snap)

    def test_other_cells_and_other_sheets_are_never_touched(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                sheet, c = self.open(layout, {"Category": 2, "Gender": 1}, name=f"others-{layout}.xlsx")
                wb = openpyxl.load_workbook(sheet.path)
                other = wb.create_sheet("Other")
                other["A1"] = "keep"
                wb.save(sheet.path)
                before = sheet.snapshot()
                self.turn(c, "dress good")
                after = openpyxl.load_workbook(sheet.path)
                self.assertEqual(after["Other"]["A1"].value, "keep")
                self.assertEqual(after["Other"].max_row, 1)
                changed = self.written(sheet, before)
                self.assertEqual(set(changed), {sheet.address("Category", 3), sheet.address("Condition", 3)})
                for coordinate, value in before.items():
                    self.assertEqual(sheet.snapshot().get(coordinate), value, f"{coordinate} changed")


class TestTheListIsNotTheRow(PlacementCase):
    """The field report, again: a word added to a LIST (a Term Helper 'Add') goes to the bottom of that list, on the sheet that holds it. That is
    not a row write: the heard value is also written into the record's own cell, once, in its own record."""

    def make(self, layout):
        folder = self.dir / f"lists-{layout}"
        folder.mkdir()
        path = folder / "book.xlsx"
        wb = openpyxl.Workbook()
        data = wb.active
        data.title = "Stock"
        config = wb.create_sheet("Config")
        config["A1"], config["B1"] = "Category", "Condition"
        for k, value in enumerate(["T-Shirt", "Jacket", "Sweater", "Dress"], start=2):
            config.cell(row=k, column=1, value=value)
        for k, value in enumerate(["New", "Good", "Fair"], start=2):
            config.cell(row=k, column=2, value=value)
        if layout == "columns":
            data["A1"], data["B1"] = "Category", "Condition"
            cells = {"Category": "A2:A200", "Condition": "B2:B200"}
        else:
            data["A1"], data["A2"] = "Category", "Condition"
            cells = {"Category": "B1:Z1", "Condition": "B2:Z2"}
        for heading, sqref in cells.items():
            column = "A" if heading == "Category" else "B"
            rule = DataValidation(type="list", formula1=f"Config!${column}$2:${column}$12")
            data.add_data_validation(rule)
            rule.add(sqref)
        wb.save(path)
        settings = Settings.load(folder / "cfg")
        bridge = XlsxBridge(path)
        settings.set_layout(str(bridge.workbook_path), "Stock", SheetLayout(0, 0, layout == "rows"))
        c = Controller(bridge, settings, on_event=self.events.append)
        c.connect()
        c.handle_transcript("start listening")
        return path, c

    def test_an_added_word_goes_to_its_list_and_into_the_record_once(self):
        from quill.session import Decision
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                path, c = self.make(layout)
                c.handle_transcript("dress wow")
                c.handle_transcript("next row")
                key = next(k for k in c.pending_terms() if "wow" in k[1])
                c.resolve_term(key, Decision.add("Condition"), "Wow")
                wb = openpyxl.load_workbook(path)
                self.assertEqual(wb["Config"]["B5"].value, "Wow", "the list grew at its bottom")
                self.assertEqual(wb["Config"]["A6"].value, None, "no other list was touched")
                data = wb["Stock"]
                cat, cond = ("A2", "B2") if layout == "columns" else ("B1", "B2")
                self.assertEqual((data[cat].value, data[cond].value), ("Dress", "Wow"), "the record has both values, together")
                extra = {(c_.coordinate) for row in data.iter_rows() for c_ in row if c_.value is not None}
                self.assertEqual(extra, {"A1", "B1", "A2", "B2"} if layout == "columns" else {"A1", "A2", "B1", "B2"})


class TestThroughTheWindow(AppCase):
    """The same placements, reached the way a person reaches them: the Append To and Next Row radios in the Turn Options panel and the By Rows /
    By Columns radios in the file settings, then dictation through the real application."""

    def work_on(self, layout, depths=None):
        folder = self.dir / f"ui-{layout}"
        folder.mkdir()
        self.sheet = Sheet(folder, layout, depths)
        self.assertTrue(self.quill.open_workbook_file(self.sheet.path, remember=False))
        self.panel = self.quill.window.panel
        if layout == "rows":
            self.panel.settings.down_radio.click()                       # By Rows
        self.assertEqual(self.quill.controller.vertical, layout == "rows")
        self.hear("start listening")

    def turn(self, *phrases):
        for phrase in phrases:
            self.hear(phrase)
        self.hear("next row")

    def check_append_to_shares_one_record(self, layout):
        self.work_on(layout)
        self.panel.append_radio.click()
        self.assertEqual(self.quill.controller.turn_mode, "append")
        self.turn("dress")
        self.turn("good")
        snap = self.sheet.snapshot()
        self.assertEqual((snap[self.sheet.address("Category", 1)], snap[self.sheet.address("Condition", 1)]), ("Dress", "Good"))
        self.assertNotIn(self.sheet.address("Category", 2), snap)
        self.assertNotIn(self.sheet.address("Condition", 2), snap)

    def check_the_next_button_starts_a_new_record(self, layout):
        self.work_on(layout)
        self.panel.append_radio.click()
        self.turn("dress")
        self.assertTrue(self.panel.new_row_button.isEnabled())
        self.panel.new_row_button.click()
        self.turn("jacket")
        snap = self.sheet.snapshot()
        self.assertEqual((snap[self.sheet.address("Category", 1)], snap[self.sheet.address("Category", 2)]), ("Dress", "Jacket"))

    def check_next_row_again_is_a_record_per_turn(self, layout):
        self.work_on(layout)
        self.panel.append_radio.click()
        self.turn("dress")
        self.panel.next_row_radio.click()
        self.assertEqual(self.quill.controller.turn_mode, "next_row")
        self.assertFalse(self.panel.new_row_button.isEnabled(), "Next is only for Append To")
        self.turn("jacket")
        self.turn("sweater")
        snap = self.sheet.snapshot()
        self.assertEqual([snap[self.sheet.address("Category", k)] for k in (1, 2, 3)], ["Dress", "Jacket", "Sweater"])

    def test_append_to_chosen_in_the_panel_shares_one_record_by_columns(self):
        self.check_append_to_shares_one_record("columns")

    def test_append_to_chosen_in_the_panel_shares_one_record_by_rows(self):
        self.check_append_to_shares_one_record("rows")

    def test_the_next_button_starts_a_new_record_by_columns(self):
        self.check_the_next_button_starts_a_new_record("columns")

    def test_the_next_button_starts_a_new_record_by_rows(self):
        self.check_the_next_button_starts_a_new_record("rows")

    def test_choosing_next_row_again_goes_back_to_a_record_per_turn_by_columns(self):
        self.check_next_row_again_is_a_record_per_turn("columns")

    def test_choosing_next_row_again_goes_back_to_a_record_per_turn_by_rows(self):
        self.check_next_row_again_is_a_record_per_turn("rows")

    def test_by_rows_chosen_in_the_file_settings_writes_a_column_per_turn_with_staggered_headings(self):
        self.work_on("rows", {"Category": 6, "Condition": 4})
        before = self.sheet.snapshot()
        self.turn("dress good")
        got = {k: v for k, v in self.sheet.snapshot().items() if before.get(k) != v}
        self.assertEqual(got, {self.sheet.address("Category", 7): "Dress", self.sheet.address("Condition", 7): "Good"})
        self.assertIn("Column", self.log(), "the log names the column, not a row")

    def test_by_columns_is_the_other_way_and_the_two_never_mix(self):
        self.work_on("columns", {"Category": 6, "Condition": 4})
        before = self.sheet.snapshot()
        self.turn("dress good")
        got = {k: v for k, v in self.sheet.snapshot().items() if before.get(k) != v}
        self.assertEqual(got, {"A10": "Dress", "G10": "Good"})
        self.assertIn("Row 10", self.log())

    def test_append_to_with_by_rows_shares_one_column(self):
        self.work_on("rows", {"Category": 6, "Condition": 4})
        self.panel.append_radio.click()
        self.turn("dress")
        self.turn("good")
        snap = self.sheet.snapshot()
        self.assertEqual((snap[self.sheet.address("Category", 7)], snap[self.sheet.address("Condition", 7)]), ("Dress", "Good"))
        self.assertNotIn(self.sheet.address("Category", 8), snap)


if __name__ == "__main__":
    unittest.main()
