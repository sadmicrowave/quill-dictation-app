"""Demo data: fill the screens with realistic content without speaking a sentence.

For looking at the app and trying its screens, not for end users. Started with ``python main.py --demo`` (or
``QUILL_DEMO=1``), which opens a throw-away sample workbook and adds a **Demo** menu. Every scenario feeds
*text* through the same code path a spoken phrase takes (the Voice Stream, the row grid, the Term Helper, the
countdown), so what is seen is the real screen, not a mock-up.
"""

from __future__ import annotations
import datetime as dt
import os
import pathlib
import tempfile
from typing import Callable

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from PySide6.QtCore import QTimer

HEADERS = ["Category", "Gender", "Size", "Brand", "Color", "Era", "Condition", "Purchase Date", "Purchase Price",
           "Sale Date", "Notes"]

#: The sample workbook's drop-down lists (with spare slots on the Config sheet so "add to list" works).
LISTS = {
    "Category": ["T-Shirt", "Jacket", "Sweater", "Hoodie", "Jeans", "Dress"],
    "Gender": ["Men", "Women", "Unisex"],
    "Size": ["XS", "S", "M", "L", "XL", "XXL"],
    "Brand": ["Nike", "Adidas", "Patagonia", "Levi's", "Carhartt"],
    "Color": ["Black", "White", "Navy", "Brown", "Gray", "Red"],
    "Era": ["1980s", "1990s", "2000s", "2010s"],
    "Condition": ["New with tags", "Excellent", "Good", "Fair"],
}
SPARE_SLOTS = 10


def demo_requested(flag: bool = False) -> bool:
    """True if demo mode was asked for (``--demo`` or ``QUILL_DEMO=1``)."""
    return flag or os.environ.get("QUILL_DEMO", "").lower() in ("1", "true", "yes", "on")


def make_demo_workbook(folder: pathlib.Path | None = None) -> pathlib.Path:
    """Write the sample workbook (an Inventory sheet with a few finished rows, and a Config sheet of lists)."""
    folder = pathlib.Path(folder) if folder else pathlib.Path(tempfile.mkdtemp(prefix="quill-demo-"))
    path = folder / "Demo Inventory.xlsx"
    wb = openpyxl.Workbook()
    inventory = wb.active
    inventory.title = "Inventory"
    inventory.append(HEADERS)
    today = dt.date.today()
    rows = [
        ["Jacket", "Men", "L", "Carhartt", "Brown", "1990s", "Good", today - dt.timedelta(days=40), 18.0, None, "Chore jacket"],
        ["T-Shirt", "Women", "S", "Nike", "White", "2000s", "Excellent", today - dt.timedelta(days=21), 6.5, today - dt.timedelta(days=3), None],
        ["Sweater", "Unisex", "M", "Patagonia", "Navy", "1980s", "Fair", today - dt.timedelta(days=9), 12.0, None, "Small hole at the cuff"],
    ]
    for row in rows:
        inventory.append(row)
    config = wb.create_sheet("Config")
    for column, (name, values) in enumerate(LISTS.items(), start=1):
        config.cell(row=1, column=column, value=name)
        for offset, value in enumerate(values, start=2):
            config.cell(row=offset, column=column, value=value)
    for header, values in LISTS.items():
        letter = get_column_letter(list(LISTS).index(header) + 1)
        rule = DataValidation(type="list", formula1=f"=Config!${letter}$2:${letter}${len(values) + 1 + SPARE_SLOTS}",
                              allow_blank=True)
        inventory.add_data_validation(rule)
        rule.add(f"{get_column_letter(HEADERS.index(header) + 1)}2:{get_column_letter(HEADERS.index(header) + 1)}200")
    for header in ("Purchase Date", "Sale Date"):
        column = get_column_letter(HEADERS.index(header) + 1)
        for row in range(2, 6):
            inventory[f"{column}{row}"].number_format = "yyyy-mm-dd"
    wb.save(path)
    return path


class Demo:
    """The demo scenarios, run against a live :class:`~quill.app.QuillApp`.

    Args:
        app: The running application.
        delay_ms: Pause between steps (the words of a phrase arrive a little at a time, as when speaking).
    """

    def __init__(self, app, delay_ms: int = 500) -> None:
        self._app = app
        self._delay = delay_ms
        self._timers: list[QTimer] = []

    # ------------------------------------------------------------------ #

    def scenarios(self) -> list[tuple[str, Callable[[], None]]]:
        """``(menu label, action)`` for each scenario, in menu order."""
        return [
            ("A Row Being Dictated", self.dictating),
            ("Terms To Sort", self.terms_to_sort),
            ("A Saved Row", self.saved_row),
            ("Everything", self.everything),
            ("Reset", self.reset),
        ]

    def reset(self) -> None:
        """Back to an empty, not-listening screen."""
        self._cancel()
        app = self._app
        if app.controller.voice_sorter is not None:
            app.controller.stop_voice_sort()
        session = app.controller.session
        if session.listening:
            app.toggle_listening(False)
        session.record.clear()
        session.pool.clear()
        session.row_terms.clear()
        session.pending = None
        app.window.clear_stream()
        app.window.update_current_row({})
        app.refresh_sorting()

    def dictating(self) -> None:
        """Listening, with a phrase arriving word by word: pills, the grid filling, the countdown."""
        self.reset()
        self._steps([
            (0, self._listen),
            (self._delay, lambda: self._partial("black t")),
            (self._delay, lambda: self._partial("black t shirt large")),
            (self._delay, lambda: self._partial("black t shirt large nike good condition")),
            (self._delay, lambda: self._phrase("black t-shirt large nike good condition price thirty five dollars "
                                                "bought it yesterday")),
        ])

    def terms_to_sort(self) -> None:
        """A row with words Quill does not know, so the Term Helper button and window fill up."""
        self.reset()
        self._steps([
            (0, self._listen),
            (self._delay, lambda: self._phrase("teal hoodie medium nineties vintage hat")),
            (self._delay, lambda: self._say_command("next row")),
        ])

    def saved_row(self) -> None:
        """A finished row: the grid clears, Last Saved shows."""
        self.reset()
        self._steps([
            (0, self._listen),
            (self._delay, lambda: self._phrase("navy jacket extra large patagonia excellent condition")),
            (self._delay, lambda: self._say_command("next row")),
        ])

    def everything(self) -> None:
        """A saved row, then a new row in progress with terms waiting: most of the main window at once."""
        self.reset()
        self._steps([
            (0, self._listen),
            (self._delay, lambda: self._phrase("white dress small adidas good condition price twelve dollars")),
            (self._delay, lambda: self._say_command("next row")),
            (self._delay, lambda: self._phrase("teal hoodie medium nineties")),
            (self._delay, lambda: self._partial("black jeans men levi")),
        ])

    # ------------------------------------------------------------------ #

    def _steps(self, steps: list[tuple[int, Callable[[], None]]]) -> None:
        """Run *steps* one after another; each delay counts from the end of the previous step."""
        at = 0
        for delay, action in steps:
            at += delay
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(action)
            timer.start(at)
            self._timers.append(timer)

    def _cancel(self) -> None:
        for timer in self._timers:
            timer.stop()
        self._timers.clear()

    def _say_command(self, text: str) -> None:
        """A spoken command ("next row") or phrase, through the relay as a recognised one."""
        self._app.relay.transcript.emit(text)

    def _partial(self, text: str) -> None:
        self._app.relay.partial.emit(text)

    def _phrase(self, text: str) -> None:
        """A finished phrase, through the same path as a spoken one (stream first, then the row)."""
        self._app.relay.transcript.emit(text)

    def _listen(self) -> None:
        self._app.toggle_listening(True)
