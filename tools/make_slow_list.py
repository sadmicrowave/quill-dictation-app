"""Rewrite tests/slow_tests.txt: run the whole suite once and list the tests that take 0.25 s or more.

    .venv/bin/python tools/make_slow_list.py

A plain ``pytest`` skips those (about a minute and a half for the rest); ``pytest --full`` runs everything.
"""
from __future__ import annotations

import collections
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
THRESHOLD = 0.25


def main() -> int:
    run = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--full", "--durations=0"],
                         cwd=ROOT, capture_output=True, text=True)
    per: collections.Counter = collections.Counter()
    for line in run.stdout.splitlines():
        m = re.match(r"([0-9.]+)s (?:call|setup|teardown)\s+(\S+)", line)
        if m:
            per[m.group(2)] += float(m.group(1))
    slow = sorted(k for k, v in per.items() if v >= THRESHOLD)
    (ROOT / "tests" / "slow_tests.txt").write_text(
        "# Tests that take 0.25 s or more: skipped by a plain `pytest`, run with `pytest --full`.\n"
        "# Rewrite with `python tools/make_slow_list.py` (runs the whole suite once).\n" + "\n".join(slow) + "\n")
    print(f"{len(slow)} slow tests of {len(per)}; the rest take {sum(v for k, v in per.items() if k not in slow):.0f} s")
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
