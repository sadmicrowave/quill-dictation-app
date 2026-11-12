"""Dictation on this machine, through the whole application (its real windows, controller and a real workbook file) with a stand-in microphone: say a
row, notes, an ID, a word Quill does not know, the mini view. Checks the screen's side of each phrase (the recogniser itself is a person's job).
Run by the VM job runner (``dictation`` job); ``--offscreen`` tries it anywhere.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys

from common import Report, parse, scratch_folder, start_qt, wait


class FakeListener:
    """Stands in for the microphone: nothing is heard until the script calls ``say``."""

    def __init__(self, model, on_transcript, on_error) -> None:
        self.on_transcript, self.on_error = on_transcript, on_error

    def preload(self) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def mute(self) -> None: ...
    def unmute(self) -> None: ...


class FakeSpeaker:
    enabled = True

    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, text, on_done=None, lead_in=0.0) -> None:
        self.said.append(text)
        if on_done:
            on_done()


def main(argv=None) -> int:
    args = parse(__doc__, argv)
    app = start_qt(args.offscreen)
    report = Report(args.out, args.offscreen)

    import openpyxl
    from quill.app import QuillApp
    from quill.bridge.xlsx_bridge import XlsxBridge
    from quill.config.settings import Settings
    from quill.ui.main_window import MainWindow
    from tests.fixtures import make_workbook
    from tests.test_counters import make_book

    MainWindow.animation_ms = 0

    class Session:
        """One application on one workbook, in a folder of its own."""

        def __init__(self, maker, name: str) -> None:
            self.folder = scratch_folder()
            self.path = maker(self.folder / name)
            self.app = QuillApp(app, Settings.load(self.folder / "cfg"), XlsxBridge(self.path), listener_factory=lambda m, t, e: FakeListener(m, t, e),
                                model_finder=lambda configured: self.folder / "model", speaker=FakeSpeaker())
            self.app.start()
            self.window = self.app.window
            self.window.widget.resize(520, 640)
            self.window.widget.show()
            wait(1300)

        def hear(self, *phrases: str) -> None:
            for phrase in phrases:
                self.app.relay.transcript.emit(phrase)
            wait(200)

        def sheet(self, name: str):
            return openpyxl.load_workbook(self.path)[name]

        def close(self) -> None:
            self.window.widget.close()
            if self.app.sorting.widget is not None:
                self.app.sorting.widget.close()

    # ---- S1: a row ---------------------------------------------------------------------------------------------------------------------------
    def a_row() -> None:
        s = Session(make_workbook, "plants.xlsx")
        s.hear("start listening")
        report.check("Start opens the gate", s.window.listening)
        s.hear("fern small bright price twelve dollars")
        heard = dict(s.window.heard_lines())
        report.check("the words fill their columns in the grid", heard.get("Species") == "Fern" and heard.get("Pot Size") == "Small" and heard.get("Light") == "Bright"
                     and heard.get("Price") in ("12", "12.0"), str(heard), shot=report.widget_shot(s.window.widget, "dictation-row-heard"))
        s.hear("next row")
        row = [s.sheet("Inventory").cell(4, c).value for c in (1, 2, 3, 5)]
        report.check("next row writes the row to the workbook", row == ["Fern", "Small", "Bright", 12.0], str(row))
        report.check("the grid is reset after the row is saved", s.window.heard_lines() == [], str(s.window.heard_lines()))
        s.hear("stop listening")
        report.check("stop listening closes the gate", not s.window.listening)
        s.close()

    report.attempt("a row", a_row)

    # ---- notes --------------------------------------------------------------------------------------------------------------------------------
    def notes() -> None:
        s = Session(make_workbook, "plants.xlsx")
        s.hear("start listening", "species fern", "start note needs repotting soon", "and the price depends on the light")
        shown = dict(s.window.heard_lines()).get("Notes", "")
        report.check("a note grows across pauses, and column names inside it are just words",
                     "needs repotting soon and the price depends on the light" in shown, shown,
                     shot=report.widget_shot(s.window.widget, "dictation-note"))
        s.hear("end note", "next row")
        cell = s.sheet("Inventory").cell(4, 7).value
        report.check("the note is saved with a capital and a full stop", cell == "Needs repotting soon and the price depends on the light.", str(cell))
        s.close()

    report.attempt("notes", notes)

    # ---- an ID counted for you -----------------------------------------------------------------------------------------------------------------
    def ids() -> None:
        s = Session(make_book, "stock.xlsx")
        s.hear("start listening")
        report.check("the next ID is offered in a grey pill", s.window.auto_lines() == [("ID", "6")], str(s.window.auto_lines()))
        s.hear("species fern")
        report.check("the grey pill is not one of the heard words", ("ID", "6") not in s.window.heard_lines(),
                     shot=report.widget_shot(s.window.widget, "dictation-id"))
        s.hear("next row")
        report.check("the ID is written with the row", s.sheet("Stock")["A7"].value == 6, str(s.sheet("Stock")["A7"].value))
        report.check("the next ID is offered again", s.window.auto_lines() == [("ID", "7")], str(s.window.auto_lines()))
        s.close()

    report.attempt("ids", ids)

    # ---- a word Quill does not know ----------------------------------------------------------------------------------------------------------
    def unknown_word() -> None:
        s = Session(make_workbook, "plants.xlsx")
        s.hear("start listening", "fern teal sparkle", "next row")
        pending = s.app.controller.pending_terms()
        report.check("a word that matches nothing waits in the Term Helper", bool(pending), str(pending))
        wait(500)
        report.check("the Term Helper window is shown", s.app.sorting.widget is not None and s.app.sorting.widget.isVisible(),
                     shot=report.widget_shot(s.app.sorting.widget, "dictation-term-helper") if s.app.sorting.widget is not None else "")
        s.close()

    report.attempt("an unknown word", unknown_word)

    # ---- the mini view while listening ---------------------------------------------------------------------------------------------------------
    def mini() -> None:
        s = Session(make_workbook, "plants.xlsx")
        s.hear("start listening", "fern")
        s.window.set_mini(True)
        wait(500)
        report.check("dictation goes on in the mini view", dict(s.window.heard_lines()).get("Species") == "Fern",
                     shot=report.widget_shot(s.window.widget, "dictation-mini"))
        s.window.set_mini(False)
        wait(500)
        report.check("the full window comes back with the row as it was", dict(s.window.heard_lines()).get("Species") == "Fern")
        s.close()

    report.attempt("the mini view", mini)

    failed = [c for c in report.checks if not c["ok"]]
    print(f"{len(report.checks) - len(failed)} of {len(report.checks)} checks held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
