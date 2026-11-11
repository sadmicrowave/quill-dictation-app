"""The journey harness: a whole Quill (the real application object with its real windows, controller, bridge and workbook file) in a
stand-in world (a fake microphone and a stand-in for Numbers), driven the way a person drives it, one step at a time.

What makes it different from a unit test: after EVERY step, :meth:`Journey.check` looks at everything at once and fails the journey on
any broken *invariant*: things that must be true at every moment whatever happened before (one copy of the file open, the grid
agreeing with the row and the heard words, the gear enabled exactly when a file is connected, no warning repeated, a workbook that
still opens...). A bug found by hand becomes an invariant (or a journey) here, so it is caught for every route that could lead to it,
including routes nobody has thought of yet.
"""
from __future__ import annotations

import openpyxl
from PySide6.QtTest import QTest

from quill.bridge.hosts import NUMBERS, SpreadsheetHosts
from quill.session import Decision
from tests.fake_chrome import FakeNativeWindows
from tests.fake_numbers import FakeNumbers
from tests.test_app import AppCase


class Journey(AppCase):
    """Base class of every journey. Subclasses are narratives: ``self.say(...)``, ``self.answer(...)``, ``self.close_file()`` ..."""

    #: Extra invariants a journey adds to :attr:`INVARIANTS` (names of methods starting ``inv_``).
    extra_invariants: tuple[str, ...] = ()

    #: True: the title bars are the macOS ones (a stand-in that keeps what each window's title bar holds: tests/fake_chrome.py), so
    #: a journey can rebuild a window and the invariant can see a title bar drawn twice. False: no native title bars (the default).
    native_titlebars = False

    def setUp(self):
        self.native = None
        if self.native_titlebars:
            self.native = FakeNativeWindows()
            for patch in self.native.patches():
                patch.start()
                self.addCleanup(patch.stop)
        super().setUp()
        self.numbers = FakeNumbers()                                    # Numbers has the workbook open, as the user's does
        self.numbers.import_xlsx(str(self.path.resolve()))
        self.quill.hosts = SpreadsheetHosts("darwin", self.numbers)
        self.quill._host = NUMBERS
        self.quill.run_in_background = lambda work, done: done(work())  # (no helper threads in a test)
        self.steps: list[str] = []
        self.window = self.quill.window
        self.session = self.quill.controller.session
        self.check("start")

    # ---------------------------------------------------------------- the person's actions ---

    def step(self, what: str) -> None:
        self.steps.append(what)
        self.check(what)

    def say(self, *phrases: str) -> None:
        """Finished phrases, as the recogniser delivers them."""
        for phrase in phrases:
            self.assertTrue(self.window.listening, f"the microphone is off, so {phrase!r} cannot be heard (press Start first)")
            self.hear(phrase)
            self.step(f"said {phrase!r}")

    def say_partially(self, text: str) -> None:
        """Words still being spoken (what appears live)."""
        self.assertTrue(self.window.listening, "the microphone is off")
        self.quill._on_partial_heard(text)
        self.step(f"hearing {text!r}")

    def start(self) -> None:
        """Press Start (the button, as a person does: it works whether or not a file is connected)."""
        if self.window.listening:
            return
        self.window.toggle_button.click()
        self.step("pressed Start")

    def stop(self) -> None:
        """Say "stop listening" (the microphone is open: that is how it is heard)."""
        if self.window.listening:
            self.hear("stop listening")
        self.step("stopped listening")

    def go_quiet(self) -> None:
        """Ten quiet seconds pass: Quill stops listening by itself."""
        self.quill._quiet_for_too_long()
        self.step("went quiet (listening stopped by itself)")

    def next_row(self) -> None:
        self.say("next row")

    def answer(self, term: str, decision: Decision) -> None:
        """The person answers one term in the Term Helper (it must be waiting there: a journey cannot answer what was never asked)."""
        key = next((k for k in self.quill.controller.pending_terms() if term in k[1]), None)
        self.assertIsNotNone(key, f"{term!r} is not waiting in the Term Helper; waiting: {self.quill.controller.pending_terms()}")
        self.quill.resolve_term(key, decision, key[1])
        self.save_settles()
        self.step(f"answered {term!r} with {decision.kind}")

    def close_term_helper(self) -> None:
        self.window.sorting_finished()
        self.step("closed the Term Helper")

    def save_settles(self) -> None:
        """The moment after Quill saved: the timer that asks the spreadsheet program to show it fires."""
        self.quill._reload_host()

    def switch_sheet(self, name: str) -> None:
        self.quill._apply_sheet(name, True)
        self.step(f"switched to sheet {name!r}")

    def close_file(self) -> None:
        """The person closes the file in their spreadsheet program; the next look notices."""
        self.numbers.docs.clear()
        self.quill._poll_local([])
        self.step("closed the file in the spreadsheet program")

    def reopen_file(self) -> None:
        self.numbers.import_xlsx(str(self.path.resolve()))
        self.quill.connect_workbook(str(self.path), quiet=True)
        self.step("opened the file again")

    def set_headings_row(self, number: int) -> None:
        panel = self.window.panel
        panel.settings.headings_box.setValue(number)                    # (the person types it in the file settings)
        panel.headings_row_changed.emit(number)
        self.step(f"chose headings row {number}")

    def rebuild_window(self, which: str) -> None:
        """The system replaces a window's native window (it happens to the Term Helper when it is closed and shown again)."""
        assert self.native is not None, "this journey has no native title bars: set native_titlebars = True"
        widget = self.window.widget if which == "main" else self.quill.sorting.widget
        self.native.rebuild(widget)
        self.step(f"the {which} window was rebuilt by the system")

    def settle(self, ms: int = 400) -> None:
        QTest.qWait(ms)
        self.step("waited")

    # ---------------------------------------------------------------- looking --------------------

    def grid(self) -> list[tuple[str, str]]:
        """The heard lines of the row grid: ``(column, value)``, top to bottom."""
        return self.window.heard_lines()

    def grid_columns(self) -> list[str]:
        table = self.window.row_table
        return [table.item(r, 0).text() for r in range(table.rowCount())]

    def saved_rows(self, sheet: str = "Inventory", first: int = 4, columns: int = 8) -> list[tuple]:
        """The rows of data in the workbook file now (below the headings row 3 of the fixture)."""
        ws = openpyxl.load_workbook(self.path)[sheet]
        rows = [tuple(ws.cell(row=r, column=c).value for c in range(1, columns + 1)) for r in range(first, ws.max_row + 1)]
        return [row for row in rows if any(v not in (None, "") for v in row[:6])]

    def count_in_log(self, text: str) -> int:
        return self.log().count(text)

    # ---------------------------------------------------------------- the invariants ------------

    #: Every method named ``inv_*`` is checked after every step; a failure names the step and the invariant.
    def check(self, after: str = "") -> None:
        failures = []
        for name in sorted(n for n in dir(self) if n.startswith("inv_")):
            try:
                getattr(self, name)()
            except AssertionError as exc:
                failures.append(f"{name[4:]}: {exc}")
        if failures:
            story = " > ".join(self.steps[-14:]) or "(setup)"
            self.fail(f"after {after!r} (steps so far: {story})\n  " + "\n  ".join(failures))

    def inv_the_file_is_open_at_most_once_in_the_spreadsheet_program(self):
        for name in {d["name"] for d in self.numbers.docs}:
            assert self.numbers.count(name) <= 1, f"{self.numbers.count(name)} copies of {name!r} are open"

    def inv_every_window_has_each_of_its_title_bar_icon_sets_exactly_once(self):
        """A window's title bar must hold one row of icons, never two drawn over each other (the main window has a right row and a
        left row; the Term Helper a left row)."""
        if self.native is None:
            return
        from quill.ui.chrome import SYMBOL_UNDO
        expected = {id(self.window.widget): [("left", SYMBOL_UNDO), ("right", "resize")], id(self.quill.sorting.widget): [("left", SYMBOL_UNDO)]}
        for key, icons in self.native.icons.items():
            assert len(icons) == len(set(icons)), f"a title bar holds {icons}: some icons are there twice"
            assert not icons or sorted(icons) == sorted(expected[key]), f"a title bar holds {icons}, expected {expected[key]}"

    def inv_the_resize_handle_under_the_grid_has_its_middle_dot_on_the_grids_divider(self):
        grip, table = self.window.row_grip, self.window.row_table
        assert abs(grip.centre() - table.divider_x()) < 0.01, f"the handle's middle dot is at {grip.centre()}, the divider at {table.divider_x()}"

    def inv_the_gear_works_exactly_when_a_file_is_connected(self):
        gear = self.window.panel.settings_button
        assert gear.isEnabled() == bool(self.quill.connected), f"gear enabled={gear.isEnabled()} but connected={self.quill.connected}"

    def inv_the_grid_agrees_with_the_row(self):
        record = dict(self.session.record)
        assert dict(self.window._row_fields) == record, f"grid has {self.window._row_fields}, the row has {record}"

    def inv_the_grid_lists_the_sheets_columns_once_each(self):
        names = self.grid_columns()
        assert len(names) == len(set(names)), f"a column is listed twice: {names}"
        if self.quill.connected:
            headers = list(self.quill.controller.sheet_headers)
            vocab = self.quill.controller.vocab
            known = set(headers) | set(vocab.columns()) | set(self.window._fields_now())           # (lists are found workbook-wide: those columns can be heard anywhere)
            assert set(headers) <= set(names), f"the grid lacks sheet columns {sorted(set(headers) - set(names))}: {names}"
            assert set(names) <= known, f"the grid lists columns nobody knows here: {sorted(set(names) - known)}"
        else:
            assert names == [], f"no file is connected but the grid lists {names}"

    def inv_muted_lines_are_exactly_the_columns_not_heard(self):
        table = self.window.row_table
        heard = {c for c, _ in self.window.heard_lines()}
        for r in range(table.rowCount()):
            item = table.item(r, 0)
            is_muted = item.foreground() == table.palette().placeholderText()
            assert is_muted == (item.text() not in heard), f"line {item.text()!r} muted={is_muted} but heard={item.text() in heard}"

    def inv_a_pending_row_is_always_visible_in_the_grid(self):
        if self.session.record:
            assert self.window.heard_lines(), "a row with values is pending but the grid shows none of it"

    def inv_the_empty_grid_hint_says_the_truth(self):
        said = "no column headings" in self.window.row_placeholder.text()
        empty_sheet = bool(self.quill.connected) and not self.quill.controller.sheet_headers
        assert said == empty_sheet, f"hint says no-columns={said}, connected={self.quill.connected}, columns={self.quill.controller.sheet_headers}"

    def inv_listening_state_agrees_everywhere(self):
        assert self.window.listening == self.session.listening, f"window {self.window.listening}, session {self.session.listening}"

    def inv_the_workbook_file_still_opens(self):
        openpyxl.load_workbook(self.path)

    def inv_a_file_that_is_not_connected_has_no_row_and_no_waiting_terms(self):
        if not self.quill.connected:
            assert self.session.record == {}, f"no file, but a row is being built: {self.session.record}"

    def inv_the_term_helper_count_is_the_number_of_terms_waiting(self):
        waiting = len(self.quill.controller.pending_terms())
        assert self.window._sorting_count == waiting, f"the button says {self.window._sorting_count}, {waiting} are waiting"

    def inv_no_term_waiting_is_empty(self):
        for column, term in self.quill.controller.pending_terms():
            assert term and term.strip(), f"an empty term is waiting: {(column, term)!r}"

    def inv_the_microphone_clock_only_runs_while_something_is_listening(self):
        timer = self.quill._quiet_timer
        busy = self.session.listening or self.quill.controller.voice_sorter is not None or self.session.awaiting_answer
        assert not (timer.isActive() and not busy), "the quiet timer is running while nothing is listening"

    def inv_there_are_never_two_of_the_same_window_on_screen(self):
        from PySide6.QtWidgets import QApplication
        titles = [w.windowTitle() for w in QApplication.topLevelWidgets() if w.isVisible() and w.windowTitle()]
        assert len(titles) == len(set(titles)), f"two windows with the same title are open: {titles}"

    def inv_no_warning_repeats_in_a_row(self):
        lines = [line.split("\t", 1)[-1] for line in self.log().splitlines() if "Warning" in line]
        for first, second in zip(lines, lines[1:]):
            assert first != second, f"the log warns twice running: {first!r}"

    def inv_nothing_was_logged_as_an_error_the_journey_did_not_expect(self):
        for line in self.log().splitlines():
            assert "Traceback" not in line and "Exception" not in line, f"the log shows a crash: {line!r}"

    def inv_the_layout_on_the_panel_is_the_one_in_force(self):
        c = self.quill.controller
        box = self.window.panel.settings
        assert box.headings_box.value() == int(c.settings.preferences["headings_row"]), "the panel shows another headings row"
