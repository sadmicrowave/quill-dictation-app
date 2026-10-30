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
