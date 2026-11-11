"""The files a Windows user brings: what Excel on Windows writes, and the names Windows allows (these run on every system, bar the last
class, which needs a real Windows).

Excel on Windows saves a plain "CSV (Comma delimited)" in the PC's ANSI code page (cp1252 in Western Europe and the Americas), with
CRLF line ends and no byte-order mark, and "CSV UTF-8" with the mark. Quill must give the file back in the encoding it came in, or the
user's own Excel shows ``cafÃ©`` the next time it opens it.
"""
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import openpyxl

from quill.bridge.csv_bridge import CsvBridge
from quill.bridge.xlsx_bridge import XlsxBridge


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)

    def csv(self, raw: bytes, name="plants.csv"):
        path = self.dir / name
        path.write_bytes(raw)
        bridge = CsvBridge(path)
        bridge.connect()
        return path, bridge


class TestCsvFromExcelOnWindows(Case):
    ANSI = b"Item,Price\r\nCaf\xe9,\x80 5\r\nIt\x92s,\x931\x94\r\n"          # é, the euro sign, a curly apostrophe and curly quotes

    def test_an_ansi_file_is_read_as_cp1252_not_as_latin_1(self):
        _, bridge = self.csv(self.ANSI)
        sheet = bridge._wb["plants"]
        self.assertEqual([[c.value for c in row] for row in sheet.iter_rows(min_row=2)], [["Café", "€ 5"], ["It’s", "“1”"]])

    def test_an_ansi_file_comes_back_in_ansi_with_its_line_ends(self):
        path, bridge = self.csv(self.ANSI)
        bridge.append_row("plants", {"Item": "Naïve"})
        self.assertEqual(path.read_bytes(), self.ANSI + b"Na\xefve,\r\n")

    def test_a_word_ansi_has_no_letter_for_moves_the_file_to_utf8_with_its_mark(self):
        path, bridge = self.csv(self.ANSI)
        bridge.append_row("plants", {"Item": "日本"})
        raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))                              # the mark tells Excel it is UTF-8
        text = raw.decode("utf-8-sig")
        self.assertEqual(text, "Item,Price\r\nCafé,€ 5\r\nIt’s,“1”\r\n日本,\r\n")
        bridge.append_row("plants", {"Item": "Aloe"})                                 # (and stays UTF-8 from then on)
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_a_utf8_file_with_a_mark_keeps_the_mark_and_without_keeps_none(self):
        marked, bridge = self.csv(b"\xef\xbb\xbfItem,Price\r\nCaf\xc3\xa9,5\r\n", "marked.csv")
        bridge.append_row("marked", {"Item": "Aloe"})
        self.assertEqual(marked.read_bytes(), b"\xef\xbb\xbfItem,Price\r\nCaf\xc3\xa9,5\r\nAloe,\r\n")
        bare, bridge = self.csv(b"Item,Price\r\nCaf\xc3\xa9,5\r\n", "bare.csv")
        bridge.append_row("bare", {"Item": "Aloe"})
        self.assertEqual(bare.read_bytes(), b"Item,Price\r\nCaf\xc3\xa9,5\r\nAloe,\r\n")

    def test_a_file_with_bytes_cp1252_leaves_unused_is_still_opened_and_kept(self):
        path, bridge = self.csv(b"Item\r\nA\x81B\r\n")                                 # (0x81 has no cp1252 letter; latin-1 does)
        bridge.append_row("plants", {"Item": "Aloe"})
        self.assertEqual(path.read_bytes(), b"Item\r\nA\x81B\r\nAloe\r\n")

    def test_a_semicolon_file_from_a_european_excel_keeps_its_delimiter_and_encoding(self):
        raw = b"Artikel;Preis\r\nK\xe4se;1,50\r\n"                                    # (Excel with a German region: ";" and ANSI)
        path, bridge = self.csv(raw, "preise.csv")
        bridge.append_row("preise", {"Artikel": "Brötchen"})
        self.assertEqual(path.read_bytes(), raw + b"Br\xf6tchen;\r\n")


class TestNamesWindowsAllows(Case):
    """Spaces, accents, dashes and punctuation in the folder and the file name; a path made of many levels."""

    NAMES = ["Stock list & more (1).xlsx", "Bilan été – août 2026.xlsx", "it's mine; really.xlsx", "100% $ ^ ~ # @ ! [x].xlsx", "日本語.xlsx"]

    def test_a_workbook_is_filled_and_read_back_under_every_name(self):
        folder = self.dir / "Mes classeurs" / "été 2026 (copie)"
        folder.mkdir(parents=True)
        for name in self.NAMES:
            with self.subTest(name=name):
                path = folder / name
                book = openpyxl.Workbook()
                book.active.title = "Stock"
                book.active.append(["Item", "Qty"])
                book.save(path)
                bridge = XlsxBridge(path)
                bridge.connect()
                bridge.append_row("Stock", {"Item": "Rosé", "Qty": 4})
                self.assertEqual(list(openpyxl.load_workbook(path)["Stock"].values), [("Item", "Qty"), ("Rosé", 4)])
                self.assertEqual(sorted(p.name for p in folder.iterdir() if p.name != name and p.suffix == ".tmp"), [])

    def test_a_csv_is_filled_under_every_name(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                path = self.dir / name.replace(".xlsx", ".csv")
                path.write_bytes(b"Item,Qty\r\n")
                bridge = CsvBridge(path)
                bridge.connect()
                bridge.append_row(bridge._sheet, {"Item": "Rosé", "Qty": 4})          # (the sheet is named after the file, minus marks a sheet name may not hold)
                self.assertEqual(path.read_bytes(), "Item,Qty\r\nRosé,4\r\n".encode())

    def test_a_deep_folder_path(self):
        folder = self.dir.joinpath(*[f"level {n} with a long folder name" for n in range(1, 8)])
        folder.mkdir(parents=True)
        path = folder / "Stock.xlsx"
        book = openpyxl.Workbook()
        book.active.append(["Item"])
        book.save(path)
        bridge = XlsxBridge(path)
        bridge.connect()
        bridge.append_row(book.active.title, {"Item": "Palm"})
        self.assertEqual(list(openpyxl.load_workbook(path).active.values), [("Item",), ("Palm",)])


@unittest.skipUnless(sys.platform == "win32", "the wording of Windows paths")
class TestWindowsPathsInTheWindow(unittest.TestCase):
    """Windows counterparts of the tray tests that the Mac wording (``/``) made skip on Windows."""

    def test_the_folder_shown_for_a_workbook(self):
        from quill.ui.tray import folder_for_display
        self.assertEqual(folder_for_display(r"C:\data\Inventory\plants.xlsx"), r"C:\data\Inventory")

    def test_the_home_folder_is_shown_as_a_tilde(self):
        from quill.ui.tray import folder_for_display
        home = str(pathlib.Path.home())
        self.assertEqual(folder_for_display(home + r"\Docs\a.xlsx"), "~" + r"\Docs")


@unittest.skipUnless(sys.platform == "win32", "asks a real Windows")
class TestWindowsPlaces(unittest.TestCase):
    def test_libreoffice_is_told_a_file_the_way_it_names_it(self):
        from quill.bridge.libreoffice_mirror import file_addresses
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "Stock list & more.xlsx"
            path.write_bytes(b"")
            found = file_addresses(path)
        self.assertTrue(found)
        for uri in found:
            self.assertTrue(uri.startswith("file:///"), uri)
            self.assertRegex(uri, r"^file:///[A-Za-z]:/")                                  # a drive, and slashes forward
            self.assertNotIn("\\", uri)
            self.assertIn("Stock%20list%20%26%20more.xlsx", uri)

    def test_a_network_share_is_named_with_two_slashes(self):
        uri = pathlib.PureWindowsPath(r"\\fileserver\team\Stock.xlsx").as_uri()
        self.assertEqual(uri, "file://fileserver/team/Stock.xlsx")

    def test_quills_working_folders_are_inside_the_users_profile(self):
        """Windows keeps ``live.json`` (the secret of the LibreOffice link) private with the folder's access list, not with file modes:
        so the folder must be under the user's own profile, where only that user and administrators may read."""
        from quill.bridge.libreoffice_mirror import _app_data_dir
        from quill.config.settings import _config_dir
        profile = pathlib.Path(os.environ["USERPROFILE"]).resolve()
        for folder in (_app_data_dir(), _config_dir()):
            self.assertTrue(profile in pathlib.Path(folder).resolve().parents, f"{folder} is outside {profile}")
