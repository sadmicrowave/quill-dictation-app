"""The mini icons of the Available Files list: by program, by file type, and a plain page with the extension."""

import unittest

from quill.ui.file_icons import kind_for, svg_for


class TestFileIcons(unittest.TestCase):
    def test_the_program_decides_first(self):
        self.assertEqual(kind_for("a.xlsx", "Numbers"), "numbers")
        self.assertEqual(kind_for("a.xlsx", "LibreOffice"), "libreoffice")
        self.assertEqual(kind_for("a.xlsx", "Excel"), "excel")

    def test_then_the_file_type(self):
        self.assertEqual(kind_for("a.XLSX"), "excel")
        self.assertEqual(kind_for("a.csv"), "csv")
        self.assertEqual(kind_for("a.ods"), "libreoffice")

    def test_an_unknown_file_is_a_white_page_with_its_extension(self):
        svg = svg_for("notes.wxyz")
        self.assertIn("WXYZ", svg)
        self.assertIn("#FFFFFF", svg)
        self.assertEqual(kind_for("notes.wxyz"), "")

    def test_a_known_file_is_a_coloured_tile(self):
        self.assertIn("<rect", svg_for("a.csv"))
        self.assertNotIn("<text", svg_for("a.csv"))
