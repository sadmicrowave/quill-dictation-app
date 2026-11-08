"""Working in an open LibreOffice document directly: the real helper script and the live link, against pretend documents."""

import datetime as dt
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

from quill.bridge.base import BridgeError
from quill.bridge.filters import ColumnFilter
from quill.bridge.libreoffice_bridge import LibreOfficeBridge, build_workbook
from quill.bridge.libreoffice_mirror import LibreOfficeMirror, file_addresses
from tests.fake_calc import Desktop, Document, fake_uno


class Live(unittest.TestCase):
    """A pretend LibreOffice with one open document, the helper script running in it, and Quill's side connected."""

    def setUp(self):
        env = mock.patch.dict("os.environ", {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        __import__("os").environ.pop("QUILL_NO_HOSTS", None)
        uno = fake_uno()
        uno.__enter__()
        self.addCleanup(uno.__exit__, None, None, None)
        self.base = pathlib.Path(tempfile.mkdtemp())
        (self.base / "user").mkdir()
        self.file = pathlib.Path(tempfile.mkdtemp()) / "Whales.xlsx"
        self.file.write_bytes(b"the file on disk")
        self.lo = Desktop()
        self.doc = Document(file_addresses(self.file)[0], ("Data", "Config"))
        self.lo.documents.append(self.doc)
        self.build_document()
        self.namespace = None
        self.mirror = LibreOfficeMirror(base=self.base, scripts_dir=self.base / "scripts", running=lambda: True,
                                        soffice="/x/soffice", wait_s=3, runner=self.run_soffice, live_retry_s=0)
        self.addCleanup(self.stop)

    def build_document(self):
        data, config = self.doc.sheet("Data"), self.doc.sheet("Config")
        for col, heading in enumerate(["Species", "Count", "Seen", "Region", "Notes"], 1):
            data.put(1, col, heading)
        data.put(2, 1, "Gray"), data.put(2, 2, 3), data.put(2, 3, ("date", 45000)), data.put(2, 4, "North")
        data.validate(2, 1, "LIST", '"Gray";"Blue";"Orca"')                       # a typed list
        data.validate(2, 4, "LIST", "$Config.$B$2:$B$9")                           # a list in a range
        config.put(1, 1, "Boat_list"), config.put(1, 2, "Region_list")
        for row, boat in enumerate(["Aurora", "Pearl"], 2):
            config.put(row, 1, boat)
        for row, region in enumerate(["North", "South", "East"], 2):
            config.put(row, 2, region)

    def run_soffice(self, args):
        entry = args[-1].split("$", 1)[1].split("?", 1)[0]
        if self.namespace is None:
            text = self.mirror.script_text().replace("WATCH_S = 0.3", "WATCH_S = 0.02").replace("QUIET_S = 0.8", "QUIET_S = 0.05")
            self.namespace = {"XSCRIPTCONTEXT": self.lo, "__name__": "quill_mirror"}
            exec(compile(text, "quill_mirror.py", "exec"), self.namespace)
        self.namespace[entry]()
        return 0

    def stop(self):
        if self.mirror._live:
            self.mirror._live.close()
        server = getattr(sys, "_quill_live", None)
        if server is not None:
            server.stop()
            del sys._quill_live

    def bridge(self):
        self.assertTrue(self.mirror.has_document(self.file))                 # (brings the link up)
        bridge = LibreOfficeBridge(self.file, lambda: self.mirror.live_link)
        bridge.connect()
        return bridge

    def wait_for(self, condition, seconds=3.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if condition():
                return True
            time.sleep(0.01)
        return condition()


class TestStructureFromTheOpenDocument(Live):
    def test_the_lists_come_from_the_document_as_it_is_now(self):
        lists = self.bridge().get_lists()
        self.assertEqual(lists["Species"], ["Gray", "Blue", "Orca"])           # typed in the rule
        self.assertEqual(lists["Region"], ["North", "South", "East"])          # a range on another sheet
        self.assertEqual(lists["Boat"], ["Aurora", "Pearl"])                   # a Config sheet's *_list column

    def test_a_list_added_after_connecting_is_seen_on_refresh_without_any_save(self):
        bridge = self.bridge()
        self.doc.sheet("Data").validate(2, 3, "LIST", '"a";"b"')
        self.doc.sheet("Data").put(1, 3, "Seen")
        bridge.refresh()
        self.assertEqual(bridge.get_lists()["Seen"], ["a", "b"])
        self.assertEqual(self.file.read_bytes(), b"the file on disk")          # the file was never touched

    def test_a_sheet_that_is_not_saved_yet_is_known_at_once(self):
        bridge = self.bridge()
        june = self.doc.sheets.insert("June")
        for col, heading in enumerate(["Species", "Count"], 1):
            june.put(1, col, heading)
        self.doc.active = "June"
        self.assertTrue(self.wait_for(lambda: "June" in bridge.sheet_names()))
        self.assertTrue(self.wait_for(lambda: bridge.active_sheet_name() == "June"))
        self.assertEqual(bridge.get_headers("June"), ["Species", "Count"])

    def test_the_snapshot_builds_a_workbook_the_normal_discovery_can_read(self):
        wb = build_workbook({"sheets": [{"name": "S", "used_rows": 3, "used_cols": 2, "block": [["A", "B"], [None, None]],
                                         "validations": [{"row": 2, "col": 1, "formula": '"x,y"'}]}], "names": []})
        self.assertEqual(wb["S"].max_row, 3)
        self.assertEqual(wb["S"].data_validations.dataValidation[0].formula1, '"x,y"')


class TestWritingToTheOpenDocument(Live):
    def test_a_row_goes_into_the_document_not_the_file_and_stays_unsaved(self):
        bridge = self.bridge()
        row = bridge.append_row("Data", {"Species": "Orca", "Count": 4})
        data = self.doc.sheet("Data")
        self.assertEqual(row, 3)
        self.assertEqual((data.cell(0, 2).data, data.cell(1, 2).data), ("Orca", 4.0))
        self.assertEqual(self.doc.saved, 0)                                      # LibreOffice was not saved either: the user saves
        self.assertEqual(self.file.read_bytes(), b"the file on disk")
        self.assertEqual(bridge.take_changes(), [])                              # nothing is shown twice
        self.assertFalse(bridge.dirty)

    def test_a_date_is_a_date_and_several_values_in_one_cell_wrap(self):
        bridge = self.bridge()
        bridge.append_row("Data", {"Species": "Blue", "Seen": dt.date(2026, 11, 8), "Notes": "calf\nadult"})
        data = self.doc.sheet("Data")
        self.assertEqual(data.cell(2, 2).data, float((dt.date(2026, 11, 8) - dt.date(1899, 12, 30)).days))
        self.assertEqual(data.cell(2, 2).NumberFormat, 36)
        self.assertTrue(data.cell(4, 2).IsTextWrapped)

    def test_a_date_column_is_recognised_from_the_documents_own_formats(self):
        self.assertIn("Seen", self.bridge().date_columns("Data"))
        self.assertIn("Count", self.bridge().numeric_columns("Data"))

    def test_a_cell_can_be_set_and_cleared_for_undo(self):
        bridge = self.bridge()
        row = bridge.append_row("Data", {"Species": "Gray"})
        self.assertTrue(bridge.set_value("Data", row, "Notes", "second look"))
        self.assertEqual(self.doc.sheet("Data").cell(4, 2).data, "second look")
        self.assertTrue(bridge.clear_value("Data", row, "Notes", "second look"))
        self.assertEqual(self.doc.sheet("Data").cell(4, 2).data, "")

    def test_a_value_is_added_to_a_list_in_a_range_by_writing_the_cell(self):
        bridge = self.bridge()
        bridge.add_to_list("Region", "West")
        self.assertEqual(self.doc.sheet("Config").cell(1, 4).data, "West")
        self.assertIn("West", bridge.get_lists()["Region"])

    def test_a_value_is_added_to_a_typed_list_in_the_rule_itself_and_again(self):
        bridge = self.bridge()
        bridge.add_to_list("Species", "Humpback")
        self.assertEqual(self.doc.sheet("Data").cell(0, 1).Validation.getFormula1(), '"Gray";"Blue";"Orca";"Humpback"')
        self.assertEqual(bridge.get_lists()["Species"], ["Gray", "Blue", "Orca", "Humpback"])
        bridge.add_to_list("Species", "Minke")
        self.assertEqual(bridge.get_lists()["Species"][-1], "Minke")
        with self.assertRaises(BridgeError):
            bridge.add_to_list("Species", "A, B")                                # a comma would split the item

    def test_a_search_hides_the_rows_that_do_not_match_and_clearing_shows_them(self):
        bridge = self.bridge()
        for species, count in (("Gray", 1), ("Blue", 9), ("Gray", 5)):
            bridge.append_row("Data", {"Species": species, "Count": count})
        shown = bridge.apply_filters("Data", [ColumnFilter("Species", values=["Gray"])])
        data = self.doc.sheet("Data")
        hidden = [r for r in range(1, 8) if not data.getRows().getByIndex(r).IsVisible]
        self.assertEqual(shown, 3)                                               # the row that was already there + two new ones
        self.assertEqual(hidden, [3])                                            # only the Blue row (row 4, zero-based 3)
        self.assertTrue(bridge.clear_filters("Data"))
        self.assertTrue(all(data.getRows().getByIndex(r).IsVisible for r in range(8)))


class TestTheLinkComingAndGoing(Live):
    def test_an_edit_in_libreoffice_is_reported_once_it_is_quiet(self):
        told = []
        self.mirror.on_event = lambda *a: told.append(a)
        self.assertTrue(self.mirror.has_document(self.file))
        for _ in range(5):
            self.doc.edit()                                                      # typing: many edits
        self.assertTrue(self.wait_for(lambda: any(t[0] == "changed" for t in told)))
        time.sleep(0.2)
        self.assertEqual([t[0] for t in told].count("changed"), 1)               # told once, not at every keystroke

    def test_quills_own_writes_are_not_news_but_the_next_edit_by_the_user_is(self):
        told = []
        self.mirror.on_event = lambda *a: told.append(a)
        bridge = self.bridge()
        bridge.append_row("Data", {"Species": "Orca", "Count": 4})
        self.doc.edit()                                                          # LibreOffice reports Quill's own write
        time.sleep(0.4)
        self.assertFalse(any(t[0] == "changed" for t in told))
        time.sleep(1.0)                                                          # ... later the user types
        self.doc.edit()
        self.assertTrue(self.wait_for(lambda: any(t[0] == "changed" for t in told)))

    def test_a_closed_document_is_an_error_not_a_guess(self):
        bridge = self.bridge()
        self.lo.documents.remove(self.doc)
        self.assertTrue(self.wait_for(lambda: not self.mirror.live_link.find(file_addresses(self.file))))
        with self.assertRaises(BridgeError):
            bridge.active_sheet_name()

    def test_without_the_link_there_is_a_sentence_not_a_crash(self):
        bridge = self.bridge()
        self.mirror._live.close()
        with self.assertRaises(BridgeError) as caught:
            bridge.append_row("Data", {"Species": "Gray"})
        self.assertIn("not answering", str(caught.exception))

    def test_connecting_needs_the_document_to_be_open(self):
        self.assertTrue(self.mirror.has_document(self.file))
        other = LibreOfficeBridge(self.file.with_name("Other.xlsx"), lambda: self.mirror.live_link)
        with self.assertRaises(BridgeError):
            other.connect()


if __name__ == "__main__":
    unittest.main()
