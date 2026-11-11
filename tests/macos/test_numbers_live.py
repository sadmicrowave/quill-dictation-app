"""The live link to Numbers: news from the watcher, questions over the link, the bridge over the open document, and the
real script run against a pretend Numbers (node) so its text is exercised too."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
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
    const each = (f) => { const out = []; for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) out.push(f(r, c)); return out; };
    return new Proxy({ cells: { value: () => each(get), textColor: () => each((r, c) => (data.colors[r] && data.colors[r][c]) || [0, 0, 0]) },
                       name: () => String(ref) }, {
      set: (target, key, v) => { if (key === "textColor") { each((r, c) => { data.colors[r] = data.colors[r] || []; data.colors[r][c] = v.map((x) => x / 65535); }); } return true; } });
  } });
  const columns = new Proxy({}, { get: (_, i) => ({ cells: { value: () => { const out = []; for (let r = 0; r < data.rowCount; r++) out.push(get(r, +i)); return out; } } }) });
  const rows = new Proxy({}, { get: (_, i) => ({ cells: new Proxy({}, { get: (_, j) => new Proxy({}, { set: (_, key, v) => {
    data.rows[+i] = data.rows[+i] || [];
    data.rows[+i][+j] = v instanceof Date ? "DATE:" + v.getFullYear() + "-" + (v.getMonth() + 1) + "-" + v.getDate() : v;
    return true; } }) }) }) });
  data.colors = data.colors || [];
  let selected = null;
  // (As the real Numbers does: a cell that is new because the table grew shows the first item of its pop-up list when the sheet has pop-ups.)
  const grow = (rowsFrom, rowsTo, colsFrom, colsTo) => {
    if (!data.popups) return;
    for (let r = 0; r < rowsTo; r++) for (let c = 0; c < colsTo; c++) if (r >= rowsFrom || c >= colsFrom) { data.rows[r] = data.rows[r] || []; data.rows[r][c] = "POPUP-DEFAULT"; }
  };
  data.clear = (ref) => {
    const m = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(String(ref));
    const c1 = parseLetters(m[1]) - 1, r1 = +m[2] - 1, c2 = parseLetters(m[3]) - 1, r2 = +m[4] - 1;
    for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) { data.rows[r] = data.rows[r] || []; data.rows[r][c] = null; }
  };
  return { get selectionRange() { return () => selected; }, set selectionRange(v) { selected = v; }, get rowCount() { const f = () => data.rowCount; return new Proxy(f, { apply: () => data.rowCount }); },
           set rowCount(v) { const was = data.rowCount; data.rowCount = v; grow(was, v, 0, data.colCount); },
           get columnCount() { return () => data.colCount; }, set columnCount(v) { const was = data.colCount; data.colCount = v; grow(data.rowCount, data.rowCount, was, v); }, ranges, columns, rows };
}

const sheets = book.sheets.map((s) => ({ name: () => s.name, tables: [makeTable(s)] }));
const sheetList = () => sheets;
Object.defineProperty(sheetList, "name", { value: () => sheets.map((s) => s.name()) });
sheetList.byName = (n) => { const s = sheets.find((x) => x.name() === n); if (!s) throw new Error("no sheet"); return s; };
sheets.forEach((s, i) => { sheetList[i] = s; });
const doc = { file: () => null, name: () => book.title, sheets: sheetList, activeSheet: () => sheets[book.active], modified: () => false };
globalThis.Application = () => ({
  running: () => book.running,
  documents: () => (book.open ? [doc] : []),
  clear: (target) => { if (target && typeof target.name === "function") { const t = sheets[book.active].tables[0]; book.sheets[book.active].clear(target.name()); } },
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

    def test_a_document_numbered_because_the_name_was_taken_is_the_same_document(self):
        answer = run_script(a_book(title="Plants 2.numbers"), "used", {"urls": self.names, "sheet": "Data"})
        self.assertEqual(answer, {"ok": True, "rows": 3, "cols": 3})                                  # "Plants 2.numbers" is "Plants"
        self.assertEqual(run_script(a_book(title="Plants 2.numbers"), "state", {})["docs"][0]["url"], "Plants")

    def test_the_open_spreadsheets_list_comes_from_the_same_script(self):
        answer = run_script(a_book(), "list", {})
        self.assertEqual(answer["text"], "Plants.numbers\t\tData\n")                                 # name, file (none for an import), sheet

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

    def run_two(self, first, first_args, second, second_args, book):
        program = FAKE_NUMBERS + "\n" + numbers_live.SCRIPT + "\n" + (
            "const a = JSON.parse(run([process.argv[1], process.argv[2]]));"
            "const mid = JSON.stringify(__book.sheets[0].colors);"
            "const b = JSON.parse(run([process.argv[3], process.argv[4]]));"
            "process.stdout.write(JSON.stringify([a, JSON.parse(mid), b, __book.sheets[0].colors, __book.sheets[0].selected]));")
        done = subprocess.run([NODE, "-e", program, "--", first, json.dumps(first_args), second, json.dumps(second_args)],
                              capture_output=True, text=True, env={"FAKE_BOOK": json.dumps(book), "PATH": ""}, timeout=20, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_a_search_fades_the_rows_that_do_not_match_and_keeps_the_matching_ones_as_they_were(self):
        book = a_book()
        book["sheets"][0]["colors"] = [[], [], [[0, 0, 0], [0.98, 0, 0.03], [0, 0, 0]]]            # a red cell in row 3 (the match)
        fade = {"urls": self.names, "sheet": "Data", "top": 2, "left": 1, "rows": 3, "cols": 3, "fade": [40000, 40000, 40000],
                "keep": [3], "jump": 3}
        answer = run_script(book, "fade", fade)
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["runs"][0]["index"], 0)                                              # (the colours are remembered as runs)
        self.assertIsNotNone(answer["runs"][0]["colour"])

    def test_clearing_the_search_paints_every_run_back_in_few_rectangles(self):
        runs = [{"index": 0, "length": 4, "colour": [0, 0, 0]}, {"index": 4, "length": 1, "colour": [64000, 0, 1800]},
                {"index": 5, "length": 4, "colour": [0, 0, 0]}]
        program = FAKE_NUMBERS + "\n" + numbers_live.SCRIPT + "\n" + (
            "run([process.argv[1], process.argv[2]]);"
            "process.stdout.write(JSON.stringify(__book.sheets[0].colors));")
        book = a_book()
        done = subprocess.run([NODE, "-e", program, "--", "unfade", json.dumps({"urls": self.names, "sheet": "Data", "top": 2, "left": 1, "cols": 3,
                                                                              "runs": runs, "selection": "A2:A2"})],
                              capture_output=True, text=True, env={"FAKE_BOOK": json.dumps(book), "PATH": ""}, timeout=20, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        colours = json.loads(done.stdout)
        self.assertAlmostEqual(colours[2][1][0], 64000 / 65535)                                       # row 3, middle cell: the red it had
        self.assertEqual(colours[1][0], [0, 0, 0])

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


ECHO = ("import sys,json\n"
        "for line in sys.stdin:\n"
        "    r = json.loads(line)\n"
        "    if r['c'] == 'hang':\n"
        "        import time; time.sleep(30)\n"
        "    if r['c'] == 'die':\n"
        "        sys.exit(1)\n"
        "    print(json.dumps({'ok': True, 'echo': r['c'], 'pid': __import__('os').getpid()}), flush=True)\n")


class TestTheWorkerProcess(unittest.TestCase):
    def worker(self, idle_s=30.0):
        worker = numbers_live.ScriptWorker([sys.executable, "-I", "-c", ECHO], idle_s=idle_s)
        self.addCleanup(worker.close)
        return worker

    def test_one_process_answers_many_questions(self):
        worker = self.worker()
        first = json.loads(worker.ask("a", {}, 5))
        second = json.loads(worker.ask("b", {}, 5))
        self.assertEqual((first["echo"], second["echo"]), ("a", "b"))
        self.assertEqual(first["pid"], second["pid"])

    def test_a_question_that_takes_too_long_kills_the_process_and_the_next_one_starts_a_new_one(self):
        worker = self.worker()
        first = json.loads(worker.ask("a", {}, 5))
        self.assertIsNone(worker.ask("hang", {}, 0.5))
        self.assertFalse(worker.alive)                                                   # (a stuck program can never hang Quill)
        self.assertNotEqual(json.loads(worker.ask("b", {}, 5))["pid"], first["pid"])

    def test_a_process_that_died_is_replaced(self):
        worker = self.worker()
        json.loads(worker.ask("a", {}, 5))
        self.assertIsNone(worker.ask("die", {}, 5))
        self.assertEqual(json.loads(worker.ask("b", {}, 5))["echo"], "b")

    def test_it_lets_go_of_the_process_when_nothing_is_asked_for_a_while(self):
        import time
        worker = self.worker(idle_s=0.3)
        worker.ask("a", {}, 5)
        self.assertTrue(worker.alive)
        time.sleep(0.8)
        self.assertFalse(worker.alive)

    def test_a_worker_that_cannot_start_falls_back_to_one_launch_per_question(self):
        runner = numbers_live.WorkerRunner(numbers_live.ScriptWorker(["/nonexistent/program"]))
        launches = []
        with mock.patch.object(numbers_live, "_system", lambda args, timeout: (launches.append(args), (0, '{"ok": true}', ""))[1]):
            code, out, _ = runner(["osascript", "-l", "JavaScript", "-e", "script", "state", "{}"], 5)
        self.assertEqual((code, out), (0, '{"ok": true}'))
        self.assertEqual(launches[0][-2:], ["state", "{}"])

    def test_the_script_the_worker_runs_has_one_entry_point_and_ends_when_input_closes(self):
        self.assertEqual(numbers_live.WORKER_SCRIPT.count("function run("), 1)
        self.assertIn("Number(data.length) === 0", numbers_live.WORKER_SCRIPT)


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

    def test_a_look_never_overlaps_another_and_nothing_runs_on_its_own(self):
        import threading
        self.assertFalse(hasattr(self.link, "start"))                                   # (no thread, no timer of its own)
        inside = []

        def slow_runner(args, timeout):
            inside.append(self.link._looking.locked())
            self.link.look()                                                            # a second look while one is under way
            return 0, json.dumps(state({})), ""

        self.link._run = slow_runner
        self.link.look()
        self.assertEqual(inside, [True])                                                 # (the second look did nothing)

    def test_every_question_has_a_time_limit(self):
        self.runner.answers.append({"ok": True})
        self.link.request("state", timeout=3.0)
        self.assertEqual(self.runner.calls[0][-2:], ["state", "{}"])
        runner_timeouts = []
        self.link._run = lambda args, timeout: (runner_timeouts.append(timeout), (0, '{"ok": true}', ""))[1]
        self.link.request("read")
        self.assertEqual(runner_timeouts, [numbers_live.ASK_TIMEOUT_S])

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

    def answer_dump_and_reload(self, cells, reload_ok=True):
        base = self.link.request

        def request(command, timeout=8.0, **fields):
            self.asked.append((command, fields))
            if command == "dump":
                return {"ok": True, "sheets": [{"name": "Data", "rows": len(cells), "cols": 2, "cells": cells}]}
            if command == "reload":
                return {"ok": reload_ok}
            return base(command, timeout, **fields)
        self.link.request = request
        self.link.look = lambda deep=True: None

    def test_a_typed_menu_is_extended_in_the_file_and_numbers_is_made_to_open_it_again(self):
        self.answer_dump_and_reload([["Species", "Count"]])
        bridge = self.bridge()
        told = []
        bridge.notify = told.append
        bridge._add_inline(bridge._discovery.sources["Species"], "Orca")
        rules = [r.formula1 for r in openpyxl.load_workbook(self.path)["Data"].data_validations.dataValidation]
        self.assertEqual(rules, ['"Fern,Moss,Orca"'])
        self.assertEqual(bridge._discovery.sources["Species"].items, ("Fern", "Moss", "Orca"))
        reloads = [f for c, f in self.asked if c == "reload"]
        self.assertEqual(len(reloads), 1)
        self.assertEqual(reloads[0]["path"], str(self.path))
        self.assertEqual(told, [])                                                           # (it simply worked)

    def test_a_document_with_changes_of_its_own_is_not_reopened_and_the_person_is_told(self):
        self.answer_dump_and_reload([["Species", "Count"], ["Typed in Numbers", 5]])
        bridge = self.bridge()
        told = []
        bridge.notify = told.append
        bridge._add_inline(bridge._discovery.sources["Species"], "Orca")
        self.assertNotIn("reload", [c for c, _ in self.asked])
        self.assertEqual([r.formula1 for r in openpyxl.load_workbook(self.path)["Data"].data_validations.dataValidation], ['"Fern,Moss,Orca"'])
        self.assertTrue(told and "changes of its own" in told[0])

    def test_numbers_that_will_not_reopen_the_file_is_reported_not_raised(self):
        self.answer_dump_and_reload([["Species", "Count"]], reload_ok=False)
        bridge = self.bridge()
        told = []
        bridge.notify = told.append
        bridge._add_inline(bridge._discovery.sources["Species"], "Orca")
        self.assertTrue(told and "reopen" in told[0])

    def test_what_the_document_holds_is_compared_with_the_file_cell_by_cell(self):
        import datetime as dt
        from quill.platforms.macos.numbers_live import _same_cell
        self.assertTrue(_same_cell(3, 3.0))
        self.assertTrue(_same_cell(None, ""))
        self.assertTrue(_same_cell("a ", "a"))
        self.assertTrue(_same_cell(dt.datetime(2026, 11, 7, 1, 0), dt.datetime(2026, 11, 7)))
        self.assertTrue(_same_cell(12, "=A1+1"))                                              # a formula: not compared
        self.assertFalse(_same_cell("a", "b"))
        self.assertFalse(_same_cell(None, "x"))
        self.assertFalse(_same_cell(5, 6))

    def test_looks_made_while_the_document_is_reopened_say_nothing(self):
        events = []
        link = NumbersLink(on_event=lambda *a: events.append(a), runner=FakeRunner([]), running=lambda: True)
        link.docs = {"Plants": {"url": "Plants", "sheet": "Data", "sheets": ["Data"], "stamp": 1}}
        link._connected = True
        with link.hold():
            link._news({})                                                                    # gone, for a moment
            link._news({"Plants": {"url": "Plants", "sheet": "Data", "sheets": ["Data"], "stamp": 1}})
        self.assertEqual(events, [])
        link._news({})                                                                        # after the hold, news is made again
        self.assertEqual(events, [("closed", "Plants", "")])

    def test_a_menu_the_file_does_not_have_is_left_alone_and_the_person_is_told(self):
        bridge = self.bridge()
        source = bridge._discovery.sources["Species"]
        from quill.bridge.introspect import ListSource
        stale = ListSource(column="Species", items=("Other", "Items"))
        with self.assertRaises(BridgeError) as caught:
            bridge._add_inline(stale, "Orca")
        self.assertIn("Add 'Orca' to the menu in Numbers", str(caught.exception))
        self.assertEqual([r.formula1 for r in openpyxl.load_workbook(self.path)["Data"].data_validations.dataValidation], ['"Fern,Moss"'])

    def test_a_search_fades_through_the_link_and_clearing_it_puts_the_colours_back(self):
        from quill.bridge.filters import ColumnFilter
        bridge = self.bridge()
        grid = bridge._grid
        base = self.link.request

        def request(command, timeout=8.0, **fields):
            self.asked.append((command, fields))
            if command == "read":
                return {"ok": True, "cells": [["Fern", 3], ["Moss", 5], ["Fern", 7]]}
            if command == "fade":
                return {"ok": True, "runs": [{"index": 0, "length": 6, "colour": [0, 0, 0]}], "selection": "B9:B9"}
            if command == "unfade":
                return {"ok": True}
            return base(command, timeout, **fields)
        self.link.request = request
        count = grid.set_autofilter("Data", 1, 1, 2, 4, {1: ColumnFilter(column="Species", values=["Fern"])})
        self.assertEqual(count, 2)
        fade = next(f for c, f in self.asked if c == "fade")
        self.assertEqual((fade["keep"], fade["jump"], fade["top"], fade["rows"]), ([2, 4], 2, 2, 3))
        grid.clear_autofilter("Data")
        unfade = next(f for c, f in self.asked if c == "unfade")
        self.assertEqual((unfade["selection"], unfade["runs"][0]["length"]), ("B9:B9", 6))
        grid.clear_autofilter("Data")                                                              # (nothing left to put back)
        self.assertEqual([c for c, _ in self.asked].count("unfade"), 1)

    def test_a_search_with_no_match_fades_nothing_and_a_search_that_cannot_paint_still_counts(self):
        from quill.bridge.filters import ColumnFilter
        bridge = self.bridge()
        base = self.link.request

        def request(command, timeout=8.0, **fields):
            self.asked.append((command, fields))
            if command == "read":
                return {"ok": True, "cells": [["Fern", 3]]}
            if command == "fade":
                return {"ok": False, "error": "no"}
            return base(command, timeout, **fields)
        self.link.request = request
        none = bridge._grid.set_autofilter("Data", 1, 1, 2, 2, {1: ColumnFilter(column="Species", values=["Orca"])})
        self.assertEqual(none, 0)
        self.assertNotIn("fade", [c for c, _ in self.asked])
        some = bridge._grid.set_autofilter("Data", 1, 1, 2, 2, {1: ColumnFilter(column="Species", values=["Fern"])})
        self.assertEqual(some, 1)                                                                    # (the colours failed; the count stands)

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


class TestWhoLooksAndWhen(PanelApp):
    """The quick look at Numbers exists only while listening."""

    def test_the_quick_timer_runs_only_while_listening_and_not_in_tests(self):
        self.app.numbers_link = NumbersLink(runner=FakeRunner([]), running=lambda: False)
        with mock.patch.dict(os.environ):
            os.environ.pop("QUILL_NO_HOSTS", None)
            self.app._set_listening(True)
            self.assertTrue(self.app._numbers_timer.isActive())
            self.assertEqual(self.app._numbers_timer.interval(), self.app.NUMBERS_LOOK_MS)
            self.app._set_listening(False)
            self.assertFalse(self.app._numbers_timer.isActive())
            os.environ["QUILL_NO_HOSTS"] = "1"
            self.app._set_listening(True)
            self.assertFalse(self.app._numbers_timer.isActive())
        self.app._set_listening(False)

    def test_the_timer_is_stopped_when_the_app_shuts_down(self):
        self.app._numbers_timer.start()
        self.app.shutdown()
        self.assertFalse(self.app._numbers_timer.isActive())


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


class TestTwoDocumentsWithTheSameName(unittest.TestCase):
    """Found on screen: with "Demo Inventory" and a leftover "Demo Inventory 27.numbers" open, Quill followed the leftover (its sheet was
    Blank) because both answer to the same name and it took the wrong one."""

    def docs(self, *titles_and_sheets):
        return [{"url": "Demo Inventory", "title": t, "sheet": s, "sheets": ["Inventory", "Blank"]} for t, s in titles_and_sheets]

    def test_the_one_called_exactly_that_wins_whatever_the_order(self):
        live, old = ("Demo Inventory", "Inventory"), ("Demo Inventory 27.numbers", "Blank")
        for order in ((live, old), (old, live)):
            chosen = numbers_live.one_document_per_name(self.docs(*order))
            self.assertEqual(chosen["Demo Inventory"]["sheet"], "Inventory", f"order {order}")

    def test_among_copies_the_highest_numbered_wins(self):
        docs = self.docs(("Demo Inventory 3.numbers", "A"), ("Demo Inventory 27.numbers", "B"), ("Demo Inventory 9.numbers", "C"))
        self.assertEqual(numbers_live.one_document_per_name(docs)["Demo Inventory"]["sheet"], "B")

    def test_a_document_saved_as_name_dot_numbers_counts_as_exact(self):
        docs = self.docs(("Demo Inventory 27.numbers", "Blank"), ("Demo Inventory.numbers", "Inventory"))
        self.assertEqual(numbers_live.one_document_per_name(docs)["Demo Inventory"]["sheet"], "Inventory")

    def test_documents_without_a_name_or_a_title_are_still_handled(self):
        docs = [{"sheet": "x"}, {"url": "Plants", "sheet": "Data"}, {"url": "Plants", "sheet": "Other"}]
        self.assertEqual(numbers_live.one_document_per_name(docs), {"Plants": {"url": "Plants", "sheet": "Data"}})

    def test_the_link_follows_the_exact_document_not_the_leftover(self):
        for order in (("Demo Inventory", "Demo Inventory 27.numbers"), ("Demo Inventory 27.numbers", "Demo Inventory")):
            runner = FakeRunner([state(*({"url": "Demo Inventory", "title": t, "sheet": "Inventory" if t == "Demo Inventory" else "Blank"}
                                         for t in order))])
            with mock.patch.dict(os.environ):
                os.environ.pop("QUILL_NO_HOSTS", None)
                link = NumbersLink(runner=runner, running=lambda: True)
                link.look()
            self.assertEqual(link.find(["Demo Inventory"])["sheet"], "Inventory", f"order {order}")

    def test_the_scripts_prefer_the_exact_name_too(self):
        from quill.platforms.macos import numbers_mirror
        for script in (numbers_live.SCRIPT, numbers_mirror.SCRIPT, numbers_mirror.PROBE, numbers_mirror.ACTIVE_SHEET):
            self.assertIn("bestScore", script)                      # (the best match, not the first)
            self.assertNotIn("return documents[i];", script.split("function findDocument")[1].split("\n}\n")[0] if "function findDocument" in script else "")


@unittest.skipUnless(NODE, "needs node")
class TestHowFarTheDataReaches(unittest.TestCase):
    """Found with the real Numbers: the 'used' size looked at the first three columns and the first three rows only, so a record was put on
    top of what a taller column to the right already held (and headings below the third row were not found)."""

    @staticmethod
    def book(rows, cols, cells):
        data = [[None] * cols for _ in range(rows)]
        for (r, c), v in cells.items():
            data[r - 1][c - 1] = v
        return {"title": "Plants.numbers", "running": True, "open": True, "active": 0,
                "sheets": [{"name": "Data", "rowCount": rows, "colCount": cols, "rows": data}]}

    def used(self, book):
        answer = run_script(book, "used", {"urls": ["Plants"], "sheet": "Data"})
        return answer["rows"], answer["cols"]

    def test_a_column_further_right_that_is_taller_than_the_first_ones_counts(self):
        cells = {(1, c): f"H{c}" for c in range(1, 8)}                         # headings across A..G
        cells.update({(2, 1): "a", (3, 1): "b"})                               # the first column: two records
        cells.update({(r, 7): f"g{r}" for r in range(2, 8)})                   # the seventh: six
        self.assertEqual(self.used(self.book(10, 7, cells)), (7, 7))

    def test_headings_far_to_the_right_count_even_with_nothing_else_in_the_first_rows(self):
        cells = {(1, 1): "title line", (5, 1): "Category"}
        cells.update({(5, c): f"H{c}" for c in range(2, 8)})                   # headings on row 5, across to G
        self.assertEqual(self.used(self.book(8, 8, cells)), (5, 7))

    def test_a_row_further_down_that_is_longer_than_the_first_rows_counts_when_headings_run_down(self):
        cells = {(r, 1): f"H{r}" for r in range(1, 8)}                         # headings down A1..A7
        cells.update({(1, 2): "x", (1, 3): "y"})                               # the first heading: two records
        cells.update({(7, c): f"r{c}" for c in range(2, 8)})                   # the seventh: six
        self.assertEqual(self.used(self.book(8, 10, cells)), (7, 7))

    def test_an_empty_table_has_no_extent(self):
        self.assertEqual(self.used(self.book(4, 3, {})), (0, 0))

    def test_blank_cells_and_gaps_do_not_move_it(self):
        cells = {(1, 1): "Species", (6, 1): "last", (3, 4): ""}                # (an empty string is empty)
        self.assertEqual(self.used(self.book(9, 5, cells)), (6, 1))


def run_steps(book: dict, steps: list, script: str | None = None) -> list:
    """Run several commands one after another in the SAME pretend Numbers (so a write can be read back); returns each answer."""
    program = FAKE_NUMBERS + "\n" + (script or numbers_live.SCRIPT) + "\n" + \
        "const out = []; for (const [c, a] of JSON.parse(process.argv[1])) out.push(JSON.parse(run([c, JSON.stringify(a)]))); process.stdout.write(JSON.stringify(out));"
    done = subprocess.run([NODE, "-e", program, "--", json.dumps(steps)], capture_output=True, text=True,
                          env={"FAKE_BOOK": json.dumps(book), "PATH": ""}, timeout=20, check=False)
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


@unittest.skipUnless(NODE, "needs node")
class TestNewCellsAreLeftEmpty(unittest.TestCase):
    """Found with the real Numbers: when the table grows, its new pop-up cells show the first item of their list, which was then saved as
    something nobody said (Men, Small, Nike ... beside the one value that was dictated)."""

    @staticmethod
    def book(popups=True):
        rows = [[f"H{r}", "x"] for r in range(1, 6)]                         # headings down A, one record in B
        return {"title": "Plants.numbers", "running": True, "open": True, "active": 0,
                "sheets": [{"name": "Data", "rowCount": 5, "colCount": 2, "rows": rows, "popups": popups}]}

    @staticmethod
    def write(*cells):
        return ["apply", {"urls": ["Plants"], "changes": [["Data", r, c, "s", t] for r, c, t in cells]}]

    @staticmethod
    def read(top, left, rows, cols):
        return ["read", {"urls": ["Plants"], "sheet": "Data", "top": top, "left": left, "rows": rows, "cols": cols}]

    def test_a_new_column_holds_only_what_was_written(self):
        done = run_steps(self.book(), [self.write((1, 3, "Dress"), (5, 3, "Good")), self.read(1, 3, 5, 1)])
        self.assertEqual([row[0] for row in done[1]["cells"]], ["Dress", None, None, None, "Good"])

    def test_a_new_row_holds_only_what_was_written(self):
        done = run_steps(self.book(), [self.write((7, 2, "Dress")), self.read(6, 1, 2, 2)])
        self.assertEqual(done[1]["cells"], [[None, None], [None, "Dress"]])

    def test_a_new_row_and_a_new_column_at_once(self):
        done = run_steps(self.book(), [self.write((7, 4, "Dress")), self.read(1, 1, 7, 4)])
        cells = done[1]["cells"]
        self.assertEqual(cells[6][3], "Dress")
        self.assertEqual([c for r, row in enumerate(cells) for k, c in enumerate(row) if k >= 2 and (r, k) != (6, 3)], [None] * 13)

    def test_the_cells_that_were_already_there_are_never_cleared(self):
        done = run_steps(self.book(), [self.write((1, 3, "Dress")), self.read(1, 1, 5, 2)])
        self.assertEqual(done[1]["cells"], [[f"H{r}", "x"] for r in range(1, 6)])

    def test_writing_inside_the_table_clears_nothing(self):
        done = run_steps(self.book(), [self.write((3, 2, "kept elsewhere")), self.read(1, 1, 5, 2)])
        self.assertEqual(done[1]["cells"][2], ["H3", "kept elsewhere"])
        self.assertEqual(done[1]["cells"][0], ["H1", "x"])

    def test_the_pretend_numbers_really_fills_new_cells_so_these_tests_mean_something(self):
        """Without the script's clearing, the same write leaves the pop-up defaults behind (what the real Numbers did)."""
        mutated = numbers_live.SCRIPT.replace("app.clear(table.ranges[", "(function(){})(table.ranges[")
        self.assertNotEqual(mutated, numbers_live.SCRIPT)
        done = run_steps(self.book(), [self.write((1, 3, "Dress"), (5, 3, "Good")), self.read(1, 3, 5, 1)], script=mutated)
        self.assertEqual([row[0] for row in done[1]["cells"]], ["Dress", "POPUP-DEFAULT", "POPUP-DEFAULT", "POPUP-DEFAULT", "Good"])

    def test_a_sheet_without_pop_ups_is_not_affected(self):
        done = run_steps(self.book(popups=False), [self.write((1, 3, "Dress")), self.read(1, 3, 3, 1)])
        self.assertEqual([row[0] for row in done[1]["cells"]], ["Dress", None, None])


class TestARereadAsksNumbersEachThingOnce(unittest.TestCase):
    """Found by counting the asks: after a sheet change Quill re-read the lists and headings with 13 questions to Numbers (the used size six
    times, a fifth of a second each), which kept the window waiting 2.3 s. Inside a re-read the same question is asked once."""

    def grid(self):
        from quill.bridge.libreoffice_bridge import LibreOfficeGrid
        asked = []

        class Doc:
            def ask(self_inner, command, **fields):
                asked.append((command, tuple(sorted(fields.items()))))
                return {"rows": 7, "cols": 4, "cells": [[1]]}

            def info(self_inner):
                return {}
        return LibreOfficeGrid(Doc()), asked

    def test_the_same_question_inside_the_block_is_asked_once(self):
        grid, asked = self.grid()
        with grid.remembering():
            self.assertEqual([grid.last_row("Data"), grid.last_col("Data"), grid.last_row("Data"), grid.last_col("Data")], [7, 4, 7, 4])
            grid.read("Data", 1, 1, 1, 1)
            grid.read("Data", 1, 1, 1, 1)
        self.assertEqual(len(asked), 2)                                         # one "used", one "read"

    def test_outside_the_block_every_question_is_asked(self):
        grid, asked = self.grid()
        grid.last_row("Data")
        grid.last_row("Data")
        self.assertEqual(len(asked), 2)

    def test_a_different_sheet_is_a_different_question_and_blocks_of_one_sheet_share_one_read(self):
        grid, asked = self.grid()
        with grid.remembering():
            grid.last_row("Data")
            grid.last_row("Config")
            grid.read("Data", 1, 1, 1, 1)
            grid.read("Data", 2, 1, 1, 1)
        self.assertEqual([c for c, _ in asked], ["used", "used", "read"])        # (the used size of each sheet; the two blocks come from one whole read)

    def test_a_write_makes_it_forget_so_nothing_stale_is_ever_used(self):
        grid, asked = self.grid()
        with grid.remembering():
            grid.last_row("Data")
            grid.write("Data", 8, 1, "x")
            grid.last_row("Data")
        self.assertEqual([c for c, _ in asked], ["used", "apply", "used"])

    def test_nothing_is_remembered_after_the_block(self):
        grid, asked = self.grid()
        with grid.remembering():
            grid.last_row("Data")
        grid.last_row("Data")
        self.assertEqual(len(asked), 2)

    def test_blocks_inside_blocks_share_one_memory(self):
        grid, asked = self.grid()
        with grid.remembering():
            grid.last_row("Data")
            with grid.remembering():
                grid.last_row("Data")
            grid.last_row("Data")
        self.assertEqual(len(asked), 1)

    def test_a_reload_of_the_vocabulary_uses_it(self):
        """The controller re-reads inside the block (a bridge without the method is read as before)."""
        from quill.controller import Controller
        entered = []

        class Bridge:
            def remembering(self_inner):
                import contextlib

                @contextlib.contextmanager
                def block():
                    entered.append("in")
                    yield
                    entered.append("out")
                return block()
        controller = Controller.__new__(Controller)
        controller.bridge = Bridge()
        controller.vocab = mock.MagicMock()
        controller.on_columns = lambda columns: None
        controller._apply_aliases = controller._apply_learning = lambda: None
        controller.bridge.get_lists = lambda: {}
        controller.bridge.get_headers = lambda: ["A"]
        controller.bridge.numeric_columns = controller.bridge.date_columns = lambda: set()
        controller.bridge.active_sheet_name = lambda: "Data"
        Controller.reload_vocab(controller)
        self.assertEqual(entered, ["in", "out"])


class TestWholeSheetReadsInsideARereread(unittest.TestCase):
    """Inside a re-read the lists are read block by block (seven asks to Numbers, 150 ms each): the used area of a sheet is asked for once and
    the blocks are cut from it. It must give exactly what asking block by block gives."""

    DATA = [["Category", "Gender", None, "Size"], ["T-Shirt", "Men", None, "S"], ["Jacket", None, None, "M"], [None, None, None, None],
            ["Dress", "Women", None, {"d": "2026-03-04T00:00:00"}]]

    def grid(self, data=None):
        from quill.bridge.libreoffice_bridge import LibreOfficeGrid
        data = self.DATA if data is None else data
        asked = []

        class Doc:
            def ask(self_inner, command, **f):
                asked.append(command)
                if command == "used":
                    rows = max((r + 1 for r, row in enumerate(data) if any(v is not None for v in row)), default=0)
                    cols = max((c + 1 for row in data for c, v in enumerate(row) if v is not None), default=0)
                    return {"rows": rows, "cols": cols}
                if command == "read":
                    top, left, rows, cols = f["top"], f["left"], f["rows"], f["cols"]
                    return {"cells": [[data[r - 1][c - 1] if 0 < r <= len(data) and 0 < c <= len(data[0]) else None
                                       for c in range(left, left + cols)] for r in range(top, top + rows)]}
                return {}

            def info(self_inner):
                return {}
        return LibreOfficeGrid(Doc()), asked

    def test_every_block_is_the_same_as_asking_for_it_directly(self):
        direct, _ = self.grid()
        remembered, _ = self.grid()
        blocks = [(1, 1, 5, 4), (2, 1, 1, 1), (1, 4, 5, 1), (3, 2, 2, 2), (4, 1, 3, 6), (6, 1, 2, 2), (1, 7, 2, 2), (5, 4, 1, 1), (1, 1, 1, 4)]
        with remembered.remembering():
            for block in blocks:
                self.assertEqual(remembered.read("S", *block), direct.read("S", *block), block)

    def test_many_blocks_cost_two_asks(self):
        grid, asked = self.grid()
        with grid.remembering():
            for block in ((1, 1, 5, 4), (2, 1, 3, 1), (1, 4, 5, 1), (3, 2, 2, 2)):
                grid.read("S", *block)
            grid.last_row("S")
        self.assertEqual(asked, ["used", "read"])

    def test_dates_still_come_back_as_dates(self):
        import datetime as dt
        grid, _ = self.grid()
        with grid.remembering():
            self.assertEqual(grid.read("S", 5, 4, 1, 1), [[dt.datetime(2026, 3, 4)]])

    def test_an_empty_sheet_reads_as_empty_cells(self):
        grid, asked = self.grid([[None, None], [None, None]])
        with grid.remembering():
            self.assertEqual(grid.read("S", 1, 1, 2, 2), [[None, None], [None, None]])

    def test_a_sheet_too_big_to_read_whole_is_read_by_blocks_as_before(self):
        grid, asked = self.grid()
        grid.WHOLE_SHEET_CELLS = 5
        with grid.remembering():
            grid.read("S", 1, 1, 2, 2)
            grid.read("S", 3, 1, 2, 2)
        self.assertEqual(asked.count("read"), 2)

    def test_outside_the_block_nothing_is_read_whole(self):
        grid, asked = self.grid()
        grid.read("S", 1, 1, 2, 2)
        self.assertEqual(asked, ["read"])


@unittest.skipUnless(NODE, "needs node")
class TestTheSheetQuestion(unittest.TestCase):
    """The quick look at an open document asks only which sheet it shows (the full quick look asks about every open document)."""

    def test_it_answers_the_open_sheet_of_the_named_document(self):
        answer = run_script(a_book(active=1), "sheet", {"urls": ["Plants", "Plants.numbers"]})
        self.assertEqual(answer, {"ok": True, "sheet": "Config"})

    def test_a_document_that_is_not_open_says_so(self):
        self.assertEqual(run_script(a_book(), "sheet", {"urls": ["Other"]}), {"ok": False, "error": "nodoc"})


class TestLookingAtOnlyTheSheet(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("QUILL_NO_HOSTS", None)
        self.events = []
        self.runner = FakeRunner([])
        self.running = True
        self.link = NumbersLink(on_event=lambda *a: self.events.append(a), runner=self.runner, running=lambda: self.running)
        self.runner.answers.append(state({}))                      # (one document, "Plants", on its sheet "Data")
        self.link.look()                                          # (the document is known: the news starts from here)
        self.events.clear()
        self.runner.calls.clear()

    def sheet(self, answer):
        self.runner.answers.append(answer)
        self.link.look_sheet(["Plants", "Plants.numbers"])

    def test_a_new_sheet_is_news_once_and_is_remembered(self):
        self.sheet({"ok": True, "sheet": "Config"})
        self.assertEqual(self.events, [("sheet", "Plants", "Config")])
        self.assertEqual(self.link.find(["Plants"])["sheet"], "Config")
        self.sheet({"ok": True, "sheet": "Config"})
        self.assertEqual(len(self.events), 1)

    def test_the_same_sheet_is_no_news(self):
        self.sheet({"ok": True, "sheet": "Data"})
        self.assertEqual(self.events, [])

    def test_it_asks_one_small_question(self):
        self.sheet({"ok": True, "sheet": "Data"})
        self.assertEqual(len(self.runner.calls), 1)
        self.assertIn("sheet", self.runner.calls[0])
        self.assertNotIn("state", self.runner.calls[0])

    def test_a_document_it_does_not_know_asks_nothing(self):
        self.link.look_sheet(["Never heard of it"])
        self.assertEqual(self.runner.calls, [])

    def test_numbers_not_running_asks_nothing(self):
        self.running = False
        self.sheet({"ok": True, "sheet": "Config"})
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.events, [])

    def test_a_failed_answer_is_no_news_and_no_error(self):
        for answer in ({"ok": False, "error": "nodoc"}, {"ok": True, "sheet": ""}, None):
            self.sheet(answer)
        self.assertEqual(self.events, [])

    def test_other_documents_are_left_as_they_were(self):
        self.runner.answers.append(state({"url": "Plants"}, {"url": "Orders", "sheet": "Q1", "sheets": ["Q1"]}))
        self.link.look()
        self.events.clear()
        self.sheet({"ok": True, "sheet": "Config"})
        self.assertEqual(self.link.find(["Orders"])["sheet"], "Q1")
        self.assertEqual(self.events, [("sheet", "Plants", "Config")])
