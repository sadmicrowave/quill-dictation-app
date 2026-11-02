"""Check, on a real screen, that the Opacity and Blur settings do what they say.

    .venv/bin/python tools/verify_window_effects.py

macOS only; needs screen recording permission for the terminal. The unit tests cannot see pixels, so this puts a
fine black-and-white striped window *behind* Quill, applies each pair of settings, takes a screenshot and measures a
patch of the window's own background (a margin with no controls on it):

* **std**: how much the stripes still show (high = sharp desktop, low = blurred or hidden);
* **mean**: how far the background is from the solid theme colour (0 = solid, larger = more see-through).

What each pair must give (dark theme; the checks are printed as OK / FAIL):

* opacity 100, any blur .......... solid: std ~0, mean = theme colour
* opacity 50, blur 0 ............. see-through and SHARP: the stripes show (std high)
* opacity 50, blur 60 and 100 .... see-through and BLURRED: std a small fraction of the sharp one, mean moved
* opacity 20 vs 80 at blur 60 ... the lower the opacity the further the mean moves
* blur 8 vs 100 at opacity 40 .... wide bands still show at a small radius and are smoothed at a large one
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


def measure(opacity: int, blur: int, band: int = 2) -> dict:
    """Run the app with these settings in this process and return the measurements."""
    sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QWidget

    from quill.app import QuillApp, QuillApplication
    from quill.bridge.factory import startup_bridge
    from quill.config.settings import Settings
    from quill.demo import make_demo_workbook

    tmp = pathlib.Path(tempfile.mkdtemp())
    settings = Settings.load(tmp / "cfg")
    settings.preferences.update({"opacity": opacity, "blur": blur, "theme": "dark"})
    app = QuillApplication(sys.argv[:1])
    app.setApplicationName("Quill")
    quill = QuillApp(app, settings, startup_bridge(settings, str(make_demo_workbook(tmp))))
    quill.start()
    window = quill.window.widget
    result = {}

    class Stripes(QWidget):
        def paintEvent(self, event):
            painter = QPainter(self)
            for y in range(0, self.height(), 2 * band):              # horizontal bands: the measured patch is tall, not wide
                painter.fillRect(0, y, self.width(), band, QColor("#ffffff"))
                painter.fillRect(0, y + band, self.width(), band, QColor("#000000"))

    stripes = Stripes()
    stripes.setWindowFlags(Qt.WindowType.FramelessWindowHint)

    def place():
        stripes.setGeometry(window.frameGeometry())
        stripes.show()                                   # an ordinary window, so no other program's window can sit between
        stripes.raise_()
        QTimer.singleShot(300, lambda: (window.raise_(), window.activateWindow()))   # Quill goes on top of it

    def look():
        g = window.frameGeometry()
        path = tmp / "shot.png"
        subprocess.run(["screencapture", "-x", "-R", f"{g.x()},{g.y()},{g.width()},{g.height()}", str(path)], check=False)
        image = QImage(str(path))
        values = [QColor(image.pixel(x, y)).lightness() for x in range(4, 14) for y in range(300, 700, 2)]
        mean = sum(values) / len(values)
        std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        result.update(mean=round(mean, 1), std=round(std, 1))
        print("RESULT " + json.dumps({"opacity": opacity, "blur": blur, "band": band, **result}))
        app.quit()

    QTimer.singleShot(2500, place)
    QTimer.singleShot(4500, look)
    app.exec()
    return result


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--case":
        measure(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
        return 0
    cases = [(100, 0, 2), (100, 60, 2), (50, 0, 2), (50, 60, 2), (50, 100, 2), (20, 60, 2), (80, 60, 2),
             (40, 8, 14), (40, 100, 14)]
    got = {}
    for opacity, blur, band in cases:
        run = subprocess.run([sys.executable, __file__, "--case", str(opacity), str(blur), str(band)], capture_output=True, text=True)
        line = next((l for l in run.stdout.splitlines() if l.startswith("RESULT ")), None)
        if line is None:
            print("no result for", opacity, blur, run.stderr[-300:])
            return 1
        data = json.loads(line[7:])
        got[(opacity, blur)] = data
        print(f"opacity {opacity:3d} blur {blur:3d} band {band:2d}: mean {data['mean']:6.1f} std {data['std']:6.1f}")
    solid = got[(100, 0)]["mean"]
    sharp = got[(50, 0)]["std"]
    checks = [
        ("opacity 100 is solid at any blur", got[(100, 0)]["std"] < 3 and got[(100, 60)]["std"] < 3
         and abs(got[(100, 60)]["mean"] - solid) < 3),
        ("opacity 50 without blur is see-through and sharp", sharp > 15 and abs(got[(50, 0)]["mean"] - solid) > 8),
        ("opacity 50 with blur is blurred (stripes mostly gone)", got[(50, 60)]["std"] < 0.35 * sharp
         and got[(50, 100)]["std"] < 0.35 * sharp),
        ("opacity 50 with blur is still see-through", abs(got[(50, 60)]["mean"] - solid) > 8),
        ("lower opacity moves the background further", abs(got[(20, 60)]["mean"] - solid) > abs(got[(80, 60)]["mean"] - solid)),
        ("more blur fades wide bands further (blur 8 leaves them, 100 smooths them)", got[(40, 8)]["std"] > 4 * max(got[(40, 100)]["std"], 0.5)),
    ]
    failed = 0
    for name, ok in checks:
        print(("OK   " if ok else "FAIL ") + name)
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
