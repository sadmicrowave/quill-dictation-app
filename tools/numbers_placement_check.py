"""Checks, against the REAL Numbers, where Quill writes a turn: one record per turn, each value in the cell where its heading crosses that
record, on sheets whose headings are filled to different heights, in both layouts (headings across the top, or down the first column).

    .venv/bin/python tools/numbers_placement_check.py [folder]

For each scenario it writes a small workbook, opens it in Numbers, runs Quill's own Numbers bridge on the open document (the same code a
dictation uses) and compares what is in Numbers afterwards with where the record belongs. It prints PASS or FAIL for each (with the cells
that differ) and exits non-zero if any failed. It leaves the scenario documents open in Numbers (named ``<scenario>_check``): close them by
hand when you have looked. It never closes a document and never saves one.

It exists because the pretend Numbers of the unit tests cannot show how the real one behaves: the real one once reported a table's size from
its first three columns only (a record went on top of data), and filled the new pop-up cells of a table that grew (values nobody said).
This is the on-screen journey S9 (docs/onscreen-journeys.md).
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import time

import openpyxl
from openpyxl.utils import get_column_letter as letter
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from quill.platforms.macos.numbers_live import NumbersBridge, NumbersLink, document_names  # noqa: E402

HEADINGS = ["Category", "Gender", "Size", "Brand", "Color", "Era", "Condition"]
LISTS = {"Category": "T-Shirt,Jacket,Sweater,Dress", "Gender": "Men,Women,Unisex", "Size": "Small,Medium,Large", "Brand": "Nike,Adidas",
         "Color": "Black,Brown,Gray", "Era": "Eighties,Nineties", "Condition": "New,Good,Fair"}
RECORD = {"Category": "Dress", "Condition": "Good"}

#: (name, layout, how many existing records each heading has, the row (or column) the headings are on)
SCENARIOS = [
    ("columns_first_column_taller", "columns", {"Category": 6, "Condition": 4}, 1),
    ("columns_later_column_taller", "columns", {"Category": 2, "Condition": 6}, 1),
    ("columns_headings_on_row_5", "columns", {"Category": 1, "Condition": 1}, 5),
    ("rows_first_headings_longer", "rows", {"Category": 6, "Condition": 4}, 1),
    ("rows_later_heading_longer", "rows", {"Category": 2, "Condition": 6}, 1),
]


def build(folder: pathlib.Path, name: str, layout: str, depths: dict[str, int], head: int) -> pathlib.Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock"
    for index, heading in enumerate(HEADINGS, start=1):
        if layout == "columns":
            for r in range(1, head):
                ws.cell(row=r, column=1, value=f"title line {r}")
            ws.cell(row=head, column=index, value=heading)
            for k in range(1, depths.get(heading, 0) + 1):
                ws.cell(row=head + k, column=index, value=f"old{index}-{k}")
            cells = f"{letter(index)}{head + 1}:{letter(index)}200"
        else:
            ws.cell(row=index, column=1, value=heading)
            for k in range(1, depths.get(heading, 0) + 1):
                ws.cell(row=index, column=1 + k, value=f"old{index}-{k}")
            cells = f"B{index}:Z{index}"
        rule = DataValidation(type="list", formula1='"' + LISTS[heading] + '"')
        ws.add_data_validation(rule)
        rule.add(cells)
    path = folder / f"{name}.xlsx"
    wb.save(path)
    return path


def numbers_bundle() -> str:
    for bundle in ("com.apple.Numbers", "com.apple.iWork.Numbers"):
        found = subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == '{bundle}'"], capture_output=True, text=True).stdout.strip()
        if found:
            return bundle
    return ""


def where(layout: str, heading: str, record: int, head: int) -> str:
    index = HEADINGS.index(heading) + 1
    return f"{letter(index)}{head + record}" if layout == "columns" else f"{letter(1 + record)}{index}"


def check(folder: pathlib.Path, bundle: str, scenario) -> bool:
    name, layout, depths, head = scenario
    name = f"{name}_check"
    path = build(folder, name, layout, depths, head)
    subprocess.run(["open", "-g", *(["-b", bundle] if bundle else []), str(path)], check=False)
    link = NumbersLink()
    for _ in range(40):                                              # (up to 20 s for the document to be listed)
        link.look(deep=False)
        if link.find(document_names(path)) is not None:
            break
        time.sleep(0.5)
    else:
        print(f"FAIL {name}: Numbers did not list the document")
        return False
    bridge = NumbersBridge(str(path), lambda: link)
    if layout == "rows":
        bridge.set_vertical(True)
    bridge.connect()
    before = {c.coordinate: c.value for row in openpyxl.load_workbook(path)["Stock"].iter_rows() for c in row if c.value is not None}
    bridge.append_row("Stock", dict(RECORD))
    live = link.request("dump", urls=document_names(path))
    sheet = next(s for s in live["sheets"] if s["name"] == "Stock")
    after = {f"{letter(c)}{r}": v for r, row in enumerate(sheet["cells"], 1) for c, v in enumerate(row, 1) if v not in (None, "")}
    record = max(depths.values()) + 1
    expected = {where(layout, heading, record, head): value for heading, value in RECORD.items()}
    new = {k: v for k, v in after.items() if before.get(k) != v}
    lost = {k: (before[k], after.get(k)) for k in before if after.get(k) != before[k]}
    ok = new == expected and not lost
    print(f"{'PASS' if ok else 'FAIL'} {name}: expected {expected}" + ("" if ok else f"; new cells {new}; changed or lost {lost or 'none'}"))
    return ok


def main() -> int:
    if sys.platform != "darwin":
        print("This check needs Numbers on a Mac.")
        return 2
    folder = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(tempfile.mkdtemp(prefix="quill-placement-"))
    folder.mkdir(parents=True, exist_ok=True)
    bundle = numbers_bundle()
    results = [check(folder, bundle, scenario) for scenario in SCENARIOS]
    print(f"{sum(results)} of {len(results)} placements correct. Documents are left open in Numbers (named *_check); close them by hand.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
