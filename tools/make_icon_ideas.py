"""Draw ten app-icon ideas for Quill (dock / app icon plus a one-colour menu bar glyph).

    python tools/make_icon_ideas.py [contact-sheet.png]

Writes ``assets/icon-ideas/NN-name.svg`` (the full-colour app icon) and
``NN-name-menubar.svg`` (the same idea as a plain black glyph, which macOS can
tint for light and dark menu bars), then, if a path is given, a contact sheet.
The glyphs are drawn on a 128 x 128 grid.
"""

from __future__ import annotations
import pathlib
import sys

OUT = pathlib.Path(__file__).resolve().parents[1] / "assets" / "icon-ideas"

#: A feather: a leaf shape with a spine.
FEATHER = ('<path d="M98 26C62 30 38 58 32 102C58 96 88 74 98 26Z" fill="{fg}"/>'
           '<path d="M32 102 84 46" stroke="{bg}" stroke-width="4" stroke-linecap="round" fill="none"/>')


def bars(xs, heights, fg, base=64, width=9):
    return "".join(f'<rect x="{x}" y="{base - h / 2}" width="{width}" height="{h}" rx="{width / 2}" fill="{fg}"/>'
                   for x, h in zip(xs, heights))


IDEAS = [
    ("quill-nib", "Quill feather", "#C9623F",
     lambda fg, bg: FEATHER.format(fg=fg, bg=bg) + f'<circle cx="30" cy="106" r="5" fill="{fg}"/>'),
    ("feather-waves", "Feather with a voice waveform in it", "#2F6FB5",
     lambda fg, bg: FEATHER.format(fg=fg, bg=bg).replace('<path d="M32 102 84 46" stroke="{bg}" stroke-width="4" stroke-linecap="round" fill="none"/>'.format(bg=bg), "")
     + bars([52, 63, 74], [14, 30, 18], bg, 60, 6) + f'<circle cx="30" cy="106" r="5" fill="{fg}"/>'),
    ("mic-feather", "Microphone with a feather tip", "#3E7D4F",
     lambda fg, bg: f'<rect x="48" y="30" width="32" height="52" rx="16" fill="{fg}"/>'
     f'<path d="M36 70a28 28 0 0 0 56 0M64 98v14M50 112h28" stroke="{fg}" stroke-width="6" stroke-linecap="round" fill="none"/>'
     f'<path d="M84 22C100 20 108 30 104 46C92 44 84 36 84 22Z" fill="{fg}"/>'),
    ("bubble-cell", "Speech bubble holding a spreadsheet cell", "#7A55C2",
     lambda fg, bg: f'<path d="M24 30h80a8 8 0 0 1 8 8v44a8 8 0 0 1-8 8H62L40 108V90H24a8 8 0 0 1-8-8V38a8 8 0 0 1 8-8Z" fill="{fg}"/>'
     f'<g stroke="{bg}" stroke-width="3" fill="none"><path d="M32 52h64M32 70h64M56 42v38M80 42v38"/></g>'
     f'<rect x="57" y="53" width="22" height="16" fill="{bg}"/>'),
    ("wave-to-grid", "A waveform turning into table cells", "#C0446B",
     lambda fg, bg: bars([20, 31, 42, 53], [20, 52, 80, 36], fg, 64, 7)
     + f'<g fill="{fg}"><rect x="70" y="36" width="20" height="16" rx="3"/><rect x="94" y="36" width="14" height="16" rx="3"/>'
     f'<rect x="70" y="56" width="20" height="16" rx="3"/><rect x="94" y="56" width="14" height="16" rx="3"/>'
     f'<rect x="70" y="76" width="20" height="16" rx="3"/><rect x="94" y="76" width="14" height="16" rx="3"/></g>'),
    ("q-wave", "Letter Q with a soundwave beside it", "#1F2A44",
     lambda fg, bg: f'<circle cx="54" cy="60" r="32" stroke="{fg}" stroke-width="12" fill="none"/>'
     f'<path d="M76 82 98 104" stroke="{fg}" stroke-width="12" stroke-linecap="round"/>'
     + bars([98, 108, 118], [14, 32, 14], fg, 40, 6)),
    ("sheet-mic", "Spreadsheet with a highlighted cell and a mic dot", "#2F6FB5",
     lambda fg, bg: f'<rect x="20" y="24" width="88" height="80" rx="10" fill="{fg}"/>'
     f'<g stroke="{bg}" stroke-width="3"><path d="M20 50h88M20 76h88M49 24v80M79 24v80"/></g>'
     f'<rect x="51" y="52" width="26" height="22" fill="{bg}"/><circle cx="102" cy="100" r="16" fill="{bg}"/>'
     f'<rect x="97" y="90" width="10" height="16" rx="5" fill="{fg}"/>'),
    ("ink-ripples", "An ink drop sending out sound ripples", "#C9623F",
     lambda fg, bg: f'<path d="M64 36C48 58 44 70 44 78a20 20 0 0 0 40 0c0-8-4-20-20-42Z" fill="{fg}"/>'
     f'<g stroke="{fg}" stroke-width="5" stroke-linecap="round" fill="none"><path d="M26 64a46 46 0 0 0 0 40"/>'
     f'<path d="M102 64a46 46 0 0 1 0 40"/><path d="M14 56a64 64 0 0 0 0 56" opacity=".6"/><path d="M114 56a64 64 0 0 1 0 56" opacity=".6"/></g>'),
    ("nib-arcs", "A pen nib and sound arcs", "#3E7D4F",
     lambda fg, bg: f'<path d="M40 104 54 56 74 24 94 56 108 104 74 90Z" transform="translate(-14 0)" fill="{fg}"/>'
     f'<path d="M60 90 60 52" stroke="{bg}" stroke-width="4" stroke-linecap="round"/><circle cx="60" cy="58" r="5" fill="{bg}"/>'
     f'<g stroke="{fg}" stroke-width="5" stroke-linecap="round" fill="none"><path d="M96 48a24 24 0 0 1 0 32"/><path d="M108 38a40 40 0 0 1 0 52"/></g>'),
    ("script-q", "A calligraphic Q written with one stroke", "#7A55C2",
     lambda fg, bg: f'<path d="M64 24C38 24 26 44 26 62C26 86 44 104 66 104C90 104 104 84 104 62C104 40 88 24 64 24Z" '
     f'stroke="{fg}" stroke-width="10" stroke-linecap="round" fill="none"/>'
     f'<path d="M72 80C84 90 96 104 116 100" stroke="{fg}" stroke-width="10" stroke-linecap="round" fill="none"/>'),
]


def app_icon(color: str, glyph: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><defs>'
            f'<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{color}" stop-opacity=".92"/>'
            f'<stop offset="1" stop-color="{color}"/></linearGradient></defs>'
            f'<rect x="4" y="4" width="120" height="120" rx="28" fill="url(#g)"/>{glyph}</svg>')


def menubar(glyph: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">{glyph}</svg>'


def write_all() -> list[tuple[str, str, str, str]]:
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for i, (slug, title, color, draw) in enumerate(IDEAS, 1):
        big = app_icon(color, draw("#FFFFFF", color))
        mono = menubar(draw("#000000", "#FFFFFF"))
        (OUT / f"{i:02d}-{slug}.svg").write_text(big, encoding="utf-8")
        (OUT / f"{i:02d}-{slug}-menubar.svg").write_text(mono, encoding="utf-8")
        made.append((f"{i:02d}", title, big, mono))
    return made


def contact_sheet(path: str, made) -> None:
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    cols, cell_w, cell_h, pad = 5, 300, 340, 24
    rows = (len(made) + cols - 1) // cols
    image = QImage(cols * cell_w + pad, rows * cell_h + pad, QImage.Format.Format_ARGB32)
    image.fill(QColor("#FAF9F5"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for n, (num, title, big, mono) in enumerate(made):
        x, y = pad + (n % cols) * cell_w, pad + (n // cols) * cell_h
        QSvgRenderer(QByteArray(big.encode())).render(p, QRectF(x, y, 200, 200))
        # menu bar glyph at real size, on a light and a dark strip
        for k, (strip, ink) in enumerate((("#E9E7E1", "#000000"), ("#2B2B2A", "#FFFFFF"))):
            p.fillRect(QRectF(x + 210, y + k * 40, 56, 30), QColor(strip))
            svg = mono.replace("#000000", ink)
            QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(x + 224, y + 4 + k * 40, 22, 22))
        p.setPen(QColor("#1F1E1D"))
        font = QFont(); font.setPointSize(13); p.setFont(font)
        p.drawText(QRectF(x, y + 206, cell_w - 20, 60), Qt.TextFlag.TextWordWrap, f"{num}  {title}")
    p.end()
    image.save(path)


if __name__ == "__main__":
    made = write_all()
    print(f"Wrote {len(made) * 2} icons to {OUT}")
    if len(sys.argv) > 1:
        contact_sheet(sys.argv[1], made)
        print("Contact sheet:", sys.argv[1])
