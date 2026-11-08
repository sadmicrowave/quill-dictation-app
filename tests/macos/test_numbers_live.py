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
  return { get selectionRange() { return () => selected; }, set selectionRange(v) { selected = v; }, get rowCount() { const f = () => data.rowCount; return new Proxy(f, { apply: () => data.rowCount }); }, set rowCount(v) { data.rowCount = v; },
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
