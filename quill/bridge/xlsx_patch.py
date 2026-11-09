"""Writes Quill's changes into an ``.xlsx`` package without rewriting the rest of it.

openpyxl saves a workbook by writing every part again, and it cannot keep the results a spreadsheet program stored
for formulas, so a file saved that way shows "edited with formulas" notices when it is next opened. Here only the
few parts that Quill changed are rewritten, as text edits that leave every other byte as it was: the cells written,
the style table when a cell needs wrapping or a date format, and inline validation lists. Everything else in the
package (stored formula results, charts, pictures, macros, other sheets) is copied across untouched.

What cannot be patched safely (a formula or other special cell being replaced, hidden rows from a filter, a part in
an unexpected layout) raises :class:`UnsupportedError`, and the caller saves the whole workbook the old way instead.
"""

from __future__ import annotations
import copy
import html
import io
import os
import posixpath
import re
import shutil
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path
from xml.sax.saxutils import escape

from defusedxml import ElementTree as SafeET
from openpyxl.styles.numbers import BUILTIN_FORMATS_REVERSE
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.datetime import to_excel

#: Largest part, in bytes, that is read whole into memory to be edited (a hostile package cannot grow it).
MAX_PART_BYTES = 256 * 1024 * 1024

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_ROW = re.compile(r"<row\b([^>]*?)(?:/>|>(.*?)</row>)", re.S)
_CELL = re.compile(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", re.S)
_ATTR = re.compile(r'([\w:]+)="([^"]*)"')
_REF = re.compile(r"^([A-Z]+)(\d+)$")
_XF = re.compile(r"<xf\b([^>]*?)(?:/>|>(.*?)</xf>)", re.S)
_NUMFMT = re.compile(r"<numFmt\b([^>]*?)/>", re.S)
_VALIDATION = re.compile(r"<dataValidation\b[^>]*>.*?</dataValidation>", re.S)
_FORMULA1 = re.compile(r"(<formula1>)(.*?)(</formula1>)", re.S)
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class UnsupportedError(Exception):
    """The change cannot be patched into the package; save the whole workbook instead."""


def patch_package(source: Path, target: Path, wb, cells: Iterable[tuple[str, int, int]],
                  list_edits: Iterable[tuple[str, str]] = ()) -> None:
    """Write *target* as *source* with the *cells* (taken as they now are in *wb*) and *list_edits* applied.

    Args:
        source: The workbook file as it is on disk now.
        target: Where to write (may be *source*: the file is then replaced in one step).
        wb: The openpyxl workbook that holds Quill's cell values.
        cells: (sheet name, row, column) of every cell written since the file was last saved.
        list_edits: (old, new) inline validation list formulas, quotes included, as they were and should now be.

    Raises:
        UnsupportedError: nothing was written; save the whole workbook instead.
        OSError: the target could not be written (another program has it open).
    """
    cells = set(cells)
    list_edits = list(list_edits)
    if not cells and not list_edits:
        raise UnsupportedError("nothing to patch")
    try:
        with zipfile.ZipFile(source) as package:
            parts = _sheet_parts(package)
            changed: dict[str, bytes] = {}
            styles = _Styles(_read(package, "xl/styles.xml"))
            matched = 0
            by_sheet: dict[str, list[tuple[int, int]]] = {}
            for sheet, row, col in cells:
                by_sheet.setdefault(sheet, []).append((row, col))
            for name in {*by_sheet, *(n for n in parts if list_edits)}:
                part = parts.get(name)
                if part is None:
                    raise UnsupportedError(f"no part for sheet {name!r}")
                original = xml = _read(package, part)
                if name in by_sheet:
                    xml = _edit_cells(xml, wb[name], by_sheet[name], styles)
                if list_edits:
                    xml, count = _edit_lists(xml, list_edits)
                    matched += count
                if xml != original:
                    changed[part] = xml.encode("utf-8")
            if list_edits and not matched:
                raise UnsupportedError("the inline list was not found in the sheets")
            if styles.changed:
                changed["xl/styles.xml"] = styles.render().encode("utf-8")
            for part, data in changed.items():
                SafeET.fromstring(data)                               # each part still has to be well-formed XML
            data = _rebuilt(package, changed)
    except (zipfile.BadZipFile, KeyError, FileNotFoundError) as exc:
        raise UnsupportedError(f"the package could not be read: {exc}") from exc
    _replace(target, data, like=source)


def _read(package: zipfile.ZipFile, name: str) -> str:
    info = package.getinfo(name)
    if info.file_size > MAX_PART_BYTES:
        raise UnsupportedError(f"{name} is too large to patch")
    return package.read(info).decode("utf-8-sig")


def _sheet_parts(package: zipfile.ZipFile) -> dict[str, str]:
    """Sheet name -> the package part that holds it."""
    book = SafeET.fromstring(package.read("xl/workbook.xml"))
    rels = SafeET.fromstring(package.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.get("Id"): rel.get("Target", "") for rel in rels.iter(f"{_PKG_REL}Relationship")}
    parts: dict[str, str] = {}
    for sheet in book.iter(f"{_MAIN}sheet"):
        target = targets.get(sheet.get(f"{_REL}id"), "")
        if not target:
            continue
        parts[sheet.get("name", "")] = posixpath.normpath(target.lstrip("/") if target.startswith("/") else f"xl/{target}")
    return parts


# ---------------------------------------------------------------------- cells


def _edit_cells(xml: str, ws, positions: list[tuple[int, int]], styles: "_Styles") -> str:
    """The sheet's XML with each of *positions* rewritten from the cell in *ws*."""
    start = xml.find("<sheetData")
    if start < 0:
        raise UnsupportedError("the sheet has no sheetData")
    open_end = xml.find(">", start)
    if open_end < 0:
        raise UnsupportedError("the sheet data is not well-formed")
    if xml[open_end - 1] == "/":                                      # <sheetData/>: an empty sheet
        head, body, tail = xml[:start], "", xml[open_end + 1:]
        opening, closing = "<sheetData>", "</sheetData>"
    else:
        end = xml.find("</sheetData>", open_end)
        if end < 0:
            raise UnsupportedError("the sheet data is not closed")
        head, body, tail = xml[:start], xml[open_end + 1:end], xml[end + len("</sheetData>"):]
        opening, closing = xml[start:open_end + 1], "</sheetData>"

    wanted: dict[int, dict[int, tuple[int, int]]] = {}
    for row, col in positions:
        wanted.setdefault(row, {})[col] = (row, col)

    out: list[str] = []
    pos = 0
    last_row = 0
    pending = sorted(wanted)
    for match in _ROW.finditer(body):
        attrs = dict(_ATTR.findall(match.group(1)))
        number = int(attrs.get("r", "0"))
        if number <= last_row:
            raise UnsupportedError("rows are not in order")
        last_row = number
        while pending and pending[0] < number:                        # new rows that belong before this one
            row = pending.pop(0)
            out.append(_new_row(row, wanted[row], ws, styles))
        out.append(body[pos:match.start()])
        pos = match.end()
        if pending and pending[0] == number:
            pending.pop(0)
            out.append(_edit_row(match, attrs, wanted[number], ws, styles))
        else:
            out.append(match.group(0))
    out.append(body[pos:])
    for row in pending:                                               # new rows after the last one
        out.append(_new_row(row, wanted[row], ws, styles))

    result = head + opening + "".join(out) + closing + tail
    return _grow_dimension(result, positions)


def _edit_row(match: re.Match, attrs: dict[str, str], edits: dict[int, tuple[int, int]], ws,
              styles: "_Styles") -> str:
    inner = match.group(2) or ""
    if "<extLst" in inner:
        raise UnsupportedError("a row has extensions")
    tag = match.group(1)
    tag = re.sub(r'\s+spans="[^"]*"', "", tag)                        # (an optional hint; stale once cells move)
    pieces: list[str] = []
    pos = 0
    placed: set[int] = set()
    last_col = 0
    for cell in _CELL.finditer(inner):
        cell_attrs = dict(_ATTR.findall(cell.group(1)))
        ref = _REF.match(cell_attrs.get("r", ""))
        if not ref:
            raise UnsupportedError("a cell has no reference")
        col = column_index_from_string(ref.group(1))
        if col <= last_col:
            raise UnsupportedError("cells are not in order")
        last_col = col
        for new in sorted(c for c in edits if c < col and c not in placed):
            pieces.append(_render(ws, edits[new], None, styles))
            placed.add(new)
        pieces.append(inner[pos:cell.start()])
        pos = cell.end()
        if col in edits:
            if "<f" in (cell.group(2) or ""):
                raise UnsupportedError("a formula cell is being replaced")
            pieces.append(_render(ws, edits[col], cell_attrs.get("s"), styles))
            placed.add(col)
        else:
            pieces.append(cell.group(0))
    pieces.append(inner[pos:])
    for new in sorted(c for c in edits if c not in placed):
        pieces.append(_render(ws, edits[new], None, styles))
    return f"<row{tag}>{''.join(pieces)}</row>"


def _new_row(row: int, edits: dict[int, tuple[int, int]], ws, styles: "_Styles") -> str:
    cells = "".join(_render(ws, edits[col], None, styles) for col in sorted(edits))
    return f'<row r="{row}">{cells}</row>'


def _render(ws, position: tuple[int, int], style: str | None, styles: "_Styles") -> str:
    """One ``<c>`` element for the cell at *position*, keeping the style index it had (None: it had none)."""
    row, col = position
    cell = ws.cell(row=row, column=col)
    ref = f"{get_column_letter(col)}{row}"
    value, kind = cell.value, cell.data_type
    number_format = None
    if value is None:
        body, type_attr = "", ""
    elif kind == "s" and isinstance(value, str):
        text = escape(_ILLEGAL.sub("", value)).replace("\r", "&#13;")
        body, type_attr = f'<is><t xml:space="preserve">{text}</t></is>', ' t="inlineStr"'
    elif kind == "b":
        body, type_attr = f"<v>{int(bool(value))}</v>", ' t="b"'
    elif kind == "n" and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value != value or value in (float("inf"), float("-inf")):
            raise UnsupportedError("a number that is not finite")
        body, type_attr = f"<v>{value!r}</v>", ""
    elif kind == "d":
        try:
            serial = to_excel(value, ws.parent.epoch)
        except (TypeError, ValueError, OverflowError) as exc:
            raise UnsupportedError(f"a date that cannot be stored: {exc}") from exc
        body, type_attr = f"<v>{serial!r}</v>", ""
        number_format = cell.number_format
    else:
        raise UnsupportedError(f"a {kind!r} cell")                         # formulas and errors: openpyxl's own save
    wrap = bool(cell.alignment and cell.alignment.wrap_text)
    index = styles.derive(int(style) if style else 0, wrap=wrap, number_format=number_format)
    attr = f' s="{index}"' if index else ""
    return f'<c r="{ref}"{attr}{type_attr}>{body}</c>' if body else f'<c r="{ref}"{attr}/>'


def _grow_dimension(xml: str, positions: list[tuple[int, int]]) -> str:
    match = re.search(r'<dimension\s+ref="([^"]+)"\s*/>', xml)
    if not match:
        return xml
    first, _, last = match.group(1).partition(":")
    a, b = _REF.match(first), _REF.match(last or first)
    if not a or not b:
        return xml
    top, left = int(a.group(2)), column_index_from_string(a.group(1))
    bottom, right = int(b.group(2)), column_index_from_string(b.group(1))
    top, bottom = min(top, *(r for r, _ in positions)), max(bottom, *(r for r, _ in positions))
    left, right = min(left, *(c for _, c in positions)), max(right, *(c for _, c in positions))
    ref = f"{get_column_letter(left)}{top}:{get_column_letter(right)}{bottom}"
    return xml[:match.start()] + f'<dimension ref="{ref}"/>' + xml[match.end():]


# ---------------------------------------------------------------------- validation lists


def _edit_lists(xml: str, edits: list[tuple[str, str]]) -> tuple[str, int]:
    """*xml* with every inline list validation that reads as an ``old`` formula changed to its ``new`` one."""
    count = 0

    def one(match: re.Match) -> str:
        nonlocal count
        block = match.group(0)
        if 'type="list"' not in block:
            return block

        def formula(found: re.Match) -> str:
            nonlocal count
            current = html.unescape(found.group(2)).lstrip("=").strip()
            first = current
            for old, new in edits:                                    # in the order made (one may build on another)
                if current == old:
                    current = new
            if current == first:
                return found.group(0)
            count += 1
            return found.group(1) + escape(current) + found.group(3)

        return _FORMULA1.sub(formula, block, count=1)

    return _VALIDATION.sub(one, xml), count


# ---------------------------------------------------------------------- styles


class _Styles:
    """The style table (``xl/styles.xml``), able to add a cell format derived from an existing one."""

    def __init__(self, xml: str) -> None:
        self._xml = xml
        block = re.search(r"<cellXfs\b[^>]*>(.*?)</cellXfs>", xml, re.S)
        if not block:
            raise UnsupportedError("no cell formats in the style table")
        self._block = block
        self._xfs = [m.group(0) for m in _XF.finditer(block.group(1))]
        self._known = len(self._xfs)
        self._formats = {int(i): html.unescape(c) for i, c in
                         (( _attr(m.group(1), "numFmtId"), _attr(m.group(1), "formatCode")) for m in _NUMFMT.finditer(xml))
                         if i is not None and c is not None}
        self._new_formats: list[tuple[int, str]] = []
        self._made: dict[tuple[int, bool, str | None], int] = {}

    @property
    def changed(self) -> bool:
        return len(self._xfs) > self._known or bool(self._new_formats)

    def derive(self, base: int, wrap: bool, number_format: str | None) -> int:
        """The index of the format *base* with wrapped text and/or *number_format*, added if it does not exist."""
        if base >= self._known:
            raise UnsupportedError("a cell uses a format that is not in the style table")
        key = (base, wrap, number_format)
        if key in self._made:
            return self._made[key]
        match = _XF.fullmatch(self._xfs[base])
        attrs = dict(_ATTR.findall(match.group(1)))
        inner = match.group(2) or ""
        wanted_format = self._format_id(number_format) if number_format else None
        needs_wrap = wrap and not re.search(r'wrapText="(1|true)"', inner)
        needs_format = wanted_format is not None and int(attrs.get("numFmtId", "0")) != wanted_format
        if not (needs_wrap or needs_format):
            self._made[key] = base
            return base
        if needs_wrap:
            attrs["applyAlignment"] = "1"
            alignment = re.search(r"<alignment\b([^>]*?)/>", inner)
            if alignment:
                kept = re.sub(r'\s+wrapText="[^"]*"', "", alignment.group(1))     # (one may say "false" already)
                inner = inner.replace(alignment.group(0), f'<alignment{kept} wrapText="1"/>')
            else:
                inner = '<alignment wrapText="1"/>' + inner
        if needs_format:
            attrs["numFmtId"] = str(wanted_format)
            attrs["applyNumberFormat"] = "1"
        text = "".join(f' {k}="{v}"' for k, v in attrs.items())
        xf = f"<xf{text}>{inner}</xf>" if inner else f"<xf{text}/>"
        if xf in self._xfs:
            index = self._xfs.index(xf)
        else:
            self._xfs.append(xf)
            index = len(self._xfs) - 1
        self._made[key] = index
        return index

    def _format_id(self, code: str) -> int:
        if code in BUILTIN_FORMATS_REVERSE:
            return BUILTIN_FORMATS_REVERSE[code]
        for number, known in [*self._formats.items(), *self._new_formats]:
            if known == code:
                return number
        number = max([163, *self._formats, *(n for n, _ in self._new_formats)]) + 1
        self._new_formats.append((number, code))
        return number

    def render(self) -> str:
        xml = self._xml
        block = self._block
        count = re.sub(r'count="\d+"', f'count="{len(self._xfs)}"', xml[block.start():block.start(1)], count=1)
        xml = xml[:block.start()] + count + "".join(self._xfs) + xml[block.end(1):]
        if self._new_formats:
            added = "".join(f'<numFmt numFmtId="{n}" formatCode="{escape(c, {chr(34): "&quot;"})}"/>'
                            for n, c in self._new_formats)
            existing = re.search(r"<numFmts\b[^>]*?(/>|>.*?</numFmts>)", xml, re.S)
            total = len(self._formats) + len(self._new_formats)
            if existing:
                block = existing.group(0)
                kept = "" if existing.group(1) == "/>" else block[block.index(">") + 1:-len("</numFmts>")]
                xml = xml[:existing.start()] + f'<numFmts count="{total}">{kept}{added}</numFmts>' + xml[existing.end():]
            else:
                root = re.search(r"<styleSheet\b[^>]*>", xml)
                if not root:
                    raise UnsupportedError("the style table has no root element")
                xml = xml[:root.end()] + f'<numFmts count="{total}">{added}</numFmts>' + xml[root.end():]
        return xml


def _attr(attrs: str, name: str) -> str | None:
    found = re.search(rf'\b{name}="([^"]*)"', attrs)
    return found.group(1) if found else None


# ---------------------------------------------------------------------- writing


def _rebuilt(package: zipfile.ZipFile, changed: dict[str, bytes]) -> bytes:
    """The package as bytes: the changed parts replaced, every other part copied as it was."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        for info in package.infolist():
            data = changed.get(info.filename)
            if data is None:
                if info.file_size > MAX_PART_BYTES:
                    raise UnsupportedError(f"{info.filename} is too large to copy")
                data = package.read(info)
            fresh = copy.copy(info)
            out.writestr(fresh, data, compress_type=info.compress_type)
    return buffer.getvalue()


def _replace(target: Path, data: bytes, like: Path) -> None:
    """Put *data* at *target*: over the same file when it is the one patched, else as a new file."""
    if target.exists() and like.exists() and os.path.samefile(target, like):
        _overwrite(target, data)
    else:
        _create(target, data, like)


def _overwrite(target: Path, data: bytes) -> None:
    """Write *data* into the existing file itself, so it stays the same file (Finder tags, owner, links and sharing).

    The package is already complete in memory, so the file is held for as short a time as possible; if the write
    fails part-way the original bytes are written back before the error goes on.
    """
    with open(target, "r+b") as out:                                  # a file another program holds refuses here
        original = out.read()
        try:
            out.seek(0)
            out.write(data)
            out.truncate()
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            out.seek(0)
            out.write(original)
            out.truncate()
            out.flush()
            raise


def _create(target: Path, data: bytes, like: Path) -> None:
    """Write a new file: to a hidden temporary file beside it first, then put it in place in one step."""
    try:
        handle, name = tempfile.mkstemp(prefix=".quill-", suffix=".tmp", dir=target.parent)
    except PermissionError as exc:                                    # a read-only folder
        raise UnsupportedError(f"no room for a temporary file: {exc}") from exc
    temp = Path(name)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        try:
            shutil.copymode(like, temp)
        except OSError:
            pass                                                      # (permissions are a nicety; the content is the point)
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
