"""Live editing in Numbers: every cell Quill writes to the file is also written into the open Numbers document.

Quill works on a spreadsheet *file*. Numbers shows its own copy of that file, which it only refreshes when the file is
loaded again (and each reload re-imports the workbook, which makes Numbers show its "may look different" warning). So
that rows appear in Numbers as each turn ends, the cells that were just written are also set in the open document
through scripting (JavaScript for Automation). The file is still written first and stays the source of truth; Numbers is shown the same cells.

Nothing here may raise. The script gets everything as separate arguments (never spliced into its text), so no value
can run as a script. Numbers is never started by this: if it is not running there is nothing to show.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import pathlib
import subprocess
from typing import Callable

from quill.bridge.mirror import MirrorResult   # (the answer type is shared; re-exported here)

log = logging.getLogger("quill.numbers")

#: Seconds the AppleScript may take (Numbers can be busy opening a big file).
TIMEOUT_S = 15
#: Seconds a look (is the document open? which sheet?) may take: it repeats every few seconds, so it gives up sooner.
QUERY_TIMEOUT_S = 5
#: Separates the fields of one cell in an argument (never appears in cell text).
FIELD = "\x1f"

Runner = Callable[[list[str]], tuple[int, str, str]]
"""Runs a command and returns ``(exit code, standard output, standard error)``."""

#: How the scripts are run. They are JavaScript for Automation, not AppleScript: the Numbers that ships now (Numbers
#: Creator Studio) answers AppleScript's ``repeat with d in documents`` with nothing at all, but answers the same
#: questions through JavaScript, and so does the older Numbers.
OSASCRIPT = ["osascript", "-l", "JavaScript", "-e"]

#: Shared by the scripts: finds the open document called ``docName`` (Numbers names an imported workbook without its
#: extension and, once edited, ``name.numbers``).
_FIND_DOCUMENT = r"""
function findDocument(app, docName) {
  const documents = app.documents();
  for (let i = 0; i < documents.length; i++) {
    let title = "";
    try { title = documents[i].name(); } catch (e) { continue; }
    if (title === docName || title.indexOf(docName + ".") === 0) return documents[i];
    if (title.slice(-8) === ".numbers" && title.slice(0, -8).replace(/ \d+$/, "") === docName) return documents[i];   // "name 2.numbers"
  }
  return null;
}
"""

#: Takes the document's file name as argument 1, then one argument per cell: sheet, row, column, kind, text.
SCRIPT = _FIND_DOCUMENT + r"""
function run(argv) {
  const app = Application("Numbers");
  if (!app.running()) return "notrunning";
  const target = findDocument(app, argv[0]);
  if (target === null) return "nodoc";
  for (let n = 1; n < argv.length; n++) {
    const fields = argv[n].split("\u001f");
    const sheetName = fields[0];
    const rowNo = parseInt(fields[1], 10);
    const colNo = parseInt(fields[2], 10);
    const kind = fields[3];
    const text = fields.length > 4 ? fields[4] : "";
    let sheet;
    try { sheet = target.sheets.byName(sheetName); sheet.name(); } catch (e) { sheet = target.sheets[0]; }
    const table = sheet.tables[0];
    if (table.rowCount() < rowNo) table.rowCount = rowNo;
    if (table.columnCount() < colNo) table.columnCount = colNo;
    const cell = table.rows[rowNo - 1].cells[colNo - 1];
    if (kind === "e") {
      app.clear(cell);
    } else if (kind === "n") {
      cell.value = parseFloat(text);
    } else if (kind === "d") {
      const bits = text.split("-");
      cell.value = new Date(parseInt(bits[0], 10), parseInt(bits[1], 10) - 1, parseInt(bits[2], 10));
    } else {
      cell.value = text;
    }
  }
  return "ok";
}
"""


#: Takes the document's file name as argument 1; answers ``ok`` if Numbers has such a document open (it changes nothing).
PROBE = _FIND_DOCUMENT + r"""
function run(argv) {
  const app = Application("Numbers");
  if (!app.running()) return "notrunning";
  return findDocument(app, argv[0]) === null ? "nodoc" : "ok";
}
"""


#: Takes the document's file name as argument 1; answers ``sheet:<name of the sheet that is open now>`` (it changes nothing).
ACTIVE_SHEET = _FIND_DOCUMENT + r"""
function run(argv) {
  const app = Application("Numbers");
  if (!app.running()) return "notrunning";
  const found = findDocument(app, argv[0]);
  if (found === null) return "nodoc";
  return "sheet:" + found.activeSheet().name();
}
"""


def _system(args: list[str], timeout: float = TIMEOUT_S) -> tuple[int, str, str]:
    """Run *args* (never through a shell) with a time limit (the child is killed and reaped when it runs out)."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)   # noqa: S603
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def cell_argument(sheet: str, row: int, col: int, value: object) -> str:
    """One cell as an argument of the script: ``sheet, row, column, kind, text`` joined by the field separator.

    *kind* is ``s`` (text), ``n`` (number), ``d`` (date) or ``e`` (empty: the cell was cleared).
    """
    if value is None or (isinstance(value, str) and not value):
        kind, text = "e", ""
    elif isinstance(value, bool):
        kind, text = "s", str(value)
    elif isinstance(value, int):
        kind, text = "n", str(value)
    elif isinstance(value, float):
        kind, text = "n", f"{value:.12f}".rstrip("0").rstrip(".") or "0"
    elif isinstance(value, dt.date):      # (a datetime is a date too)
        kind, text = "d", value.strftime("%Y-%m-%d")
    else:
        kind, text = "s", str(value).replace(FIELD, " ")
    return FIELD.join([sheet.replace(FIELD, " "), str(int(row)), str(int(col)), kind, text])


class NumbersMirror:
    """Sets cells in the open Numbers document that holds a file.

    Args:
        runner: Replaces the command runner (tests).
    """

    def __init__(self, runner: Runner | None = None) -> None:
        self._run = runner or _system
        self._ask = runner or (lambda args: _system(args, QUERY_TIMEOUT_S))      # the repeated looks

    @staticmethod
    def document_name(path: str | os.PathLike) -> str:
        """The name Numbers gives the document: an imported workbook or text file is named by its file name without the
        extension (the file's own path is not reported for imported documents), and once edited it becomes
        ``name.numbers``; the script accepts either."""
        return pathlib.Path(path).stem

    def has_document(self, path: str | os.PathLike) -> bool:
        """Does a running Numbers have a document for *path* open? (Asked without changing anything.)"""
        if os.environ.get("QUILL_NO_HOSTS"):
            return False
        code, out, _ = self._ask([*OSASCRIPT, PROBE, self.document_name(path)])
        return code == 0 and out.strip() == "ok"

    def active_sheet(self, path: str | os.PathLike) -> str | None:
        """The name of the sheet open now in the Numbers document for *path* (one small call; None if there is no such
        document, Numbers is not running, or it would not say)."""
        if os.environ.get("QUILL_NO_HOSTS"):
            return None
        code, out, _ = self._ask([*OSASCRIPT, ACTIVE_SHEET, self.document_name(path)])
        text = out.strip()
        return text[len("sheet:"):] if code == 0 and text.startswith("sheet:") and len(text) > 6 else None

    def push(self, path: str | os.PathLike, changes: list[tuple[str, int, int, object]]) -> MirrorResult:
        """Show *changes* (``(sheet, row, column, value)`` in sheet coordinates) in the Numbers document for *path*."""
        if not changes:
            return MirrorResult(True, "ok")
        if os.environ.get("QUILL_NO_HOSTS"):
            return MirrorResult(False, "disabled")
        args = [*OSASCRIPT, SCRIPT, self.document_name(path)]
        args += [cell_argument(sheet, row, col, value) for sheet, row, col, value in changes]
        code, out, err = self._run(args)
        text = out.strip()
        if code == 0 and text == "ok":
            return MirrorResult(True, "ok")
        if code == 0 and text in ("notrunning", "nodoc"):
            return MirrorResult(False, text)
        lowered = err.lower()
        if "-1743" in err or "not authorized" in lowered or "not allowed" in lowered:
            return MirrorResult(False, "denied", err.strip())
        log.debug("numbers mirror failed: %s %s", out, err)
        return MirrorResult(False, "error", (err or out).strip())
