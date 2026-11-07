"""Quill's look: one warm, rounded, modern theme in light and dark.

Qt's stock widgets look dated, and none of the off-the-shelf theme packages
fits: ``qt-material`` is Material Design, ``pyqtdarktheme`` is unmaintained,
``qdarkstyle`` is dark-only and ``PyQt-Fluent-Widgets`` is GPL (or paid). So
the app uses Qt's own *Fusion* style, which draws the same everywhere, plus a
palette and a small style sheet driven by the colour tokens below. There is no
extra dependency to ship, and changing the look means editing one table.

``auto`` follows the operating system's light/dark setting and restyles live
when the user changes it.
"""

from __future__ import annotations
import pathlib
import sys
import tempfile

from PySide6.QtCore import QEvent, QObject, Qt

from quill.ui import glass as glass_module
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QLayout, QWidget

_SCHEMES = {
    "auto": Qt.ColorScheme.Unknown,   # follow the operating system
    "light": Qt.ColorScheme.Light,
    "dark": Qt.ColorScheme.Dark,
}

#: Colour tokens per scheme. Warm neutrals with one accent.
TOKENS = {
    "light": dict(bg="#FAF9F5", surface="#FFFFFF", hover="#F1EFE8", pressed="#E8E5DC",
                  border="#E3E0D6", text="#1F1E1D", muted="#5E5C56", disabled="#B4B1A8", warn="#A8610C"),
    "dark":  dict(bg="#262624", surface="#30302E", hover="#3A3A37", pressed="#444441",
                  border="#44443F", text="#ECEBE6", muted="#A19F98", disabled="#6B6A64", warn="#F0B957"),
}

#: Accent colours: name -> (label, light scheme (accent, hover), dark scheme (accent, hover)).
#: Text on the accent is white on the light variants and near-black on the dark ones.
ACCENTS = {
    "violet":     ("Violet",     ("#7A55C2", "#6644A8"), ("#7A55C2", "#8C68D6")),
    "terracotta": ("Terracotta", ("#C9623F", "#B5552F"), ("#D97757", "#E58A6B")),
    "ocean":      ("Ocean",      ("#2F6FB5", "#255C9A"), ("#5B9BD5", "#75ADE0")),
    "forest":     ("Forest",     ("#3E7D4F", "#316A41"), ("#6BB383", "#82C197")),
    "rose":       ("Rose",       ("#C0446B", "#A93A5D"), ("#E57A9B", "#EC93AE")),
}

#: Spacing: style-sheet padding (px) and layout margin / gap. -1 keeps Qt's own defaults
#: ("compact", the original look); "comfortable" gives controls more room to breathe.
DENSITIES = {
    "compact":     dict(label="Compact", button="6px 14px", field="5px 9px", item="6px 18px",
                        header="6px", cell="3px", radius=12, margin=-1, gap=-1),
    "comfortable": dict(label="Comfortable", button="9px 20px", field="8px 12px", item="8px 22px",
                        header="10px", cell="7px", radius=14, margin=20, gap=12),
}

#: Space between a drop-down's or number box's left edge and its text, the same in every one (and every density).
TEXT_INSET = 12

DEFAULT_ACCENT = "violet"
DEFAULT_FONT_SIZE = 14
DEFAULT_SPACING = "compact"


def colors_for(dark: bool, accent: str = DEFAULT_ACCENT) -> dict[str, str]:
    """All colour tokens for a scheme and accent (unknown accents fall back to the default, violet)."""
    t = dict(TOKENS["dark" if dark else "light"])
    _, light, night = ACCENTS.get(accent, ACCENTS[DEFAULT_ACCENT])
    t["accent"], t["accent_hover"] = night if dark else light
    t["on_accent"] = _text_on(t["accent"]) if dark else "#FFFFFF"
    return t


def _luminance(hex_color: str) -> float:
    """Relative luminance (0 black to 1 white) of ``"#RRGGBB"``."""
    def channel(i: int) -> float:
        v = int(hex_color[i:i + 2], 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)


def _text_on(fill: str) -> str:
    """White or near-black text, whichever reads better on *fill* (used with the lighter dark-scheme accents)."""
    lum = _luminance(fill)
    white, dark = 1.05 / (lum + 0.05), (lum + 0.05) / (_luminance("#1F1E1D") + 0.05)
    return "#FFFFFF" if white >= dark else "#1F1E1D"


def mix(base: str, other: str, amount: float) -> str:
    """*base* nudged toward *other* by *amount* (0 to 1), as ``"#RRGGBB"``."""
    a = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02X}" for x, y in zip(a, b))


#: The warning colour of notices ("File not connected"): an amber that reads on a light and on a dark window.
WARNING_LIGHT, WARNING_DARK = "#B26A00", "#E0A030"


def rgba(hex_color: str, alpha: float) -> str:
    """``"#RRGGBB"`` as a style-sheet ``rgba(...)`` colour (alpha 0 to 1)."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {round(max(0.0, min(1.0, alpha)) * 255)})"


def palette_for(dark: bool, accent: str = DEFAULT_ACCENT) -> QPalette:
    """A palette built from the tokens (so native-drawn bits match the style sheet)."""
    t = colors_for(dark, accent)
    palette = QPalette()
    for role, key in (
        (QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.Base, "surface"),
        (QPalette.ColorRole.AlternateBase, "hover"), (QPalette.ColorRole.Button, "surface"),
        (QPalette.ColorRole.WindowText, "text"), (QPalette.ColorRole.Text, "text"),
        (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.ToolTipBase, "surface"),
        (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.PlaceholderText, "muted"),
        (QPalette.ColorRole.Highlight, "accent"), (QPalette.ColorRole.HighlightedText, "on_accent"),
        (QPalette.ColorRole.Link, "accent"), (QPalette.ColorRole.Mid, "border"),
    ):
        palette.setColor(role, QColor(t[key]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["disabled"]))
    return palette


def _chevrons(t: dict[str, str]) -> dict[str, str]:
    """Write the little chevron images used by drop-downs and spin boxes; return their paths.

    Drawn in the theme's own colours so they follow light/dark. Stored once per
    colour set in a temporary folder (a style sheet can only point at files).
    """
    key = (t["muted"], t["disabled"], t["on_accent"])
    if key not in _ICON_CACHE:
        folder = pathlib.Path(tempfile.mkdtemp(prefix="quill-icons-"))
        paths: dict[str, str] = {}
        for name, color in (("", t["muted"]), ("-disabled", t["disabled"])):
            for direction, points in (("down", "3,6 8,11 13,6"), ("up", "3,10 8,5 13,10")):
                svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
                       f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.8" '
                       f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
                path = folder / f"{direction}{name}.svg"
                path.write_text(svg, encoding="utf-8")
                paths[f"{direction}{name}"] = path.as_posix()
        check = folder / "check.svg"
        check.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
                         f'<polyline points="3.5,8.5 6.8,11.8 12.5,4.8" fill="none" stroke="{t["on_accent"]}" '
                         'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
        paths["check"] = check.as_posix()
        _ICON_CACHE[key] = paths
    return _ICON_CACHE[key]


_ICON_CACHE: dict[tuple[str, str, str], dict[str, str]] = {}


def backdrop_alpha(opacity: int, blur: int) -> float:
    """How solid a window's own background paint is.

    The opacity setting thins the *background* only (controls and text stay solid); the blur setting then decides how
    blurred what shows through it is. At 100 the background is solid whatever the blur. (Windows keeps the older
    behaviour, where without blur the whole window fades; see :func:`apply_opacity`.)
    """
    if sys.platform != "darwin" and int(blur) <= 0:
        return 1.0
    return round(max(0.08, min(100, max(0, int(opacity))) / 100), 3)


#: The look of spoken words and phrases wherever they appear: a deep violet pill with white text.
PILL_BG, PILL_FG = "#5E4A99", "#FFFFFF"

#: Border and tint of the blink that confirms something: (border colour, tint) per outcome. One blink for the whole app
#: (a Term Helper row, the Open File button ...).
FLASH_STYLES = {
    "accepted": ("#66D983", "rgba(102, 217, 131, 0.14)"),      # green: it worked / it is what was asked for
    "ignored": ("#8E8E93", "rgba(142, 142, 147, 0.16)"),     # grey: a deliberate "no", nothing was added
    "error": ("#FF3B30", "rgba(255, 59, 48, 0.14)"),         # red: it could not be carried out
}

ROOT_NAMES = ("mainRoot", "sidePanel", "settingsRoot", "sortingRoot", "helpRoot")


def native_layers(widget: QWidget) -> int:
    """How many native layers paint the background behind *widget*: 1, or 2 when a native child widget sits between it and
    its window (macOS gives such a child a layer of its own, and the two see-through backgrounds add up)."""
    parent = widget.parentWidget()
    while parent is not None and not parent.isWindow():
        if parent.windowHandle() is not None:
            return 2
        parent = parent.parentWidget()
    return 1


class _BackdropPainter(QObject):
    """Paints a window root's background (theme colour, with the backdrop alpha) just before the widget paints.

    Doing this here instead of in the style sheet means the transparency can change as the user drags the opacity
    or blur slider by a repaint of the roots, not a re-styling of every widget.
    """

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Paint:
            app = QApplication.instance()
            if app is not None:
                colors = colors_for(is_dark(app), str(app.property("quillAccent") or DEFAULT_ACCENT))
                color = QColor(colors["bg"])
                alpha = app.property("quillBackdrop")
                solid = obj.property("quillSolid")                  # a window that opts out of the opacity setting
                floor = float(obj.property("quillMinAlpha") or 0.0)   # a window that never thins below this (Settings)
                shown = 1.0 if alpha is None or solid else max(float(alpha), floor)
                color.setAlphaF(glass_module.paint_alpha(shown, is_dark(app), native_layers(obj)))
                painter = QPainter(obj)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.fillRect(obj.rect(), color)
                painter.end()
        return False


def install_backdrop(root: QWidget) -> None:
    """Make *root* (a window's root widget) paint its own background; call once when the window is built."""
    painter = _BackdropPainter(root)                  # parented to the root, so it lives and dies with it
    root.installEventFilter(painter)


def set_backdrop(app: QApplication, alpha: float) -> None:
    """Set how solid the windows' own backgrounds are (see :func:`backdrop_alpha`) and repaint them."""
    alpha = max(0.0, min(1.0, float(alpha)))
    if app.property("quillBackdrop") == alpha:
        return
    app.setProperty("quillBackdrop", alpha)
    for widget in app.allWidgets():
        if widget.objectName() in ROOT_NAMES:
            widget.update()
    if app.property("quillThemeKey") is not None:
        _restyle(app)                                    # (the controls' fills follow the same alpha)


def stylesheet_for(dark: bool, accent: str = DEFAULT_ACCENT, spacing: str = DEFAULT_SPACING,
                   font_size: int = DEFAULT_FONT_SIZE, backdrop: float = 1.0) -> str:
    """The style sheet: rounded controls, hairline borders, an accent for the main action.

    A window's own background is not painted by the style sheet but by :class:`_BackdropPainter` (so its
    transparency can change without re-styling the whole application). The fills of text boxes, drop-downs, buttons and
    cards take the same *backdrop* alpha (down to :data:`CONTROL_FLOOR`), so the opacity and blur settings show through
    them too; their text and borders stay solid.
    """
    t = colors_for(dark, accent)
    d = DENSITIES.get(spacing, DENSITIES[DEFAULT_SPACING])
    icon = _chevrons(t)
    glass = glass_module.control_alpha(float(backdrop), dark)
    win = t["bg"] if glass >= 1 else rgba(t["bg"], glass)                    # control fills thin with the window's background
    surf = t["surface"] if glass >= 1 else rgba(t["surface"], glass)
    hover = rgba(t["accent"], 0.20)            # list/menu hover: a tint, so the text colour never changes
    return f"""
QWidget {{ font-size: {font_size}pt; }}
QMainWindow, QDialog, QWidget#sortingWindow {{ background: transparent; }}
QWidget#mainRoot, QFrame#sidePanel, QWidget#settingsRoot, QWidget#sortingRoot, QWidget#helpRoot {{ background: transparent; }}
QToolTip {{ background: {mix(t['surface'], t['text'], 0.26 if dark else 0.08)}; color: {t['text']}; border: 1px solid {rgba(t['border'], 0.6)};
           border-radius: 7px; padding: 4px 8px; }}

QPushButton {{ background: {surf}; color: {t['text']}; border: 1px solid {t['accent']};
              border-radius: 8px; padding: {d['button']}; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['pressed']}; }}
QPushButton:disabled {{ color: {t['disabled']}; background: {win}; border-color: {t['border']}; }}
QPushButton:checked, QPushButton[accent="true"] {{ background: {t['accent']}; color: {t['on_accent']};
              border-color: {t['accent']}; font-weight: 600; }}
QPushButton:checked:hover, QPushButton[accent="true"]:hover {{ background: {t['accent_hover']}; }}
QPushButton[danger="true"] {{ background: #E5484D; color: #FFFFFF; border-color: #E5484D; }}
QPushButton[danger="true"]:hover {{ background: #CD3A3F; border-color: #CD3A3F; }}
QLabel#confirmTitle {{ font-weight: 600; }}
QPushButton::menu-indicator {{ width: 0; }}

QLineEdit, QSpinBox, QComboBox {{ background: {surf}; color: {t['text']};
              border: 1px solid {t['border']}; border-radius: 8px; padding: {d['field']};
              selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; }}
QComboBox:disabled, QSpinBox:disabled {{ color: {t['disabled']}; background: {t['bg']}; }}
QComboBox {{ combobox-popup: 0; padding-left: {TEXT_INSET}px; padding-right: 32px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 30px;
              border: none; background: transparent; }}
QComboBox::down-arrow {{ image: url({icon['down']}); width: 14px; height: 14px; }}
QComboBox::down-arrow:disabled {{ image: url({icon['down-disabled']}); }}
QSpinBox {{ padding-right: 28px; }}
QSpinBox::up-button {{ subcontrol-origin: padding; subcontrol-position: top right; width: 24px;
              border: none; background: transparent; }}
QSpinBox::down-button {{ subcontrol-origin: padding; subcontrol-position: bottom right; width: 24px;
              border: none; background: transparent; }}
QSpinBox::up-arrow {{ image: url({icon['up']}); width: 12px; height: 12px; }}
QSpinBox::down-arrow {{ image: url({icon['down']}); width: 12px; height: 12px; }}
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off {{ image: url({icon['up-disabled']}); }}
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off {{ image: url({icon['down-disabled']}); }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
              border-radius: 8px; selection-background-color: {hover};
              selection-color: {t['text']}; color: {t['text']}; outline: none; padding: 4px; }}
QComboBox QAbstractItemView::item {{ padding: 6px 10px; min-height: 22px; border-radius: 6px;
              color: {t['text']}; }}
QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{
              background: {hover}; color: {t['text']}; }}
QComboBox QAbstractItemView::item:disabled {{ color: {t['disabled']}; background: transparent; }}

QPlainTextEdit, QTextEdit, QTableWidget {{ background: {surf}; color: {t['text']};
              border: 1px solid {t['border']}; border-radius: 10px; padding: 4px;
              gridline-color: {t['border']}; selection-background-color: {t['accent']};
              selection-color: {t['on_accent']}; }}
QHeaderView::section {{ background: {win}; color: {t['muted']}; border: none;
              border-bottom: 1px solid {t['border']}; padding: {d['header']}; font-weight: 600; }}
QTableWidget::item {{ padding: {d['cell']}; }}
QTreeWidget#learnedList {{ background: {surf}; border: 1px solid {t['border']}; border-radius: 10px; padding: 4px;
              outline: none; }}
QTreeWidget#learnedList::branch {{ image: none; background: transparent; }}

QFrame#termRow {{ background: {surf}; border: 1px solid {t['border']}; border-radius: {d['radius']}px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {t['disabled']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 4px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
        border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: {d['item']}; border-radius: 6px; }}
QMenu::item {{ color: {t['text']}; }}
QMenu::item:selected {{ background: {hover}; color: {t['text']}; }}
QMenu::item:disabled {{ color: {t['disabled']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 8px; }}

QLabel[heading="true"] {{ color: {t['muted']}; }}
QLabel[chip="warn"] {{ background: {rgba(t['accent'], 0.16)}; color: {t['text']};
              border: 1px solid {rgba(t['accent'], 0.6)}; border-radius: 11px; padding: 2px 11px; font-weight: 500; }}
QFrame[listenPill="true"] {{ background: transparent; border: 1px solid {t['accent']}; border-radius: 12px; }}
QPushButton[accent="true"] QFrame[listenPill="true"] {{ border: 1px solid {rgba(t['on_accent'], 0.7)}; }}
QFrame[listenPill="true"] QLabel {{ background: transparent; color: {t['text']}; font-weight: 500; }}
QPushButton[accent="true"] QFrame[listenPill="true"] QLabel {{ color: {t['on_accent']}; }}
QLabel[placeholder="true"] {{ font-style: italic; color: {t['muted']}; }}
QTextEdit, QPlainTextEdit {{ placeholder-text-color: {t['muted']}; }}
QLabel[note="true"] {{ font-style: italic; color: {t['muted']}; }}
QPushButton[accent="true"] QLabel {{ background: transparent; color: {t['on_accent']}; font-weight: 600; }}
QLabel[countdown="true"] {{ background: transparent; color: {rgba(t['text'], 0.78)}; font-style: italic; font-weight: 400; }}
QPushButton[accent="true"] QLabel[countdown="true"], QPushButton:checked QLabel[countdown="true"] {{ color: {rgba(t['on_accent'], 0.92)}; font-weight: 400; }}
QPushButton[iconOnly="true"] {{ padding: 6px 9px; border-color: {t['border']}; }}
QPushButton[outline="true"][iconOnly="true"] {{ border-color: {t['accent']}; }}
QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {t['border']}; }}
QSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px; background: {t['accent']}; }}
QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -7px 0; border-radius: 9px;
              background: {t['accent']}; border: 2px solid {t['surface']}; }}
QLabel#termPrompt {{ font-weight: 500; }}
QToolButton[heading="true"] {{ border: none; background: transparent; padding: 2px 0; margin: 0; min-width: 0;
              color: {t['muted']}; }}
QToolButton[errorMark="true"] {{ background: #E5484D; color: #FFFFFF; border: none; border-radius: 10px; min-width: 20px;
              max-width: 20px; min-height: 20px; max-height: 20px; padding: 0; font-weight: 600; }}
QToolButton[errorMark="true"]:hover {{ background: #F0686C; }}
QToolButton[flatIcon="true"] {{ border: none; background: transparent; padding: 5px; border-radius: 7px; }}
QToolButton[flatIcon="true"]:hover {{ background: {rgba(t['text'], 0.08)}; }}
QToolButton[heading="true"]:hover {{ color: {t['accent']}; }}
QLabel[headingToggle="true"] {{ color: {t['muted']}; padding: 2px 0; font-weight: 400; }}
QLabel[staticHeading="true"] {{ color: {t['muted']}; padding: 2px 0; font-weight: 400; }}
QLabel[info="true"] {{ background: {rgba(t['accent'], 0.12)}; color: {t['text']}; border: 1px solid {rgba(t['accent'], 0.38)};
              border-radius: 12px; padding: 8px 14px; }}
QPushButton[outline="true"] {{ border: 1px solid {t['accent']}; }}
QPushButton[outline="true"]:disabled {{ border-color: {t['border']}; }}
QPushButton[outline="true"]:hover {{ background: {rgba(t['accent'], 0.14)}; }}
QLabel[headingToggle="true"]:hover {{ color: {t['accent']}; }}
QTreeWidget#helpNav {{ background: transparent; border: none; outline: none; padding: 0; }}
QTreeWidget#helpNav::branch {{ background: transparent; image: none; }}
QTreeWidget#helpNav::item {{ padding: 7px 10px; margin: 1px 0; border-radius: 8px; color: {t['text']}; }}
QTreeWidget#helpNav::item:hover {{ background: {rgba(t['text'], 0.06)}; }}
QTreeWidget#helpNav::item:selected {{ background: {rgba(t['text'], 0.10)}; color: {t['text']}; }}
QTextBrowser#helpPage {{ background: transparent; border: none; }}
QWidget#settingsSidebar {{ border-right: 1px solid {t['border']}; }}
QListWidget#settingsNav {{ background: transparent; border: none; outline: none; padding: 0; }}
QListWidget#settingsNav::item {{ padding: 8px 12px; margin: 1px 14px; border-radius: 8px; color: {t['text']}; }}
QListWidget#settingsNav::item:hover {{ background: {rgba(t['text'], 0.06)}; }}
QListWidget#settingsNav::item:selected {{ background: {rgba(t['text'], 0.10)}; color: {t['text']}; }}
QListWidget#settingsNav::item:disabled {{ color: {t['muted']}; margin: 1px 0; padding: 14px 26px 6px 26px; background: transparent; }}
QScrollArea#settingsPage, QWidget#settingsPageBody {{ background: transparent; }}
QWidget#settingsFooter {{ border-top: 1px solid {t['border']}; }}
QFrame#settingsDivider {{ background: {t['border']}; border: none; }}
QLabel#pageTitle {{ font-weight: 700; padding-bottom: 2px; }}
QLabel[muted="true"] {{ color: {t['muted']}; }}
QComboBox[flat="true"], QSpinBox[flat="true"] {{ background: transparent; border: 1px solid transparent;
              border-radius: 8px; padding: 6px 34px 6px 12px; }}
QSpinBox[flat="true"]::up-button, QSpinBox[flat="true"]::down-button {{ width: 30px; }}
QSpinBox[flat="true"]:hover {{ background: {rgba(t['text'], 0.06)}; }}
QComboBox[flat="true"]:focus, QSpinBox[flat="true"]:focus {{ border: 1px solid {t['accent']}; }}
QComboBox[flat="true"]:hover {{ background: {rgba(t['text'], 0.06)}; }}
QComboBox[flat="true"]:disabled, QSpinBox[flat="true"]:disabled {{ background: transparent; color: {t['disabled']}; }}
QWidget#segmented {{ background: {rgba(t['text'], 0.06)}; border-radius: 10px; }}
QToolButton[segment="true"] {{ border: none; border-radius: 8px; padding: 6px 10px; background: transparent; }}
QToolButton[segment="true"]:hover {{ background: {rgba(t['text'], 0.06)}; }}
QToolButton[segment="true"]:checked {{ background: {surf}; border: 1px solid {t['border']}; }}
QCheckBox {{ spacing: 10px; }}
QRadioButton {{ spacing: 8px; font-weight: 600; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1px solid {t['muted']}; background: transparent; }}
QRadioButton::indicator:checked {{ background: {t['accent']}; border: 1px solid {t['accent']}; }}
QFrame#sidePanel {{ background: transparent; border: none; }}
QFrame[panelEdge="true"] {{ background: {rgba(t['text'], 0.14)}; border: none; }}
QFrame[closedNote="true"] {{ background: {rgba(t['warn'], 0.14)}; border: 1px solid {rgba(t['warn'], 0.55)}; border-radius: 10px; }}
QFrame[sheetNote="true"] {{ background: transparent; border: 1.5px solid {FLASH_STYLES['accepted'][0]}; border-radius: 10px; }}
QLabel[closedTitle="true"] {{ background: transparent; color: {t['text']}; font-weight: 600; }}
QLabel[closedBody="true"] {{ background: transparent; color: {t['text']}; }}
QFrame[panelRule="true"] {{ background: {rgba(t['text'], 0.14)}; border: none; }}
QLineEdit[pillField="true"] {{ background: {PILL_BG}; color: {PILL_FG}; border: 1px solid {PILL_BG}; border-radius: 0; padding: 2px 6px;   /* square-cornered, like the pills in text */
              selection-background-color: {rgba(PILL_FG, 0.35)}; selection-color: {PILL_FG}; }}
QLineEdit[pillField="true"]:focus {{ border: 1px solid {PILL_FG}; }}
QLabel[modelName="true"] {{ font-weight: 700; }}
QLabel[modelSize="true"] {{ font-weight: 400; font-style: italic; color: {t['muted']}; }}
QLabel[modelCost="true"] {{ font-weight: 400; color: {t['muted']}; }}
QComboBox[flat="true"][rowSelected="true"] {{ color: {t['on_accent']}; }}
QLabel[panelTitle="true"] {{ font-weight: 400; }}
QLabel[panelHeading="true"] {{ font-weight: 600; color: {t['text']}; }}
QLabel[panelValue="true"] {{ font-weight: 400; font-style: normal; color: {t['text']}; }}
QFrame#fileSettings {{ background: {surf}; border: 1px solid {t['border']}; border-radius: 10px; }}
QLabel[panelNote="true"] {{ font-weight: 400; font-style: normal; color: {t['muted']}; }}
QToolButton[chromeIcon="true"] {{ border: none; background: transparent; padding: 5px; border-radius: 7px; }}
QToolButton[chromeIcon="true"]:hover {{ background: {rgba(t['text'], 0.10)}; }}
QToolButton[chromeIcon="true"]:pressed {{ background: {rgba(t['text'], 0.22)}; }}
QLabel[panelName="true"] {{ font-weight: 600; }}
QLabel[panelName="true"][muted="true"] {{ font-weight: 400; font-style: italic; color: {t['muted']}; }}
QListWidget#panelList {{ background: transparent; border: none; outline: none; padding: 0; }}
QListWidget#panelList::item {{ padding: 0 8px; margin: 2px 0; border-radius: 8px; color: {t['text']}; }}
QListWidget#panelList::item:hover {{ background: {rgba(t['accent'], 0.14)}; }}
QListWidget#panelList::item:selected {{ background: {rgba(t['accent'], 0.14)}; color: {t['text']}; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {t['muted']};
              background: {surf}; }}
QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']};
              image: url({icon['check']}); }}
QCheckBox::indicator:disabled {{ border-color: {t['disabled']}; background: {win}; }}
"""


def is_dark(app: QApplication) -> bool:
    """True if the dark look applies: chosen explicitly, or the OS is dark in auto mode."""
    mode = app.property("quillThemeMode")
    if mode in ("light", "dark"):
        return mode == "dark"
    return app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def _restyle(app: QApplication) -> None:
    dark = is_dark(app)
    accent = str(app.property("quillAccent") or DEFAULT_ACCENT)
    spacing = str(app.property("quillSpacing") or DEFAULT_SPACING)
    size = int(app.property("quillFontSize") or DEFAULT_FONT_SIZE)
    alpha = app.property("quillBackdrop")
    glass = 1.0 if alpha is None else round(float(alpha) * 20) / 20           # (steps of 5 %, so dragging a slider re-styles seldom)
    key = f"{dark}/{accent}/{spacing}/{size}/{glass}"
    if app.property("quillThemeKey") == key:
        return                      # unchanged: re-polishing every widget is slow
    app.setProperty("quillThemeKey", key)
    font = app.font()
    font.setPointSize(size)
    app.setFont(font)
    app.setPalette(palette_for(dark, accent))
    app.setStyleSheet(stylesheet_for(dark, accent, spacing, size, glass))


class _TooltipRounder(QObject):
    """Lets tooltips have rounded corners: Qt draws them in a square window, so make that window transparent.

    The style sheet then paints the rounded, softly bordered box and nothing square shows behind it.
    """

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Polish and obj.inherits("QTipLabel"):
            obj.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            obj.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        elif event.type() == QEvent.Type.Show and obj.inherits("QTipLabel"):
            from quill.ui.chrome import no_window_shadow          # the OS shadow shows a faint square corner
            no_window_shadow(obj)
        return False


def apply_theme(app: QApplication, mode: str, accent: str = DEFAULT_ACCENT,
                spacing: str = DEFAULT_SPACING, font_size: int = DEFAULT_FONT_SIZE, backdrop: float = 1.0) -> None:
    """Set the colour scheme, accent and spacing, and apply Quill's look.

    Args:
        app: The running application.
        mode: ``"auto"`` (follow the OS), ``"light"`` or ``"dark"``. Anything
            else is treated as ``"auto"``.
        accent: A key of :data:`ACCENTS`.
        spacing: ``"compact"`` or ``"comfortable"``. Layout margins and gaps
            are applied separately by :func:`apply_spacing`.
        font_size: Base text size in points (the Needs-sorting questions are 3 larger).
        backdrop: Alpha of the windows' own background (see :func:`backdrop_alpha`); 1 = solid.
    """
    if not app.property("quillFusion"):      # once: re-setting the style re-polishes everything
        app.setStyle("Fusion")
        app.setProperty("quillFusion", True)
    hints = app.styleHints()
    if mode in ("light", "dark"):
        hints.setColorScheme(_SCHEMES[mode])
    elif hasattr(hints, "unsetColorScheme"):
        hints.unsetColorScheme()             # back to the operating system's own choice
    else:
        hints.setColorScheme(Qt.ColorScheme.Unknown)
    app.setProperty("quillThemeMode", mode)
    app.setProperty("quillAccent", accent if accent in ACCENTS else DEFAULT_ACCENT)
    app.setProperty("quillSpacing", spacing if spacing in DENSITIES else DEFAULT_SPACING)
    app.setProperty("quillFontSize", max(6, min(40, int(font_size))))
    set_backdrop(app, backdrop)
    _restyle(app)
    if not app.property("quillTooltips"):
        rounder = _TooltipRounder(app)             # parented to the app, which keeps it alive
        app.installEventFilter(rounder)
        app.setProperty("quillTooltips", True)
    if not app.property("quillThemeHooked"):
        app.styleHints().colorSchemeChanged.connect(lambda *_: _restyle(app))
        app.setProperty("quillThemeHooked", True)


def apply_opacity(root: QWidget, percent: int, blur: int = 0) -> None:
    """Make a window see-through to *percent* opacity.

    On macOS the window itself stays fully opaque as an object and only its background thins (see
    :func:`backdrop_alpha`): that is what lets the window server blur the desktop behind it by the blur setting.
    Elsewhere, without blur, the whole window (background, controls and text together) is faded with the window's own
    opacity, done by the compositor. (An earlier version faded the root widget with a graphics effect; on macOS that
    left ghost copies of the text and stale pieces of the previous theme.) *root* may be any widget of the window.
    """
    percent = max(0, min(100, int(percent)))
    if root.graphicsEffect() is not None:
        root.setGraphicsEffect(None)                       # no effect may be left over from before
    root.window().setWindowOpacity(1.0 if (sys.platform == "darwin" or int(blur) > 0) else percent / 100)


def apply_spacing(widget: QWidget, spacing: str | None = None) -> None:
    """Set layout margins and gaps throughout *widget* for the chosen spacing.

    Style sheets can't change a layout's margins, so this walks the layouts.
    With no *spacing* the application's current choice is used (so a window
    built later, like a new row in the Needs-sorting list, matches).
    """
    if spacing is None:
        app = QApplication.instance()
        spacing = str(app.property("quillSpacing")) if app is not None else DEFAULT_SPACING
    d = DENSITIES.get(spacing, DENSITIES[DEFAULT_SPACING])
    layouts = ([widget.layout()] if widget.layout() else []) + widget.findChildren(QLayout)
    window = widget.window()
    for layout in layouts:
        owner = layout.parentWidget()
        if owner is not None and owner.window() is not window:
            continue                           # another window that is a child of this one (Settings, Term Helper, a
                                               # drop-down's pop-up list) keeps its own layout; findChildren reaches it too
        parent = layout.parent()
        if not (layout.property("keepSpacing") or (isinstance(parent, QWidget) and parent.property("keepSpacing"))):   # (pieces that must touch)
            layout.setSpacing(d["gap"])
        if isinstance(parent, QWidget) and not parent.property("keepMargins"):   # a widget's own layout, not a nested one
            m = d["margin"]
            layout.setContentsMargins(m, m, m, m)
