"""Check, on a real screen, that Opacity and Blur reach every control of every window.

    .venv/bin/python tools/verify_control_opacity.py            # the whole matrix (several minutes; leave the screen alone)
    .venv/bin/python tools/verify_control_opacity.py quick      # one theme, fewer cases

macOS only; needs screen recording permission. A striped window is put behind the window under test. With the blur on, the
desktop behind is smoothed to a flat grey, so how much of it shows through any spot is just how far its lightness moved
from its solid (opacity 100) lightness towards that grey:

    thickness = (grey - lightness) / (grey - solid lightness)        # 1 = solid, 0 = clear

The window's own background (a margin) is the reference. A control (text box, drop-down, button, card, table, list ...) must
be at most LIFT thicker than that, and never thinner, in every window, theme, accent, view and size. The title bar is held
to the same reference. Each failure is printed with its window, view and control.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.environ.setdefault("QUILL_NO_HOSTS", "1")

GREY = 127.5            # the lightness of the blurred black-and-white stripes
LIFT = 0.16             # how much thicker than the window's background a control may be (and at most 0.10 thinner)
BODY_TOLERANCE = 0.10   # how far the background's thickness may be from the slider's value
OPACITIES = (30, 60, 85)
SCENARIOS = ("main", "main-panel-file", "main-panel-turn", "main-log", "main-resized", "mini", "settings-general",
             "settings-appearance", "settings-sounds", "settings-keywords", "settings-speech", "help", "term-helper", "file-overlay")
#: More looks for a few scenarios: (theme, accent, spacing).
EXTRA_LOOKS = (("light", "forest", "comfortable"), ("dark", "rose", "comfortable"))
EXTRA_SCENARIOS = ("main", "main-panel-file", "main-panel-turn", "mini", "settings-general", "settings-keywords", "help", "term-helper",
                   "main-log", "file-overlay")


# --------------------------------------------------------------------------- #
# One case, in its own process                                                 #
# --------------------------------------------------------------------------- #

def run_case(case: dict) -> None:
    if case.get("cal"):
        os.environ["QUILL_CAL"] = json.dumps(case["cal"])              # force the painted alphas (see tools/calibrate_opacity.py)
    sys.path.insert(0, str(ROOT))
    import numpy as np
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import (QAbstractScrollArea, QComboBox, QFrame, QLineEdit, QPushButton, QSpinBox, QTextEdit,
                                   QPlainTextEdit, QTableWidget, QWidget)

    from quill.app import QuillApp, QuillApplication
    from quill.bridge.factory import startup_bridge
    from quill.config.settings import Settings
    from quill.demo import make_demo_workbook

    tmp = pathlib.Path(tempfile.mkdtemp())
    settings = Settings.load(tmp / "cfg")
    settings.preferences.update({"opacity": case["opacity"], "blur": case["blur"], "theme": case["theme"],
                                 "accent": case["accent"], "sorting_follows_opacity": True, "spacing": case.get("spacing", "compact")})
    app = QuillApplication(sys.argv[:1])
    app.setApplicationName("Quill")
    app.setQuitOnLastWindowClosed(False)
    quill = QuillApp(app, settings, startup_bridge(settings, str(make_demo_workbook(tmp))))
    quill.start()
    main = quill.window
    scenario = case["scenario"]
    state: dict = {}

    def target() -> QWidget:
        return state["window"]

    def setup() -> None:
        main.widget.move(60, 60)
        if scenario == "main":
            state["window"] = main.widget
        elif scenario == "main-panel-file":
            main.open_panel("file")
            state["window"] = main.widget
        elif scenario == "main-panel-turn":
            main.open_panel("turn")
            state["window"] = main.widget
        elif scenario == "main-log":
            main.set_log_collapsed(False)
            state["window"] = main.widget
        elif scenario == "main-resized":
            main.open_panel("file")
            main.widget.resize(900, 640)
            state["window"] = main.widget
        elif scenario == "mini":
            main.set_mini(True)
            state["window"] = main.widget
        elif scenario.startswith("settings-"):
            page = {"general": "General", "appearance": "Appearance", "sounds": "Sounds", "keywords": "Keywords", "speech": "Speech Model"}[scenario[9:]]
            quill.open_settings(page)
            quill._settings_dialog._dialog.move(100, 100)
            state["window"] = quill._settings_dialog._dialog
        elif scenario == "help":
            quill.open_help("welcome")
            quill.help._window.move(100, 100)
            state["window"] = quill.help._window
        elif scenario == "term-helper":
            quill.controller.session.pending = [(None, "teal"), ("Size", "medium")]
            quill.show_sorting()
            quill.sorting.widget.move(100, 100)
            state["window"] = quill.sorting.widget
        elif scenario == "file-overlay":
            main.open_panel("file")
            QTimer.singleShot(400, lambda: (main.show_file_settings(), None))
            state["window"] = main.panel.settings

    stripes = None

    class Stripes(QWidget):
        def paintEvent(self, event):
            p = QPainter(self)
            for y in range(0, self.height(), 4):
                p.fillRect(0, y, self.width(), 2, QColor("#ffffff"))
                p.fillRect(0, y + 2, self.width(), 2, QColor("#000000"))

    def place() -> None:
        nonlocal stripes
        window = target()
        g = window.frameGeometry()
        stripes = Stripes()
        stripes.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        stripes.setGeometry(g.adjusted(-6, -6, 6, 6))
        stripes.show()
        stripes.raise_()
        window.raise_()
        window.activateWindow()

    def regrow() -> None:
        window = target()
        stripes.setGeometry(window.frameGeometry().adjusted(-6, -6, 6, 6))
        stripes.show()
        stripes.raise_()
        window.raise_()

    KINDS = (QLineEdit, QComboBox, QSpinBox, QPushButton, QTextEdit, QPlainTextEdit, QTableWidget)

    def interesting(w: QWidget) -> bool:
        if not w.isVisible() or w.width() < 50 or w.height() < 22:
            return False
        if isinstance(w, QPushButton) and (w.property("accent") or w.isChecked()):
            return False                                   # an accent button is solid by design
        if isinstance(w, QLineEdit) and w.property("pillField"):
            return False                                   # a spoken-word pill is solid by design
        if isinstance(w, QComboBox) and w.property("flat"):
            return False                                   # a flat drop-down has no fill of its own
        if w.parent() is not None and isinstance(w.parent(), (QSpinBox, QComboBox)):
            return False                                   # the editor inside a spin box or drop-down
        return isinstance(w, KINDS) or (isinstance(w, QFrame) and w.objectName() in ("termRow", "fileSettings"))

    def measure() -> None:
        window = target()
        g = window.frameGeometry()
        path = tmp / "shot.png"
        subprocess.run(["screencapture", "-x", "-R", f"{g.x()},{g.y()},{g.width()},{g.height()}", str(path)], check=False)
        if case.get("keep"):
            import shutil
            shutil.copy(path, case["keep"])                         # (to look at what was measured)
        image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGB888)
        arr = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
        arr = arr[:, : image.width() * 3].reshape(image.height(), image.width(), 3).astype(float)
        light = (arr.max(axis=2) + arr.min(axis=2)) / 2                         # HSL lightness, like QColor.lightness()
        scale = image.width() / g.width()

        def patch(x0, y0, x1, y1):
            ys, xs = slice(max(0, int(y0)), max(1, int(y1))), slice(max(0, int(x0)), max(1, int(x1)))
            block = light[ys, xs]
            return float(block.mean()) if block.size else float("nan")

        out = {"case": case, "controls": []}
        # the window's own background: a margin down the left, and the title bar between the icons and the title
        bx = 5                                                        # (past the window's rim)
        out["body"] = patch(bx * scale, g.height() * 0.5 * scale, (bx + 3) * scale, g.height() * 0.5 * scale + 40)
        out["bar"] = patch(g.width() * 0.38 * scale, 18 * scale, g.width() * 0.43 * scale, 28 * scale)
        seen: dict[str, int] = {}
        for w in window.findChildren(QWidget):
            if not interesting(w):
                continue
            top_left = w.mapToGlobal(QPoint(0, 0))
            x, y = (top_left.x() - g.x()) * scale, (top_left.y() - g.y()) * scale
            width, height = w.width() * scale, w.height() * scale
            if w.objectName() == "helpPage":
                m = patch(x + 6 * scale, y + height * 0.5, x + 24 * scale, y + height * 0.5 + 40)       # the page's margin (it holds pictures)
            elif height < 70 * scale:
                m = patch(x + width * 0.42, y + 3 * scale, x + width * 0.58, y + 6.5 * scale)         # the top edge, above any text
            else:
                m = patch(x + width * 0.55, y + height * 0.62, x + width * 0.75, y + height * 0.80)    # inside, below the first line
            kind = type(w).__name__ + ("#" + w.objectName() if w.objectName() else "")
            seen[kind] = seen.get(kind, 0) + 1
            out["controls"].append({"label": f"{kind}[{seen[kind]}]@{int(top_left.x() - g.x())},{int(top_left.y() - g.y())}", "mean": m})
        print("RESULT " + json.dumps(out), flush=True)
        app.quit()

    QTimer.singleShot(2500, setup)
    QTimer.singleShot(3400, place)
    QTimer.singleShot(4800, regrow)                         # (a window may have changed size since: the stripes follow it)
    QTimer.singleShot(6200, measure)
    app.exec()


# --------------------------------------------------------------------------- #
# The matrix                                                                   #
# --------------------------------------------------------------------------- #

def spawn(case: dict) -> dict | None:
    try:
        run = subprocess.run([sys.executable, __file__, "--case", json.dumps(case)], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print("  timed out (was the computer asleep?):", case, flush=True)
        return None
    line = next((l for l in run.stdout.splitlines() if l.startswith("RESULT ")), None)
    if line is None:
        print("  no result for", case, run.stderr[-300:])
        return None
    return json.loads(line[7:])


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--case":
        run_case(json.loads(sys.argv[2]))
        return 0
    quick = "quick" in sys.argv
    only = [a for a in sys.argv[1:] if a in SCENARIOS]
    themes = (("light", "violet"),) if quick else (("light", "violet"), ("dark", "ocean"))
    opacities = (45,) if quick else OPACITIES
    failures = 0
    checked = 0
    looks = [(sc, th, ac, "compact") for sc in (only or SCENARIOS) for th, ac in themes]
    if (not only and not quick) or "extras" in sys.argv:
        looks += [(sc, th, ac, sp) for sc in (only or EXTRA_SCENARIOS) for th, ac, sp in EXTRA_LOOKS]
    for scenario, theme, accent, spacing in looks:
        if True:
            base = spawn({"scenario": scenario, "theme": theme, "accent": accent, "spacing": spacing, "opacity": 100, "blur": 0})
            if base is None:
                failures += 1
                continue
            solid = {c["label"]: c["mean"] for c in base["controls"]}
            for opacity in opacities:
                got = spawn({"scenario": scenario, "theme": theme, "accent": accent, "spacing": spacing, "opacity": opacity, "blur": 60})
                if got is None:
                    failures += 1
                    continue

                def thick(value, solid_value):
                    return (GREY - value) / (GREY - solid_value) if abs(GREY - solid_value) > 25 else None

                body = thick(got["body"], base["body"])
                bar = thick(got["bar"], base["bar"])
                tag = f"{scenario:20s} {theme:5s} {accent:7s} {spacing[:4]} opacity {opacity:3d}"
                problems = []
                if body is not None and abs(body - opacity / 100) > BODY_TOLERANCE:
                    problems.append(f"background {body:.2f} is not the slider's {opacity / 100:.2f}")
                if bar is not None and body is not None and abs(bar - body) > 0.08:
                    problems.append(f"title bar {bar:.2f} differs from the background {body:.2f}")
                rows = []
                for c in got["controls"]:
                    s = solid.get(c["label"])
                    if s is None:
                        continue
                    t = thick(c["mean"], s)
                    if t is None or body is None:
                        continue
                    checked += 1
                    rows.append((c["label"], t))
                    if t > body + LIFT:
                        problems.append(f"{c['label']} is {t:.2f} thick, background {body:.2f}")
                    if t < body - 0.10:
                        problems.append(f"{c['label']} is thinner ({t:.2f}) than the background {body:.2f}")
                worst = max((t for _, t in rows), default=float("nan"))
                print(f"{'OK  ' if not problems else 'FAIL'} {tag}  background {body if body is None else round(body, 2)}"
                      f"  bar {bar if bar is None else round(bar, 2)}  controls {len(rows)}  thickest {worst:.2f}", flush=True)
                for p in problems:
                    print("       " + p, flush=True)
                failures += bool(problems)
    print(f"{checked} controls checked; {failures} cases failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
