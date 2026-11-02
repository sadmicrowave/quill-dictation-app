"""Live editing in Numbers: every cell Quill writes to the file is also written into the open Numbers document.

Quill works on a spreadsheet *file*. Numbers shows its own copy of that file, which it only refreshes when the file is
loaded again (and each reload re-imports the workbook, which makes Numbers show its "may look different" warning). So
that rows appear in Numbers as each turn ends, the cells that were just written are also set in the open document
through AppleScript. The file is still written first and stays the source of truth; Numbers is shown the same cells.

Nothing here may raise. The script gets everything as separate arguments (never spliced into its text), so no value
can run as AppleScript. Numbers is never started by this: if it is not running there is nothing to show.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import pathlib
import subprocess
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("quill.numbers")

#: Seconds the AppleScript may take (Numbers can be busy opening a big file).
TIMEOUT_S = 15
#: Separates the fields of one cell in an argument (never appears in cell text).
FIELD = "\x1f"

Runner = Callable[[list[str]], tuple[int, str, str]]
"""Runs a command and returns ``(exit code, standard output, standard error)``."""

#: Takes the document's file name as argument 1, then one argument per cell: sheet, row, column, kind, text.
SCRIPT = r'''
on run argv
  if application "Numbers" is not running then return "notrunning"
  set docName to item 1 of argv
  tell application "Numbers"
    set targetDoc to missing value
    repeat with oneDoc in documents
      try
        set docTitle to name of oneDoc
        if docTitle is docName or docTitle starts with (docName & ".") then
          set targetDoc to oneDoc
          exit repeat
        end if
      end try
    end repeat
    if targetDoc is missing value then return "nodoc"
    repeat with n from 2 to (count of argv)
      set fields to my splitFields(item n of argv)
      set sheetName to item 1 of fields
      set rowNo to (item 2 of fields) as integer
      set colNo to (item 3 of fields) as integer
      set fieldKind to item 4 of fields
      set fieldText to ""
      if (count of fields) > 4 then set fieldText to item 5 of fields
      tell targetDoc
        set sheetRef to missing value
        try
          set sheetRef to sheet sheetName
        end try
        if sheetRef is missing value then set sheetRef to sheet 1
        tell sheetRef
          tell table 1
            if (row count) < rowNo then set row count to rowNo
            if (column count) < colNo then set column count to colNo
            if fieldKind is "e" then
              set value of cell colNo of row rowNo to missing value
            else if fieldKind is "n" then
              set value of cell colNo of row rowNo to my parseNumber(fieldText)
            else if fieldKind is "d" then
              set value of cell colNo of row rowNo to my parseDate(fieldText)
            else
              set value of cell colNo of row rowNo to fieldText
            end if
          end tell
        end tell
      end tell
    end repeat
  end tell
  return "ok"
end run

on splitFields(someText)
  set saved to AppleScript's text item delimiters
  set AppleScript's text item delimiters to (ASCII character 31)
  set pieces to text items of someText
  set AppleScript's text item delimiters to saved
  return pieces
end splitFields

on parseNumber(someText)
  set isNegative to false
  if someText starts with "-" then
    set isNegative to true
    set someText to text 2 thru -1 of someText
  end if
  set dotAt to offset of "." in someText
  if dotAt is 0 then
    set total to (someText as integer) as real
  else
    set wholePart to 0
    if dotAt > 1 then set wholePart to (text 1 thru (dotAt - 1) of someText) as integer
    set fractionText to text (dotAt + 1) thru -1 of someText
    set total to wholePart as real
    if (length of fractionText) > 0 then set total to total + ((fractionText as integer) / (10 ^ (length of fractionText)))
  end if
  if isNegative then set total to -total
  return total
end parseNumber

on parseDate(someText)
  set saved to AppleScript's text item delimiters
  set AppleScript's text item delimiters to "-"
  set bits to text items of someText
  set AppleScript's text item delimiters to saved
  set theDate to current date
  set day of theDate to 1
  set year of theDate to ((item 1 of bits) as integer)
  set month of theDate to ((item 2 of bits) as integer)
  set day of theDate to ((item 3 of bits) as integer)
  set time of theDate to 0
  return theDate
end parseDate
'''


@dataclass(frozen=True)
class MirrorResult:
    """How an attempt to show cells in Numbers went."""

    ok: bool
    reason: str = ""
    """``"ok"``, ``"notrunning"``, ``"nodoc"`` (Numbers has no such document open), ``"denied"`` (Quill may not control
    Numbers), ``"disabled"`` (the system is not asked, as in tests) or ``"error"``."""
    detail: str = ""


def _system(args: list[str]) -> tuple[int, str, str]:
    """Run *args* (never through a shell) with a time limit."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT_S, check=False)   # noqa: S603
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
    elif isinstance(value, dt.datetime):
        kind, text = "d", value.strftime("%Y-%m-%d")
    elif isinstance(value, dt.date):
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

    @staticmethod
    def document_name(path: str | os.PathLike) -> str:
        """The name Numbers gives the document: an imported workbook or text file is named by its file name without the
        extension (the file's own path is not reported for imported documents), and once edited it becomes
        ``name.numbers``; the script accepts either."""
        return pathlib.Path(path).stem

    def push(self, path: str | os.PathLike, changes: list[tuple[str, int, int, object]]) -> MirrorResult:
        """Show *changes* (``(sheet, row, column, value)`` in sheet coordinates) in the Numbers document for *path*."""
        if not changes:
            return MirrorResult(True, "ok")
        if os.environ.get("QUILL_NO_HOSTS"):
            return MirrorResult(False, "disabled")
        args = ["osascript", "-e", SCRIPT, self.document_name(path)]
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
