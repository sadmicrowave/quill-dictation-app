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


def make_demo_workbook(folder: pathlib.Path | None = None, blank_sheet: bool | None = None) -> pathlib.Path:
    """Write the sample workbook (an Inventory sheet with a few finished rows, and a Config sheet of lists).

    With *blank_sheet* (or ``QUILL_DEMO_BLANK_SHEET=1``) a third, empty sheet called **Blank** is added: the on-screen test run
    (``docs/onscreen-journeys.md``) uses it to see what Quill does with a sheet that has no column headings.
    """
    folder = pathlib.Path(folder) if folder else pathlib.Path(tempfile.mkdtemp(prefix="quill-demo-"))
    folder.mkdir(parents=True, exist_ok=True)
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
        # (no "=" in front: Excel stores a rule's range without one, and Numbers reads an "=" as a formula it cannot keep: it warns
        # "Unsupported formulas were replaced" and marks every cell of the rule with a blue triangle)
        rule = DataValidation(type="list", formula1=f"Config!${letter}$2:${letter}${len(values) + 1 + SPARE_SLOTS}",
                              allow_blank=True)
        inventory.add_data_validation(rule)
        rule.add(f"{get_column_letter(HEADERS.index(header) + 1)}2:{get_column_letter(HEADERS.index(header) + 1)}200")
    for header in ("Purchase Date", "Sale Date"):
        column = get_column_letter(HEADERS.index(header) + 1)
        for row in range(2, 6):
            inventory[f"{column}{row}"].number_format = "yyyy-mm-dd"
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    thin = Side(style="thin", color="DDD6EE")
    for cell in inventory[1]:                                   # a clear header row, so the sheet looks cared for on screen
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="7A55C2")
        cell.alignment = Alignment(vertical="center")
    for row in inventory.iter_rows(min_row=2, max_row=24, max_col=len(HEADERS)):
        for cell in row:
            cell.border = Border(bottom=thin)
    for index, name in enumerate(HEADERS, start=1):
        inventory.column_dimensions[get_column_letter(index)].width = 26 if name == "Notes" else (16 if "Date" in name or "Price" in name else 13)
    inventory.row_dimensions[1].height = 24
    if blank_sheet or (blank_sheet is None and os.environ.get("QUILL_DEMO_BLANK_SHEET", "").lower() in ("1", "true", "yes", "on")):
        wb.create_sheet("Blank")
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
            ("Promo Story (about 30 s)", self.promo),
            ("Clip: Dictate", self.clip_dictate),
            ("Clip: Term Helper", self.clip_helper),
            ("Clip: It Learns", self.clip_learns),
            ("Clip: Mini View", self.clip_mini),
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
        session.open_note = None
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

    def promo(self) -> None:
        """The story for the promo video, in real time: Start, a row spoken word by word with the voice lines moving, Next Row (it
        appears in the open spreadsheet), a second row with words Quill does not know, and the Term Helper answering them by voice."""
        self.reset()
        row_one = "black t-shirt men nike good condition purchase price thirty five dollars bought it yesterday"
        row_two = "teal hoodie women large patagonia vintage excellent condition"
        words_one = row_one.split()
        steps: list[tuple[int, Callable[[], None]]] = [(0, self._listen), (700, lambda: self._speak(4900))]
        for n in range(1, len(words_one) + 1):
            steps.append((400 if n > 1 else 250, lambda n=n: self._partial(" ".join(words_one[:n]))))
        steps.append((500, lambda: self._phrase(row_one)))
        steps.append((900, lambda: self._speak(900)))
        steps.append((500, lambda: self._say_command("next row")))
        steps.append((1500, lambda: self._speak(3600)))
        words_two = row_two.split()
        for n in range(1, len(words_two) + 1):
            steps.append((420 if n > 1 else 200, lambda n=n: self._partial(" ".join(words_two[:n]))))
        steps.append((500, lambda: self._phrase(row_two)))
        steps.append((900, lambda: self._speak(900)))
        steps.append((500, lambda: self._say_command("next row")))
        steps.append((1700, self._app.toggle_voice_sorting))                 # the Term Helper is open: answer it by voice
        for text, gap in (("color", 1300), ("yes", 1000), ("ignore", 1000), ("same as l", 1000)):
            steps.append((gap, lambda: self._speak(650)))
            steps.append((700, lambda text=text: self._say_command(text)))
        # A third row: a slurred "kinda" is heard glued to the new colour. The user trims it off in the Term Helper (Quill learns to
        # skip it from then on) and takes the suggested short code for the size; then a word is taught by voice and Settings shows both.
        row_three = "kinda cream sweater small carhartt good condition"
        words_three = row_three.split()
        steps.append((2200, lambda: self._speak(3300)))
        for n in range(1, len(words_three) + 1):
            steps.append((420 if n > 1 else 200, lambda n=n: self._partial(" ".join(words_three[:n]))))
        steps.append((500, lambda: self._phrase(row_three)))
        steps.append((900, lambda: self._speak(800)))
        steps.append((500, lambda: self._say_command("next row")))
        steps.append((2600, lambda: self._trim_term("kinda cream", "cream", "Color")))      # (the helper has been open for a moment)
        steps.append((1900, lambda: self._click_term("small", "match_button")))
        steps.append((2400, lambda: self._speak(1500)))
        steps.append((300, lambda: self._say_command("sold means sale date")))
        steps.append((2600, lambda: self._app.open_settings("Learned Words")))
        self._steps(steps)
        self._hush(90_000)

    # ------------------------------------------------------------------ #
    # Clips: one short, self-contained scenario per feature, recorded on its own (see quill-website/promo)   #
    # ------------------------------------------------------------------ #

    def _say_row(self, steps: list, text: str, lead_ms: int = 900, pace_ms: int = 400, next_row: bool = True) -> None:
        """Append the steps of one row spoken word by word (the voice lines move while it is said), then, optionally, "next row"."""
        words = text.split()
        steps.append((lead_ms, lambda: self._speak(int(len(words) * pace_ms + 700))))
        for n in range(1, len(words) + 1):
            steps.append((pace_ms if n > 1 else 250, lambda n=n: self._partial(" ".join(words[:n]))))
        steps.append((500, lambda: self._phrase(text)))
        if next_row:
            steps.append((900, lambda: self._speak(900)))
            steps.append((500, lambda: self._say_command("next row")))

    def clip_dictate(self) -> None:
        """Two rows of known words, spoken and saved: they appear in the open spreadsheet as they are said (no Term Helper)."""
        self.reset()
        steps: list[tuple[int, Callable[[], None]]] = [(0, self._listen)]
        self._say_row(steps, "black t-shirt men nike good condition purchase price thirty five dollars bought it yesterday", 700)
        self._say_row(steps, "navy sweater women patagonia excellent condition", 1500)
        steps.append((2500, lambda: None))
        self._steps(steps)
        self._hush(60_000)

    def clip_helper(self) -> None:
        """A row with words Quill does not know; the Term Helper opens and they are answered by voice."""
        self.reset()
        steps: list[tuple[int, Callable[[], None]]] = [(0, self._listen)]
        self._say_row(steps, "teal hoodie women large patagonia vintage excellent condition", 700)
        steps.append((1700, self._app.toggle_voice_sorting))
        for text, gap in (("color", 1300), ("yes", 1000), ("ignore", 1000), ("same as l", 1000)):
            steps.append((gap, lambda: self._speak(650)))
            steps.append((700, lambda text=text: self._say_command(text)))
        steps.append((2500, lambda: None))
        self._steps(steps)
        self._hush(60_000)

    def clip_learns(self) -> None:
        """A slurred word is trimmed off a term (Quill learns to skip it), a word is taught by voice, and Settings lists both."""
        self.reset()
        steps: list[tuple[int, Callable[[], None]]] = [(0, self._listen)]
        self._say_row(steps, "kinda cream sweater small carhartt good condition", 700)
        steps.append((2600, lambda: self._trim_term("kinda cream", "cream", "Color")))
        steps.append((1900, lambda: self._click_term("small", "match_button")))
        steps.append((2400, lambda: self._speak(1500)))
        steps.append((300, lambda: self._say_command("sold means sale date")))
        steps.append((2600, lambda: self._app.open_settings("Learned Words")))
        steps.append((6500, lambda: None))
        self._steps(steps)
        self._hush(60_000)

    def clip_mini(self) -> None:
        """The mini view: a slim strip beside the spreadsheet while two rows are spoken and saved."""
        self.reset()
        self._app.window.set_mini(True)
        steps: list[tuple[int, Callable[[], None]]] = [(600, self._compact_mini), (900, self._listen)]
        self._say_row(steps, "black jeans men levis good condition purchase price twenty dollars", 700)
        self._say_row(steps, "white dress women adidas excellent condition", 1200)
        steps.append((2500, lambda: None))
        self._steps(steps)
        self._hush(60_000)

    def _compact_mini(self) -> None:
        """The mini view at its compact default size (it keeps the height the full window had when the switch was made otherwise)."""
        view = self._app.window
        if view._window is not None and view._mini_base:
            view._window.resize(view.MINI_WIDTH, view._mini_base)

    def _row(self, words: str):
        return next((r for r in self._app.sorting.rows if r.key[1] == words), None)

    def _trim_term(self, heard: str, kept: str, column: str) -> None:
        """Take words off the front of a term in the Term Helper's text box one letter at a time, pick its column and press Add."""
        row = self._row(heard)
        if row is None:
            return
        cut = heard[: len(heard) - len(kept)]
        row.edit.setFocus()
        for n in range(1, len(cut) + 1):
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(lambda n=n: row.edit.setText(heard[n:].lstrip().capitalize() if n == len(cut) else heard[n:]))
            timer.start(150 * n)
            self._timers.append(timer)
        pick = QTimer()
        pick.setSingleShot(True)
        pick.timeout.connect(lambda: row.combo.setCurrentIndex(max(row.combo.findData(column), 0)))
        pick.start(150 * len(cut) + 500)
        press = QTimer()
        press.setSingleShot(True)
        press.timeout.connect(row.add_button.click)
        press.start(150 * len(cut) + 1300)
        self._timers += [pick, press]

    def _click_term(self, heard: str, button: str) -> None:
        row = self._row(heard)
        if row is not None:
            getattr(row, button).click()

    # ------------------------------------------------------------------ #

    def _hush(self, ms: int) -> None:
        """Keep the real microphone out of a scripted story (room noise would be recognised as words): the listener is muted every
        300 ms for *ms* milliseconds, then this stops by itself (demo only)."""
        import time
        end = time.monotonic() + ms / 1000
        timer = QTimer()
        timer.setInterval(300)

        def tick() -> None:
            listener = getattr(self._app, "listener", None)
            if listener is not None and hasattr(listener, "mute"):
                listener.mute()
            if time.monotonic() >= end:
                timer.stop()

        timer.timeout.connect(tick)
        timer.start()
        self._timers.append(timer)

    def _speak(self, ms: int) -> None:
        """Move the voice lines for *ms* like a person talking: a level every 70 ms that rises and falls, then silence. It ends by
        itself (demo only)."""
        import math
        import time
        start = time.monotonic()
        timer = QTimer()
        timer.setInterval(70)

        def tick() -> None:
            t = time.monotonic() - start
            if t * 1000 >= ms:
                timer.stop()
                self._app.relay.level.emit(0.0)
                return
            syllable = abs(math.sin(t * 9.0)) * (0.65 + 0.35 * math.sin(t * 2.1))
            self._app.relay.level.emit(min(1.0, 0.42 + 0.55 * syllable))

        timer.timeout.connect(tick)
        timer.start()
        self._timers.append(timer)

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
