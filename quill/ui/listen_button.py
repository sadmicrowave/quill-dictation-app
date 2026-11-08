"""The Start / Stop Listening button (the same in the main window and in the Term Helper).

A rounded rectangle of flat glass in the accent colour (the same corner as every other button, so it sits beside the Next Row
button without a second style), three parts from the left:

* a rounded-square **tile** holding the play / stop icon; while listening a green **ring** around it empties as the quiet time runs out;
* the words ("Start Listening", "Stop Listening", or "File not connected" while there is no spreadsheet);
* a darker rounded-rectangle **screen** that takes the rest of the width: a faint grid and a **voice graph** of two sine lines that is flat
  while idle and, while listening, streams from left to right with peaks and troughs that follow the voice, a green glow where
  the newest sound enters, and the count-down number ("7s") at its right end.

Nothing here runs while idle: the graph's frame timer exists only while listening (see :class:`StreamGraph`).
"""

from __future__ import annotations

import math
from collections import deque

import shiboken6
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from quill.ui.icons import make_icon
from quill.ui.theme import FLASH_STYLES

#: The words while no spreadsheet is connected.
NOT_CONNECTED_TEXT = "File not connected"
#: Corner radius (px) of the button, and of the tile and the screen inside it: the app's one button corner.
RADIUS, INNER_RADIUS = 8.0, 6.0
#: The green that says "live".
LIVE_GREEN = "#34C759"


def _mix(a: QColor | str, b: QColor | str, amount: float) -> QColor:
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * amount), round(a.green() + (b.green() - a.green()) * amount),
                  round(a.blue() + (b.blue() - a.blue()) * amount))


def _alpha(color: QColor | str, alpha: float) -> QColor:
    out = QColor(color)
    out.setAlphaF(max(0.0, min(1.0, alpha)))
    return out


def _luminance(color: QColor) -> float:
    return 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()


class StreamGraph(QWidget):
    """The voice graph: a faint grid and two sine lines.

    Idle it is a flat line. While active every frame the newest reading of the voice level enters at the left and what was
    there moves right, so the lines stream from left to right and rise into peaks and troughs when the voice is loud; the oldest
    part fades out at the right. The frame timer runs only while active and visible, so an idle window costs nothing.
    """

    FRAME_MS = 40
    STEP = 2.0                  # pixels between two readings
    TURN = 0.24                 # how far the sine turns between two readings (radians)
    GATE = 0.30                 # readings under this are room noise, not a voice: the lines stay flat for them
    LEAD = 9.0                  # room kept at the left so the green glow is not cut off by the edge
    QUIET = 0.0                 # how tall the lines are with no voice at all (share of the full height): none, a flat line

    def __init__(self) -> None:
        super().__init__()
        self._active = False
        self._target = 0.0                         # the latest voice level (0 to 1) ...
        self._level = 0.0                          # ... and the smoothed level the lines are drawn with
        self._count = 0
        self._samples: deque[tuple[float, float]] = deque()          # (level, turn) of each reading, newest first
        self._line = QColor("#FFFFFF")
        self._idle_line = QColor("#FFFFFF")
        self._grid = QColor("#FFFFFF")
        self._glow = QColor(LIVE_GREEN)
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setMinimumSize(QSize(40, 14))

    @property
    def active(self) -> bool:
        return self._active

    @property
    def level(self) -> float:
        return self._level

    def set_colors(self, line: QColor, idle_line: QColor, grid: QColor) -> None:
        self._line, self._idle_line, self._grid = QColor(line), QColor(idle_line), QColor(grid)
        self.update()

    def set_active(self, active: bool) -> None:
        """Start (streaming) or stop (a flat line)."""
        self._active = active
        self._target = self._level = 0.0
        self._count = 0
        self._samples.clear()
        if active:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_level(self, level: float) -> None:
        """The loudness of the user's voice right now (0 to 1)."""
        level = max(0.0, min(1.0, level))
        self._target = 0.0 if level < self.GATE else (level - self.GATE) / (1.0 - self.GATE)

    def hideEvent(self, event) -> None:                    # noqa: N802 (Qt name): nothing animates out of sight
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:                    # noqa: N802
        super().showEvent(event)
        if self._active:
            self._timer.start()

    def _tick(self) -> None:
        rate = 0.55 if self._target > self._level else 0.18          # quick to rise, slower to fall
        self._level += (self._target - self._level) * rate
        self._target *= 0.85                                          # silence between updates lets it fall away
        shaped = min(1.0, self._level * 1.7) ** 1.35                        # (a curve that keeps a low voice flat and lets a loud one swing wide)
        self._samples.appendleft((shaped, self._count * self.TURN))
        self._count += 1
        room = int((self.width() - self.LEAD) / self.STEP) + 2
        while len(self._samples) > room:
            self._samples.pop()
        self.update()

    def trace(self, offset: float = 0.0, share: float = 1.0) -> list[QPointF]:
        """The points of one line (the main one, or the echo with its own *offset* and *share* of the height)."""
        half = max(self.height() / 2 - 3.0, 1.0)
        cy = self.height() / 2
        points = []
        readings = list(self._samples)
        for i, (_, turn) in enumerate(readings):
            near = readings[max(i - 3, 0):i + 4]
            level = sum(r[0] for r in near) / len(near)               # (neighbours blended: soft arches)
            x = i * self.STEP
            edge = min(1.0, x / 14.0, max(self.width() - self.LEAD - x, 0.0) / 14.0)        # (the ends settle onto the centre line)
            amp = half * share * (self.QUIET + (1.0 - self.QUIET) * level) * edge
            points.append(QPointF(self.LEAD + x, cy + amp * math.sin(turn + offset)))
        return points

    def paintEvent(self, event) -> None:                             # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cy = h / 2
        painter.setPen(QPen(self._grid, 1))
        for k in range(1, 7):                                         # the faint grid: seven columns and the centre line
            x = w * k / 7
            painter.drawLine(QPointF(x, 3), QPointF(x, h - 3))
        painter.drawLine(QPointF(0, cy), QPointF(w, cy))
        if not self._active:
            painter.setPen(QPen(self._idle_line, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(2, cy), QPointF(w - 2, cy))
            painter.end()
            return
        for offset, share, width, alpha, fade in ((1.15, 0.72, 1.5, 0.5, False), (0.0, 1.0, 2.1, 1.0, True)):
            points = self.trace(offset, share)
            if len(points) < 2:
                continue
            path = QPainterPath(points[0])
            for a, b in zip(points[1:], points[2:]):                  # a spline: curves through the mid-points, the readings steer it
                path.quadTo(a, (a + b) / 2)
            path.lineTo(points[-1])
            gradient = QLinearGradient(0, 0, w, 0)
            top = _alpha(self._line, self._line.alphaF() * alpha)
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(0.55, _alpha(top, top.alphaF() * (0.9 if fade else 1.0)))
            gradient.setColorAt(1.0, _alpha(top, top.alphaF() * (0.25 if fade else 0.6)))
            pen = QPen(gradient, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)                             # the green glow where the newest sound enters
        for radius, alpha in ((8.5, 0.10), (6.0, 0.18), (3.6, 0.38)):
            painter.setBrush(_alpha(self._glow, alpha))
            painter.drawEllipse(QPointF(self.LEAD, cy), radius, radius)
        painter.end()


class _Disc(QLabel):
    """The rounded-square tile around the play / stop icon, with the count-down ring around it while listening."""

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fill = QColor(255, 255, 255, 56)
        self.track = QColor(255, 255, 255, 56)
        self.ring: float | None = None                               # share of the quiet time left (None: no ring)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    @staticmethod
    def progress_path(rect: QRectF, radius: float, share: float) -> QPainterPath:
        """The first *share* of the outline of a rounded rectangle, from the top middle clockwise (the ring that empties)."""
        outline = QPainterPath()
        outline.addRoundedRect(rect, radius, radius)
        share = max(0.0, min(1.0, share))
        steps = max(int(120 * share), 2)
        path = QPainterPath()
        for i in range(steps + 1):
            # (a rounded rectangle's path starts at the top left corner's end: shift so that the start is the top middle)
            at = (0.5 * rect.width() / (2 * (rect.width() + rect.height())) + share * i / steps) % 1.0
            point = outline.pointAtPercent(at)
            (path.moveTo if i == 0 else path.lineTo)(point)
        return path

    def paintEvent(self, event) -> None:                             # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.fill)
        tile = QRectF(self.rect()).adjusted(3.5, 3.5, -3.5, -3.5)
        painter.drawRoundedRect(tile, INNER_RADIUS, INNER_RADIUS)
        if self.ring is not None:
            ring = tile.adjusted(-2.0, -2.0, 2.0, 2.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self.track, 2.0))
            painter.drawRoundedRect(ring, INNER_RADIUS + 2, INNER_RADIUS + 2)
            pen = QPen(QColor(LIVE_GREEN), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(self.progress_path(ring, INNER_RADIUS + 2, self.ring))
        painter.end()
        super().paintEvent(event)                                    # the icon on top


class _Screen(QFrame):
    """The darker rounded screen that holds the voice graph and the count-down number."""

    def __init__(self) -> None:
        super().__init__()
        self.fill = QColor(0, 0, 0, 60)
        self.rim = QColor(255, 255, 255, 90)
        self.rim_width = 1.2
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:                             # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8)
        painter.setPen(QPen(self.rim, self.rim_width))
        painter.setBrush(self.fill)
        painter.drawRoundedRect(rect, INNER_RADIUS, INNER_RADIUS)
        painter.end()


class ListenButton(QPushButton):
    """The Start / Stop Listening button. See the module text for how it looks.

    Not checkable (a press is a click); ``isChecked()`` says whether it is listening. The words, the icon, the count-down and
    the graph are children (``text_pill``, ``icon_label``, ``countdown_label``, ``wave``) so the window can reach them.
    """

    HEIGHT, HEIGHT_COMPACT = 48, 42
    #: How long the "no" shake lasts (0 turns it off: tests), how far it swings (pixels), and how long the red blink stays.
    shake_ms = 420
    SHAKE_PX = 7
    ALERT_MS = 700

    def __init__(self, idle_text: str = "Start Listening", live_text: str = "Stop Listening") -> None:
        super().__init__()
        self._idle_text, self._live_text = idle_text, live_text
        self._active = False
        self._compact = False
        self._notice = False
        self._alert = False
        self._count_total = 0                               # the most seconds the count-down has shown since it began
        self.fixed_tip: str | None = None                  # a tooltip that stays whatever the state
        self._colors = ("#1F1E1D", "#FFFFFF", "#7A55C2")          # text, on accent, accent
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("keepMargins", True)
        self.setProperty("listenButton", True)
        self.setProperty("outline", True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.icon_label = _Disc()
        self.text_pill = QLabel()                          # the words
        self.screen = _Screen()
        self.wave = StreamGraph()
        self.countdown_label = QLabel()                    # "7s": the quiet timer counting down
        self.countdown_label.setProperty("countdown", True)
        self.countdown_label.setVisible(False)
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner = QHBoxLayout(self.screen)
        inner.setContentsMargins(14, 0, 10, 0)
        inner.setSpacing(6)
        inner.addWidget(self.wave, 1)
        inner.addWidget(self.countdown_label, 0)
        row = QHBoxLayout(self)
        row.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)
        row.setContentsMargins(6, 0, 12, 0)
        row.setSpacing(16)                                 # (room around the words: after the tile, and before the screen)
        row.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.text_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.screen, 1, Qt.AlignmentFlag.AlignVCenter)
        self._row = row
        for part in (self.icon_label, self.text_pill, self.screen, self.countdown_label, self.wave):
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)       # clicks reach the button
        self.set_active(False)

    # ------------------------------------------------------------------ #

    @property
    def active(self) -> bool:
        return self._active

    def isChecked(self) -> bool:                           # noqa: N802 (Qt name): "on" means listening
        return self._active

    @property
    def notice(self) -> bool:
        """Is the "File not connected" notice showing in place of Start Listening?"""
        return self._notice

    @property
    def notice_text(self) -> str:
        return NOT_CONNECTED_TEXT if self._notice else ""

    @property
    def alerting(self) -> bool:
        """Is the red "no" blink showing?"""
        return self._alert

    def sizeHint(self) -> QSize:                           # noqa: N802 (Qt name)
        return QSize(300, self.HEIGHT_COMPACT if self._compact else self.HEIGHT)

    def minimumSizeHint(self) -> QSize:                    # noqa: N802
        return QSize(0, self.sizeHint().height())

    def set_notice(self, shown: bool, tip: str = "") -> None:
        """While the notice shows, the button says "File not connected" (and *tip* explains it on hover); it can still be pressed."""
        self._notice = shown
        self.fixed_tip = tip if shown and tip else None
        self._show_text()
        self._style()

    def set_active(self, active: bool) -> None:
        """Listening (darker accent, stop icon, streaming graph, ring) or idle (accent, play icon, flat graph)."""
        self._active = active
        if not active:
            self._count_total = 0
            self.icon_label.ring = None
            self.countdown_label.setVisible(False)
        self.wave.set_active(active)
        self.setProperty("accent", active)
        self.setProperty("outline", not active)
        self._show_text()
        self._style()

    def set_countdown(self, seconds: int | None, share: float | None = None) -> None:
        """Show the seconds left, "7s", and the ring that empties with them (None hides both).

        *share* (0 to 1) is how much of the quiet time is left, exactly; with it the ring empties smoothly instead of in whole
        seconds. Without it the ring follows the whole seconds.
        """
        self.countdown_label.setVisible(seconds is not None)
        if seconds is None:
            self._count_total = 0
            self.icon_label.ring = None
        else:
            self._count_total = max(self._count_total, seconds, 1)
            self.countdown_label.setText(f"{seconds}s")
            self.icon_label.ring = max(0.0, min(1.0, share)) if share is not None else seconds / self._count_total
        self.icon_label.update()

    def set_compact(self, compact: bool) -> None:
        """The mini view: the same button with a little less height."""
        self._compact = compact
        self.updateGeometry()
        self._show_text()
        self._style()

    def set_colors(self, text: str, on_accent: str, accent: str) -> None:
        """Redraw for the theme's colours (text, the colour on the accent, the accent)."""
        self._colors = (text, on_accent, accent)
        self._style()

    def set_chip(self, chip: QWidget) -> None:               # (kept so older callers still work: the notice is drawn here now)
        chip.setVisible(False)

    # ------------------------------------------------------------------ #

    def _state(self) -> str:
        return "none" if self._notice and not self._active else ("live" if self._active else "ready")

    def _show_text(self) -> None:
        text = NOT_CONNECTED_TEXT if self._state() == "none" else (self._live_text if self._active else self._idle_text)
        self.text_pill.setText(text)
        self.setToolTip(self.fixed_tip or text)
        self.setAccessibleName(text)
        height = self.HEIGHT_COMPACT if self._compact else self.HEIGHT
        self.icon_label.setFixedSize(height - 10, height - 10)
        self.screen.setFixedHeight(height - 14)                    # (the screen sits inside the capsule, not against its edges)

    def _fills(self) -> dict:
        """Every colour for the state now (the capsule, the disc, the screen, the lines, the words)."""
        text, on_accent, accent = self._colors
        state = self._state()
        if state == "none":
            capsule = _alpha(text, 0.07)
            rim = _alpha(text, 0.16)
            fg = _alpha(text, 0.62)
            disc = _alpha(text, 0.10)
            screen = _alpha(text, 0.07)
            screen_fg = _alpha(text, 0.55)
            screen_rim = _alpha(text, 0.14)
        else:
            capsule = QColor(accent) if state == "ready" else _mix(accent, "#000000", 0.16)
            rim = _alpha("#FFFFFF", 0.30)
            fg = QColor(on_accent)
            disc = _alpha(on_accent, 0.22)
            screen = _mix(accent, "#000000", 0.30)
            screen_fg = QColor("#FFFFFF") if _luminance(screen) < 0.5 else QColor("#1F1E1D")
            screen_rim = _alpha(screen_fg, 0.35)
        return dict(capsule=capsule, rim=rim, fg=fg, disc=disc, screen=screen, screen_fg=screen_fg, screen_rim=screen_rim,
                    state=state)

    def _style(self) -> None:
        """Push the colours to the parts and redraw."""
        f = self._fills()
        state = f["state"]
        label_style = f"color: {f['fg'].name(QColor.NameFormat.HexArgb)}; background: transparent; font-weight: 600;"
        self.text_pill.setStyleSheet(label_style)
        self.countdown_label.setStyleSheet(f"color: {_alpha(f['screen_fg'], 0.6).name(QColor.NameFormat.HexArgb)}; background: transparent; "
                                           f"font-size: 11px; font-weight: 500; font-style: normal;")
        self.icon_label.fill = f["disc"]
        self.icon_label.track = _alpha(f["fg"], 0.25)
        icon = make_icon("stop" if self._active else "play", f["fg"].name(), 14)
        self.icon_label.setPixmap(icon.pixmap(14, 14))
        self.screen.fill = f["screen"]
        self.screen.rim = f["screen_rim"]
        self.screen.rim_width = 1.2
        line = _alpha(f["screen_fg"], 0.95 if state == "live" else 0.55)
        self.wave.set_colors(line, _alpha(f["screen_fg"], 0.55 if state != "none" else 0.45), _alpha(f["screen_fg"], 0.07))
        for part in (self.icon_label, self.screen, self.wave):
            part.update()
        self.update()

    def paintEvent(self, event) -> None:                   # noqa: N802 (Qt name)
        f = self._fills()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = RADIUS
        capsule = QColor(f["capsule"])
        if f["state"] == "none":                                     # (a see-through capsule: hover and press deepen its tint a little)
            if self.isDown():
                capsule.setAlphaF(min(1.0, capsule.alphaF() + 0.10))
            elif self.underMouse():
                capsule.setAlphaF(min(1.0, capsule.alphaF() + 0.05))
        elif self.isDown():
            capsule = _mix(capsule, "#000000", 0.12)
        elif self.underMouse():
            capsule = _mix(capsule, "#FFFFFF", 0.07)
        painter.setPen(QPen(f["rim"], 1.2) if f["state"] == "none" else Qt.PenStyle.NoPen)
        painter.setBrush(capsule)
        painter.drawRoundedRect(rect, radius, radius)
        if f["state"] != "none":                                     # the flat glass: a pale film on the top half, a thin light rim
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            painter.setClipPath(clip)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 15))
            painter.drawRect(QRectF(rect.left(), rect.center().y(), rect.width(), rect.height() / 2))
            painter.setBrush(QColor(255, 255, 255, 33))
            painter.drawRect(QRectF(rect.left(), rect.top(), rect.width(), rect.height() / 2))
            painter.restore()
            painter.setPen(QPen(f["rim"], 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)
        if self._alert:                                              # the red "no": a red tint and rim
            border, _ = FLASH_STYLES["error"]
            painter.setPen(QPen(QColor(border), 1.6))
            painter.setBrush(QColor(255, 59, 48, 46))
            painter.drawRoundedRect(rect, radius, radius)
        painter.end()

    def enterEvent(self, event) -> None:                   # noqa: N802 (Qt name)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:                   # noqa: N802
        self.update()
        super().leaveEvent(event)

    def alert(self) -> None:
        """Say "no" without words: the button shakes side to side and blinks red, once. Used when Start is pressed and
        nothing can start (no spreadsheet is connected); the Files panel opening is then the way out."""
        self._alert = True
        self.update()
        QTimer.singleShot(self.ALERT_MS, self._clear_alert)
        if self.shake_ms <= 0 or not self.isVisible() or getattr(self, "_shaking", False):
            return
        self._shaking = True
        home = self.pos()
        swing = QVariantAnimation(self)
        swing.setDuration(self.shake_ms)
        swing.setStartValue(0.0)
        swing.setEndValue(1.0)

        def step(t: float) -> None:                                  # a few quick swings that die away
            self.move(home.x() + round(self.SHAKE_PX * math.sin(t * math.pi * 5) * (1 - t)), home.y())

        def done() -> None:
            self._shaking = False
            if shiboken6.isValid(self):
                self.move(home)
                if self.parentWidget() is not None and self.parentWidget().layout() is not None:
                    self.parentWidget().layout().activate()          # (the layout is the authority on where it sits)
        swing.valueChanged.connect(step)
        swing.finished.connect(done)
        swing.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _clear_alert(self) -> None:
        if shiboken6.isValid(self):
            self._alert = False
            self.update()
