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
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLayout, QWidget

_SCHEMES = {
    "auto": Qt.ColorScheme.Unknown,   # follow the operating system
    "light": Qt.ColorScheme.Light,
    "dark": Qt.ColorScheme.Dark,
}

#: Colour tokens per scheme. Warm neutrals with one accent.
TOKENS = {
    "light": dict(bg="#FAF9F5", surface="#FFFFFF", hover="#F1EFE8", pressed="#E8E5DC",
                  border="#E3E0D6", text="#1F1E1D", muted="#6F6D66", disabled="#B4B1A8"),
    "dark":  dict(bg="#262624", surface="#30302E", hover="#3A3A37", pressed="#444441",
                  border="#44443F", text="#ECEBE6", muted="#A19F98", disabled="#6B6A64"),
}

#: Accent colours: name -> (label, light scheme (accent, hover), dark scheme (accent, hover)).
#: Text on the accent is white on the light variants and near-black on the dark ones.
ACCENTS = {
    "terracotta": ("Terracotta", ("#C9623F", "#B5552F"), ("#D97757", "#E58A6B")),
    "ocean":      ("Ocean",      ("#2F6FB5", "#255C9A"), ("#5B9BD5", "#75ADE0")),
    "forest":     ("Forest",     ("#3E7D4F", "#316A41"), ("#6BB383", "#82C197")),
    "violet":     ("Violet",     ("#7A55C2", "#6644A8"), ("#A58BE0", "#B6A0E8")),
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

DEFAULT_ACCENT = "terracotta"
DEFAULT_FONT_SIZE = 12
DEFAULT_SPACING = "compact"


def colors_for(dark: bool, accent: str = DEFAULT_ACCENT) -> dict[str, str]:
    """All colour tokens for a scheme and accent (unknown accents fall back to terracotta)."""
    t = dict(TOKENS["dark" if dark else "light"])
    _, light, night = ACCENTS.get(accent, ACCENTS[DEFAULT_ACCENT])
    t["accent"], t["accent_hover"] = night if dark else light
    t["on_accent"] = "#1F1E1D" if dark else "#FFFFFF"
    return t


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
        (QPalette.ColorRole.Link, "accent"),
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


def stylesheet_for(dark: bool, accent: str = DEFAULT_ACCENT, spacing: str = DEFAULT_SPACING,
                   font_size: int = DEFAULT_FONT_SIZE) -> str:
    """The style sheet: rounded controls, hairline borders, an accent for the main action."""
    t = colors_for(dark, accent)
    d = DENSITIES.get(spacing, DENSITIES[DEFAULT_SPACING])
    icon = _chevrons(t)
    win = t["bg"]                                        # all colours are solid: see-through is
    surf = t["surface"]                                  # applied to the whole window, never per colour
    hover = rgba(t["accent"], 0.20)            # list/menu hover: a tint, so the text colour never changes
    return f"""
QMainWindow, QDialog, QWidget#sortingWindow {{ background: transparent; }}
QWidget#mainRoot, QWidget#settingsRoot, QWidget#sortingRoot {{ background: {win}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
           border-radius: 6px; padding: 4px 8px; }}

QPushButton {{ background: {surf}; color: {t['text']}; border: 1px solid {t['border']};
              border-radius: 8px; padding: {d['button']}; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['pressed']}; }}
QPushButton:disabled {{ color: {t['disabled']}; background: {win}; }}
QPushButton:checked, QPushButton[accent="true"] {{ background: {t['accent']}; color: {t['on_accent']};
              border-color: {t['accent']}; font-weight: 600; }}
QPushButton:checked:hover, QPushButton[accent="true"]:hover {{ background: {t['accent_hover']}; }}
QPushButton::menu-indicator {{ width: 0; }}

QLineEdit, QSpinBox, QComboBox {{ background: {surf}; color: {t['text']};
              border: 1px solid {t['border']}; border-radius: 8px; padding: {d['field']};
              selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; }}
QComboBox:disabled, QSpinBox:disabled {{ color: {t['disabled']}; background: {t['bg']}; }}
QComboBox {{ combobox-popup: 0; padding-right: 32px; }}
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

QPlainTextEdit, QTextEdit, QTableWidget {{ background: {surf}; color: {t['text']};
              border: 1px solid {t['border']}; border-radius: 10px; padding: 4px;
              gridline-color: {t['border']}; selection-background-color: {t['accent']};
              selection-color: {t['on_accent']}; }}
QHeaderView::section {{ background: {win}; color: {t['muted']}; border: none;
              border-bottom: 1px solid {t['border']}; padding: {d['header']}; font-weight: 600; }}
QTableWidget::item {{ padding: {d['cell']}; }}

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
QLabel[note="true"] {{ font-size: {max(font_size - 2, 7)}pt; font-style: italic; color: {t['muted']}; }}
QPushButton[accent="true"] QLabel {{ background: transparent; color: {t['on_accent']}; font-weight: 600; }}
QPushButton[iconOnly="true"] {{ padding: 6px 9px; }}
QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {t['border']}; }}
QSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px; background: {t['accent']}; }}
QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -7px 0; border-radius: 9px;
              background: {t['accent']}; border: 2px solid {t['surface']}; }}
QLabel#termPrompt {{ font-size: {font_size + 3}pt; font-weight: 500; }}
QToolButton[heading="true"] {{ border: none; background: transparent; padding: 2px 0;
              font-size: {font_size}pt;
              color: {t['muted']}; }}
QToolButton[flatIcon="true"] {{ border: none; background: transparent; padding: 5px; border-radius: 7px; }}
QToolButton[flatIcon="true"]:hover {{ background: {rgba(t['text'], 0.08)}; }}
QToolButton[heading="true"]:hover {{ color: {t['accent']}; }}
QWidget#settingsSidebar {{ border-right: 1px solid {t['border']}; }}
QListWidget#settingsNav {{ background: transparent; border: none; outline: none; padding: 0; }}
QListWidget#settingsNav::item {{ padding: 8px 12px; margin: 1px 0; border-radius: 8px; color: {t['text']}; }}
QListWidget#settingsNav::item:hover {{ background: {rgba(t['text'], 0.06)}; }}
QListWidget#settingsNav::item:selected {{ background: {rgba(t['text'], 0.10)}; color: {t['text']}; }}
QListWidget#settingsNav::item:disabled {{ color: {t['muted']}; padding: 14px 12px 4px 12px; background: transparent; }}
QScrollArea#settingsPage, QWidget#settingsPageBody {{ background: transparent; }}
QWidget#settingsFooter {{ border-top: 1px solid {t['border']}; }}
QFrame#settingsDivider {{ background: {t['border']}; border: none; }}
QLabel#pageTitle {{ font-size: {font_size + 3}pt; padding-bottom: 4px; }}
QLabel[muted="true"] {{ color: {t['muted']}; }}
QComboBox[flat="true"] {{ background: transparent; border: none; border-radius: 8px;
              padding: 6px 34px 6px 12px; }}
QComboBox[flat="true"]:hover {{ background: {rgba(t['text'], 0.06)}; }}
QComboBox[flat="true"]:disabled {{ background: transparent; color: {t['disabled']}; }}
QWidget#segmented {{ background: {rgba(t['text'], 0.06)}; border-radius: 10px; }}
QToolButton[segment="true"] {{ border: none; border-radius: 8px; padding: 6px 10px; background: transparent; }}
QToolButton[segment="true"]:hover {{ background: {rgba(t['text'], 0.06)}; }}
QToolButton[segment="true"]:checked {{ background: {t['surface']}; border: 1px solid {t['border']}; }}
QCheckBox {{ spacing: 10px; }}
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
    key = f"{dark}/{accent}/{spacing}/{size}"
    if app.property("quillThemeKey") == key:
        return                      # unchanged: re-polishing every widget is slow
    app.setProperty("quillThemeKey", key)
    font = app.font()
    font.setPointSize(size)
    app.setFont(font)
    app.setPalette(palette_for(dark, accent))
    app.setStyleSheet(stylesheet_for(dark, accent, spacing, size))


def apply_theme(app: QApplication, mode: str, accent: str = DEFAULT_ACCENT,
                spacing: str = DEFAULT_SPACING, font_size: int = DEFAULT_FONT_SIZE) -> None:
    """Set the colour scheme, accent and spacing, and apply Quill's look.

    Args:
        app: The running application.
        mode: ``"auto"`` (follow the OS), ``"light"`` or ``"dark"``. Anything
            else is treated as ``"auto"``.
        accent: A key of :data:`ACCENTS`.
        spacing: ``"compact"`` or ``"comfortable"``. Layout margins and gaps
            are applied separately by :func:`apply_spacing`.
        font_size: Base text size in points (the Needs-sorting questions are 3 larger).
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
    _restyle(app)
    if not app.property("quillThemeHooked"):
        app.styleHints().colorSchemeChanged.connect(lambda *_: _restyle(app))
        app.setProperty("quillThemeHooked", True)


def apply_opacity(root: QWidget, percent: int) -> None:
    """Fade a window's whole contents (background, controls and text together) to *percent*.

    *root* is the window's root widget (the one that paints the background).
    Fading the root, rather than the native window or each colour, makes every
    pixel follow the setting uniformly and lets what is *behind* the window (blurred,
    if blur is on) show through. At 100 the effect is removed, so the window is
    completely solid and costs nothing.
    """
    percent = max(0, min(100, int(percent)))
    if percent >= 100:
        if root.graphicsEffect() is not None:
            root.setGraphicsEffect(None)
        return
    effect = root.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(root)
        root.setGraphicsEffect(effect)
    effect.setOpacity(percent / 100)


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
    for layout in layouts:
        layout.setSpacing(d["gap"])
        if isinstance(layout.parent(), QWidget):      # a widget's own layout, not a nested one
            m = d["margin"]
            layout.setContentsMargins(m, m, m, m)
