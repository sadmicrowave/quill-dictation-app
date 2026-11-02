"""How thick each part of a see-through window is painted, so that what the user sees matches the Opacity slider.

The slider's value is how thick the window should look: 1 is solid, 0 clear. What has to be *painted* to get that look is not
the same number: macOS composites a window's layers in its own way, gives some windows two layers whose backgrounds add, and
does it differently for a dark colour than for a light one. So the paint alphas come from tables measured on a real screen
(``tools/calibrate_opacity.py`` writes them here, ``tools/verify_control_opacity.py`` checks the result):

* **paint**: the alpha of the window's own background, per number of layers behind it (a window with a native child widget
  has two);
* **bar**: the alpha of the tint over the (system-drawn) title bar, which must look as thick as the background beside it;
* **control**: the alpha of the fill of text boxes, drop-downs, buttons and cards, which is laid over the background and
  must make the pair a little thicker than the background alone (:data:`CONTROL_LIFT`).

Each table is a list of values at :data:`KNOTS` (the slider's 0.2, 0.4, 0.6 and 0.8; 0 and 1 are fixed), read with straight lines
between. ``QUILL_CAL='{"paint": 0.3, "bar": 0.4, "control": 0.1}'`` forces those alphas (the calibration tool does this).
"""
from __future__ import annotations

import json
import os

#: How much thicker than the window's own background a control may look.
CONTROL_LIFT = 0.08
#: The thinnest fill a control gets (so it never vanishes into the background).
CONTROL_FLOOR = 0.06

KNOTS = (0.2, 0.4, 0.6, 0.8)

# Measured on a real screen with tools/calibrate_opacity.py (paint1 = a window with one layer behind its background: the
# value is the slider's own).
TABLES: dict = {
    "light": {"paint1": list(KNOTS), "paint2": [0.112, 0.231, 0.379, 0.561], "bar": [0.2, 0.4, 0.6, 0.8],
              "control": [0.06, 0.069, 0.15, 0.312]},
    "dark": {"paint1": list(KNOTS), "paint2": [0.101, 0.227, 0.352, 0.561], "bar": [0.2, 0.4, 0.6, 0.8],
             "control": [0.06, 0.06, 0.06, 0.06]},
}

try:
    OVERRIDE: dict = json.loads(os.environ.get("QUILL_CAL", "{}"))
except ValueError:
    OVERRIDE = {}


def _read(values: list[float], thick: float) -> float:
    """The table's value for slider position *thick* (straight lines between knots; 0 -> the first knot's trend, 1 -> 1)."""
    thick = max(0.0, min(1.0, float(thick)))
    xs = (0.0, *KNOTS, 1.0)
    ys = (0.0, *values, 1.0)
    for i in range(len(xs) - 1):
        if thick <= xs[i + 1]:
            span = xs[i + 1] - xs[i]
            return ys[i] + (ys[i + 1] - ys[i]) * ((thick - xs[i]) / span if span else 0.0)
    return 1.0


def paint_alpha(thick: float, dark: bool, layers: int) -> float:
    """The alpha to paint a window's background so that, behind *layers* native layers, it looks *thick* thick."""
    if "paint" in OVERRIDE:
        return float(OVERRIDE["paint"])
    if thick >= 1.0:
        return 1.0
    return max(0.0, min(1.0, _read(TABLES["dark" if dark else "light"]["paint2" if layers > 1 else "paint1"], thick)))


def bar_alpha(thick: float, dark: bool) -> float:
    """The alpha of the tint over the title bar for a window that should look *thick* thick."""
    if "bar" in OVERRIDE:
        return float(OVERRIDE["bar"])
    if thick >= 1.0:
        return 1.0
    return max(0.0, min(1.0, _read(TABLES["dark" if dark else "light"]["bar"], thick)))


def control_alpha(thick: float, dark: bool) -> float:
    """The alpha of a control's fill for a window that looks *thick* thick."""
    if "control" in OVERRIDE:
        return float(OVERRIDE["control"])
    if thick >= 0.995:
        return 1.0
    return max(CONTROL_FLOOR, min(1.0, _read(TABLES["dark" if dark else "light"]["control"], thick)))
