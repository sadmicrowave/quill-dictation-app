"""Mini icons for the Available Files list: one per spreadsheet program or file type, drawn here from simple shapes.

They are Quill's own drawings (the Excel one follows the look of the Excel logo, with its word removed and its greens shifted a
little; the others are a Numbers-style bar tile and white pages with an L or CSV), so the app can be sold without
licensing anyone's artwork. A file with no known program or type gets a white page with its extension.
"""

from __future__ import annotations

import os
from html import escape

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

#: The Numbers look, flat: a green rounded tile with three white bars standing on a white base line.
BARS = ('<g fill="#FFFFFF"><rect x="6.4" y="12.4" width="3.4" height="4.8" rx="1.3"/><rect x="10.4" y="5" width="3.6" height="12.2" rx="1.3"/>'
        '<rect x="14.6" y="8.6" width="3.4" height="8.6" rx="1.3"/><rect x="6.4" y="18.4" width="11.6" height="1.6" rx="0.8"/></g>')
#: The Excel picture: a sheet of tiles in two columns and four rows (darker towards the bottom) behind a box with an X.
EXCEL = ('<rect x="6.8" y="2.6" width="7.6" height="4.3" fill="#31925B"/><rect x="14.4" y="2.6" width="7.6" height="4.3" fill="#72C98F"/>'
         '<rect x="6.8" y="6.9" width="7.6" height="4.8" fill="#2F8A57"/><rect x="14.4" y="6.9" width="7.6" height="4.8" fill="#56A877"/>'
         '<rect x="6.8" y="11.7" width="7.6" height="4.5" fill="#297850"/><rect x="14.4" y="11.7" width="7.6" height="4.5" fill="#449563"/>'
         '<rect x="6.8" y="16.2" width="7.6" height="4.8" fill="#226445"/><rect x="14.4" y="16.2" width="7.6" height="4.8" fill="#2F7249"/>'
         '<rect x="2.3" y="6.9" width="10.1" height="10.1" rx="1.2" fill="#2E8052"/>'
         '<path d="M5.1 9.7 9.6 14.2M9.6 9.7 5.1 14.2" stroke="#FFFFFF" stroke-width="1.7" stroke-linecap="round" fill="none"/>')
#: A white page with a folded corner; the pictures below go in its middle.
PAGE = ('<path d="M5 3h9l5 5v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" fill="#FFFFFF" stroke="#B8B8B8" stroke-width="1"/>'
        '<path d="M14 3v5h5" fill="#E4E4E4" stroke="#B8B8B8" stroke-width="1"/>')
WORDS = {"csv": "CSV"}                     # what a page says when the type has its own word
TEXT = "#555555"                                               # the colour of the words and letters on a page
#: LibreOffice Calc, flat: a teal-green rounded tile with a white sheet (a grid of 2 columns and 3 rows).
GRID = ('<rect x="5.5" y="5" width="13" height="14" rx="1.6" fill="#FFFFFF"/><path d="M12 5v14M5.5 9.7h13M5.5 14.3h13" '
        'stroke="#1F8F6A" stroke-width="1.2" fill="none"/>')
TILES = {"numbers": ("#3E8E2F", BARS), "libreoffice": ("#1F8F6A", GRID)}      # a coloured tile behind a picture
EXTENSIONS = {".xlsx": "excel", ".xlsm": "excel", ".xls": "excel", ".numbers": "numbers", ".ods": "libreoffice",
              ".csv": "csv", ".tsv": "csv"}


def kind_for(name: str, program: str = "") -> str:
    """Which tile a file gets: the program showing it when that is known (an .xlsx open in LibreOffice is LibreOffice's tile,
    because that is what the user sees), else its type (.xlsx: Excel), else "" (a plain page with the extension).

    *program* may be a program name ("LibreOffice Calc") or a description ("Excel (.xlsx), open in LibreOffice Calc": the part
    after "open in" is the program)."""
    program = program.lower()
    if "open in " in program:
        program = program.split("open in ", 1)[1]
    shown = next((key for key in ("excel", "numbers", "libreoffice") if key in program), "")
    return shown or EXTENSIONS.get(os.path.splitext(name)[1].lower(), "")


def svg_for(name: str, program: str = "") -> str:
    """The SVG of the mini icon for the file *name* shown by *program* ("" when unknown)."""
    kind = kind_for(name, program)
    if kind == "excel":
        body = EXCEL
    elif kind in TILES:
        colour, art = TILES[kind]
        body = f'<rect x="2" y="2" width="20" height="20" rx="5" fill="{colour}"/>{art}'
    else:
        word = WORDS.get(kind) or os.path.splitext(name)[1].lstrip(".").upper()[:4]                 # (all words are the same size)
        middle = ""
        if word:
            middle = (f'<text x="12" y="16.5" font-size="6" font-weight="700" text-anchor="middle" fill="{TEXT}" '
                      f'font-family="Helvetica,Arial,sans-serif">{escape(word)}</text>')
        body = PAGE + middle
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
