"""Shared by the VM journey scripts (``looks.py``, ``dictation.py``, ``libreoffice.py``): a report of checks, screenshots, and a Qt application.

Each script is run by the VM job runner as ``python <script> --out <folder>`` and writes ``checks.json`` there: a list of
``{"name", "ok", "detail", "shot"}``. ``--offscreen`` runs it with Qt's headless plugin (for trying a script on any machine; checks that need the real
screen then say they were skipped).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[2]


def parse(description: str, argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--out", type=pathlib.Path, required=True, help="the folder for the checks and the screenshots")
    parser.add_argument("--offscreen", action="store_true", help="Qt's headless plugin (no real screen)")
    return parser.parse_args(argv)


def start_qt(offscreen: bool):
    """The QApplication, with the project on the path. The display plugin is chosen before Qt is imported."""
    if offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    for variable in ("QUILL_NO_HOSTS", "QUILL_NO_SOUND"):                 # (set by the test suite; a journey runs the real thing)
        os.environ.pop(variable, None)
    os.environ["QUILL_NO_SOUND"] = "1"                                    # ... but no noise from the VM
    sys.path.insert(0, str(ROOT))
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([sys.argv[0]])


class Report:
    """The checks of one run, kept as they are made and written out at the end (and after each one, so a crash loses nothing)."""

    def __init__(self, out: pathlib.Path, offscreen: bool = False) -> None:
        self.out = pathlib.Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.checks: list[dict] = []
        self.offscreen = offscreen

    def check(self, name: str, ok: bool, detail: str = "", shot: str = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": str(detail), "shot": shot})
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""), flush=True)
        self.save()
        return bool(ok)

    def skip(self, name: str, why: str) -> None:
        """Not run (it needs something this machine does not have): counted as held, and said so."""
        self.check(name, True, f"skipped: {why}")

    def save(self) -> None:
        (self.out / "checks.json").write_text(json.dumps(self.checks, indent=2), encoding="utf-8")

    def attempt(self, name: str, function) -> None:
        """Run *function*; an error in it is one failed check, not the end of the run."""
        try:
            function()
        except Exception:                                                  # noqa: BLE001
            self.check(name, False, traceback.format_exc(limit=6))

    # ---- pictures ----------------------------------------------------------------------------------------------------------------------------
    def widget_shot(self, widget, name: str) -> str:
        """The widget as Qt draws it (its own pixels), saved as ``<name>.png``."""
        path = self.out / f"{name}.png"
        widget.grab().save(str(path))
        return path.name

    def screen_shot(self, name: str, rect=None) -> str:
        """What is on the real screen now (tool tips, menus and other windows included), cropped to *rect* (a QRect, global coordinates)."""
        from PySide6.QtGui import QGuiApplication
        pixmap = QGuiApplication.primaryScreen().grabWindow(0)
        if rect is not None:
            pixmap = pixmap.copy(rect)
        path = self.out / f"{name}.png"
        pixmap.save(str(path))
        return path.name


def wait(ms: int) -> None:
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


def screen_image():
    """The whole screen as a QImage (for reading pixels), or None where there is no real screen."""
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    return screen.grabWindow(0).toImage() if screen is not None else None


def corners_are_clear(image, rect, margin: int = 4, radius_hint: int = 5) -> tuple[bool, str]:
    """Do the four corners of the window at *rect* (global coordinates) show what is behind it, not a square dark corner?

    For each corner a pixel *inside* the window box and right at its corner is compared with one just *outside* it. A rounded window shows the desktop
    in the corner, so the two are alike; a square window with black behind the border shows black against the desktop.
    """
    if image is None:
        return True, "no screen"
    points = {"top-left": (rect.left(), rect.top(), -margin, -margin), "top-right": (rect.right(), rect.top(), margin, -margin),
              "bottom-left": (rect.left(), rect.bottom(), -margin, margin), "bottom-right": (rect.right(), rect.bottom(), margin, margin)}
    bad = []
    for name, (x, y, dx, dy) in points.items():
        inside = image.pixelColor(x, y)
        outside = image.pixelColor(max(0, min(image.width() - 1, x + dx)), max(0, min(image.height() - 1, y + dy)))
        darkness = (inside.red() + inside.green() + inside.blue()) / 3
        difference = max(abs(inside.red() - outside.red()), abs(inside.green() - outside.green()), abs(inside.blue() - outside.blue()))
        if darkness < 25 and difference > 40:                               # nearly black, and not what is behind it
            bad.append(f"{name} is {inside.name()} against {outside.name()}")
    return not bad, "; ".join(bad)


def scratch_folder(prefix: str = "quill-vm-") -> pathlib.Path:
    return pathlib.Path(tempfile.mkdtemp(prefix=prefix))
