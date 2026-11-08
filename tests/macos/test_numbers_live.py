"""The live link to Numbers: news from the watcher, questions over the link, the bridge over the open document, and the
real script run against a pretend Numbers (node) so its text is exercised too."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation

from quill.bridge.base import BridgeError
from quill.bridge.libreoffice_bridge import LibreOfficeBridge
from quill.platforms.macos import numbers_live
from quill.platforms.macos.numbers_live import NumbersBridge, NumbersLink, document_names
from tests.test_side_panel_and_turns import PanelApp

NODE = shutil.which("node")

#: A pretend Numbers for the real script (it runs under node): one document, tables of plain rows, the calls the script makes.
FAKE_NUMBERS = r"""
const book = JSON.parse(process.env.FAKE_BOOK);
const parseLetters = (s) => s.split("").reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);

function makeTable(data) {
  const get = (r, c) => (data.rows[r] && data.rows[r][c] !== undefined ? data.rows[r][c] : null);
  const ranges = new Proxy({}, { get: (_, ref) => {
    const m = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(String(ref));
    const c1 = parseLetters(m[1]) - 1, r1 = +m[2] - 1, c2 = parseLetters(m[3]) - 1, r2 = +m[4] - 1;
    return { cells: { value: () => { const out = []; for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) out.push(get(r, c)); return out; } } };
  } });
  const columns = new Proxy({}, { get: (_, i) => ({ cells: { value: () => { const out = []; for (let r = 0; r < data.rowCount; r++) out.push(get(r, +i)); return out; } } }) });
  const rows = new Proxy({}, { get: (_, i) => ({ cells: new Proxy({}, { get: (_, j) => new Proxy({}, { set: (_, key, v) => {
    data.rows[+i] = data.rows[+i] || [];
    data.rows[+i][+j] = v instanceof Date ? "DATE:" + v.getFullYear() + "-" + (v.getMonth() + 1) + "-" + v.getDate() : v;
    return true; } }) }) }) });
  return { get rowCount() { const f = () => data.rowCount; return new Proxy(f, { apply: () => data.rowCount }); }, set rowCount(v) { data.rowCount = v; },
           get columnCount() { return () => data.colCount; }, set columnCount(v) { data.colCount = v; }, ranges, columns, rows };
}

const sheets = book.sheets.map((s) => ({ name: () => s.name, tables: [makeTable(s)] }));
const sheetList = () => sheets;
Object.defineProperty(sheetList, "name", { value: () => sheets.map((s) => s.name()) });
sheetList.byName = (n) => { const s = sheets.find((x) => x.name() === n); if (!s) throw new Error("no sheet"); return s; };
sheets.forEach((s, i) => { sheetList[i] = s; });
const doc = { name: () => book.title, sheets: sheetList, activeSheet: () => sheets[book.active], modified: () => false };
globalThis.Application = () => ({
  running: () => book.running,
  documents: () => (book.open ? [doc] : []),
  clear: () => {},
});
globalThis.__book = book;
"""


def run_script(book: dict, command: str, arguments: dict) -> dict:
    """Run the real script text with a pretend Numbers; returns the answer."""
    program = FAKE_NUMBERS + "\n" + numbers_live.SCRIPT + "\n" + \
        "process.stdout.write(run([process.argv[1], process.argv[2]]));"
    done = subprocess.run([NODE, "-e", program, "--", command, json.dumps(arguments)],
                          capture_output=True, text=True, env={"FAKE_BOOK": json.dumps(book), "PATH": ""}, timeout=20, check=False)
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


def a_book(**extra) -> dict:
    book = {"title": "Plants.numbers", "running": True, "open": True, "active": 0,
            "sheets": [{"name": "Data", "rowCount": 4, "colCount": 3,
                        "rows": [["Species", "Count", "Seen"], ["Fern", 3, None], ["Moss", 5, None], [None, None, None]]},
                       {"name": "Config", "rowCount": 2, "colCount": 1, "rows": [["Region"], ["North"]]}]}
    book.update(extra)
    return book


@unittest.skipUnless(NODE, "needs node")
class TestTheRealScript(unittest.TestCase):
    names = ["Plants", "Plants.numbers"]

    def test_state_names_the_document_without_its_extension_and_the_open_sheet(self):
        answer = run_script(a_book(), "state", {})
        self.assertEqual(answer["docs"][0]["url"], "Plants")
        self.assertEqual(answer["docs"][0]["sheet"], "Data")
        self.assertEqual(answer["docs"][0]["sheets"], ["Data", "Config"])

    def test_numbers_that_is_not_running_is_not_asked_anything(self):
        self.assertEqual(run_script(a_book(running=False), "state", {}), {"ok": True, "running": False, "docs": []})

    def test_a_document_that_is_not_open_is_nodoc(self):
        self.assertEqual(run_script(a_book(), "used", {"urls": ["Other"], "sheet": "Data"}), {"ok": False, "error": "nodoc"})

    def test_used_rows_end_at_the_last_filled_row_and_columns_at_the_headings(self):
        self.assertEqual(run_script(a_book(), "used", {"urls": self.names, "sheet": "Data"}), {"ok": True, "rows": 3, "cols": 3})

    def test_a_block_is_read_with_blanks_as_none_and_past_the_table_as_none(self):
        answer = run_script(a_book(), "read", {"urls": self.names, "sheet": "Data", "top": 2, "left": 1, "rows": 3, "cols": 4})
        self.assertEqual(answer["cells"], [["Fern", 3, None, None], ["Moss", 5, None, None], [None, None, None, None]])

    def test_a_row_past_the_end_makes_the_table_longer_and_the_cells_are_set(self):
        book = a_book()
        program = FAKE_NUMBERS + "\n" + numbers_live.SCRIPT + "\n" + \
            "const out = run([process.argv[1], process.argv[2]]); process.stdout.write(JSON.stringify([JSON.parse(out), __book.sheets[0].rowCount, __book.sheets[0].rows[5]]));"
        changes = [["Data", 6, 1, "s", "Orca"], ["Data", 6, 2, "n", "4.5"], ["Data", 6, 3, "d", "2026-11-07"]]
        done = subprocess.run([NODE, "-e", program, "--", "apply", json.dumps({"urls": self.names, "changes": changes})],
                              capture_output=True, text=True, env={"FAKE_BOOK": json.dumps(book), "PATH": ""}, timeout=20, check=False)
        answer, rows, row = json.loads(done.stdout)
        self.assertEqual((answer, rows), ({"ok": True}, 6))
        self.assertEqual(row, ["Orca", 4.5, "DATE:2026-11-7"])

    def test_the_snapshot_has_every_sheet_with_its_size(self):
        answer = run_script(a_book(), "snapshot", {"urls": self.names})
        self.assertEqual([s["name"] for s in answer["sheets"]], ["Data", "Config"])
        self.assertEqual(answer["sheets"][0]["used_rows"], 3)
        self.assertEqual(answer["sheets"][0]["block"][0], ["Species", "Count", "Seen"])


class FakeRunner:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, args, timeout):
        self.calls.append(args)
        answer = self.answers.pop(0) if self.answers else {"ok": True, "running": True, "docs": []}
        return (0, json.dumps(answer), "") if answer is not None else (1, "", "boom")


def state(*docs):
    return {"ok": True, "running": True, "docs": [dict({"url": "Plants", "sheet": "Data", "sheets": ["Data"], "stamp": 1}, **d) for d in docs]}


class TestTheNews(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ)                 # (the tests' own switch that stops programs being asked is off here:
        patch.start()                                       # the runner is a pretend one)
        self.addCleanup(patch.stop)
        os.environ.pop("QUILL_NO_HOSTS", None)
        self.events = []
        self.runner = FakeRunner([])
        self.running = True
        self.link = NumbersLink(on_event=lambda *a: self.events.append(a), runner=self.runner, running=lambda: self.running)

    def look(self, answer):
        self.runner.answers.append(answer)
        self.link.look()

    def test_a_document_opening_changing_moving_and_closing_are_each_said_once(self):
        self.look(state({}))
        self.look(state({}))                                                         # nothing new: nothing said
        self.look(state({"stamp": 2}))
        self.look(state({"stamp": 2, "sheet": "Config"}))
        self.look(state())
        self.assertEqual(self.events, [("opened", "Plants", "Data"), ("changed", "Plants", "Data"),
                                       ("sheet", "Plants", "Config"), ("closed", "Plants", "")])

    def test_an_edited_document_renamed_with_its_extension_is_the_same_document(self):
        self.look(state({"title": "Plants"}))
        self.look(state({"title": "Plants.numbers"}))
        self.assertEqual(self.events, [("opened", "Plants", "Data")])
        self.assertIsNotNone(self.link.find(["Plants.numbers"]))

    def test_numbers_quitting_closes_its_documents_and_loses_the_link_once(self):
        self.look(state({}))
        self.running = False
        self.link.look()
        self.link.look()
        self.assertEqual(self.events[1:], [("closed", "Plants", ""), ("lost", "", "")])
        self.assertFalse(self.link.connected)

    def test_a_few_failed_looks_in_a_row_lose_the_link_but_one_does_not(self):
        self.look(state({}))
        self.look(None)
        self.assertTrue(self.link.connected)
        self.look(None)
        self.look(None)
        self.assertFalse(self.link.connected)
        self.assertEqual(self.events[-1], ("lost", "", ""))

    def test_questions_carry_their_values_as_json_never_as_script_text(self):
        self.runner.answers.append({"ok": True})
        hostile = 'x"); do shell script "rm -rf ~'
        self.link.request("apply", urls=["P"], changes=[["S", 1, 1, "s", hostile]])
        args = self.runner.calls[0]
        self.assertEqual(args[:4], ["osascript", "-l", "JavaScript", "-e"])
        self.assertEqual(args[4], numbers_live.SCRIPT)
        self.assertNotIn("rm -rf", args[4])
        self.assertIn(hostile, json.loads(args[6])["changes"][0])

    def test_nothing_is_asked_while_numbers_is_not_running(self):
        self.running = False
        self.assertIsNone(self.link.request("state"))
        self.assertEqual(self.runner.calls, [])

    def test_document_names(self):
        self.assertEqual(document_names("/a/Plants.xlsx"), ["Plants", "Plants.numbers"])


class TestTheBridge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = pathlib.Path(self._tmp.name) / "Plants.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Data"
        ws.append(["Species", "Count"])
        rule = DataValidation(type="list", formula1='"Fern,Moss"', allow_blank=True)
        ws.add_data_validation(rule)
        rule.add("A2:A50")
        wb.save(self.path)
        self.link = NumbersLink(runner=FakeRunner([]), running=lambda: True)
        self.link.docs = {"Plants": {"url": "Plants", "sheet": "Data", "sheets": ["Data"]}}
        self.link._connected = True
        self.asked = []

        def request(command, timeout=8.0, **fields):
            self.asked.append((command, fields))
            if command == "snapshot":
                return {"ok": True, "names": [], "sheets": [{"name": "Data", "used_rows": 1, "used_cols": 2, "left": [["Species", "Count"]],
                                                              "block": [["Species", "Count"]], "validations": []}]}
            if command == "used":
                return {"ok": True, "rows": 1, "cols": 2}
            return {"ok": True, "cells": [["Species", "Count"]]}

        self.link.request = request

    def bridge(self):
        bridge = NumbersBridge(self.path, lambda: self.link)
        bridge.connect()
        return bridge

    def test_it_is_a_live_libreoffice_style_bridge_that_says_numbers(self):
        bridge = self.bridge()
        self.assertIsInstance(bridge, LibreOfficeBridge)
        self.assertEqual(NumbersBridge.PROGRAM, "Numbers")
        self.assertEqual(bridge.addresses, ["Plants", "Plants.numbers"])

    def test_the_drop_down_rules_come_from_the_saved_file_and_the_headings_from_numbers(self):
        bridge = self.bridge()
        self.assertEqual(bridge.get_lists()["Species"], ["Fern", "Moss"])

    def test_a_document_numbers_does_not_have_open_will_not_connect(self):
        self.link.docs = {}
        with self.assertRaises(BridgeError) as caught:
            self.bridge()
        self.assertIn("Numbers is not answering", str(caught.exception))

    def test_a_pop_up_menu_cannot_be_extended_from_quill(self):
        bridge = self.bridge()
        source = next(iter(bridge._discovery.sources.values()))
        with self.assertRaises(BridgeError) as caught:
            bridge._add_inline(source, "Orca")
        self.assertIn("pop-up menu", str(caught.exception))

    def test_a_row_goes_into_numbers_and_then_into_the_file_in_one_save(self):
        bridge = self.bridge()
        bridge._grid.write("Data", 2, 1, "Fern")
        bridge._grid.write("Data", 2, 2, 3)
        self.assertEqual([c for c, _ in self.asked if c == "apply"], ["apply", "apply"])       # (live, cell by cell)
        self.assertEqual(openpyxl.load_workbook(self.path)["Data"]["A2"].value, None)          # (the file waits for the end of the row)
        bridge._after_write()
        sheet = openpyxl.load_workbook(self.path)["Data"]
        self.assertEqual((sheet["A2"].value, sheet["B2"].value), ("Fern", 3))
        self.assertEqual(bridge.take_changes(), [])                                              # (no second display of the cells)

    def test_a_file_that_cannot_be_written_never_stops_the_dictation(self):
        bridge = self.bridge()
        bridge._grid.write("Nowhere", 2, 1, "Fern")                                              # (the file has no such sheet)
        bridge._after_write()                                                                     # (no error)
        bridge._grid.write("Data", 2, 1, "Moss")
        bridge._after_write()
        self.assertEqual(openpyxl.load_workbook(self.path)["Data"]["A2"].value, "Moss")


class TestAppTakesOverTheOpenNumbersDocument(PanelApp):
    def setUp(self):
        super().setUp()
        from quill.bridge.xlsx_bridge import XlsxBridge
        self.logged = []
        self.app.window.append_log = lambda text, level="info", **kw: self.logged.append((level, text))
        self.app._program_holding = lambda path: "numbers"
        link = NumbersLink(runner=FakeRunner([]), running=lambda: True)
        link.docs = {self.plants.stem: {"url": self.plants.stem, "sheet": "Sheet1", "sheets": ["Sheet1"]}}
        link._connected = True
        self.app.numbers_link = link
        made = self.made = []

        class FakeNumbersBridge(type(self.app.controller.bridge)):
            PROGRAM = "Numbers"

            def __init__(self, path, link):
                super().__init__(path)
                made.append(path)

        patcher = mock.patch("quill.platforms.offered", lambda platform, what, default=None: FakeNumbersBridge if what == "NumbersBridge" else default)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertIsInstance(self.app.controller.bridge, XlsxBridge)

    def test_the_file_is_taken_over_and_the_log_says_the_xlsx_is_left_alone(self):
        self.assertTrue(self.app._attach_live_if_open_in_numbers())
        self.assertEqual(len(self.made), 1)
        self.assertTrue(any("Numbers" in text and "works in it directly" in text and "file too" in text for _, text in self.logged))

    def test_only_when_numbers_holds_the_file_and_knows_the_document(self):
        self.app._program_holding = lambda path: "libreoffice"
        self.assertFalse(self.app._attach_live_if_open_in_numbers())
        self.app._program_holding = lambda path: "numbers"
        self.app.numbers_link.docs = {}
        self.assertFalse(self.app._attach_live_if_open_in_numbers())
        self.assertEqual(self.made, [])


if __name__ == "__main__":
    unittest.main()
