"""Where Quill's bundled images live (works from source and from a PyInstaller build)."""

from __future__ import annotations
import pathlib
import sys

#: Sizes of the PNGs shipped for the window / Dock icon.
ICON_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def assets_dir() -> pathlib.Path:
    """The folder holding ``icon.svg``, ``icon-<size>.png``, ``Quill.icns`` and ``Quill.ico``."""
    bundle = getattr(sys, "_MEIPASS", None)
    base = pathlib.Path(bundle) / "quill" if bundle else pathlib.Path(__file__).resolve().parent
    return base / "assets"


def asset_path(name: str) -> pathlib.Path:
    """Full path of a bundled asset."""
    return assets_dir() / name


def app_icon():
    """The application icon as a QIcon (every shipped size, so Qt picks the sharpest)."""
    from PySide6.QtGui import QIcon
    icon = QIcon()
    for size in ICON_SIZES:
        path = asset_path(f"icon-{size}.png")
        if path.exists():
            icon.addFile(str(path))
    return icon
