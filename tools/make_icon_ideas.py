"""Draw ten app-icon ideas for Quill (dock / app icon plus a one-colour menu bar glyph).

    python tools/make_icon_ideas.py [contact-sheet.png]            # ideas 01-10
    python tools/make_icon_ideas.py --more [contact-sheet.png]     # ideas 11-20
    python tools/make_icon_ideas.py --new [contact-sheet.png]      # a third round: 21-40 (all new symbols)
    python tools/make_icon_ideas.py --mix [contact-sheet.png]      # a fourth round: 41-50, recombining the liked parts
    python tools/make_icon_ideas.py --ring [contact-sheet.png]     # a fifth round: 51-56, the ring with vertical sound lines in purples
    python tools/make_icon_ideas.py --clip [contact-sheet.png]     # a sixth round: 57-59, idea 47 on purples
    python tools/make_icon_ideas.py --sheet [contact-sheet.png]    # a seventh round: 60-63, the Excel-style tiled sheet in purples
    python tools/make_icon_ideas.py --offset [contact-sheet.png]   # an eighth round: 64-67, the Excel offset layout
    python tools/make_icon_ideas.py --all [contact-sheet.png]      # the first forty, one sheet

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


#: How big the white glyph is relative to the icon's own box (the box itself stays full size).
GLYPH_SCALE = 0.72


def shade(color: str, amount: float) -> str:
    """Lighten (amount > 0) or darken (amount < 0) a ``#RRGGBB`` colour."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    target = 255 if amount > 0 else 0
    k = abs(amount)
    return "#" + "".join(f"{round(c + (target - c) * k):02X}" for c in (r, g, b))


IDEAS_NEW = [
    ("open-book", "An open book with sound arcs rising from it", "#2F6FB5",
     lambda fg, bg: f'<path d="M18 50C34 43 50 44 64 52C78 44 94 43 110 50V102C94 95 78 96 64 104C50 96 34 95 18 102Z" fill="{fg}"/>'
     f'<path d="M64 54V102" stroke="{bg}" stroke-width="4" stroke-linecap="round"/>'
     f'<g stroke="{fg}" stroke-width="6" stroke-linecap="round" fill="none"><path d="M46 34a26 26 0 0 1 36 0"/><path d="M36 22a42 42 0 0 1 56 0" opacity=".65"/></g>'),
    ("headphones", "Headphones", "#7A55C2",
     lambda fg, bg: f'<path d="M24 82V66a40 40 0 0 1 80 0v16" stroke="{fg}" stroke-width="9" stroke-linecap="round" fill="none"/>'
     f'<rect x="14" y="74" width="26" height="42" rx="11" fill="{fg}"/><rect x="88" y="74" width="26" height="42" rx="11" fill="{fg}"/>'),
    ("checklist", "A checklist with the first item ticked", "#3E7D4F",
     lambda fg, bg: f'<g stroke="{fg}" stroke-width="7" stroke-linecap="round" fill="none"><rect x="18" y="26" width="26" height="26" rx="7"/>'
     f'<rect x="18" y="74" width="26" height="26" rx="7" opacity=".7"/><path d="M58 39h50M58 87h38" /></g>'
     f'<path d="M24 39 30 46 40 32" stroke="{fg}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
     f'<path d="M58 63h42" stroke="{fg}" stroke-width="7" stroke-linecap="round" opacity=".7"/>'),
    ("clipboard-wave", "A clipboard holding a voice waveform", "#C0446B",
     lambda fg, bg: f'<rect x="26" y="22" width="76" height="92" rx="12" fill="{fg}"/><rect x="48" y="14" width="32" height="18" rx="8" fill="{fg}" stroke="{bg}" stroke-width="5"/>'
     + bars([40, 51, 62, 73, 84], [14, 30, 44, 24, 12], bg, 74, 7)),
    ("cassette", "A dictaphone cassette", "#C9623F",
     lambda fg, bg: f'<rect x="14" y="30" width="100" height="68" rx="12" fill="{fg}"/><rect x="28" y="42" width="72" height="28" rx="14" fill="{bg}"/>'
     f'<circle cx="46" cy="56" r="8" fill="{fg}"/><circle cx="82" cy="56" r="8" fill="{fg}"/><path d="M38 98l8-14h36l8 14" stroke="{bg}" stroke-width="4" stroke-linejoin="round" fill="none"/>'),
    ("speaker-cone", "A speaker cone: rings around a dot", "#1F2A44",
     lambda fg, bg: f'<circle cx="64" cy="64" r="44" stroke="{fg}" stroke-width="8" fill="none"/><circle cx="64" cy="64" r="26" stroke="{fg}" stroke-width="7" fill="none" opacity=".75"/>'
     f'<circle cx="64" cy="64" r="11" fill="{fg}"/>'),
    ("enso", "A brush-stroke circle with a dot", "#C0446B",
     lambda fg, bg: f'<path d="M92 30A44 44 0 1 0 108 70" stroke="{fg}" stroke-width="12" stroke-linecap="round" fill="none"/><circle cx="100" cy="42" r="7" fill="{fg}"/>'),
    ("pencil-waves", "A pencil with sound arcs at its tip", "#3E7D4F",
     lambda fg, bg: f'<g transform="rotate(-45 64 64)"><rect x="52" y="14" width="24" height="70" rx="5" fill="{fg}"/><path d="M52 90h24L64 112Z" fill="{fg}"/>'
     f'<rect x="52" y="26" width="24" height="6" fill="{bg}"/></g>'
     f'<g stroke="{fg}" stroke-width="6" stroke-linecap="round" fill="none"><path d="M82 98a24 24 0 0 0 16-16" opacity=".8"/><path d="M82 112a40 40 0 0 0 30-30" opacity=".5"/></g>'),
    ("typing-pill", "A pill with three typing dots", "#2F6FB5",
     lambda fg, bg: f'<rect x="12" y="38" width="104" height="52" rx="26" fill="{fg}"/>'
     f'<circle cx="42" cy="64" r="8" fill="{bg}"/><circle cx="64" cy="64" r="8" fill="{bg}" opacity=".75"/><circle cx="86" cy="64" r="8" fill="{bg}" opacity=".5"/>'),
    ("radio-mast", "A radio mast broadcasting", "#7A55C2",
     lambda fg, bg: f'<path d="M64 52 44 112M64 52 84 112M52 90h24" stroke="{fg}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
     f'<circle cx="64" cy="44" r="8" fill="{fg}"/><g stroke="{fg}" stroke-width="6" stroke-linecap="round" fill="none"><path d="M44 28a28 28 0 0 0 0 32"/><path d="M84 28a28 28 0 0 1 0 32"/>'
     f'<path d="M30 20a46 46 0 0 0 0 48" opacity=".6"/><path d="M98 20a46 46 0 0 1 0 48" opacity=".6"/></g>'),
    ("voice-to-cell", "A voice waveform turning into a spreadsheet cell", "#C9623F",
     lambda fg, bg: bars([14, 25, 36], [22, 48, 30], fg, 64, 7)
     + f'<path d="M54 64h20M66 54l10 10-10 10" stroke="{fg}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
     f'<rect x="84" y="42" width="32" height="44" rx="8" fill="{fg}"/>'),
    ("sprout", "A sprout growing from the ground", "#3E7D4F",
     lambda fg, bg: f'<path d="M20 108h88" stroke="{fg}" stroke-width="8" stroke-linecap="round"/><path d="M64 108V58" stroke="{fg}" stroke-width="7" stroke-linecap="round"/>'
     f'<path d="M64 70C64 46 46 34 24 36 24 58 40 72 64 70Z" fill="{fg}"/><path d="M64 56C64 36 80 24 104 26 104 48 88 60 64 56Z" fill="{fg}"/>'),
    ("abacus", "An abacus", "#1F2A44",
     lambda fg, bg: f'<rect x="16" y="22" width="96" height="84" rx="10" stroke="{fg}" stroke-width="8" fill="none"/>'
     f'<g stroke="{fg}" stroke-width="5"><path d="M16 50h96M16 78h96"/></g>'
     f'<g fill="{fg}"><circle cx="38" cy="36" r="8"/><circle cx="58" cy="36" r="8"/><circle cx="92" cy="36" r="8"/>'
     f'<circle cx="46" cy="64" r="8"/><circle cx="82" cy="64" r="8"/><circle cx="100" cy="64" r="8"/>'
     f'<circle cx="34" cy="92" r="8"/><circle cx="70" cy="92" r="8"/><circle cx="90" cy="92" r="8"/></g>'),
    ("pushpin", "A pushpin", "#C0446B",
     lambda fg, bg: f'<circle cx="64" cy="40" r="22" fill="{fg}"/><path d="M50 56h28L72 86H56Z" fill="{fg}"/><path d="M64 86V116" stroke="{fg}" stroke-width="6" stroke-linecap="round"/>'
     f'<circle cx="57" cy="33" r="6" fill="{bg}" opacity=".45"/>'),
    ("stacked-rows", "A stack of rows with a leading dot", "#2F6FB5",
     lambda fg, bg: f'<rect x="14" y="26" width="100" height="22" rx="8" fill="{fg}"/><rect x="14" y="53" width="100" height="22" rx="8" fill="{fg}" opacity=".8"/>'
     f'<rect x="14" y="80" width="100" height="22" rx="8" fill="{fg}" opacity=".6"/><circle cx="28" cy="37" r="5" fill="{bg}"/>'),
    ("record-bars", "A record ring with a waveform inside", "#C9623F",
     lambda fg, bg: f'<circle cx="64" cy="64" r="46" stroke="{fg}" stroke-width="9" fill="none"/>' + bars([40, 51, 62, 73, 84], [14, 30, 44, 26, 12], fg, 64, 7)),
    ("page-wave", "A page with a folded corner and a waveform line", "#7A55C2",
     lambda fg, bg: f'<path d="M30 14H78L102 38V114H30Z" fill="{fg}"/><path d="M78 14V38H102" fill="{bg}" opacity=".35"/>'
     f'<path d="M42 78c6 0 6-18 12-18s6 28 12 28 6-22 12-22 6 12 12 12" stroke="{bg}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'),
    ("bolt-ring", "A lightning bolt in a ring: dictation at speed", "#3E7D4F",
     lambda fg, bg: f'<circle cx="64" cy="64" r="46" stroke="{fg}" stroke-width="8" fill="none"/><path d="M70 22 38 70h22l-6 36 36-52H68Z" fill="{fg}"/>'),
    ("signal-fan", "Signal arcs fanning out from a corner dot", "#1F2A44",
     lambda fg, bg: f'<circle cx="30" cy="98" r="9" fill="{fg}"/><g stroke="{fg}" stroke-width="9" stroke-linecap="round" fill="none"><path d="M30 64a34 34 0 0 1 34 34"/>'
     f'<path d="M30 38a60 60 0 0 1 60 60"/><path d="M30 14a84 84 0 0 1 84 84" opacity=".7"/></g>'),
    ("bookmark-tick", "A bookmark ribbon with a tick", "#C0446B",
     lambda fg, bg: f'<path d="M36 14H92a6 6 0 0 1 6 6V114L64 90 30 114V20a6 6 0 0 1 6-6Z" fill="{fg}"/>'
     f'<path d="M48 48 60 60 82 36" stroke="{bg}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'),
]


def up_bars(xs, heights, fg, floor, width=7):
    """Bars standing on a floor line (bottom-aligned), like an equaliser."""
    return "".join(f'<rect x="{x}" y="{floor - h}" width="{width}" height="{h}" rx="{width / 2}" fill="{fg}"/>'
                   for x, h in zip(xs, heights))


PAGE = lambda fg, bg: (f'<path d="M30 14H78L102 38V114H30Z" fill="{fg}"/>'
                       f'<path d="M78 14V38H102" fill="{bg}" opacity=".35"/>')

#: Round four: the parts that were liked (the audio lines of 24 and 36, the stack of 35, the page of 37) recombined.
IDEAS_MIX = [
    ("page-bars", "The page with audio lines on it", "#7A55C2",
     lambda fg, bg: PAGE(fg, bg) + bars([42, 53, 64, 75, 86], [14, 30, 48, 26, 12], bg, 78, 7)),
    ("page-bars-rows", "The page: audio lines on top, two rows below", "#C0446B",
     lambda fg, bg: PAGE(fg, bg) + bars([44, 55, 66, 77, 88], [10, 22, 34, 18, 8], bg, 58, 6)
     + f'<path d="M42 86h44M42 102h30" stroke="{bg}" stroke-width="6" stroke-linecap="round"/>'),
    ("stack-top-bars", "A stack of rows; the top row carries the audio lines", "#2F6FB5",
     lambda fg, bg: f'<rect x="14" y="20" width="100" height="36" rx="11" fill="{fg}"/>'
     + bars([36, 47, 58, 69, 80, 91], [10, 20, 28, 18, 24, 8], bg, 38, 6)
     + f'<rect x="14" y="62" width="100" height="22" rx="8" fill="{fg}" opacity=".8"/><rect x="14" y="90" width="100" height="22" rx="8" fill="{fg}" opacity=".6"/>'
     f'<circle cx="28" cy="73" r="5" fill="{bg}"/><circle cx="28" cy="101" r="5" fill="{bg}"/>'),
    ("ring-stack", "A record ring around a stack of rows", "#C9623F",
     lambda fg, bg: f'<circle cx="64" cy="64" r="48" stroke="{fg}" stroke-width="9" fill="none"/>'
     f'<g stroke="{fg}" stroke-width="9" stroke-linecap="round"><path d="M40 46h48"/><path d="M40 64h48" opacity=".8"/><path d="M40 82h30" opacity=".6"/></g>'),
    ("two-pages", "Two pages: the front one carries the audio lines", "#3E7D4F",
     lambda fg, bg: f'<path d="M36 8H84L108 32V96H36Z" fill="{fg}" opacity=".5"/>'
     f'<path d="M20 26H68L92 50V120H20Z" fill="{fg}"/><path d="M68 26V50H92" fill="{bg}" opacity=".35"/>'
     + bars([34, 45, 56, 67], [14, 30, 44, 24], bg, 88, 7)),
    ("rows-with-bars", "Three rows, each ending in audio lines", "#1F2A44",
     lambda fg, bg: "".join(
         f'<rect x="14" y="{y}" width="100" height="24" rx="9" fill="{fg}" opacity="{o}"/><circle cx="29" cy="{y + 12}" r="5" fill="{bg}"/>'
         + bars([70, 80, 90, 100], hs, bg, y + 12, 5)
         for y, o, hs in ((20, 1, [8, 16, 10, 14]), (52, .85, [12, 8, 16, 10]), (84, .7, [6, 14, 8, 12])))),
    ("clipboard-rows", "A clipboard: audio lines above, rows below", "#C9623F",
     lambda fg, bg: f'<rect x="26" y="22" width="76" height="92" rx="12" fill="{fg}"/><rect x="48" y="14" width="32" height="18" rx="8" fill="{fg}" stroke="{bg}" stroke-width="5"/>'
     + bars([42, 53, 64, 75, 86], [10, 20, 30, 16, 8], bg, 54, 6)
     + f'<path d="M42 82h44M42 98h30" stroke="{bg}" stroke-width="6" stroke-linecap="round"/>'),
    ("page-voice-to-rows", "A page: audio lines on the left becoming rows on the right", "#2F6FB5",
     lambda fg, bg: PAGE(fg, bg) + bars([40, 49, 58], [14, 32, 20], bg, 76, 6)
     + f'<path d="M68 58h24M68 76h24M68 94h16" stroke="{bg}" stroke-width="6" stroke-linecap="round"/>'),
    ("ring-page", "A record ring holding a small page with audio lines", "#7A55C2",
     lambda fg, bg: f'<circle cx="64" cy="64" r="50" stroke="{fg}" stroke-width="8" fill="none"/>'
     f'<path d="M46 34H74L90 50V94H46Z" fill="{fg}"/><path d="M74 34V50H90" fill="{bg}" opacity=".35"/>'
     + bars([54, 63, 72], [12, 26, 16], bg, 74, 5)),
    ("equaliser-on-stack", "Audio lines standing on a stack of rows", "#C0446B",
     lambda fg, bg: up_bars([18, 30, 42, 54, 66, 78, 90, 102], [14, 28, 44, 32, 22, 36, 18, 10], fg, 54, 8)
     + f'<rect x="14" y="62" width="100" height="16" rx="7" fill="{fg}"/><rect x="14" y="84" width="100" height="16" rx="7" fill="{fg}" opacity=".75"/>'
     f'<rect x="14" y="106" width="100" height="16" rx="7" fill="{fg}" opacity=".5"/>'),
]


def ring_bars(heights, ring=9, r=48, width=7, gap=11):
    """A record ring with vertical sound lines inside (round five: the ring of 44 with the lines of 36)."""
    n = len(heights)
    xs = [64 - (n * width + (n - 1) * (gap - width)) / 2 + i * gap for i in range(n)]
    return lambda fg, bg: (f'<circle cx="64" cy="64" r="{r}" stroke="{fg}" stroke-width="{ring}" fill="none"/>'
                           + bars([round(x, 1) for x in xs], heights, fg, 64, width))


#: Round five: the ring with vertical sound lines, in purples (not orange).
IDEAS_RING = [
    ("ring-violet", "Ring with sound lines, violet", "#7A55C2", ring_bars([14, 30, 46, 30, 14])),
    ("ring-indigo", "Ring with sound lines, indigo", "#5B4BC4", ring_bars([14, 30, 46, 30, 14])),
    ("ring-plum", "Ring with sound lines, plum", "#9446B8", ring_bars([14, 30, 46, 30, 14])),
    ("ring-violet-seven", "Seven lines, violet", "#7A55C2", ring_bars([10, 22, 36, 48, 30, 18, 8], width=6, gap=9)),
    ("ring-indigo-bold", "Bold ring, five lines, indigo", "#5B4BC4", ring_bars([16, 34, 52, 34, 16], ring=11, r=47, width=8, gap=12)),
    ("ring-plum-irregular", "Irregular lines (like speech), plum", "#9446B8", ring_bars([12, 40, 22, 50, 18, 34], width=6, gap=10)),
]


#: Round six: idea 47 (the clipboard: audio lines above, rows below) on purple backgrounds.
_CLIPBOARD = next(idea[3] for idea in IDEAS_MIX if idea[0] == "clipboard-rows")
IDEAS_CLIP = [
    ("clipboard-violet", "Clipboard, violet", "#7A55C2", _CLIPBOARD),
    ("clipboard-indigo", "Clipboard, indigo", "#5B4BC4", _CLIPBOARD),
    ("clipboard-plum", "Clipboard, plum", "#9446B8", _CLIPBOARD),
]


def rrect(x, y, w, h, tl=0, tr=0, br=0, bl=0):
    """A rectangle path with a separate corner radius on each corner."""
    return (f"M{x + tl} {y}H{x + w - tr}" + (f"A{tr} {tr} 0 0 1 {x + w} {y + tr}" if tr else "")
            + f"V{y + h - br}" + (f"A{br} {br} 0 0 1 {x + w - br} {y + h}" if br else "")
            + f"H{x + bl}" + (f"A{bl} {bl} 0 0 1 {x} {y + h - bl}" if bl else "")
            + f"V{y + tl}" + (f"A{tl} {tl} 0 0 1 {x + tl} {y}" if tl else "") + "Z")


def tiled_sheet(color: str, x: float, y: float, w: float, h: float, radius: float, rows: int = 4, cols: int = 3,
                light: bool = False, banded: bool = False) -> str:
    """A rounded block of tiles in shades of *color*: lighter at the top, darker at the bottom, with a
    darker first column, like the sheet in the Excel icon."""
    out, tw, th = [], w / cols, h / rows
    for r in range(rows):
        for c in range(cols):
            if banded:                       # strongly alternating rows, so it still reads as a grid when small
                amount = (0.90 if r % 2 == 0 else 0.58) - (0.07 if c == 0 else 0.0)
            else:
                amount = ((0.80 - 0.09 * r - (0.05 if c == 0 else 0.0)) if light
                          else (0.30 - 0.17 * r - (0.07 if c == 0 else 0.0)))
            tl = radius if (r == 0 and c == 0) else 0
            tr = radius if (r == 0 and c == cols - 1) else 0
            br = radius if (r == rows - 1 and c == cols - 1) else 0
            bl = radius if (r == rows - 1 and c == 0) else 0
            out.append(f'<path d="{rrect(x + c * tw, y + r * th, tw + .4, th + .4, tl, tr, br, bl)}" fill="{shade(color, amount)}"/>')
    if banded:                               # grid lines between the cells
        line = shade(color, 0.12)
        for r in range(1, rows):
            out.append(f'<rect x="{x}" y="{y + r * th - 0.9:.1f}" width="{w}" height="1.8" fill="{line}"/>')
        for c in range(1, cols):
            out.append(f'<rect x="{x + c * tw - 0.9:.1f}" y="{y}" width="1.8" height="{h}" fill="{line}"/>')
    return "".join(out)


def sound_lines(cx: float, cy: float, scale: float = 1.0, simple: bool = False) -> str:
    """The white waveform overlay, with a soft shadow beneath it.

    *simple* draws five thicker lines instead of seven thin ones, for icons of 48 px and under,
    where seven lines blur into a smudge."""
    if simple:
        xs, hs, half = [-26, -13, 0, 13, 26], [24, 46, 66, 40, 20], 5.0
    else:
        xs, hs, half = [-33, -22, -11, 0, 11, 22, 33], [14, 30, 46, 60, 40, 24, 12], 3.5
    def one(fill, dy=0, opacity=1):
        return "".join(f'<rect x="{cx + (x - half) * scale:.1f}" y="{cy + (dy - h / 2) * scale:.1f}" width="{2 * half * scale:.1f}" '
                       f'height="{h * scale:.1f}" rx="{half * scale:.1f}" fill="{fill}" opacity="{opacity}"/>' for x, h in zip(xs, hs))
    return f'<g>{one("#000", 3.5, .16)}{one("#000", 2, .2)}{one("#FFFFFF")}</g>'


def sheet_icon_full(color: str) -> str:
    """Idea A: the icon itself is the tiled sheet (full width, no offset box, no label) with white sound lines."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><defs>'
            '<linearGradient id="edge" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".30"/>'
            '<stop offset=".18" stop-color="#FFFFFF" stop-opacity="0"/><stop offset=".85" stop-color="#000" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#000" stop-opacity=".16"/></linearGradient></defs>'
            '<rect x="6" y="8" width="116" height="116" rx="29" fill="#000" opacity=".10"/>'
            f'{tiled_sheet(color, 4, 4, 120, 120, 28)}'
            '<rect x="4.6" y="4.6" width="118.8" height="118.8" rx="27.4" fill="none" stroke="url(#edge)" stroke-width="1.2"/>'
            + sound_lines(64, 64, 1.0) + '</svg>')


def sheet_icon_plate(color: str) -> str:
    """Idea B: a light plate (like the Excel icon) carrying the tiled sheet, with white sound lines on it."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><defs>'
            '<linearGradient id="plate" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F4F5FA"/><stop offset="1" stop-color="#DDE0EE"/></linearGradient>'
            '<linearGradient id="edge" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".9"/>'
            '<stop offset=".2" stop-color="#FFFFFF" stop-opacity="0"/><stop offset="1" stop-color="#8A90B0" stop-opacity=".35"/></linearGradient></defs>'
            '<rect x="6" y="9" width="116" height="116" rx="29" fill="#5A6088" opacity=".16"/>'
            '<rect x="4" y="4" width="120" height="120" rx="28" fill="url(#plate)"/>'
            '<rect x="4.6" y="4.6" width="118.8" height="118.8" rx="27.4" fill="none" stroke="url(#edge)" stroke-width="1.2"/>'
            '<rect x="26" y="26" width="76" height="80" rx="12" fill="#000" opacity=".12" transform="translate(0 3)"/>'
            + tiled_sheet(color, 26, 24, 76, 80, 12)
            + sound_lines(64, 64, 0.72) + '</svg>')


#: Round seven: the Excel-style tiled sheet in purples, no small box, no label, white sound lines on top.
IDEAS_SHEET = [
    ("sheet-full-violet", "Tiled sheet fills the icon, violet", None, lambda: sheet_icon_full("#7A55C2")),
    ("sheet-full-indigo", "Tiled sheet fills the icon, indigo", None, lambda: sheet_icon_full("#5B4BC4")),
    ("sheet-plate-violet", "Tiled sheet on a light plate, violet", None, lambda: sheet_icon_plate("#7A55C2")),
    ("sheet-plate-indigo", "Tiled sheet on a light plate, indigo", None, lambda: sheet_icon_plate("#5B4BC4")),
]


def offset_box(color: str, x=16.0, y=39.0, size=50.0, simple: bool = False, border: bool = False) -> str:
    """The small front box (Excel's X box) holding the white sound lines."""
    deep = shade(color, -0.22)
    return (f'<rect x="{x}" y="{y + 3}" width="{size}" height="{size}" rx="11" fill="#000" opacity=".22"/>'
            f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="11" fill="{deep}"/>'
            f'<rect x="{x + .6}" y="{y + .6}" width="{size - 1.2}" height="{size - 1.2}" rx="10.4" fill="none" stroke="#FFFFFF" stroke-opacity=".22" stroke-width="1.2"/>'
            + (f'<rect x="{x + 2.2}" y="{y + 2.2}" width="{size - 4.4}" height="{size - 4.4}" rx="9" fill="none" '
               'stroke="#FFFFFF" stroke-opacity=".92" stroke-width="1.7"/>' if border else '')   # a white inlay all round
            + sound_lines(x + size / 2, y + size / 2, (0.44 if not simple else 0.52) * size / 50, simple))


def sheet_offset_plate(color: str) -> str:
    """The Excel layout: a light plate, a tiled sheet set to the right, and a small box on the left that
    pushes the sheet off-centre; the sound lines are in the small box. No text."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><defs>'
            '<linearGradient id="plate" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F4F5FA"/><stop offset="1" stop-color="#DDE0EE"/></linearGradient>'
            '<linearGradient id="edge" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".9"/>'
            '<stop offset=".2" stop-color="#FFFFFF" stop-opacity="0"/><stop offset="1" stop-color="#8A90B0" stop-opacity=".35"/></linearGradient></defs>'
            '<rect x="6" y="9" width="116" height="116" rx="29" fill="#5A6088" opacity=".16"/>'
            '<rect x="4" y="4" width="120" height="120" rx="28" fill="url(#plate)"/>'
            '<rect x="4.6" y="4.6" width="118.8" height="118.8" rx="27.4" fill="none" stroke="url(#edge)" stroke-width="1.2"/>'
            '<rect x="42" y="21" width="68" height="86" rx="10" fill="#000" opacity=".12" transform="translate(0 3)"/>'
            + tiled_sheet(color, 42, 21, 68, 86, 10)
            + offset_box(color, 16, 39, 50) + '</svg>')


def sheet_offset_body(color: str, simple: bool = False, box: tuple[int, int, int] = (16, 39, 50)) -> str:
    """The same layout on a purple icon body: pale tiles, a deep small box, white sound lines.

    *box* is the small front box as (x, y, size); a larger one stays readable at Dock sizes.
    """
    top, bottom = shade(color, 0.10), shade(color, -0.12)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><defs>'
            f'<linearGradient id="base" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>'
            '<linearGradient id="edge" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".32"/>'
            '<stop offset=".18" stop-color="#FFFFFF" stop-opacity="0"/><stop offset=".85" stop-color="#000" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#000" stop-opacity=".16"/></linearGradient></defs>'
            '<rect x="6" y="8" width="116" height="116" rx="29" fill="#000" opacity=".10"/>'
            '<rect x="4" y="4" width="120" height="120" rx="28" fill="url(#base)"/>'
            '<rect x="4.6" y="4.6" width="118.8" height="118.8" rx="27.4" fill="none" stroke="url(#edge)" stroke-width="1.2"/>'
            '<rect x="42" y="21" width="68" height="86" rx="10" fill="#000" opacity=".16" transform="translate(0 3)"/>'
            + tiled_sheet(color, 42, 21, 68, 86, 10, light=True, banded=True)
            + offset_box(color, *box, simple, border=True) + '</svg>')


#: Round eight: the Excel layout (an offset sheet behind a small front box that holds the sound lines).
IDEAS_OFFSET = [
    ("offset-plate-violet", "Offset sheet and small box on a light plate, violet", None, lambda: sheet_offset_plate("#7A55C2")),
    ("offset-plate-indigo", "Offset sheet and small box on a light plate, indigo", None, lambda: sheet_offset_plate("#5B4BC4")),
    ("offset-body-violet", "Offset sheet and small box on a violet icon", None, lambda: sheet_offset_body("#7A55C2")),
    ("offset-body-indigo", "Offset sheet and small box on an indigo icon", None, lambda: sheet_offset_body("#5B4BC4")),
]


def menubar_square(size: float = 96.0) -> str:
    """The menu bar glyph for the offset icons: the small rounded square with its sound lines cut out."""
    x0 = 64 - size / 2
    xs = [-33, -22, -11, 0, 11, 22, 33]
    hs = [14, 30, 46, 60, 40, 24, 12]
    k = size / 50 * 0.44
    path = rrect(x0, x0, size, size, 22, 22, 22, 22)
    for x, h in zip(xs, hs):
        path += rrect(64 + (x - 3.5) * k, 64 - h / 2 * k, 7 * k, h * k, 3.5 * k, 3.5 * k, 3.5 * k, 3.5 * k)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><path d="{path}" fill="#000000" fill-rule="evenodd"/></svg>'


def app_icon(color: str, draw) -> str:
    """A dock-style icon in the modern macOS manner: a flat colour with only a *hint* of depth.

    Like the Mail or Arduino icons: a barely-there light-to-dark shift in the body,
    a hairline highlight on the top edge, a faint shade on the bottom edge, a flat
    white glyph and a very soft shadow under it. *draw* is the idea's ``lambda fg, bg: svg``.
    """
    top, bottom = shade(color, 0.10), shade(color, -0.10)
    glyph = lambda fg, bg: (f'<g transform="translate(64 64) scale({GLYPH_SCALE}) translate(-64 -64)">'
                            f'{draw(fg, bg)}</g>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><defs>'
        f'<linearGradient id="base" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/>'
        f'<stop offset="1" stop-color="{bottom}"/></linearGradient>'
        '<linearGradient id="edge" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".32"/>'
        '<stop offset=".18" stop-color="#FFFFFF" stop-opacity="0"/><stop offset=".85" stop-color="#000000" stop-opacity="0"/>'
        '<stop offset="1" stop-color="#000000" stop-opacity=".14"/></linearGradient></defs>'
        # one soft shadow under the icon
        '<rect x="6" y="8" width="116" height="116" rx="29" fill="#000" opacity=".10"/>'
        '<rect x="4" y="4" width="120" height="120" rx="28" fill="url(#base)"/>'
        '<rect x="4.6" y="4.6" width="118.8" height="118.8" rx="27.4" fill="none" stroke="url(#edge)" stroke-width="1.2"/>'
        # the glyph: flat white, with the faintest drop shadow so it sits slightly above the surface
        f'<g transform="translate(0 2)" opacity=".12">{glyph("#000000", "none")}</g>'
        f'{glyph("#FFFFFF", color)}'
        '</svg>')


def menubar(glyph: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">{glyph}</svg>'


def write_everything() -> list[tuple[str, str, str, str]]:
    """The first forty ideas, in order (01-20 are the first two rounds, 21-40 the third)."""
    return write_all(False) + write_all(True) + write_all(batch="new")


def write_all(more: bool = False, batch: str = "") -> list[tuple[str, str, str, str]]:
    """Write one batch of ideas: 01-10, *more* (11-20), ``batch="new"`` (21-40) or ``batch="mix"`` (41-50)."""
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    ideas, first = ((IDEAS_OFFSET, 64) if batch == "offset" else (IDEAS_SHEET, 60) if batch == "sheet" else (IDEAS_CLIP, 57) if batch == "clip" else (IDEAS_RING, 51) if batch == "ring" else (IDEAS_MIX, 41) if batch == "mix" else (IDEAS_NEW, 21) if batch == "new"
                    else (IDEAS_MORE, 11) if more else (IDEAS, 1))
    for i, (slug, title, color, draw) in enumerate(ideas, first):
        if color is None:                                   # a ready-made icon (no glyph function)
            big = draw()
            if slug.startswith("offset"):
                mono = menubar_square()
            else:
                mono = menubar(sound_lines(64, 64, 1.0).replace('"#FFFFFF"', '"#000000"').replace('fill="#000" opacity', 'fill="none" opacity'))
        else:
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


def render_png(svg: str, path: str, size: int = 1024) -> None:
    """Draw one icon at full size (for reviewing details)."""
    from PySide6.QtCore import QByteArray, QRectF
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    image.save(path)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    made = (write_all(batch="offset") if "--offset" in sys.argv else write_all(batch="sheet") if "--sheet" in sys.argv else write_all(batch="clip") if "--clip" in sys.argv else write_all(batch="ring") if "--ring" in sys.argv else write_all(batch="mix") if "--mix" in sys.argv else write_all(batch="new") if "--new" in sys.argv else write_everything() if "--all" in sys.argv
            else write_all(more="--more" in sys.argv))
    print(f"Wrote {len(made) * 2} icons to {OUT}")
    if ("--ring" in sys.argv or "--clip" in sys.argv or "--sheet" in sys.argv or "--offset" in sys.argv) and len(args) > 1:
        render_png(made[0][2], args[1])                 # the first ring at 1024 px
    if args:
        contact_sheet(args[0], made)
        print("Contact sheet:", args[0])
