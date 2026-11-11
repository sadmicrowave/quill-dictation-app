"""Random walks: many short sessions of arbitrary things a person might do, in arbitrary order, with every invariant checked after
every step. This finds the bugs nobody wrote a journey for (a Term Helper answered after the file was closed, a sheet switched while
a row is half built ...). Seeds are fixed so a failure is reproducible: the failing seed and the steps are in the message; to replay
one, run it alone with ``-k seed_17``.
"""
import random

from quill.session import Decision
from tests.journeys.harness import Journey

PHRASES = ["fern", "small", "fern small", "cactus large", "orchid", "thriving", "next row", "delete row", "undo", "start listening",
           "stop listening", "flibbertigibbet", "fern gobbledygook", "price twelve", "nonsense words here", "search for fern", "clear search"]
SEEDS = range(80)
STEPS = 30


class RandomWalks(Journey):
    def walk(self, seed: int) -> None:
        rng = random.Random(seed)
        actions = [
            ("say", 8), ("partial", 3), ("start", 3), ("stop", 1), ("quiet", 1), ("answer", 3), ("close_helper", 2), ("sheet", 1),
            ("close_file", 1), ("reopen", 2), ("headings", 1), ("mini", 1), ("remove_line", 1), ("settle", 1),
        ]
        if self.native is not None:
            actions += [("rebuild_main", 1), ("rebuild_helper", 3)]          # (the system replaces a window's native window)
        names = [a for a, w in actions for _ in range(w)]
        for _ in range(STEPS):
            action = rng.choice(names)
            if action == "say":
                if self.window.listening:
                    self.say(rng.choice([p for p in PHRASES if p != "start listening"]))
            elif action == "partial":
                if self.window.listening:
                    self.say_partially(rng.choice(PHRASES[:6]))
            elif action == "start":
                self.start()
            elif action == "stop":
                self.stop()
            elif action == "quiet":
                self.go_quiet()
            elif action == "answer":
                pending = self.quill.controller.pending_terms()
                if pending:
                    key = rng.choice(pending)
                    self.answer(key[1], rng.choice([Decision.add("Species"), Decision.ignore()]))
            elif action == "close_helper":
                self.close_term_helper()
            elif action == "sheet":
                if self.quill.connected:
                    self.switch_sheet(rng.choice(["Inventory", "Config"]))
            elif action == "close_file":
                if self.quill.connected:
                    self.close_file()
            elif action == "reopen":
                if not self.quill.connected:
                    self.reopen_file()
            elif action == "headings":
                if self.quill.connected:
                    self.set_headings_row(rng.choice([0, 1, 3]))
            elif action == "mini":
                self.window.set_mini(not self.window._mini)
                self.step("toggled the mini view")
            elif action == "remove_line":
                shown = [c for c, _ in self.grid()]
                if shown:
                    self.window._remove_row_requested(rng.choice(shown))
                    self.step("removed a line")
            elif action == "settle":
                self.settle(30)
            elif action == "rebuild_main":
                self.rebuild_window("main")
            elif action == "rebuild_helper":
                self.rebuild_window("sorting")
        self.steps.append("(end)")


def _make(seed: int):
    def test(self):
        self.steps.append(f"seed {seed}")
        self.walk(seed)
    test.__name__ = f"test_seed_{seed}"
    return test


for _seed in SEEDS:
    setattr(RandomWalks, f"test_seed_{_seed}", _make(_seed))


class RandomWalksWithNativeTitleBars(RandomWalks):
    """The same walks with the macOS title bars and the system replacing windows' native windows now and then."""
    native_titlebars = True


for _seed in range(40):
    setattr(RandomWalksWithNativeTitleBars, f"test_seed_{_seed}", _make(_seed))
