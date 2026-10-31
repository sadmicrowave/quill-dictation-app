"""Draw ten app-icon ideas for Quill (dock / app icon plus a one-colour menu bar glyph).

    python tools/make_icon_ideas.py [contact-sheet.png]            # ideas 01-10
    python tools/make_icon_ideas.py --more [contact-sheet.png]     # ideas 11-20
    python tools/make_icon_ideas.py --all [contact-sheet.png]      # all twenty, one sheet

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
     f'<path d="M62 66 100 106" stroke="{fg}" stroke-width="12" stroke-linecap="round"/>'
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


IDEAS_MORE = [
    ("pen-wave", "A pen drawing a waveform line", "#C0446B",
     lambda fg, bg: f'<path d="M14 84C26 84 28 52 40 52S54 96 66 96 76 66 86 66" stroke="{fg}" stroke-width="7" '
     f'stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
     f'<path d="M84 70 108 30 116 36 92 76Z" fill="{fg}"/><path d="M84 70 80 84 92 76Z" fill="{fg}"/>'),
    ("cursor-waves", "A text cursor with sound waves either side", "#1F2A44",
     lambda fg, bg: f'<path d="M64 22v84M52 22h24M52 106h24" stroke="{fg}" stroke-width="8" stroke-linecap="round" fill="none"/>'
     f'<g stroke="{fg}" stroke-width="6" stroke-linecap="round" fill="none"><path d="M36 48a24 24 0 0 0 0 32"/>'
     f'<path d="M92 48a24 24 0 0 1 0 32"/><path d="M22 38a42 42 0 0 0 0 52" opacity=".6"/><path d="M106 38a42 42 0 0 1 0 52" opacity=".6"/></g>'),
    ("cell-ripple", "One spreadsheet cell sending out ripples", "#2F6FB5",
     lambda fg, bg: f'<rect x="46" y="48" width="36" height="32" rx="6" fill="{fg}"/>'
     f'<rect x="32" y="36" width="64" height="56" rx="12" stroke="{fg}" stroke-width="5" fill="none" opacity=".75"/>'
     f'<rect x="18" y="24" width="92" height="80" rx="18" stroke="{fg}" stroke-width="4" fill="none" opacity=".45"/>'),
    ("inkwell", "An inkwell with a feather", "#3E7D4F",
     lambda fg, bg: f'<path d="M34 70h50a8 8 0 0 1 8 8v22a10 10 0 0 1-10 10H36a10 10 0 0 1-10-10V78a8 8 0 0 1 8-8Z" fill="{fg}"/>'
     f'<rect x="42" y="58" width="34" height="12" rx="3" fill="{fg}"/><ellipse cx="59" cy="84" rx="18" ry="5" fill="{bg}" opacity=".5"/>'
     f'<path d="M104 18C84 22 68 40 62 62 80 58 100 44 104 18Z" fill="{fg}"/>'),
    ("notebook-mic", "A notebook with a microphone on the page", "#7A55C2",
     lambda fg, bg: f'<rect x="28" y="16" width="76" height="96" rx="10" fill="{fg}"/>'
     f'<g fill="{bg}"><circle cx="28" cy="36" r="4"/><circle cx="28" cy="56" r="4"/><circle cx="28" cy="76" r="4"/><circle cx="28" cy="96" r="4"/></g>'
     f'<rect x="56" y="34" width="20" height="34" rx="10" fill="{bg}"/>'
     f'<path d="M48 62a18 18 0 0 0 36 0M66 80v10M56 92h20" stroke="{bg}" stroke-width="5" stroke-linecap="round" fill="none"/>'),
    ("q-arcs", "Concentric arcs that read as a Q", "#C9623F",
     lambda fg, bg: f'<g stroke="{fg}" stroke-width="9" stroke-linecap="round" fill="none"><path d="M96 40A44 44 0 1 0 100 78"/>'
     f'<path d="M80 48A26 26 0 1 0 82 74" opacity=".7"/></g><path d="M70 70 104 104" stroke="{fg}" stroke-width="10" stroke-linecap="round"/>'),
    ("bubble-tick", "A speech bubble with a tick: heard and filed", "#3E7D4F",
     lambda fg, bg: f'<path d="M24 28h80a8 8 0 0 1 8 8v48a8 8 0 0 1-8 8H60L38 112V92H24a8 8 0 0 1-8-8V36a8 8 0 0 1 8-8Z" fill="{fg}"/>'
     f'<path d="M42 60 56 74 88 42" stroke="{bg}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'),
    ("mic-row", "A microphone leading a row of cells", "#2F6FB5",
     lambda fg, bg: f'<rect x="16" y="34" width="26" height="44" rx="13" fill="{fg}"/>'
     f'<path d="M10 70a19 19 0 0 0 38 0M29 90v12M20 102h18" stroke="{fg}" stroke-width="5" stroke-linecap="round" fill="none"/>'
     f'<g fill="{fg}"><rect x="58" y="44" width="22" height="20" rx="4"/><rect x="84" y="44" width="22" height="20" rx="4"/>'
     f'<rect x="58" y="70" width="22" height="20" rx="4" opacity=".6"/><rect x="84" y="70" width="22" height="20" rx="4" opacity=".6"/></g>'),
    ("lines-feather", "Lines of text with a feather writing the last one", "#1F2A44",
     lambda fg, bg: f'<g stroke="{fg}" stroke-width="7" stroke-linecap="round"><path d="M20 34h70M20 54h56M20 74h40"/></g>'
     f'<path d="M110 52C92 58 78 76 76 98 94 92 108 76 110 52Z" fill="{fg}"/><path d="M76 98 100 66" stroke="{bg}" stroke-width="3" stroke-linecap="round"/>'),
    ("quote-wave", "Quotation marks with a voice waveform", "#C0446B",
     lambda fg, bg: f'<path d="M20 64V40q0-10 10-10h8v12h-8v8h10v24Z" fill="{fg}"/>'
     f'<path d="M72 64V40q0-10 10-10h8v12h-8v8h10v24Z" fill="{fg}"/>'
     + bars([30, 42, 54, 66, 78, 90], [14, 26, 40, 26, 36, 14], fg, 96, 7)),
]


def shade(color: str, amount: float) -> str:
    """Lighten (amount > 0) or darken (amount < 0) a ``#RRGGBB`` colour."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    target = 255 if amount > 0 else 0
    k = abs(amount)
    return "#" + "".join(f"{round(c + (target - c) * k):02X}" for c in (r, g, b))


def app_icon(color: str, draw) -> str:
    """A dock-style icon: lit gradient body, bevelled rim, soft shadows, an embossed glyph and a gloss.

    *draw* is the idea's ``lambda fg, bg: svg`` glyph. Only gradients, opacity and
    plain shapes are used, so any SVG renderer draws it the same way.
    """
    top, bottom, deep = shade(color, 0.22), shade(color, -0.20), shade(color, -0.45)
    body = draw("url(#glyph)", color)
    shadow = draw("#000000", "none")
    emboss = draw("#FFFFFF", "none")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><defs>'
        f'<linearGradient id="base" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/>'
        f'<stop offset=".55" stop-color="{color}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>'
        '<linearGradient id="rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".85"/>'
        '<stop offset=".5" stop-color="#FFFFFF" stop-opacity=".05"/><stop offset="1" stop-color="#000000" stop-opacity=".45"/></linearGradient>'
        '<linearGradient id="gloss" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".62"/>'
        '<stop offset="1" stop-color="#FFFFFF" stop-opacity=".02"/></linearGradient>'
        '<linearGradient id="glyph" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF"/>'
        '<stop offset="1" stop-color="#E9E4DE"/></linearGradient>'
        f'<radialGradient id="glow" cx=".5" cy=".95" r=".7"><stop offset="0" stop-color="{shade(color, 0.45)}" stop-opacity=".55"/>'
        f'<stop offset="1" stop-color="{shade(color, 0.45)}" stop-opacity="0"/></radialGradient></defs>'
        # soft ground shadow (stacked, getting fainter and wider)
        '<rect x="9" y="12" width="110" height="112" rx="30" fill="#000" opacity=".10"/>'
        '<rect x="7" y="9" width="114" height="114" rx="30" fill="#000" opacity=".12"/>'
        '<rect x="6" y="7" width="116" height="116" rx="29" fill="#000" opacity=".16"/>'
        # body, light from the top, warm bounce light at the bottom
        '<rect x="4" y="4" width="120" height="120" rx="28" fill="url(#base)"/>'
        '<rect x="4" y="4" width="120" height="120" rx="28" fill="url(#glow)"/>'
        # bevelled rim: bright on top, dark underneath
        '<rect x="5.5" y="5.5" width="117" height="117" rx="26.5" fill="none" stroke="url(#rim)" stroke-width="3"/>'
        f'<rect x="4" y="4" width="120" height="120" rx="28" fill="none" stroke="{deep}" stroke-opacity=".55" stroke-width="1"/>'
        # embossed glyph: dark shadow below, a thin highlight above, then the glyph itself
        f'<g transform="translate(0 5)" opacity=".16">{shadow}</g><g transform="translate(0 3.2)" opacity=".26">{shadow}</g>'
        f'<g transform="translate(0 1.6)" opacity=".35">{shadow}</g>'
        f'<g transform="translate(0 -1.2)" opacity=".5">{emboss}</g>{body}'
        # glossy highlight over the top half, with a curved lower edge
        '<path d="M5 62V32A27 27 0 0 1 32 5H96A27 27 0 0 1 123 32V62Q64 84 5 62Z" fill="url(#gloss)"/>'
        '<path d="M14 12H114" stroke="#FFFFFF" stroke-opacity=".55" stroke-width="2" stroke-linecap="round"/>'
        '</svg>')


def menubar(glyph: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">{glyph}</svg>'


def write_everything() -> list[tuple[str, str, str, str]]:
    """All twenty ideas, in order."""
    return write_all(False) + write_all(True)


def write_all(more: bool = False) -> list[tuple[str, str, str, str]]:
    """Write one batch of ideas (numbered from 01, or from 11 with *more*)."""
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for i, (slug, title, color, draw) in enumerate(IDEAS_MORE if more else IDEAS, 11 if more else 1):
        big = app_icon(color, draw)
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
    cols, cell_w, cell_h, pad = 4, 330, 372, 30
    rows = (len(made) + cols - 1) // cols
    image = QImage(cols * cell_w + pad, rows * cell_h + pad, QImage.Format.Format_ARGB32)
    image.fill(QColor("#FAF9F5"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for n, (num, title, big, mono) in enumerate(made):
        x, y = pad + (n % cols) * cell_w, pad + (n // cols) * cell_h
        QSvgRenderer(QByteArray(big.encode())).render(p, QRectF(x, y, 240, 240))
        # menu bar glyph at real size, on a light and a dark strip
        for k, (strip, ink) in enumerate((("#E9E7E1", "#000000"), ("#2B2B2A", "#FFFFFF"))):
            p.fillRect(QRectF(x + 250, y + k * 40, 56, 30), QColor(strip))
            svg = mono.replace("#000000", ink)
            QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(x + 264, y + 4 + k * 40, 22, 22))
        p.setPen(QColor("#1F1E1D"))
        font = QFont(); font.setPointSize(13); p.setFont(font)
        p.drawText(QRectF(x, y + 250, cell_w - 20, 60), Qt.TextFlag.TextWordWrap, f"{num}  {title}")
    p.end()
    image.save(path)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    made = write_everything() if "--all" in sys.argv else write_all(more="--more" in sys.argv)
    print(f"Wrote {len(made) * 2} icons to {OUT}")
    if args:
        contact_sheet(args[0], made)
        print("Contact sheet:", args[0])
