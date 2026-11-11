"""Small reusable widgets."""

from __future__ import annotations


from typing import Callable

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QWidget,
)

from quill.ui.icons import make_icon
from quill.ui.listen_button import ListenButton
from quill.ui.theme import PILL_BG, PILL_FG

#: Height of a pill notice ("File not connected", "Start Listening").
CHIP_HEIGHT = 22

#: Lines of the full text shown in a tooltip before "…and n more".
TOOLTIP_LINES = 40


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with an ellipsis to fit its width.

    However much text it is given it stays one line high; the full text is kept
    in :attr:`full_text` and the tooltip.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        self.setText(text)

    def setText(self, text: str) -> None:                       # noqa: N802 (Qt name)
        self.full_text = text
        self._elide()

    def setFullText(self, text: str, tooltip: str | None = None) -> None:   # noqa: N802
        """Show *text* shortened to fit; *tooltip* (default: the text) has all of it."""
        self.setToolTip(tooltip if tooltip is not None else text)
        self.setText(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self.full_text, Qt.TextElideMode.ElideRight,
                                           max(self.width(), 40)))


def tooltip_lines(items: list[tuple[str, str]], limit: int = TOOLTIP_LINES) -> str:
    """``"Column: value"`` lines for a tooltip, capped with a count of what was left out."""
    lines = [f"{key}: {value}" for key, value in items[:limit]]
    if len(items) > limit:
        lines.append(f"…and {len(items) - limit} more")
    return "\n".join(lines)


class ResizeGrip(QWidget):
    """A thin strip at the bottom edge of a box that is dragged up or down to resize it (vertically only).

    ``dragged`` carries how far (px) the pointer moved since the last step: positive is down.
    """

    dragged = Signal(int)
    released = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Drag up or down to resize.")
        self.setFixedHeight(8)
        self._last: int | None = None
        self._ink = QColor("#888")
        #: Where (x, in this strip) the middle dot sits: asked every time it is drawn. None: the middle of the strip.
        self.centre_provider: Callable[[], float] | None = None

    def set_color(self, color: str) -> None:
        self._ink = QColor(color)
        self.update()

    def centre(self) -> float:
        """The x of the middle dot: where :attr:`centre_provider` says (the box's divider), else the middle of the strip."""
        if self.centre_provider is not None:
            try:
                return float(self.centre_provider())
            except Exception:
                pass
        return self.width() / 2

    def mousePressEvent(self, event) -> None:                       # noqa: N802 (Qt name)
        self._last = int(event.globalPosition().y())

    def mouseMoveEvent(self, event) -> None:                        # noqa: N802 (Qt name)
        if self._last is not None:
            y = int(event.globalPosition().y())
            if y != self._last:
                step, self._last = y - self._last, y
                self.dragged.emit(step)

    def mouseReleaseEvent(self, event) -> None:                     # noqa: N802 (Qt name)
        if self._last is not None:
            self._last = None
            self.released.emit()

    def paintEvent(self, event) -> None:                            # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = QColor(self._ink)
        ink.setAlpha(150 if self.underMouse() else 70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        centre = self.centre()
        for offset in (-8, 0, 8):                                     # three small dots, the usual "drag here" mark
            painter.drawEllipse(QRectF(centre + offset - 1.5, self.height() - 4.5, 3, 3))
        painter.end()

    def enterEvent(self, event) -> None:                            # noqa: N802 (Qt name)
        self.update()

    def leaveEvent(self, event) -> None:                            # noqa: N802 (Qt name)
        self.update()


#: Room (px) the tool tip's padding and border add around its text, side to side and top to bottom.
TOOLTIP_PAD_X, TOOLTIP_PAD_Y = 8, 4
TOOLTIP_PADDING = 2 * TOOLTIP_PAD_X + 2
#: Gap (px) between the pointer and the tool tip below it.
TOOLTIP_DROP = 18
#: Seconds a tool tip stays up when the pointer does not move away.
TOOLTIP_SECONDS = 8
#: The widest a tip's text may be (pt); longer lines are wrapped at word breaks, so a tip never stretches across the desktop.
TOOLTIP_MAX_TEXT = 300


class TipWindow(QWidget):
    """A tool tip drawn by hand: a rounded, lighter-grey card (the system's tips are square-cornered and cannot be styled)."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._fill, self._edge, self._ink = QColor("#555"), QColor("#777"), QColor("#fff")

    def set_look(self, fill: str, edge: str, ink: str) -> None:
        self._fill, self._edge, self._ink = QColor(fill), QColor(edge), QColor(ink)

    def set_text(self, text: str) -> QSize:
        """Show *text* (lines separated by newlines) and return the size the tip needs."""
        metrics = QFontMetrics(QToolTip.font())
        text = fit_tip(text, metrics)
        self._text = text
        lines = text.split("\n")
        size = QSize(max(metrics.horizontalAdvance(line) for line in lines) + TOOLTIP_PADDING,
                     metrics.lineSpacing() * len(lines) + 2 * TOOLTIP_PAD_Y + 2)
        self.resize(size)
        self.update()
        return size

    def paintEvent(self, event) -> None:                             # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self._fill)
        painter.setPen(self._edge)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        painter.setPen(self._ink)
        painter.setFont(QToolTip.font())
        painter.drawText(self.rect().adjusted(TOOLTIP_PAD_X + 1, TOOLTIP_PAD_Y + 1, -TOOLTIP_PAD_X, -TOOLTIP_PAD_Y),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._text)
        painter.end()


def fit_tip(text: str, metrics: QFontMetrics | None = None, limit: int = TOOLTIP_MAX_TEXT) -> str:
    """*text* with every line wrapped at word breaks so none is wider than *limit* (an unbroken word stays whole)."""
    metrics = metrics or QFontMetrics(QToolTip.font())
    wrapped: list[str] = []
    for line in text.split("\n"):
        current = ""
        for word in line.split(" "):
            trial = f"{current} {word}" if current else word
            if current and metrics.horizontalAdvance(trial) > limit:
                wrapped.append(current)
                current = word
            else:
                current = trial
        wrapped.append(current)
    return "\n".join(wrapped)


class CenteredToolTips(QObject):
    """Shows every tool tip centred on the pointer, as a rounded card (the system puts the tip's left edge at the pointer
    and draws it square).

    One application-level event filter; plain-text tips only (a rich-text tip keeps the system's look and placement).
    The tip goes away when the pointer leaves, on a click, a key or the wheel, when the window is deactivated, or
    after :data:`TOOLTIP_SECONDS`.
    """

    _HIDE_ON = (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel,
                QEvent.Type.WindowDeactivate, QEvent.Type.Hide)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window: TipWindow | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(TOOLTIP_SECONDS * 1000)
        self._timer.timeout.connect(self._hide)

    @property
    def window(self) -> TipWindow:
        """The tip's window, made on first use (and again if the application's windows were all closed and deleted)."""
        if self._window is None or not shiboken6.isValid(self._window):
            self._window = TipWindow()
        return self._window

    def _hide(self) -> None:
        if self._window is not None and shiboken6.isValid(self._window):
            self._window.hide()

    @staticmethod
    def tip_for(obj, pos) -> str:
        """The tool tip text *obj* would show at *pos* ("" when none), including the items of a list."""
        parent = obj.parentWidget() if isinstance(obj, QWidget) else None
        if isinstance(parent, QAbstractItemView) and obj is parent.viewport():
            return str(parent.indexAt(pos).data(Qt.ItemDataRole.ToolTipRole) or "")
        return obj.toolTip() if isinstance(obj, QWidget) else ""

    @staticmethod
    def position(pointer: QPoint, text: str) -> QPoint:
        """Where the tip's top-left goes so it is centred on *pointer* (just below it)."""
        metrics = QFontMetrics(QToolTip.font())
        width = max((metrics.horizontalAdvance(line) for line in fit_tip(text, metrics).split("\n")), default=0) + TOOLTIP_PADDING
        return QPoint(pointer.x() - width // 2, pointer.y() + TOOLTIP_DROP)

    def show_tip(self, pointer: QPoint, text: str) -> None:
        """Draw *text* centred on *pointer*, kept on the screen."""
        from quill.ui.theme import colors_for, is_dark, mix
        app = QApplication.instance()
        dark = is_dark(app)
        t = colors_for(dark, str(app.property("quillAccent") or "#7A55C2"))
        fill = mix(t["surface"], t["text"], 0.26 if dark else 0.08)             # lighter than the window, in both themes
        self.window.set_look(fill, mix(fill, t["text"], 0.22), t["text"])
        size = self.window.set_text(text)
        spot = self.position(pointer, text)
        screen = app.screenAt(pointer)
        if screen is not None:
            room = screen.availableGeometry()
            spot.setX(max(room.left() + 4, min(spot.x(), room.right() - size.width() - 4)))
            if spot.y() + size.height() > room.bottom():
                spot.setY(pointer.y() - size.height() - 8)                      # no room below: above the pointer
        self.window.move(spot)
        self.window.show()
        self._timer.start()

    def eventFilter(self, obj, event) -> bool:                      # noqa: N802 (Qt name)
        kind = event.type()
        if kind == QEvent.Type.ToolTip:
            text = self.tip_for(obj, event.pos())
            if not text or ("<" in text and ">" in text):                       # (rich text keeps the system's tip)
                return False
            self.show_tip(event.globalPos(), text)
            return True
        if kind in self._HIDE_ON and self._window is not None and shiboken6.isValid(self._window) \
                and self._window.isVisible() and obj is not self._window:
            self._window.hide()
        return False


class PopupClickThrough(QObject):
    """One click on a Start / Stop Listening button works even while a drop-down is open.

    An open drop-down list grabs the mouse, so the first click outside it only closes it and the click is
    lost. Here, a click that lands on a :class:`ListenButton` while a popup is open closes the popup and presses
    the button as well.
    """

    def eventFilter(self, obj, event) -> bool:                      # noqa: N802 (Qt name)
        if event.type() != QEvent.Type.MouseButtonPress or event.button() != Qt.MouseButton.LeftButton:
            return False
        popup = QApplication.activePopupWidget()
        if popup is None:
            return False
        target = QApplication.widgetAt(event.globalPosition().toPoint())
        while target is not None and not isinstance(target, ListenButton):
            target = target.parentWidget()
        if target is None or not target.isEnabled():
            return False
        popup.close()
        QTimer.singleShot(0, target.click)
        return True


class Pill(QLabel):
    """A count drawn as a fully rounded badge, inline with the text around it.

    Painted by hand (not with a style sheet) so the rounding is identical on
    every platform and theme.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.fill = QColor("#FFFFFF")
        self.ink = QColor("#7A55C2")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        font = self.font()
        font.setBold(True)
        self.setFont(font)

    def set_colors(self, fill: str, ink: str) -> None:
        """Badge background and number colour (``"#RRGGBB"``)."""
        self.fill, self.ink = QColor(fill), QColor(ink)
        self.update()

    def sizeHint(self):                                          # noqa: N802 (Qt name)
        metrics = self.fontMetrics()
        height = metrics.height() + 6
        return super().sizeHint().expandedTo(self._size(max(height, metrics.horizontalAdvance(self.text()) + 18), height))

    def minimumSizeHint(self):                                   # noqa: N802
        return self.sizeHint()                                  # never squeezed below its natural size

    @staticmethod
    def _size(width: int, height: int):
        from PySide6.QtCore import QSize
        return QSize(width, height)

    def changeEvent(self, event) -> None:                        # noqa: N802
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.updateGeometry()                               # a style sheet may change the font after the first hint
        super().changeEvent(event)

    def paintEvent(self, event) -> None:                         # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())                              # the whole widget is the pill, so it can never be clipped
        radius = min(rect.height(), rect.width()) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.fill)
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(self.ink)
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()


class FooterButton(QPushButton):
    """An icon button of the window's footer. All of them are the same size; one that is *on* (its panel is open) is drawn
    selected, with the same muted fill as the title bar's buttons, and goes back to the plain look when it is off.

    Args:
        icon_name: The icon (see :mod:`quill.ui.icons`).
        tip: What it does; the words are kept off the button, so the footer can hold several.
        checkable: True for a button that stays selected while its panel is open; False for one that only acts when pressed.
        idle_opacity: How strongly the icon is drawn while the button is off (1 = full); it is drawn in full while selected.
    """

    SIZE = (30, 22)
    ICON = 14

    def __init__(self, icon_name: str, tip: str = "", checkable: bool = True, idle_opacity: float = 1.0) -> None:
        super().__init__()
        self._icon_name = icon_name
        self._idle_opacity = idle_opacity
        self._colors = ("#1F1E1D", "#FFFFFF")                         # icon colour plain, and while selected (on the accent)
        self.setProperty("footerButton", True)
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(*self.SIZE)
        self.setIconSize(QSize(self.ICON, self.ICON))
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.toggled.connect(lambda _: self._draw())
        self._draw()

    def set_colors(self, plain: str, selected: str) -> None:
        self._colors = (plain, selected)
        self._draw()

    def _draw(self) -> None:
        on = self.isChecked()
        icon = make_icon(self._icon_name, self._colors[1] if on else self._colors[0], self.ICON)
        if not on and self._idle_opacity < 1.0:
            pixmap = icon.pixmap(self.ICON, self.ICON)
            faded = QPixmap(pixmap.size())
            faded.setDevicePixelRatio(pixmap.devicePixelRatio())      # (before painting: else the icon is drawn at half size in a corner)
            faded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(faded)
            painter.setOpacity(self._idle_opacity)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            icon = QIcon(faded)
        self.setIcon(icon)


#: The look of spoken words and commands wherever they appear in text: a pill in the app's own font and size.
PILL_STYLE = f"background-color:{PILL_BG}; color:{PILL_FG}"


def pill(text: str) -> str:
    """*text* as an inline code pill in rich text (``yes``, ``ignore``, a spoken word)."""
    import html
    return f'<span style="{PILL_STYLE}">&nbsp;{html.escape(text)}&nbsp;</span>'


def pillify(text: str) -> str:
    """Rich text from plain *text* in which every ‘quoted’ part (what was heard or answered) becomes a pill."""
    import html
    import re
    parts = re.split(r"‘([^’]*)’", text)
    return "".join(pill(part) if i % 2 else html.escape(part) for i, part in enumerate(parts))


def connection_tip(hint: str | None = None) -> str:
    """The tooltip of the "File not connected" pill: plain lines, like every other tooltip in the app (no markup, no
    symbols, so it is drawn by the same tip as everything else). A *hint* replaces the default explanation."""
    if hint:
        return wrap_tip(hint)
    return "Not connected\nQuill has no spreadsheet to read lists from or write rows to."


def wrap_tip(text: str, width: int = 52) -> str:
    """*text* with its lines wrapped at *width* characters, so a tooltip stays a readable block, not a long strip."""
    import textwrap
    return "\n".join(textwrap.fill(line, width) if line else "" for line in text.splitlines())
