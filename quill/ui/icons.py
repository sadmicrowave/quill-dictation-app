"""Small line icons drawn from SVG in whatever colour the theme needs."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

#: Icon name -> SVG body (24 x 24 box, ``COLOR`` is replaced by the requested colour).
SHAPES = {
    "play": '<path d="M7 4.5 19 12 7 19.5Z" fill="COLOR" stroke="COLOR" stroke-width="1.5" '
            'stroke-linejoin="round"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2.5" fill="COLOR"/>',
    "monitor": '<g fill="none" stroke="COLOR" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
               '<rect x="3" y="4" width="18" height="12" rx="2.2"/><path d="M8.5 20h7M12 16v4"/></g>',
    "sun": '<g fill="none" stroke="COLOR" stroke-width="1.8" stroke-linecap="round">'
           '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2'
           'M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6"/></g>',
    "moon": '<path d="M20 14.2A8.2 8.2 0 1 1 9.8 4a6.6 6.6 0 0 0 10.2 10.2Z" fill="none" stroke="COLOR" '
            'stroke-width="1.8" stroke-linejoin="round"/>',
    # Lucide-style "minimize" / "maximize": arrows pointing in / out
    "minimize": '<g fill="none" stroke="COLOR" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/></g>',
    "maximize": '<g fill="none" stroke="COLOR" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></g>',
    "folder": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.5h7.5A2.5 2.5 0 0 1 21 10v7.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5Z" '
              'fill="none" stroke="COLOR" stroke-width="1.8" stroke-linejoin="round"/>',
    "folder-open": '<path d="M3 17.5V6.5A2.5 2.5 0 0 1 5.5 4H9l2 2.5h6A2.5 2.5 0 0 1 19.5 9v1.5" fill="none" stroke="COLOR" '
                   'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>'
                   '<path d="M3 17.5 5.2 11a2 2 0 0 1 1.9-1.4H21a1 1 0 0 1 .95 1.3l-2.1 6.3A2.5 2.5 0 0 1 17.5 19H5.5A2.5 2.5 0 0 1 3 17.5Z" '
                   'fill="COLOR" fill-opacity=".25" stroke="COLOR" stroke-width="1.8" stroke-linejoin="round"/>',
    "question": '<g fill="none" stroke="COLOR" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
                '<circle cx="12" cy="12" r="9"/><path d="M9.4 9.3a2.7 2.7 0 1 1 3.8 2.5c-.8.4-1.2.9-1.2 1.8"/></g>'
                '<circle cx="12" cy="17.2" r="1.1" fill="COLOR"/>',
    "undo": '<g fill="none" stroke="COLOR" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></g>',
    # a media player's "skip to next": a triangle with a bar after it
    "next": '<path d="M5.5 5.5 15 12l-9.5 6.5Z" fill="COLOR" stroke="COLOR" stroke-width="1.5" stroke-linejoin="round"/>'
            '<rect x="17" y="5.5" width="2.6" height="13" rx="1.2" fill="COLOR"/>',
    # two speech bubbles: one turn of the conversation (what is said, and what Quill makes of it)
    "turn": '<g fill="none" stroke="COLOR" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M4 5.5h10.5a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5H8.5L5.5 16v-2.5H4A1.5 1.5 0 0 1 2.5 12V7A1.5 1.5 0 0 1 4 5.5Z"/>'
            '<path d="M19 10.5h1a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5h-1V21l-3-2.5h-5a1.5 1.5 0 0 1-1.5-1.5v-.5"/></g>',
    "gear": '<g fill="none" stroke="COLOR" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>'
            '<circle cx="12" cy="12" r="3"/></g>',
    "more": '<g fill="COLOR"><circle cx="5.5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="18.5" cy="12" r="1.7"/></g>',
    "close": '<g fill="none" stroke="COLOR" stroke-width="1.9" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></g>',
    "search": '<g fill="none" stroke="COLOR" stroke-width="1.9" stroke-linecap="round">'
              '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></g>',
    # Three sliders: the usual "settings" glyph, simple enough to stay crisp when small.
    "settings": '<g fill="none" stroke="COLOR" stroke-width="2" stroke-linecap="round">'
                '<path d="M4 6h8M18 6h2M4 12h2M12 12h8M4 18h10M20 18h0"/>'
                '<circle cx="15" cy="6" r="2.4"/><circle cx="9" cy="12" r="2.4"/>'
                '<circle cx="17" cy="18" r="2.4"/></g>',
}


def svg_for(name: str, color: str) -> str:
    """The SVG text for icon *name* in *color* (``"#RRGGBB"``)."""
    body = SHAPES[name].replace("COLOR", color)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'


def titlebar_png(name: str, size: int = 19, scale: int = 2) -> bytes:
    """PNG bytes of icon *name* for the macOS title bar: black (the system tints it) with the fine lines of the
    other title-bar symbols, so it does not look heavier or whiter than they do."""
    from PySide6.QtCore import QBuffer, QIODevice
    svg = svg_for(name, "#000000").replace('stroke-width="1.8"', 'stroke-width="1.35"').replace('fill-opacity=".25"', 'fill-opacity="0"')
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(data)


def make_icon(name: str, color: str, size: int = 18, scale: int = 2) -> QIcon:
    """Render icon *name* as a QIcon *size* points square (drawn at *scale*x for sharp screens)."""
    renderer = QSvgRenderer(QByteArray(svg_for(name, color).encode("utf-8")))
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)
