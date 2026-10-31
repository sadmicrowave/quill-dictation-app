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
    "question": '<g fill="none" stroke="COLOR" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
                '<circle cx="12" cy="12" r="9"/><path d="M9.4 9.3a2.7 2.7 0 1 1 3.8 2.5c-.8.4-1.2.9-1.2 1.8"/></g>'
                '<circle cx="12" cy="17.2" r="1.1" fill="COLOR"/>',
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
