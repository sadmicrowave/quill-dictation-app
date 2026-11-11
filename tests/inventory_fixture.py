"""A small inventory workbook for tests (a Config sheet of drop-down lists with spare slots, an Inventory sheet with validation).

    python -m tests.inventory_fixture [output.xlsx]

The workbook has a Config sheet of drop-down lists (with spare slots, so
"Add it to the list" works), an Inventory sheet with validation on Type, Size,
Era, Color and Condition, plus an Appraisal amount and Notes. Open it in Excel,
run Quill, and say for example:

    start listening
    this item is a black t-shirt in good condition
    appraisal thirty five dollars
    next row

Say something it doesn't know ("from the nineties") to see the Needs-sorting
window; choosing Era > Same as 1990s teaches Quill that phrase.
"""
from __future__ import annotations
import pathlib
import sys

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HEADERS = ["Item", "Type", "Size", "Era", "Color", "Condition", "Appraisal", "Notes"]

#: Drop-down lists; each gets 10 spare slots on the Config sheet.
LISTS = {
    "Type": ["T-Shirt", "Blouse", "Jacket", "Skirt", "Jeans", "Hoodie"],
    "Size": ["XS", "S", "M", "L", "XL", "XXL"],
    "Era": ["1970s", "1980s", "1990s", "2000s"],
    "Color": ["Black", "White", "Navy Blue", "Red", "Green"],
    "Condition": ["New with tags", "Excellent", "Good", "Fair"],
}
SPARE_SLOTS = 10

#: A few finished rows so numeric columns are recognisable and searches have something to find.
SAMPLE_ROWS = [
    ("Vintage tee", "T-Shirt", "L", "1990s", "Black", "Good", 28, ""),
    ("Silk blouse", "Blouse", "M", "2000s", "White", "Excellent", 45, "Pearl buttons"),
    ("Denim jacket", "Jacket", "L", "1980s", "Navy Blue", "Fair", 60, ""),
    ("Pleated skirt", "Skirt", "S", "1990s", "Red", "Good", 32, ""),
]


def build(path: str | pathlib.Path) -> pathlib.Path:
    """Write the demo workbook to *path* and return it."""
    wb = openpyxl.Workbook()
    inv = wb.active
    inv.title = "Inventory"
    inv.append(HEADERS)
    for cell in inv[1]:
        cell.font = Font(bold=True)
    for row in SAMPLE_ROWS:
        inv.append(row)

    cfg = wb.create_sheet("Config")
    for col, (name, values) in enumerate(LISTS.items(), start=1):
        cfg.cell(row=1, column=col, value=name).font = Font(bold=True)
        for r, value in enumerate(values, start=2):
            cfg.cell(row=r, column=col, value=value)
        last = 1 + len(values) + SPARE_SLOTS
        letter = get_column_letter(col)
        dv = DataValidation(type="list", formula1=f"=Config!${letter}$2:${letter}${last}",
                            allow_blank=True)
        inv.add_data_validation(dv)
        target = get_column_letter(HEADERS.index(name) + 1)
        dv.add(f"{target}2:{target}500")

    for col, width in enumerate((22, 12, 8, 10, 12, 16, 11, 24), start=1):
        inv.column_dimensions[get_column_letter(col)].width = width
    inv.freeze_panes = "A2"
    path = pathlib.Path(path)
    wb.save(path)
    return path


if __name__ == "__main__":
    out = build(sys.argv[1] if len(sys.argv) > 1 else "Quill Demo Inventory.xlsx")
    print(f"Wrote {out}")
