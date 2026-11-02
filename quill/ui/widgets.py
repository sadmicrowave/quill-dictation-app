"""Small reusable widgets."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QWidget,
)

from quill.ui.icons import make_icon

#: Height of a pill notice ("File stream not connected", "Start Listening").
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


class WaveMeter(QWidget):
    """The sound lines of the app icon: still and muted while idle, green and moving while listening.

    The animation is a loop (each line rises and falls a little after its neighbour) driven by a timer that
    only runs while the widget is :meth:`set_active`.
    """

    HEIGHTS = (8, 16, 24, 34, 22, 14, 8)         # the app icon's lines (relative heights)
    FRAME_MS = 40
    SPEED = 0.10                                 # radians per frame while quiet
    QUIET = 0.30                                 # how tall the short stack is with no voice (share of the full height)

    def __init__(self) -> None:
        super().__init__()
        self._active = False
        self._phase = 0.0
        self._target = 0.0                       # the latest voice level (0 to 1) ...
        self._level = 0.0                        # ... and the smoothed level the lines are drawn with
        self._idle: QColor | None = None                 # None: the muted text colour of the palette
        self._live = QColor("#34c759")
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(QSize(34, 22))

    @property
    def active(self) -> bool:
        return self._active

    def set_colors(self, idle: str, live: str) -> None:
        """*idle* is the muted still colour, *live* the colour while listening."""
        self._idle, self._live = QColor(idle), QColor(live)
        self.update()

    def _resting_color(self) -> QColor:
        if self._idle is not None:
            return self._idle
        muted = QColor(self.palette().buttonText().color())
        muted.setAlpha(110)
        return muted

    def set_active(self, active: bool) -> None:
        """Start (green, moving) or stop (muted, still)."""
        self._active = active
        self._phase = 0.0
        self._target = self._level = 0.0
        if active:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_level(self, level: float) -> None:
        """The loudness of the user's voice right now (0 to 1): the lines rise and speed up with it."""
        self._target = max(0.0, min(1.0, level))

    @property
    def level(self) -> float:
        return self._level

    def hideEvent(self, event) -> None:                    # noqa: N802 (Qt name): nothing animates out of sight
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:                    # noqa: N802
        super().showEvent(event)
        if self._active:
            self._timer.start()

    def _tick(self) -> None:
        rate = 0.55 if self._target > self._level else 0.18         # quick to rise, slower to fall
        self._level += (self._target - self._level) * rate
        self._target *= 0.85                                         # silence between updates lets it fall away
        self._phase = (self._phase + self.SPEED + 0.22 * self._level) % (2 * math.pi)
        self.update()

    def bar_heights(self) -> list[float]:
        """Each line's height as a share of the widget's (1 = full)."""
        top = max(self.HEIGHTS)
        shares = []
        for i, h in enumerate(self.HEIGHTS):
            base = h / top
            if self._active:
                height = self.QUIET + (1.0 - self.QUIET) * self._level          # short stack with no voice, up to full
                base *= height * (0.7 + 0.3 * math.sin(self._phase - i * 0.8))
            shares.append(max(base, 0.16))
        return shares

    def paintEvent(self, event) -> None:                             # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._live if self._active else self._resting_color())
        count, width = len(self.HEIGHTS), 2.0
        step = (self.width() - width) / (count - 1)
        for i, share in enumerate(self.bar_heights()):
            h = share * (self.height() - 2)
            painter.drawRoundedRect(QRectF(i * step, (self.height() - h) / 2, width, h), width / 2, width / 2)
        painter.end()


class ListenButton(QPushButton):
    """The Start / Stop Listening button, the same in the main window and in the Term Helper.

    From the left: an outlined pill holding the play / stop icon and "Start Listening" (or "Stop Listening"),
    or, instead of it while there is no spreadsheet, a notice chip; then the "7s" countdown, outside the
    pill; and the sound lines at the right edge. The button is outlined in the accent colour while idle and filled
    with it while listening.
    """

    def __init__(self, idle_text: str = "Start Listening", live_text: str = "Stop Listening") -> None:
        super().__init__()
        self._idle_text, self._live_text = idle_text, live_text
        self._active = False
        self._compact = False
        self._notice = False
        self.fixed_tip: str | None = None                  # a tooltip that stays whatever the state
        self._colors = ("#1F1E1D", "#FFFFFF", "#7A55C2")          # text, on accent, accent
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("keepMargins", True)
        self.setProperty("outline", True)
        self.icon_label = QLabel()
        self.text_pill = QLabel()                          # the words inside the pill
        self.pill = QFrame()                               # border only, no fill: [icon  Start Listening]
        self.pill.setProperty("listenPill", True)
        self.pill.setProperty("keepMargins", True)
        self.pill.setFixedHeight(CHIP_HEIGHT + 2)
        inside = QHBoxLayout(self.pill)
        inside.setContentsMargins(9, 0, 13, 0)
        inside.setSpacing(6)
        inside.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        inside.addWidget(self.text_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.countdown_label = QLabel()                    # "7s": the quiet timer counting down
        self.countdown_label.setProperty("countdown", True)
        self.countdown_label.setVisible(False)
        self.wave = WaveMeter()
        self._inner = QHBoxLayout(self)
        self._inner.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)   # never wider than the room it is given
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._inner.setContentsMargins(10, 0, 14, 0)
        self._inner.setSpacing(10)
        self._inner.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self._inner.addWidget(self.countdown_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._inner.addStretch(1)
        self._inner.addWidget(self.wave, 0, Qt.AlignmentFlag.AlignVCenter)
        for part in (self.pill, self.countdown_label, self.wave):
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)       # clicks reach the button
        self.set_active(False)

    @property
    def active(self) -> bool:
        return self._active

    def isChecked(self) -> bool:                           # noqa: N802 (Qt name): "on" means listening
        return self._active

    def set_chip(self, chip: QWidget) -> None:
        """Seat a notice chip at the left of the button, where the pill goes (shown or hidden by the caller)."""
        chip.setParent(self)
        chip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._inner.insertWidget(1, chip, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_notice(self, shown: bool, tip: str = "") -> None:
        """While a notice chip is shown it takes the pill's place, and *tip* explains it on hover."""
        self._notice = shown
        self.fixed_tip = tip if shown and tip else None
        self._show_text()

    def set_active(self, active: bool) -> None:
        """Listening (filled, stop icon, green moving lines) or idle (outlined, play icon, still muted lines)."""
        self._active = active
        self.wave.set_active(active)
        self.setProperty("accent", active)
        self.setProperty("outline", not active)
        for widget in (self, self.pill, self.text_pill, self.countdown_label):   # descendants of the button's state
            self._repolish(widget)
        self._show_text()
        self._draw_icon()

    def set_countdown(self, seconds: int | None) -> None:
        """Show the seconds left, "7s" (None hides it)."""
        self.countdown_label.setVisible(seconds is not None)
        if seconds is not None:
            self.countdown_label.setText(f"{seconds}s")

    def set_compact(self, compact: bool) -> None:
        """The mini view keeps the whole pill (icon, words, outline): only the room around it is tighter."""
        self._compact = compact
        self.pill.setProperty("compact", compact)
        self._repolish(self.pill)
        self._show_text()

    def set_colors(self, text: str, on_accent: str, accent: str) -> None:
        """Redraw for the theme's colours: the lines rest in a muted *text* colour, the icon is *accent* or *on_accent*."""
        self._colors = (text, on_accent, accent)
        muted = QColor(text)
        muted.setAlpha(110)
        self.wave.set_colors(muted.name(QColor.NameFormat.HexArgb), "#34c759")
        self._draw_icon()

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)

    def _show_text(self) -> None:
        text = self._live_text if self._active else self._idle_text
        self.text_pill.setText(text)
        self.text_pill.setVisible(True)
        self.pill.setVisible(not self._notice)
        self.setToolTip(self.fixed_tip or text)
        self.setAccessibleName(text)

    def _draw_icon(self) -> None:
        _, on_accent, accent = self._colors
        self.icon_label.setPixmap(make_icon("stop" if self._active else "play", on_accent if self._active else accent,
                                            14).pixmap(14, 14))


#: Room (px) the tool tip's border and padding add around its text (see ``QToolTip`` in theme.py).
TOOLTIP_PADDING = 12
#: Gap (px) between the pointer and the tool tip below it.
TOOLTIP_DROP = 18


class CenteredToolTips(QObject):
    """Shows every tool tip centred on the pointer (the system puts its left edge at the pointer).

    One application-level event filter; plain-text tips only (a rich-text tip keeps the system's placement).
    """

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
        width = max((metrics.horizontalAdvance(line) for line in text.split("\n")), default=0) + TOOLTIP_PADDING
        return QPoint(pointer.x() - width // 2, pointer.y() + TOOLTIP_DROP)

    def eventFilter(self, obj, event) -> bool:                      # noqa: N802 (Qt name)
        if event.type() != QEvent.Type.ToolTip:
            return False
        text = self.tip_for(obj, event.pos())
        if not text or ("<" in text and ">" in text):                       # (rich text keeps the system placement)
            return False
        QToolTip.showText(self.position(event.globalPos(), text), text, obj)
        return True


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


class HeadingToggle(QLabel):
    """A clickable heading ("Log  v"): plain text that starts exactly at the content's left edge.

    A QToolButton centres its text inside extra margins, which pushed these headings about 8 px in
    from the edge everything else lines up with; a label has none.
    """

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("headingToggle", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMargin(0)
        self.setContentsMargins(0, 0, 0, 0)

    def click(self) -> None:
        """Act as if the heading had been clicked (also used by tests)."""
        self.clicked.emit()

    def mousePressEvent(self, event) -> None:                    # noqa: N802 (Qt name)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


#: The look of spoken words and commands wherever they appear in text: a pill in the app's own font and size.
PILL_STYLE = "background-color:#5E4A99; color:#FFFFFF"


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
    """The tooltip of the "File stream not connected" chip, as short lines with bold, italics and icons.

    Spaced out (line height, letter spacing) so it can be taken in at a glance rather than read as a paragraph.
    A plain *hint* replaces the default explanation.
    """
    import html
    if hint:
        body = "<br>".join(html.escape(line) for line in wrap_tip(hint).splitlines())
        return f'<div style="line-height:150%; letter-spacing:0.3px">{body}</div>'
    return (
        '<div style="line-height:155%; letter-spacing:0.35px">'
        '<b><span style="color:#E0A030">⚠&nbsp;&nbsp;Not connected</span></b><br>'
        'Quill has no spreadsheet to <i>read lists from</i><br>or <i>write rows to</i>.'
        '<br><br><b>Connect one:</b><br>'
        '📗&nbsp;&nbsp;<b>Spreadsheet program</b>: open a workbook,<br>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;and Quill<br>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;attaches within a few seconds<br>'
        '📁&nbsp;&nbsp;<b>File ▸ Open Spreadsheet File…</b><br>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;and pick an <i>.xlsx</i> or <i>.csv</i> file'
        '<br><br>▶&nbsp;&nbsp;Then press <b>Start</b> to listen.'
        '</div>')


def wrap_tip(text: str, width: int = 52) -> str:
    """*text* with its lines wrapped at *width* characters, so a tooltip stays a readable block, not a long strip."""
    import textwrap
    return "\n".join(textwrap.fill(line, width) if line else "" for line in text.splitlines())
