"""Which runners the ``tests`` workflow uses for an event, as the matrix the workflow reads (printed as ``matrix={...}`` for ``$GITHUB_OUTPUT``).

    python tools/ci_plan.py --event pull_request --base develop --changed changed.txt

* A pull request into ``develop`` (the everyday lane) runs the quick tests on macOS 26 and Windows 2025: both, unless every changed file belongs to one system
  only (a change that touches only the Windows provider or the Windows installer needs no Mac run, and the other way round).
* Everything else (a pull request into ``main``, a push to ``main``, the weekly run, a manual run) uses every runner.

The patterns below name files that only one system ever runs. A file in no list counts for both, so a doubtful change always gets the full pair.
"""
from __future__ import annotations

import argparse
import json
import pathlib

MAC = {"os": "macos-26"}
WINDOWS = {"os": "windows-2025"}
EVERY_RUNNER = [{"os": "macos-26"}, {"os": "macos-15"}, {"os": "macos-15-intel"}, {"os": "windows-2025"}, {"os": "windows-2022"},
                {"os": "windows-11-arm", "experimental": True}]

#: Files only Windows runs (its provider, its packaging).
WINDOWS_ONLY = ("quill/platforms/windows/", "packaging/quill_win", "tools/build_win.bat", "tools/Send Quill self-check.bat",
                ".github/workflows/dev-build.yml")
#: Files only a Mac runs.
MAC_ONLY = ("quill/platforms/macos/", "tests/macos/", "packaging/quill_mac", "tools/build_mac.sh", "tools/onscreen_setup.sh", "tools/quill-demo.command",
            "tools/numbers_placement_check.py", "docs/onscreen-journeys.md")


def belongs_to(path: str, prefixes: tuple[str, ...]) -> bool:
    return path.startswith(prefixes)


def runners_for(changed: list[str]) -> list[dict]:
    """The quick lane's runners for a pull request that changed *changed*: one system when only its own files changed, else both."""
    files = [f.strip() for f in changed if f.strip()]
    if files and all(belongs_to(f, WINDOWS_ONLY) for f in files):
        return [WINDOWS]
    if files and all(belongs_to(f, MAC_ONLY) for f in files):
        return [MAC]
    return [MAC, WINDOWS]


def plan(event: str, base: str = "", changed: list[str] | None = None) -> dict:
    if event == "pull_request" and base == "develop":
        return {"include": runners_for(changed or [])}
    return {"include": EVERY_RUNNER}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--event", required=True)
    parser.add_argument("--base", default="", help="the branch a pull request goes into")
    parser.add_argument("--changed", type=pathlib.Path, help="a file with the changed paths, one per line")
    args = parser.parse_args(argv)
    changed = args.changed.read_text(encoding="utf-8").splitlines() if args.changed and args.changed.is_file() else []
    print("matrix=" + json.dumps(plan(args.event, args.base, changed), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
