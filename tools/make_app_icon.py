"""Build Quill's application icon files from the chosen design (idea 66: the offset sheet on violet).

    python tools/make_app_icon.py

Writes into ``quill/assets/``: ``icon.svg``, ``icon-<size>.png`` (16 to 1024), ``Quill.icns``
(macOS; needs the ``iconutil`` tool, so it is only rebuilt on a Mac) and ``Quill.ico`` (Windows;
written directly, PNG-compressed, no extra packages). The files are committed, so this only needs
re-running to change the design.
"""

from __future__ import annotations
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from make_icon_ideas import render_png, sheet_offset_body  # noqa: E402
from quill.assets import ICON_SIZES  # noqa: E402

OUT = ROOT / "quill" / "assets"
COLOR = "#7A55C2"                      # violet
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
#: The small front box as (x, y, size): bigger than the first design (16, 39, 50) so the sound lines read in the Dock.
BOX = (11, 32, 64)
SMALL = 48                              # at this size and below the simplified sound lines are used


def svg_for(size: int) -> str:
    """The icon's SVG for *size* px: seven thin sound lines are fine large, five bold ones read better small."""
    return sheet_offset_body(COLOR, simple=size <= SMALL, box=BOX)


def write_ico(path: pathlib.Path, svg: str | None = None) -> None:
    """A multi-size .ico whose entries are PNG images (Windows Vista and later)."""
    images = []
    with tempfile.TemporaryDirectory() as tmp:
        for size in ICO_SIZES:
            png = pathlib.Path(tmp) / f"{size}.png"
            render_png(svg or svg_for(size), str(png), size)
            images.append((size, png.read_bytes()))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    directory, data = b"", b""
    for size, blob in images:
        directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    path.write_bytes(header + directory + data)


def write_icns(path: pathlib.Path) -> bool:
    """A macOS .icns through ``iconutil``; returns False where that tool does not exist."""
    if shutil.which("iconutil") is None:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        iconset = pathlib.Path(tmp) / "Quill.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            render_png(svg_for(size), str(iconset / f"icon_{size}x{size}.png"), size)
            render_png(svg_for(size * 2), str(iconset / f"icon_{size}x{size}@2x.png"), size * 2)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(path)], check=True)
    return True


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon.svg").write_text(sheet_offset_body(COLOR, box=BOX), encoding="utf-8")
    (OUT / "icon-small.svg").write_text(sheet_offset_body(COLOR, simple=True, box=BOX), encoding="utf-8")
    for size in ICON_SIZES:
        render_png(svg_for(size), str(OUT / f"icon-{size}.png"), size)
    write_ico(OUT / "Quill.ico")
    made_icns = write_icns(OUT / "Quill.icns")
    print(f"Wrote the icon files to {OUT}" + ("" if made_icns else " (no iconutil here: kept the existing .icns)"))


if __name__ == "__main__":
    main()
