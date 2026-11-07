"""The mini icons of the Available Files list: by program, by file type, and a plain page with the extension."""

import unittest

from quill.ui.file_icons import kind_for, svg_for


class TestFileIcons(unittest.TestCase):
    def test_the_program_showing_the_file_decides_first(self):
        self.assertEqual(kind_for("a.xlsx", "Numbers"), "numbers")
        self.assertEqual(kind_for("a.xlsx", "LibreOffice Calc"), "libreoffice")
        self.assertEqual(kind_for("a.numbers", "Excel"), "excel")

    def test_a_description_is_read_by_the_part_after_open_in(self):
        self.assertEqual(kind_for("a.xlsx", "Excel (.xlsx), open in LibreOffice Calc"), "libreoffice")
        self.assertEqual(kind_for("a.xlsx", "Excel (.xlsx), open in Numbers"), "numbers")
        self.assertEqual(kind_for("a.xlsx", "Excel (.xlsx)"), "excel")
        self.assertEqual(kind_for("a.csv", "CSV file"), "csv")

    def test_the_type_is_used_when_no_program_is_known(self):
        self.assertEqual(kind_for("a.xlsx"), "excel")

    def test_the_program_is_used_when_the_type_is_unknown(self):
        self.assertEqual(kind_for("a.wxyz", "LibreOffice"), "libreoffice")

    def test_then_the_file_type(self):
        self.assertEqual(kind_for("a.XLSX"), "excel")
        self.assertEqual(kind_for("a.csv"), "csv")
        self.assertEqual(kind_for("a.ods"), "libreoffice")

    def test_an_unknown_file_is_a_white_page_with_its_extension(self):
        svg = svg_for("notes.wxyz")
        self.assertIn("WXYZ", svg)
        self.assertIn("#FFFFFF", svg)
        self.assertEqual(kind_for("notes.wxyz"), "")

    def test_csv_text_is_the_same_size_as_the_fallback_text(self):
        import re
        size = lambda svg: re.search(r'font-size="([\d.]+)"', svg).group(1)
        self.assertEqual(size(svg_for("a.csv")), size(svg_for("a.txt")))

    def test_csv_is_a_page_with_its_word_and_libreoffice_a_green_tile(self):
        self.assertIn(">CSV<", svg_for("a.csv"))
        self.assertIn("#1F8F6A", svg_for("a.ods"))
        self.assertNotIn("<text", svg_for("a.xlsx", "LibreOffice Calc"))

    def test_numbers_is_a_tile_with_bars_and_a_line_under_them(self):
        svg = svg_for("a.numbers")
        self.assertIn("#3E8E2F", svg)
        self.assertNotIn("gradient", svg.lower())

    def test_excel_has_no_word_in_it(self):
        self.assertNotIn("<text", svg_for("a.xlsx"))
