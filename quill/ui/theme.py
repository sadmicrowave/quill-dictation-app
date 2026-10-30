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

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_SCHEMES = {
    "auto": Qt.ColorScheme.Unknown,   # follow the operating system
    "light": Qt.ColorScheme.Light,
    "dark": Qt.ColorScheme.Dark,
}

#: Colour tokens per scheme. Warm neutrals with one accent.
TOKENS = {
    "light": dict(bg="#FAF9F5", surface="#FFFFFF", hover="#F1EFE8", pressed="#E8E5DC",
                  border="#E3E0D6", text="#1F1E1D", muted="#6F6D66", accent="#C9623F",
                  accent_hover="#B5552F", on_accent="#FFFFFF", disabled="#B4B1A8"),
    "dark":  dict(bg="#262624", surface="#30302E", hover="#3A3A37", pressed="#444441",
                  border="#44443F", text="#ECEBE6", muted="#A19F98", accent="#D97757",
                  accent_hover="#E58A6B", on_accent="#1F1E1D", disabled="#6B6A64"),
}


def palette_for(dark: bool) -> QPalette:
    """A palette built from the tokens (so native-drawn bits match the style sheet)."""
    t = TOKENS["dark" if dark else "light"]
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


def stylesheet_for(dark: bool) -> str:
    """The style sheet: rounded controls, hairline borders, an accent for the main action."""
    t = TOKENS["dark" if dark else "light"]
    return f"""
QMainWindow, QDialog {{ background: {t['bg']}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
           border-radius: 6px; padding: 4px 8px; }}

QPushButton {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
              border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['pressed']}; }}
QPushButton:disabled {{ color: {t['disabled']}; background: {t['bg']}; }}
QPushButton:checked, QPushButton[accent="true"] {{ background: {t['accent']}; color: {t['on_accent']};
              border-color: {t['accent']}; font-weight: 600; }}
QPushButton:checked:hover, QPushButton[accent="true"]:hover {{ background: {t['accent_hover']}; }}
QPushButton::menu-indicator {{ width: 0; }}

QLineEdit, QSpinBox, QComboBox {{ background: {t['surface']}; color: {t['text']};
              border: 1px solid {t['border']}; border-radius: 8px; padding: 5px 9px;
              selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; }}
QComboBox:disabled, QSpinBox:disabled {{ color: {t['disabled']}; background: {t['bg']}; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
              border-radius: 8px; selection-background-color: {t['accent']};
              selection-color: {t['on_accent']}; outline: none; padding: 4px; }}

QPlainTextEdit, QTextEdit, QTableWidget {{ background: {t['surface']}; color: {t['text']};
              border: 1px solid {t['border']}; border-radius: 10px; padding: 4px;
              gridline-color: {t['border']}; selection-background-color: {t['accent']};
              selection-color: {t['on_accent']}; }}
QHeaderView::section {{ background: {t['bg']}; color: {t['muted']}; border: none;
              border-bottom: 1px solid {t['border']}; padding: 6px; font-weight: 600; }}
QTableWidget::item {{ padding: 3px; }}

QFrame#termRow {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
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
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['accent']}; color: {t['on_accent']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 8px; }}

QCheckBox {{ spacing: 8px; }}
"""


def _is_dark(app: QApplication) -> bool:
    """True if the dark look applies: chosen explicitly, or the OS is dark in auto mode."""
    mode = app.property("quillThemeMode")
    if mode in ("light", "dark"):
        return mode == "dark"
    return app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def _restyle(app: QApplication) -> None:
    dark = _is_dark(app)
    if app.property("quillThemeDark") is dark:
        return                      # unchanged: re-polishing every widget is slow
    app.setProperty("quillThemeDark", dark)
    app.setPalette(palette_for(dark))
    app.setStyleSheet(stylesheet_for(dark))


def apply_theme(app: QApplication, mode: str) -> None:
    """Set the colour scheme and apply Quill's look.

    Args:
        app: The running application.
        mode: ``"auto"`` (follow the OS), ``"light"`` or ``"dark"``. Anything
            else is treated as ``"auto"``.
    """
    if not app.property("quillFusion"):      # once: re-setting the style re-polishes everything
        app.setStyle("Fusion")
        app.setProperty("quillFusion", True)
    app.styleHints().setColorScheme(_SCHEMES.get(mode, Qt.ColorScheme.Unknown))
    app.setProperty("quillThemeMode", mode)
    _restyle(app)
    if not app.property("quillThemeHooked"):
        app.styleHints().colorSchemeChanged.connect(lambda *_: _restyle(app))
        app.setProperty("quillThemeHooked", True)
