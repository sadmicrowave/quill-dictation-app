"""Measure, on a real screen, which alphas have to be painted for the Opacity slider's values to look right.

    .venv/bin/python tools/calibrate_opacity.py

Prints the TABLES for ``quill/ui/glass.py`` (leave the screen alone while it runs, a quarter of an hour). For each theme and each
slider position it finds, by trial and error against measurements (see ``verify_control_opacity.py``), the alpha of

* the window's background (``paint``): so that the background looks as thick as the slider says,
* the title bar tint (``bar``): so that the bar looks as thick as the background,
* a control's fill (``control``): so that a control looks CONTROL_LIFT thicker than the background.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import verify_control_opacity as V                      # noqa: E402
from quill.ui import glass                              # noqa: E402


def thick(value: float, solid: float) -> float:
    return (V.GREY - value) / (V.GREY - solid)


def solve(measure, target: float, start: float, lo: float = 0.0, hi: float = 1.0, steps: int = 5) -> float:
    """Find x with measure(x) = target (measure rises with x) by secant steps from *start*, kept inside [lo, hi]."""
    x, y = start, measure(start)
    prev = None
    for _ in range(steps):
        if abs(y - target) < 0.012:
            break
        slope = 1.0 if prev is None or abs(x - prev[0]) < 1e-6 else (y - prev[1]) / (x - prev[0])
        slope = max(0.4, min(3.0, slope))
        nx = max(lo, min(hi, x + (target - y) / slope))
        prev = (x, y)
        x, y = nx, measure(nx)
    return x


def calibrate(theme: str, scenario: str = "main") -> dict:
    accent = "violet" if theme == "light" else "ocean"
    base = V.spawn({"scenario": scenario, "theme": theme, "accent": accent, "opacity": 100, "blur": 0})
    solid_body, solid_bar = base["body"], base["bar"]
    solid_ctl = {c["label"]: c["mean"] for c in base["controls"]}
    out = {"paint2": [], "bar": [], "control": []}
    for t in glass.KNOTS:
        cache: dict = {}

        def run(paint: float, bar: float, control: float) -> dict:
            key = (round(paint, 3), round(bar, 3), round(control, 3))
            if key not in cache:
                cache[key] = V.spawn({"scenario": scenario, "theme": theme, "accent": accent, "opacity": 50, "blur": 60,
                                      "cal": {"paint": key[0], "bar": key[1], "control": key[2]}})
            return cache[key]

        paint = solve(lambda p: thick(run(p, t, 0.1)["body"], solid_body), t, start=t)
        bar = solve(lambda s: thick(run(paint, s, 0.1)["bar"], solid_bar), t, start=t)

        def controls(c: float) -> float:
            got = run(paint, bar, c)
            values = [thick(x["mean"], solid_ctl[x["label"]]) for x in got["controls"] if x["label"] in solid_ctl]
            return sum(values) / len(values)

        control = solve(controls, min(1.0, t + glass.CONTROL_LIFT), start=0.15, lo=glass.CONTROL_FLOOR, hi=1.0)
        final = run(paint, bar, control)
        print(f"  {theme:5s} {t:.1f}: paint {paint:.3f} bar {bar:.3f} control {control:.3f}   -> background "
              f"{thick(final['body'], solid_body):.2f} bar {thick(final['bar'], solid_bar):.2f} controls {controls(control):.2f}", flush=True)
        out["paint2"].append(round(paint, 3))
        out["bar"].append(round(bar, 3))
        out["control"].append(round(control, 3))
    return out


def main() -> int:
    tables = {theme: calibrate(theme) for theme in ("light", "dark")}
    print("\nTABLES = {")
    for theme, t in tables.items():
        print(f'    "{theme}": {{"paint1": list(KNOTS), "paint2": {t["paint2"]}, "bar": {t["bar"]}, "control": {t["control"]}}},')
    print("}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
