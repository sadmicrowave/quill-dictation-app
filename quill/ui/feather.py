"""Quill's feather: the one drawing behind the app icon, the menu bar glyph and the About picture.

The feather is built from a few smooth curves (no straight strokes): a bent quill, a vane that is wider on one side, a thin rib
and a notch where the barbs part. Everything is a filled shape whose width changes along its length, like a brush stroke.
Points are on a 128 x 128 grid; :func:`icon_svg` wraps the feather in the app icon's squircle plate.
"""

from __future__ import annotations

import math

Point = tuple[float, float]

#: The app icon's plate colour (the accent violet) and the feather's colour on it.
PLATE = "#7A55C2"
INK = "#FFFFFF"


def bezier(p0: Point, p1: Point, p2: Point, p3: Point, n: int = 80) -> list[Point]:
    """*n* + 1 points along a cubic bezier curve."""
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def _normals(center: list[Point]) -> list[Point]:
    n = len(center)
    out = []
    for i in range(n):
        a, b = center[max(i - 1, 0)], center[min(i + 1, n - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        out.append((-dy / length, dx / length))
    return out


def tapered(center: list[Point], width) -> list[Point]:
    """A filled outline that follows *center* with a width ``width(t)`` (t from 0 to 1) that changes along it."""
    n = len(center)
    left, right = [], []
    for i, ((x, y), (nx, ny)) in enumerate(zip(center, _normals(center))):
        half = width(i / (n - 1)) / 2
        left.append((x + nx * half, y + ny * half))
        right.append((x - nx * half, y - ny * half))
    return left + right[::-1]


def blade(center: list[Point], wl, wr) -> list[Point]:
    """An outline around *center*, ``wl(t)`` wide on the left and ``wr(t)`` on the right (a vane is wider on one side)."""
    n = len(center)
    nrm = _normals(center)
    left = [(x + nx * wl(i / (n - 1)), y + ny * wl(i / (n - 1))) for i, ((x, y), (nx, ny)) in enumerate(zip(center, nrm))]
    right = [(x - nx * wr(i / (n - 1)), y - ny * wr(i / (n - 1))) for i, ((x, y), (nx, ny)) in enumerate(zip(center, nrm))]
    return left + right[::-1]


def _sub(points: list[Point], a: float, b: float) -> list[Point]:
    n = len(points) - 1
    return points[round(a * n):round(b * n) + 1]


def _at(points: list[Point], u: float) -> tuple[Point, Point]:
    i = round(u * (len(points) - 1))
    return points[i], _normals(points)[i]


def _vane_width(peak: float, lean: float = 0.62):
    """Width along a vane: nothing at both ends, widest a little before the middle."""
    power = math.log(lean) / math.log(0.5)
    return lambda u: peak * math.sin(math.pi * (u ** power)) ** 0.8


#: The quill's centre line: base lower left, tip upper right, bent a little.
SHAFT = bezier((24, 108), (32, 70), (66, 40), (110, 14), 160)
LEFT, RIGHT = 24.0, 19.0                                   # how wide the vane is on each side of the quill


def parts() -> dict[str, list[Point]]:
    """The pieces of the feather as outlines: ``body`` (the vane), ``quill``, ``rib`` (a thin line along the vane) and ``notch``
    (the sweeping cut where the barbs part). The rib and notch are *cut* from the vane, the others are drawn."""
    body = blade(_sub(SHAFT, 0.16, 1.0), _vane_width(LEFT), _vane_width(RIGHT))
    quill = tapered(SHAFT, lambda t: 6.5 - 5.2 * t)
    rib = tapered(_sub(SHAFT, 0.26, 0.94), lambda t: 3.4 - 2.4 * t)
    (x0, y0), (nx0, ny0) = _at(SHAFT, 0.46)
    (x1, y1), (nx1, ny1) = _at(SHAFT, 0.64)
    a = (x0 + nx0 * 2, y0 + ny0 * 2)
    b = (x1 + nx1 * (RIGHT + 5), y1 + ny1 * (RIGHT + 5))
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    notch = tapered(bezier(a, (mid[0] - 3, mid[1] + 2), (mid[0] + 3, mid[1] - 2), b, 40), lambda t: 0.8 + 5.4 * t)
    return {"body": body, "quill": quill, "rib": rib, "notch": notch}


def _d(points: list[Point]) -> str:
    return "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in points) + "Z"


def glyph_svg(ink: str = INK, cut: str = PLATE) -> str:
    """The feather alone (SVG elements on the 128 grid); *cut* is the colour behind it, shown through the rib and notch."""
    p = parts()
    return (f'<path d="{_d(p["body"])}" fill="{ink}"/><path d="{_d(p["quill"])}" fill="{ink}"/>'
            f'<path d="{_d(p["rib"])}" fill="{cut}"/><path d="{_d(p["notch"])}" fill="{cut}"/>')


def squircle(cx: float = 64, cy: float = 64, r: float = 60, n: float = 5.0, steps: int = 160) -> list[Point]:
    """The icon's plate: a superellipse, rounder and more continuous than a rounded rectangle."""
    pts = []
    for i in range(steps):
        a = 2 * math.pi * i / steps
        c, s = math.cos(a), math.sin(a)
        pts.append((cx + r * math.copysign(abs(c) ** (2 / n), c), cy + r * math.copysign(abs(s) ** (2 / n), s)))
    return pts


def _shade(color: str, k: float) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{max(0, min(255, round(v * k))):02X}" for v in (r, g, b))


def icon_svg(plate: str = PLATE, ink: str = INK) -> str:
    """The full app icon: the feather on a squircle that is one quiet shade lighter at the top than at the bottom."""
    defs = (f'<defs><linearGradient id="plate" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{_shade(plate, 1.12)}"/>'
            f'<stop offset="1" stop-color="{_shade(plate, 0.88)}"/></linearGradient></defs>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">{defs}'
            f'<path d="{_d(squircle())}" fill="url(#plate)"/>{glyph_svg(ink, _shade(plate, 1.0))}</svg>')
