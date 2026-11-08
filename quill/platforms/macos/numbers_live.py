"""The live link to Numbers: Quill works in the document as it is open in Numbers, saved or not.

Numbers cannot tell anyone what happens in it, and it keeps no connection open, so this is the Numbers counterpart of
:mod:`quill.bridge.libreoffice_live` built the other way round: a small JavaScript for Automation script answers one
question per launch (about 0.1 s of processor time), and :meth:`NumbersLink.look` turns the difference between two answers
into the same news LibreOffice sends (``opened``, ``closed``, ``sheet``, ``changed``, ``lost``).

There is **no thread and no timer of its own** here. Who looks, and how often, is the app's decision (see ``QuillApp``): the
one check loop looks every few seconds while Numbers runs, and a quicker look runs only while Quill is listening, which
ends by itself when it goes quiet. Nothing is asked while Numbers is not running, a look never overlaps another, and every
question has a time limit after which its process is killed.

* :class:`NumbersLink`: the questions and the comparison of two looks; it looks like the LibreOffice link (``find``, ``request``,
  ``connected``) so the same bridge code works over it.
* :class:`NumbersBridge`: the workbook bridge over the open document. Its drop-down rules come from the file (Numbers
  does not let a script read a pop-up menu's items); its headings, sheets, lists kept in cells and every row come live.

Nothing here raises: a failed question is "not answering", and the caller works on the file instead. Every value goes to the
script as JSON in one argument, never as script text.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import pathlib
import subprocess
import threading
from typing import Callable

from openpyxl.worksheet.datavalidation import DataValidation

from quill.bridge.base import BridgeError
from quill.bridge.filters import ColumnFilter
from quill.bridge.libreoffice_bridge import LibreOfficeBridge, LibreOfficeGrid, build_workbook
from quill.bridge.libreoffice_mirror import change_fields
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.diagnostics import exc_kind, syslog

log = logging.getLogger("quill.numbers")

#: Seconds one question may take (a big table can keep Numbers busy a moment).
ASK_TIMEOUT_S = 8.0
#: Seconds Numbers may take to open a file again.
RELOAD_TIMEOUT_S = 20.0
#: Failed looks in a row before the link is called lost.
LOST_AFTER = 3
#: ``Called with (kind, document name, sheet)``: ``opened``, ``closed``, ``sheet``, ``changed`` or ``lost``.
EventCallback = Callable[[str, str, str], None]
Runner = Callable[[list[str], float], tuple[int, str, str]]

#: The script. ``argv[0]`` is the command, ``argv[1]`` its arguments as JSON; the answer is JSON.
SCRIPT = r"""
function titleKey(title) { return title.slice(-8) === ".numbers" ? title.slice(0, -8) : title; }

function findDocument(app, names) {
  const documents = app.documents();
  for (let i = 0; i < documents.length; i++) {
    let title = "";
    try { title = documents[i].name(); } catch (e) { continue; }
    if (names.indexOf(title) >= 0 || names.indexOf(titleKey(title)) >= 0) return documents[i];
  }
  return null;
}

function letters(n) {
  let s = "";
  while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

function plain(v) {
  if (v instanceof Date) {
    const p = (x) => (x < 10 ? "0" : "") + x;
    return {d: v.getFullYear() + "-" + p(v.getMonth() + 1) + "-" + p(v.getDate()) + "T" + p(v.getHours()) + ":" + p(v.getMinutes()) + ":" + p(v.getSeconds())};
  }
  return v === undefined ? null : v;
}

function tableOf(doc, sheetName) {
  let sheet;
  try { sheet = doc.sheets.byName(sheetName); sheet.name(); } catch (e) { sheet = doc.sheets[0]; }
  return sheet.tables[0];
}

function block(table, top, left, rows, cols) {
  const rowCount = table.rowCount(), colCount = table.columnCount();
  const bottom = Math.min(top + rows - 1, rowCount), right = Math.min(left + cols - 1, colCount);
  const out = [];
  for (let r = 0; r < rows; r++) { const line = []; for (let c = 0; c < cols; c++) line.push(null); out.push(line); }
  if (bottom < top || right < left) return out;
  const flat = table.ranges[letters(left) + top + ":" + letters(right) + bottom].cells.value();
  const width = right - left + 1;
  for (let i = 0; i < flat.length; i++) {
    const v = plain(flat[i]);
    out[Math.floor(i / width)][i % width] = (v === "" ? null : v);
  }
  return out;
}

function usedSize(table) {
  const rowCount = table.rowCount(), colCount = table.columnCount();
  let rows = 0, cols = 0;
  const head = block(table, 1, 1, Math.min(rowCount, 3), colCount);
  for (let r = 0; r < head.length; r++) for (let c = 0; c < head[r].length; c++) if (head[r][c] !== null) cols = Math.max(cols, c + 1);
  for (let c = 1; c <= Math.min(colCount, 3) && rows < rowCount; c++) {
    const column = table.columns[c - 1].cells.value();
    for (let r = column.length - 1; r >= rows; r--) if (column[r] !== null && column[r] !== "") { rows = Math.max(rows, r + 1); break; }
  }
  return {rows: rows, cols: cols};
}

function stamp(table) {
  const text = JSON.stringify(block(table, 1, 1, 6, Math.min(table.columnCount(), 60))) + table.rowCount() + "x" + table.columnCount();
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
  return h;
}

// Text colours, for a search that fades the rows that do not match (Numbers has no way to hide rows). Colours are read as
// fractions (0 to 1) and set as 0 to 65535; the colours are remembered as runs (index, length, colour) so that clearing the
// search puts every cell's own colour back exactly.
function toSet(colour) {
  if (colour === null || colour === undefined) return null;
  const big = colour.some((x) => x > 1);
  return colour.map((x) => (big ? Math.round(x) : Math.round(x * 65535)));
}

function addressOf(top, left, bottom, right) { return letters(left) + top + ":" + letters(right) + bottom; }

function paintIndexes(table, top, left, cols, start, length, colour) {
  // Paint cells start .. start+length-1 of the block (row-major) in at most three rectangles.
  if (colour === null) return;
  let at = start;
  const end = start + length;
  while (at < end) {
    const row = Math.floor(at / cols), col = at % cols;
    if (col === 0 && end - at >= cols) {                                          // whole rows: one rectangle
      const whole = Math.floor((end - at) / cols);
      table.ranges[addressOf(top + row, left, top + row + whole - 1, left + cols - 1)].textColor = colour;
      at += whole * cols;
    } else {                                                                      // the rest of one row
      const last = Math.min(end - at, cols - col);
      table.ranges[addressOf(top + row, left + col, top + row, left + col + last - 1)].textColor = colour;
      at += last;
    }
  }
}

function runsOf(colours) {
  const runs = [];
  for (let i = 0; i < colours.length; i++) {
    const key = JSON.stringify(colours[i]);
    if (runs.length && runs[runs.length - 1].key === key) runs[runs.length - 1].length++;
    else runs.push({index: i, length: 1, key: key, colour: toSet(colours[i])});
  }
  return runs.map((r) => ({index: r.index, length: r.length, colour: r.colour}));
}

function paintRuns(table, top, left, cols, runs, rowsOnly) {
  // rowsOnly: only the cells of those rows (block row numbers, 0-based); null: every cell.
  for (let i = 0; i < runs.length; i++) {
    const run = runs[i];
    if (rowsOnly === null) { paintIndexes(table, top, left, cols, run.index, run.length, run.colour); continue; }
    const first = Math.floor(run.index / cols), last = Math.floor((run.index + run.length - 1) / cols);
    for (let row = first; row <= last; row++) {
      if (rowsOnly.indexOf(row) < 0) continue;
      const from = Math.max(run.index, row * cols), to = Math.min(run.index + run.length, (row + 1) * cols);
      paintIndexes(table, top, left, cols, from, to - from, run.colour);
    }
  }
}

function writeCell(doc, app, change) {
  const table = tableOf(doc, change[0]);
  const rowNo = change[1], colNo = change[2], kind = change[3], text = change[4];
  if (table.rowCount() < rowNo) table.rowCount = rowNo;
  if (table.columnCount() < colNo) table.columnCount = colNo;
  const cell = table.rows[rowNo - 1].cells[colNo - 1];
  if (kind === "e") app.clear(cell);
  else if (kind === "n") cell.value = parseFloat(text);
  else if (kind === "d") { const b = text.split("-"); cell.value = new Date(parseInt(b[0], 10), parseInt(b[1], 10) - 1, parseInt(b[2], 10)); }
  else cell.value = text;
}

function handle(command, args) {
  const app = Application("Numbers");
  if (!app.running()) return JSON.stringify({ok: true, running: false, docs: []});
  if (command === "state") {
    const docs = [], documents = app.documents();
    for (let i = 0; i < documents.length; i++) {
      try {
        const d = documents[i], title = d.name(), sheets = d.sheets.name(), sheet = d.activeSheet().name();
        const doc = {url: titleKey(title), title: title, sheet: sheet, sheets: sheets};
        if (args.deep) doc.stamp = stamp(tableOf(d, sheet));                    // (reading cells: only the slower look does it)
        docs.push(doc);
      } catch (e) {}
    }
    return JSON.stringify({ok: true, running: true, docs: docs});
  }
  const doc = findDocument(app, args.urls || []);
  if (doc === null) return JSON.stringify({ok: false, error: "nodoc"});
  if (command === "used") {
    const size = usedSize(tableOf(doc, args.sheet));
    return JSON.stringify({ok: true, rows: size.rows, cols: size.cols});
  }
  if (command === "read") {
    return JSON.stringify({ok: true, cells: block(tableOf(doc, args.sheet), args.top, args.left, args.rows, args.cols)});
  }
  if (command === "apply") {
    for (let i = 0; i < args.changes.length; i++) writeCell(doc, app, args.changes[i]);
    return JSON.stringify({ok: true});
  }
  if (command === "fade") {
    const table = tableOf(doc, args.sheet);
    let selection = null;
    try { selection = table.selectionRange().name(); } catch (e) {}                 // (painting moves the selection: remember it)
    const flat = table.ranges[addressOf(args.top, args.left, args.top + args.rows - 1, args.left + args.cols - 1)].cells.textColor();
    const runs = runsOf(flat);
    table.ranges[addressOf(args.top, args.left, args.top + args.rows - 1, args.left + args.cols - 1)].textColor = args.fade;
    paintRuns(table, args.top, args.left, args.cols, runs, args.keep.map((r) => r - args.top));
    if (args.jump) table.selectionRange = table.ranges[addressOf(args.jump, args.left, args.jump, args.left)];
    return JSON.stringify({ok: true, runs: runs, selection: selection});
  }
  if (command === "unfade") {
    const table = tableOf(doc, args.sheet);
    paintRuns(table, args.top, args.left, args.cols, args.runs, null);
    if (args.selection) { try { table.selectionRange = table.ranges[args.selection]; } catch (e) {} }
    return JSON.stringify({ok: true});
  }
  if (command === "dump") {
    const sheets = [], list = doc.sheets();
    for (let i = 0; i < list.length; i++) {
      const table = list[i].tables[0], size = usedSize(table);
      sheets.push({name: list[i].name(), rows: size.rows, cols: size.cols,
                   cells: size.rows && size.cols ? block(table, 1, 1, Math.min(size.rows, 5000), Math.min(size.cols, 100)) : []});
    }
    return JSON.stringify({ok: true, sheets: sheets});
  }
  if (command === "reload") {
    // Close this document without saving and open the file again, so Numbers imports it afresh (a pop-up menu's items can
    // only be set that way). The caller has checked that nothing in the document is missing from the file.
    const sheetName = doc.activeSheet().name(), stem = titleKey(doc.name());
    app.close(doc, {saving: "no"});
    app.open(Path(args.path));
    const waiter = Application.currentApplication();
    waiter.includeStandardAdditions = true;
    for (let tries = 0; tries < 75; tries++) {                                  // (up to about 15 seconds)
      const again = findDocument(app, [stem, stem + ".numbers"]);
      if (again !== null) {
        try { again.activeSheet = again.sheets.byName(sheetName); } catch (e) {}
        return JSON.stringify({ok: true});
      }
      waiter.delay(0.2);
    }
    return JSON.stringify({ok: false, error: "the file did not open"});
  }
  if (command === "snapshot") {
    const sheets = [], list = doc.sheets();
    for (let i = 0; i < list.length; i++) {
      const name = list[i].name(), table = list[i].tables[0], size = usedSize(table);
      sheets.push({name: name, used_rows: size.rows, used_cols: size.cols,
                   block: size.rows && size.cols ? block(table, 1, 1, Math.min(size.rows, 30), Math.min(size.cols, 60)) : [],
                   left: size.rows && size.cols ? block(table, 1, 1, Math.min(size.rows, 300), Math.min(size.cols, 3)) : [],
                   validations: []});
    }
    return JSON.stringify({ok: true, sheets: sheets, names: []});
  }
  return JSON.stringify({ok: false, error: "unknown command"});
}

function answer(command, args) {
  try { return handle(command, args); } catch (e) { return JSON.stringify({ok: false, error: String(e.message || e).slice(0, 120)}); }
}

function run(argv) {
  return answer(argv[0], JSON.parse(argv[1] || "{}"));
}
"""

#: The same script as a worker: it answers one request per line on standard input (``{"c": command, "a": arguments}``) with one
#: line of JSON, and leaves when standard input closes. Starting ``osascript`` costs about 0.15 s of processor time and answering
#: costs about 0.002 s, so the link keeps one of these while it is in use and lets it go when it is not (see :class:`ScriptWorker`).
WORKER_SCRIPT = SCRIPT.replace("function run(argv) {\n  return answer(argv[0], JSON.parse(argv[1] || \"{}\"));\n}\n", "") + r"""
ObjC.import("Foundation");
function run() {
  const input = $.NSFileHandle.fileHandleWithStandardInput;
  const output = $.NSFileHandle.fileHandleWithStandardOutput;
  let pending = "";
  for (;;) {
    const data = input.availableData;
    if (Number(data.length) === 0) break;                              // Quill closed the pipe (or quit): leave
    pending += $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding).js;
    let at;
    while ((at = pending.indexOf("\n")) >= 0) {
      const line = pending.slice(0, at);
      pending = pending.slice(at + 1);
      let reply;
      try { const request = JSON.parse(line); reply = answer(request.c, request.a || {}); }
      catch (e) { reply = JSON.stringify({ok: false, error: "bad request"}); }
      output.writeData($.NSString.alloc.initWithUTF8String(reply + "\n").dataUsingEncoding($.NSUTF8StringEncoding));
    }
  }
  return "";
}
"""


def _system(args: list[str], timeout: float) -> tuple[int, str, str]:
    """Run *args* (never through a shell) with a time limit."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)   # noqa: S603
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


class ScriptWorker:
    """One ``osascript`` process kept while Numbers is being asked things, so a question costs about 2 ms of processor time
    instead of the 150 ms a new process costs.

    It is started by the first question, restarted if it died, killed when a question outlives its time limit (so a stuck
    Numbers can never hang Quill), let go of after :data:`IDLE_S` seconds without a question (one single-shot timer, re-armed
    by each question; nothing runs in between) and ends by itself when Quill quits, because its input closes.
    """

    #: Seconds without a question after which the process is let go of.
    IDLE_S = 45.0

    def __init__(self, command: list[str] | None = None, idle_s: float | None = None) -> None:
        self._command = command or ["osascript", "-l", "JavaScript", "-e", WORKER_SCRIPT]
        self._idle_s = self.IDLE_S if idle_s is None else idle_s
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._idle: threading.Timer | None = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ask(self, command: str, arguments: dict, timeout: float) -> str | None:
        """One question; the answer line, or None (no process, or no answer in time: the process is then killed)."""
        with self._lock:
            try:
                if not self.alive:
                    self._proc = subprocess.Popen(self._command,                                              # noqa: S603
                                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                line = json.dumps({"c": command, "a": arguments}).encode("utf-8") + b"\n"
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
                reply = self._read_line(timeout)
            except (OSError, ValueError):
                reply = None
            if reply is None:
                self._kill()
            else:
                self._rearm()
            return reply

    def close(self) -> None:
        with self._lock:
            self._kill()

    # ------------------------------------------------------------------ #

    def _read_line(self, timeout: float) -> str | None:
        import select
        import time
        fd, deadline, data = self._proc.stdout.fileno(), time.monotonic() + timeout, b""
        while b"\n" not in data:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                return None
            chunk = os.read(fd, 65536)
            if not chunk:
                return None                                            # the process ended
            data += chunk
        return data.split(b"\n", 1)[0].decode("utf-8", "replace")

    def _rearm(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
        self._idle = threading.Timer(self._idle_s, self.close)
        self._idle.daemon = True
        self._idle.start()

    def _kill(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        proc, self._proc = self._proc, None
        if proc is None:
            return
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


class WorkerRunner:
    """The runner the link uses: the worker for questions, one ``osascript`` launch each when the worker will not answer."""

    def __init__(self, worker: ScriptWorker | None = None) -> None:
        self.worker = worker or ScriptWorker()

    def __call__(self, args: list[str], timeout: float) -> tuple[int, str, str]:
        command, arguments = args[-2], args[-1]
        try:
            reply = self.worker.ask(command, json.loads(arguments), timeout)
        except ValueError:
            reply = None
        if reply is not None:
            return 0, reply, ""
        return _system(args, timeout)                                  # (one launch for this question)

    def close(self) -> None:
        self.worker.close()


def _numbers_running() -> bool:
    """Is Numbers running? (Read from the system's list of applications: no process is started, and Numbers is never started.)"""
    from quill.platforms.macos.processes import running_executables
    names = running_executables()
    return True if names is None else "numbers" in names


def document_names(path: str | os.PathLike) -> list[str]:
    """The names Numbers may give the document of *path*: an imported workbook is named by its file name without the
    extension, and once edited ``name.numbers``."""
    stem = pathlib.Path(path).stem
    return [stem, stem + ".numbers"]


class NumbersLink:
    """Questions to Numbers, and what is open there as of the last look.

    Args:
        on_event: Called, on whatever thread made the look, for every piece of news; keep it quick (the app hands it to the window's thread).
        runner: ``runner(args, timeout)`` returning ``(exit code, output, error)`` (tests).
        running: Says whether Numbers runs (tests).
    """

    def __init__(self, on_event: EventCallback | None = None, runner: Runner | None = None,
                 running: Callable[[], bool] | None = None) -> None:
        self.on_event = on_event
        self._run = runner or WorkerRunner()
        self._running = running or _numbers_running
        self.docs: dict[str, dict] = {}
        self._connected = False
        self._failures = 0
        self._lock = threading.Lock()
        self._looking = threading.Lock()                 # one look at a time
        self._held = 0                                    # while above zero the looks are taken but no news is made (see hold)

    # ------------------------------------------------------------------ #

    @property
    def connected(self) -> bool:
        """Is Numbers answering? (False while it is not running, and after it stopped answering.)"""
        return self._connected

    def hold(self):
        """``with link.hold():`` -- while it lasts, looks update what is known but say nothing, so a document that Quill itself
        closes and opens again is not reported as one that vanished."""
        from contextlib import contextmanager

        @contextmanager
        def held():
            with self._lock:
                self._held += 1
            try:
                yield
            finally:
                with self._lock:
                    self._held -= 1
        return held()

    def close(self) -> None:
        """Let go of the worker process (Quill is quitting, or Numbers is not wanted any more)."""
        closer = getattr(self._run, "close", None)
        if closer is not None:
            closer()

    def find(self, urls: list[str]) -> dict | None:
        """What is known of the open document called any of *urls* (``{"url", "sheet", "sheets", "modified"}``), or None."""
        for name in urls:
            key = name[:-len(".numbers")] if name.endswith(".numbers") else name
            if key in self.docs:
                return self.docs[key]
        return None

    def request(self, command: str, timeout: float = ASK_TIMEOUT_S, **fields) -> dict | None:
        """Ask Numbers one thing (the fields travel as JSON); None if it did not answer."""
        if os.environ.get("QUILL_NO_HOSTS") or not self._running():
            return None
        code, out, err = self._run(["osascript", "-l", "JavaScript", "-e", SCRIPT, command, json.dumps(fields)], timeout)
        if code != 0:
            log.debug("numbers did not answer: %s", err.strip())
            return None
        try:
            return json.loads(out)
        except ValueError:
            return None

    # ------------------------------------------------------------------ #

    def look(self, deep: bool = True) -> None:
        """One look at what is open now, and the news that follows from it. Does nothing if Numbers is not running (and says
        so, once, if it just quit) or if another look is still under way. May take a moment: call it off the window's thread.

        *deep*: also read the top rows of the open sheet to notice edits (``changed``). The quick look used while listening
        asks only which documents are open and which sheet each shows, which is all that following a sheet needs."""
        if os.environ.get("QUILL_NO_HOSTS") or not self._looking.acquire(blocking=False):
            return
        try:
            self._look(deep)
        finally:
            self._looking.release()

    def _look(self, deep: bool) -> None:
        if not self._running():
            self._news(None)
            return
        answer = self.request("state", timeout=ASK_TIMEOUT_S, deep=deep)
        if answer is None or not answer.get("ok"):
            self._failures += 1
            if self._failures >= LOST_AFTER:
                self._news(None)
            return
        self._failures = 0
        self._news({d["url"]: d for d in answer.get("docs", []) if d.get("url")})

    def _news(self, now: dict[str, dict] | None) -> None:
        """Compare what is open now with what was, and say the differences. ``None``: Numbers is gone or not answering."""
        events: list[tuple[str, str, str]] = []
        with self._lock:
            before = self.docs
            if self._held:                                       # (Quill is reopening a document: learn the state, tell nobody)
                self.docs, self._connected = (now or {}), now is not None
                return
            if now is None:
                was = self._connected
                self.docs, self._connected = {}, False
                events += [("closed", url, "") for url in before]
                if was:
                    events.append(("lost", "", ""))
            else:
                self._connected = True
                self.docs = now
                for url, doc in now.items():
                    old = before.get(url)
                    if "stamp" not in doc and old is not None:
                        doc["stamp"] = old.get("stamp")                           # (a quick look does not read cells: keep the last reading)
                    if old is None:
                        events.append(("opened", url, doc.get("sheet") or ""))
                    elif old.get("sheet") != doc.get("sheet"):
                        events.append(("sheet", url, doc.get("sheet") or ""))
                    elif old.get("stamp") != doc.get("stamp") or old.get("sheets") != doc.get("sheets"):
                        events.append(("changed", url, doc.get("sheet") or ""))
                events += [("closed", url, "") for url in before if url not in now]
        for event in events:
            if self.on_event is not None:
                try:
                    self.on_event(*event)
                except Exception:                                    # (a listener never stops the watcher)
                    log.debug("a Numbers listener failed", exc_info=True)


class NumbersGrid(LibreOfficeGrid):
    """The cells of an open Numbers document.

    Numbers has no way to hide rows or filter from a script (checked: no filter rules, a row cannot be made smaller than 8
    points, and the table's ``filtered`` flag cannot be turned on). A search therefore **fades** the rows that do not match
    (their text turns grey; every cell's own colour is remembered and put back when the search is cleared) and moves the
    selection to the first match.
    """

    #: Told every cell written, so the bridge can write the same cells to the file (None: nobody listens).
    record: Callable[[tuple[str, int, int, object]], None] | None = None
    #: The grey the rows that do not match are drawn in (0 to 65535 per channel).
    FADE = (40000, 40000, 40000)

    def __init__(self, document) -> None:
        super().__init__(document)
        self._faded: dict[str, dict] = {}                     # per sheet: where the fade is and the colours to put back

    def write(self, sheet: str, row: int, col: int, value: object) -> None:
        super().write(sheet, row, col, value)
        if self.record is not None:
            self.record((sheet, row, col, value))

    def set_autofilter(self, sheet, header_row, first_col, last_col, last_row, criteria: dict[int, ColumnFilter]):
        self.clear_autofilter(sheet)
        count = max(last_row - header_row, 0)
        block = self.read(sheet, header_row + 1, first_col, count, last_col - first_col + 1) if count else []
        keep = [header_row + 1 + i for i, row in enumerate(block)
                if all(flt.matches(row[col - first_col]) for col, flt in criteria.items())]
        if count and keep:
            width = last_col - first_col + 1
            try:
                answer = self._doc.ask("fade", sheet=sheet, top=header_row + 1, left=first_col, rows=count, cols=width,
                                       fade=list(self.FADE), keep=keep, jump=keep[0], timeout=30.0)
                self._faded[sheet] = {"top": header_row + 1, "left": first_col, "cols": width, "runs": answer.get("runs", []),
                                      "selection": answer.get("selection") or ""}
            except BridgeError:
                pass                                          # (a search still counts its matches if the colours cannot be changed)
        return len(keep)

    def clear_autofilter(self, sheet: str) -> None:
        state = self._faded.pop(sheet, None)
        if state is not None:
            try:
                self._doc.ask("unfade", sheet=sheet, top=state["top"], left=state["left"], cols=state["cols"], runs=state["runs"],
                                selection=state["selection"], timeout=30.0)
            except BridgeError:
                pass                                          # (the document may be gone: nothing to put back)

    def get_cursor(self, sheet: str):
        return None

    def set_cursor(self, sheet: str, row: int, col: int) -> None:
        return None


class NumbersBridge(LibreOfficeBridge):
    """The workbook bridge for a file that is open in Numbers, through :class:`NumbersLink`.

    Numbers keeps its own copy of an imported workbook, and the ``.xlsx`` is what the user (and every other program) has, so
    each row goes to both: into the open Numbers document (unsaved there) and into the file, the way the file bridge writes
    it. A file that cannot be written (in use, or lacking the sheet) never stops the dictation; Numbers still has the row.

    Args:
        path: The file (it names the document and is what the Open Spreadsheets list matches).
        link: Returns the link, or None.
    """

    PROGRAM = "Numbers"
    GRID = NumbersGrid

    def __init__(self, path, link) -> None:
        super().__init__(path, link)
        self._pending: list[tuple[str, int, int, object]] = []
        self._file: XlsxBridge | None = None
        self._file_stamp: int | None = None
        self._file_failed = False

    def connect(self, workbook: str | None = None) -> None:
        super().connect(workbook)
        self._pending.clear()
        self._file = None
        self._grid.record = self._pending.append

    def _after_write(self) -> None:
        """The cells just written to Numbers are written to the file too (one save for all of them)."""
        cells, self._pending[:] = list(self._pending), []
        if not cells or self._path is None:
            return
        try:
            stamp = self._path.stat().st_mtime_ns
            if self._file is None or stamp != self._file_stamp:               # (the file changed under us: read it again)
                self._file = XlsxBridge(self._path)
                self._file.connect()
            grid = self._file._grid
            for sheet, row, col, value in cells:
                grid.write(sheet, row, col, value)
            grid.changes.clear()
            self._file._after_write()
            self._file_stamp = self._path.stat().st_mtime_ns
            self._file_failed = False
        except Exception as exc:                                              # (never stops the dictation: Numbers has the row)
            self._file = None
            if not self._file_failed:
                self._file_failed = True
                log.warning("the rows could not be saved to the file: %s", exc_kind(exc))
                syslog().info("Rows could not be saved to the file beside Numbers")

    def disconnect(self) -> None:
        super().disconnect()
        self._file = None

    @property
    def addresses(self) -> list[str]:
        return document_names(self._path) if self._path else []

    def _load_structure(self) -> None:
        snapshot = self._doc.ask("snapshot", timeout=15.0)
        workbook = build_workbook(snapshot)
        self._add_rules_from_file(workbook)
        from quill.bridge.introspect import discover
        self._discovery = discover(workbook, self._vertical, self._headings_row)

    def _add_rules_from_file(self, workbook) -> None:
        """Numbers will not say what a pop-up menu holds, so the drop-down rules (and names) come from the saved file."""
        if self._path is None or not self._path.is_file():
            return
        try:
            import openpyxl
            saved = openpyxl.load_workbook(self._path)
        except Exception:                                              # (no file, or one that will not open: the live cells still work)
            return
        for ws in saved.worksheets:
            if ws.title not in workbook.sheetnames:
                continue
            target = workbook[ws.title]
            for rule in ws.data_validations.dataValidation:
                if rule.type == "list" and rule.formula1:
                    target.add_data_validation(copy.copy(rule))
        for name, defined in saved.defined_names.items():
            if name not in workbook.defined_names:
                workbook.defined_names[name] = copy.copy(defined)

    #: Told, in a sentence for the person, when something about Numbers is worth saying (the app puts it in the log).
    notify: Callable[[str], None] | None = None

    def _add_inline(self, source, value: str) -> None:
        """Add *value* to a typed drop-down list, so that Numbers shows it at once.

        Numbers' scripting cannot read or change what a pop-up menu holds (checked: its dictionary names the format "pop up
        menu" and nothing more), but Numbers builds its menus when it opens a file. So the list is changed in the file's rule,
        and then, if the open document holds nothing that the file lacks, Numbers is made to open the file again: the
        document reappears on the same sheet with the new item in its menu. If the document has changes of its own (the
        person typed in Numbers), reopening would lose them, so it is left alone and the menu shows the value next time the
        file is opened.
        """
        if self._path is None or not self._path.is_file():
            raise BridgeError(f"Quill can't change the '{source.column}' menu while the file isn't saved. "
                              f"Add '{value}' to the menu in Numbers.")
        self._after_write()                                                # (rows waiting for the file go first)
        try:
            file = XlsxBridge(self._path)
            file.connect()
            file._discovery.sources[source.column] = source
            file._add_inline(source, value)
            changed = any(rule.type == "list" and (rule.formula1 or "").lstrip("=").strip() == '"' + ",".join([*source.items, value]) + '"'
                          for ws in file._wb.worksheets for rule in ws.data_validations.dataValidation)
            if not changed:
                raise BridgeError(f"The '{source.column}' menu in the file is not the one Numbers shows. Add '{value}' to the menu in Numbers.")
            file._after_write()
        except OSError as exc:
            raise BridgeError(f"Couldn't save the '{source.column}' menu to the file ({exc.strerror or exc}).") from exc
        self._discovery.sources[source.column] = type(source)(column=source.column, items=(*source.items, value))
        self._show_menu_in_numbers(source.column, value)

    def _tell(self, message: str) -> None:
        if self.notify is not None:
            self.notify(message)

    def _show_menu_in_numbers(self, column: str, value: str) -> None:
        """Make the open document show the file's new menu (see :meth:`_add_inline`)."""
        link = self._link()
        if link is None or self._doc is None:
            return
        if not self._document_matches_file():
            self._tell(f"Added '{value}' to the {column} menu in the file. Numbers has changes of its own that the file lacks, "
                       "so it was not reopened: the menu shows the value the next time the file is opened in Numbers.")
            return
        hold = link.hold()
        with hold:
            try:
                answer = self._doc.ask("reload", timeout=RELOAD_TIMEOUT_S, path=str(self._path))
            except BridgeError as exc:
                self._tell(f"Added '{value}' to the {column} menu in the file, but Numbers could not reopen it ({exc}). "
                           "The menu shows the value the next time the file is opened.")
                return
            link.look()
        self._stamp += 1
        if not answer.get("ok"):
            self._tell(f"Added '{value}' to the {column} menu in the file, but Numbers did not reopen it.")

    def _document_matches_file(self) -> bool:
        """Does the open document hold exactly what the file holds (so reopening the file loses nothing)? Cells the file keeps
        as formulas are not compared; anything else that differs says no."""
        try:
            import openpyxl
            saved = openpyxl.load_workbook(self._path)
            live = self._doc.ask("dump", timeout=30.0)["sheets"]
        except Exception:
            return False
        if [s["name"] for s in live] != saved.sheetnames:
            return False
        for sheet in live:
            ws = saved[sheet["name"]]
            for r, row in enumerate(sheet["cells"], 1):
                for c, cell in enumerate(row, 1):
                    if not _same_cell(_plain_cell(cell), ws.cell(row=r, column=c).value):
                        return False
            if ws.max_row > max(sheet["rows"], 1) and any(ws.cell(row=r, column=c).value not in (None, "")
                                                         for r in range(sheet["rows"] + 1, ws.max_row + 1)
                                                         for c in range(1, ws.max_column + 1)):
                return False                                               # (the file has rows Numbers lacks)
        return True


def _plain_cell(value):
    import datetime as dt
    if isinstance(value, dict) and "d" in value:
        return dt.datetime.fromisoformat(value["d"])
    return value


def _same_cell(live, saved) -> bool:
    import datetime as dt
    if isinstance(saved, str) and saved.startswith("="):
        return True                                                         # (a formula: the document shows its result, not the formula)
    blank = (None, "")
    if live in blank or saved in blank:
        return live in blank and saved in blank
    if isinstance(saved, (dt.datetime, dt.date)) or isinstance(live, dt.datetime):
        a = live.date() if isinstance(live, dt.datetime) else live
        b = saved.date() if isinstance(saved, dt.datetime) else saved
        return a == b
    if isinstance(live, (int, float)) and isinstance(saved, (int, float)) and not isinstance(live, bool) and not isinstance(saved, bool):
        return abs(float(live) - float(saved)) < 1e-9
    return str(live).strip() == str(saved).strip()


__all__ = ["NumbersLink", "NumbersBridge", "NumbersGrid", "document_names", "change_fields", "DataValidation"]
