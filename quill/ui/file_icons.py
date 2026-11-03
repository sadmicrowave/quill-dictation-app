"""Mini icons for the Available Files list: one per spreadsheet program or file type, drawn here from simple shapes.

They are Quill's own designs (a coloured tile with a grid or chart), not copies of any program's logo, so the app can be
sold without licensing anyone's artwork. A file with no known program or type gets a white page with its extension.
"""

from __future__ import annotations

import os
from html import escape

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

#: Program name (as the hosts report it, lower case) -> the tile colour and the picture on it.
GRID = '<path d="M6 8h12M6 12h12M6 16h12M10 6v12M14 6v12" stroke="#FFFFFF" stroke-width="1.5" fill="none"/>'
BARS = '<g fill="#FFFFFF"><rect x="6" y="12" width="3" height="6" rx="1"/><rect x="10.5" y="7" width="3" height="11" rx="1"/>' \
       '<rect x="15" y="10" width="3" height="8" rx="1"/></g>'
COMMAS = '<g fill="#FFFFFF"><circle cx="8" cy="10" r="1.5"/><circle cx="12" cy="10" r="1.5"/><circle cx="16" cy="10" r="1.5"/>' \
         '<circle cx="8" cy="15" r="1.5"/><circle cx="12" cy="15" r="1.5"/><circle cx="16" cy="15" r="1.5"/></g>'
TILES = {
    "excel": ("#1F7A4D", GRID),
    "numbers": ("#2FA84F", BARS),
    "libreoffice": ("#1E9AA8", GRID),
    "csv": ("#6B7A8C", COMMAS),
}
EXTENSIONS = {".xlsx": "excel", ".xlsm": "excel", ".xls": "excel", ".numbers": "numbers", ".ods": "libreoffice",
              ".csv": "csv", ".tsv": "csv"}


def kind_for(name: str, program: str = "") -> str:
    """Which tile a file gets: its program if known (Excel, Numbers, LibreOffice), else its type, else "" (a plain page)."""
    program = program.lower()
    for key in ("excel", "numbers", "libreoffice"):
        if key in program:
            return key
    return EXTENSIONS.get(os.path.splitext(name)[1].lower(), "")


def svg_for(name: str, program: str = "") -> str:
    """The SVG of the mini icon for the file *name* shown by *program* ("" when unknown)."""
    kind = kind_for(name, program)
    if kind in TILES:
        colour, art = TILES[kind]
        body = f'<rect x="2" y="2" width="20" height="20" rx="5" fill="{colour}"/>{art}'
    else:
        ext = os.path.splitext(name)[1].lstrip(".").upper()[:4]
        label = f'<text x="12" y="16.5" font-size="6" font-weight="700" text-anchor="middle" fill="#555555" ' \
                f'font-family="Helvetica,Arial,sans-serif">{escape(ext)}</text>' if ext else ""
        body = ('<path d="M5 3h9l5 5v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" fill="#FFFFFF" stroke="#B8B8B8" '
                'stroke-width="1"/><path d="M14 3v5h5" fill="#E4E4E4" stroke="#B8B8B8" stroke-width="1"/>' + label)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'


def file_icon(name: str, program: str = "", size: int = 18, scale: int = 2) -> QIcon:
    """The mini icon for a file as a QIcon *size* points square."""
    renderer = QSvgRenderer(QByteArray(svg_for(name, program).encode("utf-8")))
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)
