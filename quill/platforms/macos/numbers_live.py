"""The live link to Numbers: Quill works in the document as it is open in Numbers, saved or not.

Numbers cannot tell anyone what happens in it, and it keeps no connection open, so this is the Numbers counterpart of
:mod:`quill.bridge.libreoffice_live` built the other way round: a small JavaScript for Automation script answers one
question per launch (about 80 ms), and a watcher thread asks one cheap question a second while Numbers runs, then turns
the differences into the same news LibreOffice sends (``opened``, ``closed``, ``sheet``, ``changed``, ``lost``).

* :class:`NumbersLink`: the watcher and the questions; it looks like the LibreOffice link (``find``, ``request``,
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
#: Seconds between two looks at what is open in Numbers.
POLL_S = 1.0
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

function run(argv) {
  const app = Application("Numbers");
  if (!app.running()) return JSON.stringify({ok: true, running: false, docs: []});
  const args = JSON.parse(argv[1] || "{}");
  const command = argv[0];
  if (command === "state") {
    const docs = [], documents = app.documents();
    for (let i = 0; i < documents.length; i++) {
      try {
        const d = documents[i], title = d.name(), sheets = d.sheets.name(), sheet = d.activeSheet().name();
        docs.push({url: titleKey(title), title: title, sheet: sheet, sheets: sheets, modified: d.modified(), stamp: stamp(tableOf(d, sheet))});
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
"""


def _system(args: list[str], timeout: float) -> tuple[int, str, str]:
    """Run *args* (never through a shell) with a time limit."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)   # noqa: S603
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


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
    """Questions to Numbers, and what is open there, kept up to date by a watcher thread.

    Args:
        on_event: Called on the watcher thread for every piece of news; keep it quick (the app hands it to the window's thread).
        runner: ``runner(args, timeout)`` returning ``(exit code, output, error)`` (tests).
        running: Says whether Numbers runs (tests).
        poll_s: Seconds between looks.
    """

    def __init__(self, on_event: EventCallback | None = None, runner: Runner | None = None,
                 running: Callable[[], bool] | None = None, poll_s: float = POLL_S) -> None:
        self.on_event = on_event
        self._run = runner or _system
        self._running = running or _numbers_running
        self._poll_s = poll_s
        self.docs: dict[str, dict] = {}
        self._connected = False
        self._failures = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #

    @property
    def connected(self) -> bool:
        """Is Numbers answering? (False while it is not running, and after it stopped answering.)"""
        return self._connected

    def start(self) -> None:
        """Begin watching (once)."""
        if os.environ.get("QUILL_NO_HOSTS") or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._watch, name="quill-numbers-link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

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

    def _watch(self) -> None:
        while not self._stop.wait(self._poll_s):
            self.look()

    def look(self) -> None:
        """One look at what is open now (the watcher's step; also called directly in tests)."""
        if not self._running():
            self._news(None)
            return
        answer = self.request("state", timeout=ASK_TIMEOUT_S)
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
    """The cells of an open Numbers document. Numbers has no way to hide rows, so a search only counts what matches."""

    #: Told every cell written, so the bridge can write the same cells to the file (None: nobody listens).
    record: Callable[[tuple[str, int, int, object]], None] | None = None

    def write(self, sheet: str, row: int, col: int, value: object) -> None:
        super().write(sheet, row, col, value)
        if self.record is not None:
            self.record((sheet, row, col, value))

    def set_autofilter(self, sheet, header_row, first_col, last_col, last_row, criteria: dict[int, ColumnFilter]):
        count = max(last_row - header_row, 0)
        block = self.read(sheet, header_row + 1, first_col, count, last_col - first_col + 1) if count else []
        return sum(1 for row in block if all(flt.matches(row[col - first_col]) for col, flt in criteria.items()))

    def clear_autofilter(self, sheet: str) -> None:
        return None

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

    def _add_inline(self, source, value: str) -> None:
        raise BridgeError(f"Numbers does not let Quill change a pop-up menu. Add '{value}' to the '{source.column}' menu in Numbers.")


__all__ = ["NumbersLink", "NumbersBridge", "NumbersGrid", "document_names", "change_fields", "DataValidation"]
