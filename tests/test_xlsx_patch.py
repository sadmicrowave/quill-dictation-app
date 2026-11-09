"""Quill writes into an .xlsx by patching the package, so what it did not touch stays exactly as it was."""
import datetime as dt
import pathlib
import re
import tempfile
import unittest
import zipfile

import openpyxl

from quill.bridge.xlsx_bridge import XlsxBridge
from quill.bridge.xlsx_patch import UnsupportedError, patch_package
from tests.fixtures import make_workbook


def with_stored_results(path: pathlib.Path) -> None:
    """Give every formula cell the stored result a spreadsheet program would have saved (openpyxl cannot)."""
    with zipfile.ZipFile(path) as package:
        parts = {i.filename: package.read(i) for i in package.infolist()}
    for name, data in parts.items():
        if name.startswith("xl/worksheets/sheet"):
            text = data.decode()
            text = re.sub(r"(<c r=\"[A-Z]+(\d+)\"[^>]*><f>[^<]*</f>)<v\s*/>|(<c r=\"[A-Z]+(\d+)\"[^>]*><f>[^<]*</f>)<v></v>",
                          lambda m: f"{m.group(1) or m.group(3)}<v>{(m.group(2) or m.group(4))}00</v>", text)
            parts[name] = text.encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in parts.items():
            out.writestr(name, data)


def stored(path: pathlib.Path, sheet: str, ref: str):
    return openpyxl.load_workbook(path, data_only=True)[sheet][ref].value


class PatchCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = make_workbook(pathlib.Path(self._tmp.name) / "plants.xlsx")
        with_stored_results(self.path)
        self.bridge = XlsxBridge(self.path)
        self.bridge.connect()

    def tearDown(self):
        self._tmp.cleanup()

    def parts(self) -> dict[str, bytes]:
        with zipfile.ZipFile(self.path) as package:
            return {i.filename: package.read(i) for i in package.infolist()}


class TestStoredResultsSurvive(PatchCase):
    def test_fixture_has_stored_results(self):
        self.assertIsNotNone(stored(self.path, "Inventory", "H4"))

    def test_written_row_keeps_every_stored_formula_result(self):
        before = stored(self.path, "Inventory", "H4")
        self.bridge.append_row("Inventory", {"Species": "Fern"})
        self.assertEqual(stored(self.path, "Inventory", "H4"), before)
        self.assertEqual(openpyxl.load_workbook(self.path)["Inventory"]["A4"].value, "Fern")

    def test_formulas_are_still_formulas(self):
        self.bridge.append_row("Inventory", {"Species": "Fern"})
        self.assertTrue(str(openpyxl.load_workbook(self.path)["Inventory"]["H4"].value).startswith("="))

    def test_parts_that_were_not_touched_are_byte_identical(self):
        before = self.parts()
        self.bridge.append_row("Inventory", {"Species": "Fern"})
        after = self.parts()
        self.assertEqual(list(before), list(after))
        changed = {name for name in before if before[name] != after[name]}
        self.assertEqual(changed, {"xl/worksheets/sheet1.xml"})

    def test_other_cells_of_the_sheet_are_unchanged(self):
        before = self.parts()["xl/worksheets/sheet1.xml"].decode()
        self.bridge.append_row("Inventory", {"Species": "Fern"})
        after = self.parts()["xl/worksheets/sheet1.xml"].decode()
        cells = lambda xml: {m.group(1): m.group(0) for m in re.finditer(r'<c r="([A-Z]+\d+)"[^>]*?(?:/>|>.*?</c>)', xml, re.S)}
        was, now = cells(before), cells(after)
        self.assertEqual({k: v for k, v in now.items() if k != "A4"}, {k: v for k, v in was.items() if k != "A4"})

    def test_no_temporary_file_is_left(self):
        self.bridge.append_row("Inventory", {"Species": "Fern"})
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["plants.xlsx"])


class TestWhatIsWritten(PatchCase):
    def reread(self):
        return openpyxl.load_workbook(self.path)["Inventory"]

    def test_text_number_and_bool(self):
        grid = self.bridge._grid
        grid.write("Inventory", 4, 1, "Fern & <b> \"x\"")
        grid.write("Inventory", 4, 5, 12.5)
        grid.write("Inventory", 4, 9, 7)
        grid.write("Inventory", 4, 10, True)
        self.bridge._after_write()
        ws = self.reread()
        self.assertEqual((ws["A4"].value, ws["E4"].value, ws["I4"].value, ws["J4"].value), ('Fern & <b> "x"', 12.5, 7, True))

    def test_text_with_spaces_and_lines(self):
        self.bridge._grid.write("Inventory", 4, 1, "  one\ntwo  ")
        self.bridge._after_write()
        cell = self.reread()["A4"]
        self.assertEqual(cell.value, "  one\ntwo  ")
        self.assertTrue(cell.alignment.wrap_text)

    def test_clearing_a_cell(self):
        self.bridge._grid.write("Inventory", 2, 1, "Hello")
        self.bridge._after_write()
        self.bridge._grid.write("Inventory", 2, 1, None)
        self.bridge._after_write()
        self.assertIsNone(self.reread()["A2"].value)

    def test_date_gets_a_date_format(self):
        self.bridge.append_row("Inventory", {"Acquired": dt.date(2026, 10, 30)})
        cell = self.reread()["F4"]
        self.assertEqual(cell.value.date(), dt.date(2026, 10, 30))
        self.assertTrue(cell.is_date)

    def test_new_row_far_below_and_a_new_column(self):
        self.bridge._grid.write("Inventory", 40, 1, "Low")
        self.bridge._grid.write("Inventory", 4, 30, "Wide")
        self.bridge._after_write()
        ws = self.reread()
        self.assertEqual((ws["A40"].value, ws["AD4"].value), ("Low", "Wide"))
        self.assertIn("AD40", ws.dimensions)

    def test_writing_again_after_a_save(self):
        self.bridge._grid.write("Inventory", 4, 1, "One")
        self.bridge._after_write()
        self.bridge._grid.write("Inventory", 4, 1, "Two")
        self.bridge._grid.write("Inventory", 5, 1, "Three")
        self.bridge._after_write()
        ws = self.reread()
        self.assertEqual((ws["A4"].value, ws["A5"].value), ("Two", "Three"))
        self.assertEqual(stored(self.path, "Inventory", "H4"), 400)

    def test_inline_list_extended(self):
        wb = openpyxl.load_workbook(self.path)
        inline = [dv for ws in wb.worksheets for dv in ws.data_validations.dataValidation
                  if dv.type == "list" and dv.formula1.startswith('"')]
        self.assertTrue(inline, "the fixture has an inline list")
        column = next(c for c, s in self.bridge._discovery.sources.items() if s.is_inline)
        self.bridge.add_to_list(column, "Quite New")
        wb = openpyxl.load_workbook(self.path)
        formulas = [dv.formula1 for ws in wb.worksheets for dv in ws.data_validations.dataValidation]
        self.assertTrue(any("Quite New" in f for f in formulas))
        self.assertEqual(stored(self.path, "Inventory", "H4"), 400)


class TestFallsBackToAFullSave(PatchCase):
    def test_replacing_a_formula_cell(self):
        self.bridge._grid.write("Inventory", 4, 8, "typed over")
        self.bridge._after_write()
        self.assertEqual(openpyxl.load_workbook(self.path)["Inventory"]["H4"].value, "typed over")

    def test_writing_a_formula(self):
        self.bridge._grid.write("Inventory", 4, 1, "=1+1")
        self.bridge._after_write()
        self.assertEqual(openpyxl.load_workbook(self.path)["Inventory"]["A4"].value, "=1+1")

    def test_a_filter_is_saved_whole(self):
        from quill.bridge.filters import ColumnFilter
        self.bridge._grid.set_autofilter("Inventory", 1, 1, 3, 3, {1: ColumnFilter(column="Species", values=("zzz",))})
        self.bridge._after_write()
        self.assertTrue(openpyxl.load_workbook(self.path)["Inventory"].auto_filter.ref)
        self.assertFalse(self.bridge._grid.restructured)

    def test_patch_package_refuses_when_nothing_to_do(self):
        with self.assertRaises(UnsupportedError):
            patch_package(self.path, self.path, self.bridge._wb, [])

    def test_a_package_that_is_not_a_zip(self):
        bad = self.path.with_name("bad.xlsx")
        bad.write_bytes(b"not a zip")
        with self.assertRaises(UnsupportedError):
            patch_package(bad, bad, self.bridge._wb, [("Inventory", 4, 1)])


class TestStyleTable(unittest.TestCase):
    """Style tables as other programs write them (LibreOffice spells out ``wrapText="false"``)."""

    XML = ('<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="0"/>'
           '<cellXfs count="2"><xf numFmtId="0" fontId="0"/>'
           '<xf numFmtId="0" fontId="1" applyAlignment="false"><alignment horizontal="left" wrapText="false"/>'
           '<protection locked="true"/></xf></cellXfs></styleSheet>')

    def test_wrap_replaces_an_existing_false(self):
        from quill.bridge.xlsx_patch import _Styles
        from defusedxml import ElementTree
        styles = _Styles(self.XML)
        index = styles.derive(1, wrap=True, number_format=None)
        xml = styles.render()
        ElementTree.fromstring(xml)                                    # no duplicate attribute
        self.assertEqual(index, 2)
        self.assertEqual(xml.count("wrapText"), 2)
        self.assertIn('horizontal="left" wrapText="1"/><protection', xml)
        self.assertIn('cellXfs count="3"', xml)

    def test_same_request_gives_the_same_index(self):
        from quill.bridge.xlsx_patch import _Styles
        styles = _Styles(self.XML)
        self.assertEqual(styles.derive(0, True, None), styles.derive(0, True, None))
        self.assertEqual(styles.derive(0, False, None), 0)

    def test_new_number_format_is_declared_once(self):
        from quill.bridge.xlsx_patch import _Styles
        styles = _Styles(self.XML)
        a = styles.derive(0, False, "dd/mm/yyyy")
        b = styles.derive(1, False, "dd/mm/yyyy")
        xml = styles.render()
        self.assertEqual(xml.count('formatCode="dd/mm/yyyy"'), 1)
        self.assertIn('<numFmts count="1">', xml)
        self.assertNotEqual(a, b)


class TestSafety(PatchCase):
    def test_a_locked_file_keeps_the_original_and_the_pending_change(self):
        from unittest import mock
        from quill.bridge.base import BridgeLockedError
        original = self.path.read_bytes()
        self.bridge._grid.write("Inventory", 4, 1, "Fern")
        with mock.patch("quill.bridge.xlsx_patch._overwrite", side_effect=PermissionError(13, "in use")):
            with self.assertRaises(BridgeLockedError):
                self.bridge._after_write()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["plants.xlsx"])
        self.assertTrue(self.bridge.dirty)
        self.assertTrue(self.bridge.flush())
        self.assertEqual(openpyxl.load_workbook(self.path)["Inventory"]["A4"].value, "Fern")

    def test_the_file_stays_the_same_file(self):
        before = self.path.stat()
        self.bridge._grid.write("Inventory", 4, 1, "Fern")
        self.bridge._after_write()
        after = self.path.stat()
        self.assertEqual((after.st_ino, after.st_dev), (before.st_ino, before.st_dev))
        self.assertEqual(openpyxl.load_workbook(self.path)["Inventory"]["A4"].value, "Fern")

    def test_a_write_that_fails_part_way_puts_the_original_back(self):
        from unittest import mock
        from quill.bridge.base import BridgeLockedError
        original = self.path.read_bytes()
        self.bridge._grid.write("Inventory", 4, 1, "Fern")
        with mock.patch("quill.bridge.xlsx_patch.os.fsync", side_effect=OSError(28, "No space left")):
            with self.assertRaises(BridgeLockedError):             # (any failed write is kept and retried)
                self.bridge._after_write()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(self.bridge.dirty)

    def test_a_copy_has_the_changes_and_the_original_does_not(self):
        self.bridge._grid.write("Inventory", 4, 1, "Fern")
        copy = pathlib.Path(self.bridge.save_copy())
        self.assertEqual(openpyxl.load_workbook(copy)["Inventory"]["A4"].value, "Fern")
        self.assertIsNone(openpyxl.load_workbook(self.path)["Inventory"]["A4"].value)
        self.assertEqual(stored(copy, "Inventory", "H4"), 400)

    def test_control_characters_never_reach_the_xml(self):
        self.bridge._grid.write("Inventory", 4, 1, "ok")
        self.bridge._after_write()
        xml = self.parts()["xl/worksheets/sheet1.xml"].decode()
        self.assertIsNone(re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", xml))

    def test_markup_in_text_stays_text(self):
        hostile = '</t></is></c><c r="Z9"><f>HYPERLINK("x")</f></c>'
        self.bridge._grid.write("Inventory", 4, 1, hostile)
        self.bridge._after_write()
        ws = openpyxl.load_workbook(self.path)["Inventory"]
        self.assertEqual(ws["A4"].value, hostile)
        self.assertIsNone(ws["Z9"].value)


if __name__ == "__main__":
    unittest.main()
