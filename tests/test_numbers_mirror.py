"""Live editing in Numbers: the cells Quill writes are also shown in the open Numbers document."""
import datetime as dt
import os
import pathlib
import sys
import tempfile
import unittest
import unittest.mock
from unittest import mock

import openpyxl
from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.csv_bridge import CsvBridge
from quill.bridge.grid import MAX_CHANGES, OpenpyxlGrid
from quill.platforms.macos.numbers_mirror import FIELD, SCRIPT, MirrorResult, NumbersMirror, cell_argument
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from tests.fixtures import make_workbook
from tests.test_app import FakeListener, FakeSpeaker
from tests.test_open_file import DeadExcel
from tests.test_side_panel_and_turns import FakeHosts, make_vertical

_app = QApplication.instance() or QApplication([])


class FakeRun:
    def __init__(self, code=0, out="ok", err=""):
        self.calls, self.reply = [], (code, out, err)

    def __call__(self, args):
        self.calls.append(args)
        return self.reply


def mirror_with(code=0, out="ok", err=""):
    run = FakeRun(code, out, err)
    return NumbersMirror(run), run


class Env(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        os.environ.pop("QUILL_NO_HOSTS", None)                       # these tests ask the (fake) system
        self.addCleanup(patcher.stop)


class TestCellArguments(unittest.TestCase):
    def test_each_kind_of_value(self):
        parts = lambda v: cell_argument("Inventory", 4, 2, v).split(FIELD)
        self.assertEqual(parts("Fern"), ["Inventory", "4", "2", "s", "Fern"])
        self.assertEqual(parts(12)[3:], ["n", "12"])
        self.assertEqual(parts(19.99)[3:], ["n", "19.99"])
        self.assertEqual(parts(-4.5)[3:], ["n", "-4.5"])
        self.assertEqual(parts(3.0)[3:], ["n", "3"])
        self.assertEqual(parts(dt.date(2026, 3, 5))[3:], ["d", "2026-03-05"])
        self.assertEqual(parts(dt.datetime(2026, 3, 5, 9, 30))[3:], ["d", "2026-03-05"])
        self.assertEqual(parts(None)[3:], ["e", ""])
        self.assertEqual(parts("")[3:], ["e", ""])
        self.assertEqual(parts("two\nlines")[4], "two\nlines")                 # a cell with sub-rows keeps its line breaks

    def test_a_number_is_plain_decimal_never_exponent_notation(self):
        self.assertEqual(cell_argument("S", 1, 1, 0.00001).split(FIELD)[4], "0.00001")
        self.assertEqual(cell_argument("S", 1, 1, 1e-12).split(FIELD)[4], "0.000000000001")

    def test_the_separator_can_never_appear_inside_a_field(self):
        argument = cell_argument(f"Sh{FIELD}eet", 1, 1, f"a{FIELD}b")
        self.assertEqual(len(argument.split(FIELD)), 5)


class TestPushing(Env):
    def test_the_script_and_the_document_name_come_first_and_every_cell_is_its_own_argument(self):
        mirror, run = mirror_with()
        result = mirror.push("/x/My Plants.xlsx", [("Inventory", 4, 1, "Fern"), ("Inventory", 4, 2, "Small")])
        self.assertTrue(result.ok)
        args = run.calls[0]
        self.assertEqual(args[:3], ["osascript", "-e", SCRIPT])
        self.assertEqual(args[3], "My Plants")                            # the name Numbers gives an imported file
        self.assertEqual(len(args), 6)

    def test_values_are_never_part_of_the_script_text(self):
        mirror, run = mirror_with()
        hostile = 'x" & (do shell script "rm -rf ~") & "'
        mirror.push("/x/a.xlsx", [("Sheet", 1, 1, hostile)])
        self.assertNotIn("rm -rf", run.calls[0][2])
        self.assertIn(hostile, run.calls[0][-1])                           # it travels as a plain argument

    def test_nothing_to_show_asks_nothing(self):
        mirror, run = mirror_with()
        self.assertTrue(mirror.push("/x/a.xlsx", []).ok)
        self.assertEqual(run.calls, [])

    def test_results(self):
        cases = [((0, "ok", ""), True, "ok"), ((0, "notrunning\n", ""), False, "notrunning"),
                 ((0, "nodoc\n", ""), False, "nodoc"),
                 ((1, "", "execution error: Not authorized to send Apple events to Numbers. (-1743)"), False, "denied"),
                 ((1, "", "execution error: something else (-1728)"), False, "error")]
        for reply, ok, reason in cases:
            mirror, _ = mirror_with(*reply)
            result = mirror.push("/x/a.xlsx", [("S", 1, 1, "v")])
            self.assertEqual((result.ok, result.reason), (ok, reason), reply)

    def test_the_system_is_not_asked_when_hosts_are_switched_off(self):
        os.environ["QUILL_NO_HOSTS"] = "1"
        mirror, run = mirror_with()
        self.assertEqual(mirror.push("/x/a.xlsx", [("S", 1, 1, "v")]).reason, "disabled")
        self.assertEqual(run.calls, [])

    def test_the_document_is_found_by_name_with_or_without_the_numbers_extension(self):
        self.assertEqual(NumbersMirror.document_name("/a/b/Apparel Inventory.xlsx"), "Apparel Inventory")
        self.assertIn('n starts with (docName & ".")', SCRIPT.replace("docTitle", "n"))

    def test_the_script_never_starts_numbers_and_avoids_its_reserved_words(self):
        self.assertTrue(SCRIPT.index('application "Numbers" is not running') < SCRIPT.index('tell application "Numbers"'))
        import re
        for word in ("kind", "value", "name", "row", "column", "text", "date", "table"):
            self.assertIsNone(re.search(rf"\bset {word} to\b", SCRIPT), word)          # (a variable by that name breaks inside the tell)

    def test_text_items_are_split_outside_the_tell_block(self):
        self.assertIn("on splitFields", SCRIPT)
        tell = SCRIPT[SCRIPT.index('tell application "Numbers"'): SCRIPT.index("on splitFields")]
        self.assertNotIn("text items", tell)


class TestWrittenCellsAreRemembered(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_row_is_recorded_cell_by_cell_in_sheet_coordinates_then_forgotten(self):
        bridge = XlsxBridge(make_workbook(self.dir / "p.xlsx"))
        bridge.connect()
        row = bridge.append_row("Inventory", {"Species": "Fern", "Pot Size": "Small"})
        changes = bridge.take_changes()
        self.assertEqual(changes, [("Inventory", row, 1, "Fern"), ("Inventory", row, 2, "Small")])
        self.assertEqual(bridge.take_changes(), [])

    def test_a_rows_down_sheet_records_real_coordinates_not_the_swapped_view(self):
        bridge = XlsxBridge(make_vertical(self.dir / "v.xlsx"))
        bridge.set_vertical(True)
        bridge.connect()
        column = bridge.append_row("Stock", {"Fruit": "Banana"})
        self.assertEqual(bridge.take_changes(), [("Stock", 1, column, "Banana")])    # row 1 (the Fruit heading's row), column C

    def test_undo_and_back_fills_are_recorded_too(self):
        bridge = XlsxBridge(make_workbook(self.dir / "p.xlsx"))
        bridge.connect()
        row = bridge.append_row("Inventory", {"Species": "Fern"})
        bridge.take_changes()
        bridge.set_value("Inventory", row, "Pot Size", "Large")
        bridge.clear_value("Inventory", row, "Pot Size", "Large")
        self.assertEqual(bridge.take_changes(), [("Inventory", row, 2, "Large"), ("Inventory", row, 2, None)])

    def test_a_list_value_added_to_a_config_sheet_is_recorded_on_that_sheet(self):
        bridge = XlsxBridge(make_workbook(self.dir / "p.xlsx"))
        bridge.connect()
        bridge.add_to_list("Species", "Ficus")
        sheets = {c[0] for c in bridge.take_changes()}
        self.assertEqual(sheets, {"Config"})

    def test_a_csv_file_records_its_cells_too(self):
        path = self.dir / "b.csv"
        path.write_text("Bird,Place\nWren,Park\n")
        bridge = CsvBridge(path)
        bridge.connect()
        bridge.append_row("b", {"Bird": "Owl"})
        self.assertEqual(bridge.take_changes()[0][1:], (3, 1, "Owl"))

    def test_nobody_taking_them_cannot_grow_the_list_without_end(self):
        wb = openpyxl.Workbook()
        grid = OpenpyxlGrid(wb)
        for i in range(MAX_CHANGES + 100):
            grid.write(wb.active.title, 1, 1, i)
        self.assertLessEqual(len(grid.changes), MAX_CHANGES)
        self.assertTrue(grid.changes_lost)                                          # (and a viewer is told to reload, not shown half)

    def test_a_pile_that_was_dropped_is_taken_as_nothing_so_the_viewer_reloads(self):
        bridge = XlsxBridge(make_workbook(pathlib.Path(tempfile.mkdtemp()) / "p.xlsx"))
        bridge.connect()
        for i in range(MAX_CHANGES + 5):
            bridge._grid.write("Inventory", 1, 1, i)
        self.assertEqual(bridge.take_changes(), [])
        bridge._grid.write("Inventory", 2, 1, "x")                                 # recording starts again
        self.assertEqual(bridge.take_changes(), [("Inventory", 2, 1, "x")])
        self.assertEqual(bridge.take_changes(), [])                                # and what was taken is forgotten

    def test_a_bridge_that_does_not_edit_a_file_has_none(self):
        from quill.bridge.base import WorkbookBridge
        self.assertEqual(WorkbookBridge.take_changes(object()), [])


class FakeMirror:
    def __init__(self, result=MirrorResult(True, "ok")):
        self.result, self.pushed, self.installed_note = result, [], False

    def has_document(self, path):
        return False

    def active_sheet(self, path):
        return None

    def push(self, path, changes):
        self.pushed.append((path, list(changes)))
        return self.result


class AppWithMirror(Env):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.plants = make_workbook(self.dir / "plants.xlsx")
        self.mirror = FakeMirror()
        self.make()

    def make(self, mirror=None):
        os.environ["QUILL_NO_HOSTS"] = "1"                          # (no real system lookups while the app starts)
        self.app = QuillApp(_app, Settings.load(self.dir / "cfg"), XlsxBridge(self.plants),
                            listener_factory=lambda *a: FakeListener(*a), model_finder=lambda c: self.dir,
                            speaker=FakeSpeaker(), sound_player=lambda p: None, live_bridge_factory=lambda: DeadExcel(),
                            hosts=FakeHosts(), mirror=mirror or self.mirror)
        self.app.run_in_background = lambda work, done: done(work())
        self.app.start()
        self.app.controller.handle_transcript("start listening")

    def turn(self, words="fern small"):
        self.app.controller.handle_transcript(words)
        self.app.controller.handle_transcript("next row")


class TestAppShowsRowsInNumbers(AppWithMirror):
    def test_the_cells_of_a_saved_row_are_pushed_to_numbers_with_the_files_path(self):
        self.turn()
        path, changes = self.mirror.pushed[-1]
        self.assertEqual(path, str(self.plants.resolve()))
        self.assertEqual(changes, [("Inventory", 4, 1, "Fern"), ("Inventory", 4, 2, "Small")])

    def test_when_numbers_has_them_the_file_is_not_reloaded(self):
        self.turn()
        self.assertFalse(self.app._host_reload.isActive())

    def test_when_numbers_does_not_have_the_file_open_the_old_reload_still_happens(self):
        self.make(FakeMirror(MirrorResult(False, "nodoc")))
        self.turn()
        self.assertTrue(self.app._host_reload.isActive())

    def test_a_refusal_is_explained_once_and_still_falls_back_to_reloading(self):
        self.make(FakeMirror(MirrorResult(False, "denied", "not authorized")))
        self.turn()
        self.app._host_reload.stop()
        self.turn("cactus")
        text = self.app.window.log.toPlainText()
        self.assertEqual(text.count("Allow it in System Settings"), 1)
        self.assertIn("Automation", text)
        self.assertTrue(self.app._host_reload.isActive())                       # (the second turn also fell back)

    def test_an_undo_is_shown_too(self):
        self.turn("zorb")                                                     # an unknown word: the Term Helper has a row
        self.mirror.pushed.clear()
        from quill.session import Decision
        key = self.app.controller.pending_terms()[0]
        self.app.resolve_term(key, Decision.add("Species"), key[1])
        self.assertTrue(self.mirror.pushed)                                   # the list value and the back-filled cell

    def test_live_excel_is_never_mirrored(self):
        self.app.controller.bridge = type("Live", (), {"take_changes": lambda s: [("S", 1, 1, "x")], "workbook_path": "/x/a.xlsx",
                                                       "host_reload": True})()
        self.mirror.pushed.clear()
        self.app._show_in_viewer()
        self.assertEqual(self.mirror.pushed, [])

    def test_a_csv_file_is_not_mirrored_or_reloaded(self):
        path = self.dir / "b.csv"
        path.write_text("Bird\nWren\n")
        self.app.controller.bridge = CsvBridge(path)
        self.app.controller.bridge.connect()
        self.mirror.pushed.clear()
        self.app._show_in_viewer()
        self.assertEqual(self.mirror.pushed, [])


class TestAppAlsoShowsRowsInLibreOffice(AppWithMirror):
    def make(self, mirror=None, lo=None):
        self.lo = lo or FakeMirror()
        os.environ["QUILL_NO_HOSTS"] = "1"
        self.app = QuillApp(_app, Settings.load(self.dir / "cfg"), XlsxBridge(self.plants),
                            listener_factory=lambda *a: FakeListener(*a), model_finder=lambda c: self.dir,
                            speaker=FakeSpeaker(), sound_player=lambda p: None, live_bridge_factory=lambda: DeadExcel(),
                            hosts=FakeHosts(), mirror=mirror or self.mirror, lo_mirror=self.lo)
        self.app.run_in_background = lambda work, done: done(work())
        self.app.start()
        self.app.controller.handle_transcript("start listening")

    def test_the_other_program_gets_the_cells_when_numbers_does_not_have_the_file(self):
        self.make(FakeMirror(MirrorResult(False, "nodoc")), FakeMirror())
        self.turn()
        self.assertEqual(self.lo.pushed[-1][1], [("Inventory", 4, 1, "Fern"), ("Inventory", 4, 2, "Small")])
        self.assertFalse(self.app._host_reload.isActive())                      # LibreOffice has them: no reload

    def test_numbers_having_them_means_libreoffice_is_not_asked(self):
        self.turn()
        self.assertEqual(self.lo.pushed, [])

    def test_the_program_known_to_hold_the_file_is_asked_first(self):
        from quill.bridge.hosts import OpenFile
        self.app._open_files = [OpenFile("plants.xlsx", str(self.plants.resolve()), "LibreOffice")]
        self.turn()
        self.assertTrue(self.lo.pushed)
        self.assertEqual(self.mirror.pushed, [])

    def test_when_neither_has_it_the_old_reload_still_happens(self):
        self.make(FakeMirror(MirrorResult(False, "nodoc")), FakeMirror(MirrorResult(False, "notrunning")))
        self.turn()
        self.assertTrue(self.app._host_reload.isActive())

    def test_the_added_script_is_announced_once(self):
        self.lo.installed_note = True
        self.make(FakeMirror(MirrorResult(False, "nodoc")), self.lo)
        self.lo.installed_note = True
        self.turn()
        self.turn("cactus")
        self.assertEqual(self.app.window.log.toPlainText().count("small script to LibreOffice"), 1)


class TestSeveralProgramsAtOnce(AppWithMirror):
    """Excel with one workbook, Numbers with another, LibreOffice with a third: each turn goes where its file is shown."""

    def setUp(self):
        super().setUp()
        from quill.bridge.hosts import OpenFile
        self.book1 = make_workbook(self.dir / "workbook1.xlsx")
        self.book2 = make_workbook(self.dir / "workbook2.xlsx")
        self.book3 = make_workbook(self.dir / "workbook3.xlsx")
        self.numbers, self.libre = FakeMirror(), FakeMirror()
        self.app.mirror, self.app.lo_mirror = self.numbers, self.libre
        self.app._open_files = [OpenFile("workbook1.xlsx", str(self.book1), "Excel", live=True),
                                OpenFile("workbook2.xlsx", str(self.book2), "Numbers"),
                                OpenFile("workbook3.xlsx", str(self.book3), "LibreOffice Calc")]

    def row_goes_to(self, path):
        self.app.open_workbook_file(str(path))
        self.app._open_files = self.app._open_files        # (the list is what the last look found)
        self.numbers.pushed.clear()
        self.libre.pushed.clear()
        if not self.app.controller.session.listening:
            self.app.controller.handle_transcript("start listening")
        self.turn()
        return bool(self.numbers.pushed), bool(self.libre.pushed)

    def test_each_file_is_shown_in_the_program_that_has_it(self):
        self.assertEqual(self.row_goes_to(self.book2), (True, False))          # Numbers
        self.assertEqual(self.row_goes_to(self.book3), (False, True))          # LibreOffice
        self.assertEqual(self.row_goes_to(self.book2), (True, False))          # and back: nothing to set

    def test_a_file_in_a_program_with_no_live_display_is_not_offered_to_the_others(self):
        from quill.bridge.hosts import OpenFile
        self.app._open_files = [OpenFile("workbook2.xlsx", str(self.book2), "WPS Office")]
        self.assertEqual(self.row_goes_to(self.book2), (False, False))
        self.assertTrue(self.app._host_reload.isActive())                      # the reload fallback

    def test_a_file_that_excel_has_is_worked_in_excel(self):
        from unittest import mock
        self.app.open_workbook_file(str(self.book1))
        with mock.patch.object(self.app, "use_live_excel") as use, mock.patch.object(self.app, "connect_workbook"):
            self.app._attach_live_if_open_in_excel()
        use.assert_called()


@unittest.skipUnless(sys.platform == "darwin" and os.environ.get("QUILL_NUMBERS_LIVE") == "1",
                     "needs Numbers on this Mac: QUILL_NUMBERS_LIVE=1 with plants.xlsx open in it")
class TestRealNumbers(Env):
    """Optional, on a real Mac: open the file in Numbers first. Writes one test row into the open Numbers document."""

    def test_a_row_shows_up_in_the_open_document(self):
        path = pathlib.Path(os.environ["QUILL_NUMBERS_FILE"])
        result = NumbersMirror().push(path, [("Inventory", 30, 1, "Live test"), ("Inventory", 30, 3, 1.5)])
        self.assertTrue(result.ok, result)


if __name__ == "__main__":
    unittest.main()


class TestHeardTermsDoNotOutliveTheirWorkbook(unittest.TestCase):
    def test_switching_workbook_forgets_what_was_waiting_but_reconnecting_the_same_one_does_not(self):
        from quill.controller import Controller
        tmp = pathlib.Path(tempfile.mkdtemp())
        first, second = make_workbook(tmp / "a.xlsx"), make_workbook(tmp / "b.xlsx")
        bridge = XlsxBridge(first)
        controller = Controller(bridge, Settings.load(tmp / "cfg"), FakeSpeaker())
        controller.connect()
        controller.session.pending = [("Color", "teal")]
        controller.session.pool[("Color", "teal")] = 1
        controller.session.alias_hints[("Color", "teal")] = "T"
        controller.session.origins[("Color", "teal")] = ("Inventory", 4)
        controller.connect()                                          # the same file again (a refresh)
        self.assertEqual(controller.session.pending, [("Color", "teal")])
        controller.connect(str(second))
        self.assertIsNone(controller.session.pending)
        self.assertFalse(controller.session.pool or controller.session.alias_hints or controller.session.origins)

    def test_hints_are_bounded(self):
        from quill.session import Session
        from quill.parser.commands import CommandMatcher
        from quill.parser.vocab import Vocabulary
        session = Session(Vocabulary(), CommandMatcher({}))
        session.pending = [("C", "x0")]
        for i in range(session.MAX_HINTS + 50):
            session.alias_hints[("C", f"x{i}")] = "X"
        session._trim_hints()
        self.assertEqual(set(session.alias_hints), {("C", "x0")})                 # only the one still waiting is kept


class TestAskingWhetherAProgramHasTheFile(unittest.TestCase):
    def setUp(self):
        patch = unittest.mock.patch.dict("os.environ", {}, clear=False)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("QUILL_NO_HOSTS", None)

    def test_numbers_is_asked_by_document_name_and_changes_nothing(self):
        mirror, run = mirror_with(0, "ok")
        self.assertTrue(mirror.has_document("/x/plants.xlsx"))
        self.assertEqual(run.calls[0][-1], "plants")
        self.assertIn("documents", run.calls[0][2])
        self.assertNotIn("set value", run.calls[0][2])
        self.assertFalse(mirror_with(0, "nodoc")[0].has_document("/x/p.xlsx"))
        self.assertFalse(mirror_with(0, "notrunning")[0].has_document("/x/p.xlsx"))

    def test_libreoffice_is_asked_through_its_script_with_a_probe_job(self):
        import json
        from quill.bridge.libreoffice_mirror import LibreOfficeMirror
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "LibreOffice" / "4" / "user").mkdir(parents=True)
        seen = {}

        def runner(args):
            seen["job"] = json.loads((tmp / "mirror" / "in.json").read_text())
            (tmp / "mirror" / "out.json").write_text("ok")
            return 0

        mirror = LibreOfficeMirror(runner=runner, scripts_dir=tmp / "LibreOffice/4/user/Scripts/python", base=tmp / "mirror",
                                   running=lambda: True, soffice="/x/soffice", wait_s=1)
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("QUILL_NO_HOSTS", None)
            self.assertTrue(mirror.has_document("/x/a.xlsx"))
        self.assertTrue(seen["job"]["probe"])
        self.assertEqual(seen["job"]["changes"], [])

    def test_hosts_know_which_programs_are_installed(self):
        from quill.bridge.hosts import SpreadsheetHosts
        hosts = SpreadsheetHosts("darwin", lambda a: "")
        self.assertTrue(hosts.installed("auto"))
        self.assertFalse(hosts.installed("nonsense"))
        self.assertIsInstance(hosts.installed("numbers"), bool)


class TestAskingWhichSheetIsOpen(unittest.TestCase):
    def setUp(self):
        patch = unittest.mock.patch.dict("os.environ", {}, clear=False)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("QUILL_NO_HOSTS", None)

    def test_numbers_answers_with_the_name_of_the_sheet_and_nothing_is_changed(self):
        mirror, run = mirror_with(0, "sheet:2024")
        self.assertEqual(mirror.active_sheet("/x/Apparel Inventory SAMPLE.xlsx"), "2024")
        self.assertEqual(run.calls[0][-1], "Apparel Inventory SAMPLE")
        self.assertIn("active sheet", run.calls[0][2])
        self.assertNotIn("set value", run.calls[0][2])
        for answer in ("nodoc", "notrunning", "", "sheet:"):
            self.assertIsNone(mirror_with(0, answer)[0].active_sheet("/x/a.xlsx"))
        self.assertIsNone(mirror_with(1, "sheet:2024")[0].active_sheet("/x/a.xlsx"))

    def test_libreoffice_answers_through_its_script(self):
        import json
        from quill.bridge.libreoffice_mirror import LibreOfficeMirror
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "LibreOffice" / "4" / "user").mkdir(parents=True)
        seen = {}

        def runner(args):
            seen["job"] = json.loads((tmp / "mirror" / "in.json").read_text())
            (tmp / "mirror" / "out.json").write_text("sheet:Plants")
            return 0

        mirror = LibreOfficeMirror(runner=runner, scripts_dir=tmp / "LibreOffice/4/user/Scripts/python", base=tmp / "mirror",
                                   running=lambda: True, soffice="/x/soffice", wait_s=1)
        self.assertEqual(mirror.active_sheet("/x/a.xlsx"), "Plants")
        self.assertTrue(seen["job"]["sheet"])
        self.assertEqual(seen["job"]["changes"], [])
        self.assertIn("getActiveSheet", mirror.script_text())

    def test_a_workbook_gets_a_new_active_sheet_and_rows_go_there(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        bridge = XlsxBridge(make_workbook(tmp / "p.xlsx"))
        bridge.connect()
        self.assertEqual(bridge.active_sheet_name(), "Inventory")
        self.assertTrue(bridge.set_active_sheet("Config"))
        self.assertEqual(bridge.active_sheet_name(), "Config")
        self.assertFalse(bridge.set_active_sheet("Nope"))
        self.assertEqual(bridge.active_sheet_name(), "Config")
