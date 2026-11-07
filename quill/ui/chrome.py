"""Window chrome: make each OS's title bar match Quill's theme.

"Chrome" is the frame around a window's content: the title bar, its buttons
and the border. Quill keeps the operating system's own frame (so dragging,
snapping and accessibility behave natively) and only tints it:

  * **Windows 11**: a dark title bar when the dark theme is on, the title bar
    and border painted in the theme's colours (so it reads as one surface with the
    content) and rounded corners. Uses the DWM API through ``ctypes``.
  * **macOS**: a transparent title bar that takes the window's background
    colour, and the light/dark window appearance. Uses PyObjC (``AppKit``).

Both are cosmetic and best-effort: an old Windows build, a missing PyObjC or any
error simply leaves the standard frame, and nothing here can break the app.
The platform calls are injectable so the logic is testable on any machine.
"""

from __future__ import annotations

import shiboken6
from quill import platforms
from quill.ui import glass
from PySide6.QtCore import QEvent, QObject, QTimer
import contextlib
import sys
from typing import Callable

def apply_chrome(widget, dark: bool, colors: dict[str, str], platform: str | None = None,
                 opacity: int = 100, blur: int = 0) -> str | None:
    """Tint *widget*'s native title bar to match the theme.

    Args:
        widget: A top-level QWidget (its native window is created if needed).
        dark: Whether the dark theme is active.
        colors: The theme colours (``bg``, ``text``, ``border``).
        opacity: Window opacity in percent (macOS: lets the window be see-through).
        blur: Blur strength 0 to 100 (macOS vibrancy, Windows 11 acrylic; 0 = off).
        platform: Override ``sys.platform`` (tests).

    Returns:
        ``"windows"`` or ``"macos"`` when something was applied, else None.
    """
    platform = platform or sys.platform
    try:
        if not _native_platform(platform):
            return None      # headless / offscreen: winId() is not a real OS window
        handle = int(widget.winId())
        if platform == "darwin":
            if not mac_chrome(handle, dark, colors, opacity=opacity, blur=blur):
                return None
            plain_title(widget)
            return "macos"
        apply = platforms.offered(platform, "apply_chrome")          # (Windows: its own provider)
        if apply is not None:
            return "windows" if apply(handle, dark, colors, blur=blur) else None
    except Exception:
        return None
    return None


def no_window_shadow(widget, platform: str | None = None) -> bool:
    """Take the operating system's shadow off a (macOS) window, so a rounded, transparent one has no square edge."""
    platform = platform or sys.platform
    try:
        if platform != "darwin" or not _native_platform(platform):
            return False
        import AppKit
        import objc
        window = objc.objc_object(c_void_p=int(widget.winId())).window()
        if window is None:
            return False
        window.setHasShadow_(False)
        window.setOpaque_(False)
        window.setBackgroundColor_(AppKit.NSColor.clearColor())
        return True
    except Exception:
        return False


_TITLE_ID = "quillWindowTitle"
_RULE_ID = "quillBarRule"
#: The size (pt) of the window title and of the side panel's title in the title bar. Fixed: no setting changes it.
TITLE_POINTS = 14


class _TitleFilter(QObject):
    """Re-applies the plain title whenever its window is shown (the native window may be rebuilt on show), and
    keeps it centred in the room the side panel leaves while the window is resized."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            _redraw_lights(obj)
            if getattr(obj, "_quill_title_inset", 0):
                set_title_inset(obj, obj._quill_title_inset)
        if event.type() == QEvent.Type.Show:
            for delay in (0, 250, 800):                              # again once the system has finished laying the bar out
                QTimer.singleShot(delay, lambda: (plain_title(obj), _redraw_lights(obj)))
        return False


def _redraw_lights(widget) -> None:
    """Scale the window's close / minimise / zoom buttons again (the system makes new layers when it shows a window), and
    put the side panel's line, title and X back in the title bar the system has now."""
    refresh_chrome(widget)


def refresh_chrome_soon(widget) -> None:
    """:func:`refresh_chrome` now and again a moment later (the system lays the title bar out again after a change of look,
    and resets what was set in the meantime)."""
    for delay in (0, 200, 700):
        QTimer.singleShot(delay, lambda: refresh_chrome(widget) if shiboken6.isValid(widget) else None)


def refresh_chrome(widget) -> None:
    """Re-attach and re-place what the title bar holds for the side panel (its line, title and X), and the bottom rule.

    The system may rebuild a window's title bar views whenever its look changes (opacity, blur, theme) or it is shown, and
    anything added to the old ones is then gone; call this after such a change. The window buttons are drawn larger again too.
    """
    try:
        if not _native_platform(sys.platform) or not shiboken6.isValid(widget) or not widget.isVisible():
            return                                           # (headless runs, or a window that is gone or hidden)
        kit = getattr(widget, "_quill_titlebar", None)
        if kit is not None:
            kit.refresh()
        import AppKit
        import objc
        window = objc.objc_object(c_void_p=int(widget.winId())).window()
        if window is not None:
            larger_traffic_lights(window)
        if window is not None and getattr(widget, "_quill_title_filter", None) is not None:
            title_bar_rule(AppKit, window.standardWindowButton_(0).superview(), window)
    except Exception:
        pass


def native_window_rebuilt(widget) -> bool:
    """True if the (macOS) native window was replaced since the chrome was applied, so its styling and icons are gone.

    Closing a window to the tray and showing it again makes Qt build a new native window; the title bar label
    that :func:`plain_title` adds is how a window that was styled is told from one that was not.
    """
    try:
        if not _native_platform("darwin") or getattr(widget, "_quill_title_filter", None) is None:
            return False
        import objc
        window = objc.objc_object(c_void_p=int(widget.winId())).window()
        if window is None:
            return False
        bar = window.standardWindowButton_(0).superview()
        return not any(v.identifier() == _TITLE_ID for v in bar.subviews())
    except Exception:
        return False


class _RebuildWatcher(QObject):
    """Calls *on_rebuilt* when a window is shown on a new native window (see :func:`native_window_rebuilt`)."""

    def __init__(self, widget, on_rebuilt: Callable[[], None]) -> None:
        super().__init__(widget)
        self._widget, self._on_rebuilt = widget, on_rebuilt
        widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._widget and event.type() == QEvent.Type.Show:
            QTimer.singleShot(0, self._check)
        return False

    def _check(self) -> None:
        if self._widget.isVisible() and native_window_rebuilt(self._widget):
            self._on_rebuilt()


def watch_native_window(widget, on_rebuilt: Callable[[], None]) -> QObject:
    """Run *on_rebuilt* whenever *widget* comes back on a rebuilt native window (to style it and add its icons again)."""
    return _RebuildWatcher(widget, on_rebuilt)


def plain_title(widget) -> bool:
    """Show the window's title in the regular weight, centred in the (macOS) title bar.

    The system draws title bars in bold and offers no way to change that, so the real title is hidden
    and an ordinary label shows the same text. It follows later changes of ``windowTitle``.
    """
    try:
        if not _native_platform("darwin"):
            return False
        import AppKit
        import objc
        if getattr(widget, "_quill_title_filter", None) is None:
            widget._quill_title_filter = _TitleFilter(widget)
            widget.installEventFilter(widget._quill_title_filter)
        window = objc.objc_object(c_void_p=int(widget.winId())).window()
        if window is None:
            return False
        close = window.standardWindowButton_(0)
        bar = close.superview()                                      # the frame view that holds the title bar
        label = next((v for v in bar.subviews() if v.identifier() == _TITLE_ID), None)
        if label is None:
            label = AppKit.NSTextField.labelWithString_(widget.windowTitle())
            label.setIdentifier_(_TITLE_ID)
            label.setFont_(AppKit.NSFont.systemFontOfSize_weight_(TITLE_POINTS, 0.0))
            label.setTextColor_(AppKit.NSColor.labelColor())            # full strength, not the muted grey
            label.setAutoresizingMask_(13)                           # centred sideways, fixed distance from the top
            bar.addSubview_(label)
            window.setTitleVisibility_(1)                            # hide the bold system title
            widget.windowTitleChanged.connect(lambda text, v=label, c=close: _retitle(v, c, text, getattr(widget, "_quill_title_inset", 0.0)))
        _retitle(label, close, widget.windowTitle(), getattr(widget, "_quill_title_inset", 0.0))
        title_bar_rule(AppKit, bar, window)
        return True
    except Exception:
        return False


def muted_line_color(appkit, bar):
    """The colour of the title bar's thin lines: the text colour at a low strength, for the bar's light or dark look."""
    dark = "Dark" in str(bar.effectiveAppearance().name())
    return appkit.NSColor.colorWithWhite_alpha_(1.0 if dark else 0.0, 0.14)


def bar_extent(window, bar) -> tuple[float, float]:
    """Where the title bar is inside *bar*, as ``(y of its bottom edge, its height)``.

    *bar* is what holds the window's close button: usually the title bar itself, but while the window is see-through the
    system makes it the whole frame view, with the title bar at its top.
    """
    height = bar.bounds().size.height
    try:
        bar_height = window.frame().size.height - window.contentView().frame().size.height
    except Exception:
        return 0.0, height
    if bar_height <= 0 or bar_height > height:
        return 0.0, height
    return height - bar_height, bar_height


def title_bar_rule(appkit, bar, window=None) -> None:
    """One muted line along the bottom of the title bar, across its whole width (so across the side panel's part too).

    Added to (or found in) *bar* (see :func:`bar_extent` for where the title bar is in it), and drawn in its current light or
    dark look.
    """
    size = bar.bounds().size
    bottom = bar_extent(window, bar)[0] if window is not None else 0.0
    rule = next((v for v in bar.subviews() if v.identifier() == _RULE_ID), None)
    if rule is None:
        rule = appkit.NSView.alloc().initWithFrame_(((0, bottom), (size.width, 1)))
        rule.setIdentifier_(_RULE_ID)
        rule.setWantsLayer_(True)
        rule.setAutoresizingMask_(_NS_VIEW_WIDTH | _NS_VIEW_MIN_Y_MARGIN)       # follows the width, keeps its place under the top
        bar.addSubview_(rule)
    rule.setFrame_(((0, bottom), (size.width, 1)))
    rule.layer().setBackgroundColor_(muted_line_color(appkit, bar).CGColor())


def _retitle(label, close, text: str, inset: float = 0.0) -> None:
    """Set the label's text and centre it across the window (less the side panel's room), level with the close button."""
    label.setStringValue_(text)
    label.sizeToFit()
    size, bounds, button = label.frame().size, close.superview().bounds().size, close.frame()
    room = bounds.width - inset
    label.setFrameOrigin_(((room - size.width) / 2,
                           button.origin.y + (button.size.height - size.height) / 2))


def set_title_inset(widget, points: float, platform: str | None = None) -> bool:
    """Keep the window's title centred in what is left of the title bar while a side panel *points* wide takes
    the right-hand end (0 centres it across the whole bar again)."""
    try:
        if not _native_platform(platform or sys.platform):
            return False
        import objc
        window = objc.objc_object(c_void_p=int(widget.winId())).window()
        close = window.standardWindowButton_(0)
        label = next(v for v in close.superview().subviews() if v.identifier() == _TITLE_ID)
        widget._quill_title_inset = float(points)
        label.setAutoresizingMask_(8 if points > 0 else 13)      # a panel: stay put (placed by hand); else centred sideways
        _retitle(label, close, label.stringValue(), float(points))
        return True
    except Exception:
        return False


def _native_platform(platform: str) -> bool:
    """True only when Qt is really drawing with the OS's windowing system.

    Handing a fake window id to PyObjC would crash the process, so this check
    matters: under the ``offscreen`` plugin (tests, servers) nothing is applied.
    """
    from PySide6.QtGui import QGuiApplication
    native = {"darwin": "cocoa"}.get(platform) or platforms.offered(platform, "NATIVE_QPA")
    return QGuiApplication.platformName() == native


#: Identifier of the blur view Quill adds, so it can be found and removed again.
BLUR_ID = "quillBlur"
TINT_ID = "quillTint"
FROST_ID = "quillFrost"
#: The most the window's colour is washed over the blur (at the slider's top).
FROST_MAX = 0.45

#: NSVisualEffectView settings: Sidebar material, blend with what is behind the window, always active.
_MATERIAL_SIDEBAR, _BEHIND_WINDOW, _STATE_ACTIVE = 7, 0, 1
_NS_WINDOW_BELOW, _NS_WINDOW_ABOVE = -1, 1
_NS_VIEW_SIZABLE = 2 | 16                  # width and height
_NS_VIEW_WIDTH, _NS_VIEW_MIN_Y_MARGIN = 2, 8


def mac_chrome(view_id: int, dark: bool, colors: dict[str, str], appkit=None, opacity: int = 100,
               blur: int = 0) -> bool:
    """Make the title bar transparent and match the appearance; True if applied.

    Args:
        view_id: ``QWidget.winId()``, which on macOS is the window's ``NSView``.
        appkit: The ``AppKit`` module (injectable; imported lazily otherwise).
    """
    if appkit is None:
        try:
            import AppKit as appkit      # PyObjC; optional dependency on macOS
            import objc
        except ImportError:
            return False
        view = objc.objc_object(c_void_p=view_id)
    else:
        view = appkit.view_for(view_id)
    window = view.window()
    if window is None:
        return False
    r, g, b = (int(colors["bg"][i:i + 2], 16) / 255 for i in (1, 3, 5))
    window.setTitlebarAppearsTransparent_(True)
    tall_titlebar(window, appkit)
    larger_traffic_lights(window)
    see_through = opacity < 100                            # at 100 the window is solid, whatever the blur
    window.setOpaque_(not see_through)                     # a see-through window must not be marked opaque
    # The window's own backdrop (Qt paints it, with the opacity as its alpha: theme.backdrop_alpha) is what thins. The
    # system backing is clear so the desktop shows through it, and the window server blurs that desktop by the
    # slider's radius (set_background_blur). Controls and text stay solid.
    srgb = getattr(appkit.NSColor, "colorWithSRGBRed_green_blue_alpha_", appkit.NSColor.colorWithDeviceRed_green_blue_alpha_)
    lift = BAR_DARK_LIFT / 255 if dark else 0.0                    # (the dark title bar is drawn a little lighter by the system)
    r, g, b = (max(0.0, c - lift) for c in (r, g, b))
    window.setBackgroundColor_(srgb(r, g, b, 0.0 if see_through else 1.0))      # (sRGB: the space Qt paints the body in)
    name = "NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua"
    window.setAppearance_(appkit.NSAppearance.appearanceNamed_(name))
    tint = (r, g, b, glass.bar_alpha(max(0.08, opacity / 100), dark)) if opacity < 100 else (r, g, b, 1.0)
    radius = blur_radius(blur) if see_through else 0
    blurred = set_background_blur(window, radius) if appkit_is_real(appkit) else False
    # Where the window server cannot blur, a vibrancy view (fixed blur, always whole) stands in for it.
    _set_blur(view, appkit, 1.0 if (radius > 0 and not blurred) else 0.0, window, tint if see_through else None)
    window.invalidateShadow()               # the shadow follows the visible shape
    return True


#: The window server's blur radius (px) at the slider's top. 0 is no blur.
MAX_BLUR_RADIUS = 60


#: How much larger the close / minimise / zoom buttons are drawn than the system's own, and the gap each next one is moved
#: along (pt), so the bigger circles keep their space.
TRAFFIC_SCALE, TRAFFIC_SHIFT = 1.3, 4.0
#: 1 when the scaled circle grows upward from its frame (so it needs moving down by half the growth); 0 for none.
TRAFFIC_DROP = 1.0
#: How much lighter (out of 255) the system draws a dark title bar than the colour it is given; the bar is given that much less.
BAR_DARK_LIFT = 4


def larger_traffic_lights(window) -> bool:
    """Draw the three window buttons at :data:`TRAFFIC_SCALE` times their size, like the larger ones Finder and Claude have.

    The system has no setting for it, so each button's layer is scaled (about its own middle) and the second and third
    are nudged along so the circles do not touch. The click area stays the system's. Safe to call again.
    """
    try:
        for index in (0, 1, 2):
            button = window.standardWindowButton_(index)
            button.setWantsLayer_(True)
            # (the layer grows from its lower edge, so it is also moved down by half of what it grew: the circles then stay
            # centred where the system put them, level with the title and the icons)
            try:
                height = float(button.frame().size.height)
            except Exception:
                height = 0.0
            drop = (TRAFFIC_SCALE - 1.0) * height / 2 * TRAFFIC_DROP
            button.layer().setAffineTransform_((TRAFFIC_SCALE, 0.0, 0.0, TRAFFIC_SCALE, TRAFFIC_SHIFT * index, -drop))
        return True
    except Exception:
        return False


def blur_radius(blur: int) -> int:
    """The window server's blur radius for the blur slider's value (0 to 100)."""
    return round(max(0, min(100, int(blur))) * MAX_BLUR_RADIUS / 100)


def appkit_is_real(appkit) -> bool:
    """True for the real AppKit module (the tests pass a fake, which has no window server behind it)."""
    return getattr(appkit, "__name__", "") == "AppKit"


def set_background_blur(window, radius: int) -> bool:
    """Blur what is behind *window* by *radius* px, using the window server's own call (the one terminal emulators use
    for a frosted background). Works with a see-through window and, unlike a vibrancy view, takes any radius.

    Returns:
        True if it was applied; False where the call is not available.
    """
    try:
        import ctypes
        for path in ("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight",
                     "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"):
            try:
                lib = ctypes.CDLL(path)
                connection = lib.CGSMainConnectionID
                setter = lib.CGSSetWindowBackgroundBlurRadius
            except (OSError, AttributeError):
                continue
            connection.restype = ctypes.c_int
            setter.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
            setter.restype = ctypes.c_int
            return setter(connection(), int(window.windowNumber()), int(radius)) == 0
    except Exception:
        pass
    return False


#: NSWindowToolbarStyleUnified: the taller title bar (and the larger close / minimise / zoom buttons) of a window with a toolbar.
_TOOLBAR_STYLE_UNIFIED = 3
TOOLBAR_ID = "quillToolbar"


def tall_titlebar(window, appkit) -> bool:
    """Give *window* the same title bar height, and the same size of close / minimise / zoom buttons, as a window
    with a toolbar (Claude's, Finder's): an empty toolbar does it. Every Quill window gets it from :func:`mac_chrome`,
    so a window added later looks right without doing anything.

    Returns:
        True if the toolbar was added (or was already there).
    """
    try:
        if window.toolbar() is not None:
            return True
        toolbar = appkit.NSToolbar.alloc().initWithIdentifier_(TOOLBAR_ID)
        toolbar.setShowsBaselineSeparator_(False)          # no line under the title bar
        window.setToolbar_(toolbar)
        window.setToolbarStyle_(_TOOLBAR_STYLE_UNIFIED)
        return True
    except Exception:
        return False


def _set_blur(view, appkit, strength: float, window=None, tint=None) -> None:
    """The pieces behind Qt's content view that make a see-through window look right.

    * A vibrancy view (*strength* above 0): the stand-in for the window server's blur, used only where
      :func:`set_background_blur` is not available. Always whole, never half-faded (a faded one lets the sharp desktop
      through). 0 removes it.
    * A strip over the title bar in the window's colour (*tint*, an ``(r, g, b, alpha)`` tuple): the title bar is not
      Qt's, so without it the bar would stay clear while the rest of the window thins. None removes it.
    """
    holder = view.superview()
    if holder is None:
        return
    existing = {v.identifier(): v for v in holder.subviews() if v.identifier() in (BLUR_ID, TINT_ID, FROST_ID)}
    for old in (FROST_ID,):                                   # (an earlier version's wash: never wanted any more)
        if old in existing:
            existing.pop(old).removeFromSuperview()
    effect = existing.get(BLUR_ID)
    if strength <= 0 and effect is not None:
        effect.removeFromSuperview()
    elif strength > 0:
        if effect is None:
            effect = appkit.NSVisualEffectView.alloc().initWithFrame_(holder.bounds())
            effect.setIdentifier_(BLUR_ID)
            effect.setMaterial_(_MATERIAL_SIDEBAR)
            effect.setBlendingMode_(_BEHIND_WINDOW)
            effect.setState_(_STATE_ACTIVE)
            effect.setAutoresizingMask_(_NS_VIEW_SIZABLE)
            holder.addSubview_positioned_relativeTo_(effect, _NS_WINDOW_BELOW, view)
        effect.setAlphaValue_(1.0)
    strip = existing.get(TINT_ID)
    if tint is None:
        if strip is not None:
            strip.removeFromSuperview()
        return
    height = holder.bounds().size.height - view.frame().size.height     # the title bar
    if strip is None:
        strip = appkit.NSView.alloc().initWithFrame_(((0, 0), (0, 0)))
        strip.setIdentifier_(TINT_ID)
        strip.setWantsLayer_(True)
        strip.setAutoresizingMask_(_NS_VIEW_WIDTH | _NS_VIEW_MIN_Y_MARGIN)   # follows the width, stays at the top
        holder.addSubview_positioned_relativeTo_(strip, _NS_WINDOW_BELOW, view)
    strip.setFrame_(((0, holder.bounds().size.height - height), (holder.bounds().size.width, height)))
    r, g, b, a = tint
    make = getattr(appkit.NSColor, "colorWithSRGBRed_green_blue_alpha_", appkit.NSColor.colorWithDeviceRed_green_blue_alpha_)
    strip.layer().setBackgroundColor_(make(r, g, b, a).CGColor())             # (sRGB, the colour space Qt paints the body in)


# --------------------------------------------------------------------------- #
# Always on top, without recreating the window                                 #
# --------------------------------------------------------------------------- #

#: NSWindow levels: a normal window and a floating (always on top) one.
_NS_NORMAL_LEVEL, _NS_FLOATING_LEVEL = 0, 3


def set_always_on_top(widget, on: bool, platform: str | None = None,
                      appkit=None, user32=None) -> bool:
    """Float *widget* above other windows (or stop) using the OS, not Qt's window flag.

    Changing Qt's ``WindowStaysOnTopHint`` destroys and recreates the native window,
    which interrupts any animation and loses the title-bar styling. The native calls
    change the level in place.

    Returns:
        True if the OS did it; False if the caller must fall back to the Qt flag
        (headless runs, other platforms, or a missing PyObjC).
    """
    platform = platform or sys.platform
    try:
        if not _native_platform(platform):
            return False
        handle = int(widget.winId())
        if platform == "darwin":
            if appkit is None:
                import AppKit as appkit            # noqa: F811 (PyObjC, optional)
                import objc
                view = objc.objc_object(c_void_p=handle)
            else:
                view = appkit.view_for(handle)
            window = view.window()
            if window is None:
                return False
            window.setLevel_(_NS_FLOATING_LEVEL if on else _NS_NORMAL_LEVEL)
            return True
        topmost = platforms.offered(platform, "set_topmost")
        if topmost is not None:
            return bool(topmost(handle, on, user32=user32)) if user32 is not None else bool(topmost(handle, on))
    except Exception:
        return False
    return False


# --------------------------------------------------------------------------- #
# A button in the title bar                                                    #
# --------------------------------------------------------------------------- #

#: SF Symbol names for "shrink to the mini view" / "back to the full window".
SYMBOL_MINI = "arrow.down.right.and.arrow.up.left"
SYMBOL_FULL = "arrow.up.left.and.arrow.down.right"
SYMBOL_SETTINGS = "slider.horizontal.3"
SYMBOL_UNDO = "arrow.uturn.backward"
SYMBOL_HELP = "questionmark.circle"
SYMBOL_FOLDER = "folder"
SYMBOL_TURN = "bubble.left.and.bubble.right"
_NS_LAYOUT_LEFT, _NS_LAYOUT_RIGHT = 1, 2


def _symbol(appkit, name: str, text: str):
    """The SF Symbol *name* at the title bar's icon size (the plain picture where sizing is not available)."""
    image = appkit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, text)
    if image is None:
        return None
    try:
        config = appkit.NSImageSymbolConfiguration.configurationWithPointSize_weight_(SYMBOL_POINTS, 0.0)
        return image.imageWithSymbolConfiguration_(config) or image
    except Exception:
        return image


class TitlebarButton:
    """A borderless icon button placed at the right end of a macOS title bar.

    Created by :func:`add_titlebar_button`; keeps the Cocoa objects alive and
    swaps the icon with :meth:`set_mini`.
    """

    def __init__(self, button, controller, target, appkit, extras=(), holder=None, row=None, row_x=0.0, base_width=0,
                 panel=None, reference=None, window=None) -> None:
        self._button, self._controller, self._target, self._appkit = button, controller, target, appkit
        self._extras = list(extras)                # (button, target) pairs kept alive beside the main one
        self._holder, self._row, self._row_x, self._base_width = holder, row, row_x, base_width
        self._panel = panel                        # the side panel's line, title and close button (right side only)
        self._reference = reference                # the window's close button: icons are centred on it, like the title
        self._window = window
        self._lift = 0.0                           # how far the icons were raised to line up with the title
        self._inset = 0.0

    def _resize_holder(self) -> None:
        if self._holder is not None:
            self._holder.setFrameSize_((self._base_width + self._inset, _ICON_HEIGHT + self._lift))
            self._row.setFrameOrigin_((self._row_x, self._lift))

    def set_inset(self, points: float) -> None:
        """Move the icons *points* to the left of the window's right edge (the side panel's room); the panel's line,
        title and close button appear in that room, from the top of the title bar. 0 puts everything back."""
        self._inset = float(points)
        try:
            self._resize_holder()
            if self._panel is not None:
                self._panel.place(points)
        except Exception:
            pass

    def refresh(self) -> None:
        """Put the panel's pieces back in the current title bar and place them again (see :func:`refresh_chrome`)."""
        try:
            if self._panel is not None:
                self._panel.place(self._inset)
        except Exception:
            pass

    def set_panel_title(self, text: str) -> None:
        """The side panel's title, drawn in the title bar."""
        try:
            if self._panel is not None:
                self._panel.title.setStringValue_(text)
                self._panel.title.sizeToFit()
                self._panel.place(self._inset)
        except Exception:
            pass

    def settle(self, tries: int = 8) -> None:
        """Run :meth:`align` a few times, a moment apart (the system lays an accessory out after it is added).

        Every title bar button group does this by itself when it is made, in every window.
        """
        def step(left: int) -> None:
            if abs(self.align()) > 0.5 and left > 0:
                QTimer.singleShot(150, lambda: step(left - 1))

        QTimer.singleShot(100, lambda: step(tries))

    def align(self) -> float:
        """Raise the icons until their middle is level with the window's close button (and so the title).

        The system decides where an accessory sits and it varies between macOS versions, so this measures and
        corrects (call it a few times, a moment apart, until it returns about 0).

        Returns:
            How far off they were, in points.
        """
        try:
            ref = self._reference if not callable(getattr(self._reference, "superview", None)) or self._window is None \
                else self._window.standardWindowButton_(0)
            bar = ref.superview()
            rect = self._row.convertRect_toView_(self._row.bounds(), bar)
            delta = (ref.frame().origin.y + ref.frame().size.height / 2) - (rect.origin.y + rect.size.height / 2)
            if abs(delta) > 0.5:
                self._lift = max(0.0, min(40.0, self._lift + delta))
                self._resize_holder()
            return delta
        except Exception:
            return 0.0

    def set_extra_active(self, index: int, active: bool) -> None:
        """Keep the *index*-th extra icon filled (as while hovered) to show its panel is open."""
        try:
            button = self._extras[index][0]
            button._on = active
            if not active:
                button._hover = False                       # (it is hovered again by the next pointer entry)
            button.refreshFill()
        except Exception:
            pass

    def set_mini(self, mini: bool) -> None:
        """Show the "back to full" icon while in the mini view, "shrink" otherwise."""
        name = SYMBOL_FULL if mini else SYMBOL_MINI
        text = "Back to the Full Window" if mini else "Mini View"
        image = _symbol(self._appkit, name, text)
        if image is not None:
            self._button.setImage_(image)
        self._button.setToolTip_(text)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or grey out the main icon."""
        self._button.setEnabled_(enabled)

    def set_extra_enabled(self, index: int, enabled: bool) -> None:
        """Enable or grey out the *index*-th extra icon (counting from the left)."""
        self._extras[index][0].setEnabled_(enabled)

    def set_extra_image(self, index: int, png: bytes, tip: str, muted: bool) -> bool:
        """Give the *index*-th extra icon (counting from the left) its own picture (PNG bytes, drawn as a template
        so the system colours it for the title bar), a tooltip, and dim it when *muted*. Returns False if it can't."""
        try:
            button = self._extras[index][0]
            data = self._appkit.NSData.dataWithBytes_length_(png, len(png))
            image = self._appkit.NSImage.alloc().initWithData_(data)
            image.setTemplate_(True)
            image.setSize_((FOLDER_POINTS, FOLDER_POINTS))
            button.setImage_(image)
            button.setToolTip_(tip)
            button.setAlphaValue_(0.45 if muted else 1.0)
            return True
        except Exception:
            return False

    def click(self) -> None:
        """Press the button (used by tests)."""
        self._button.performClick_(None)

    def remove(self) -> None:
        """Take the icons out of the title bar."""
        self._controller.removeFromParentViewController()


#: Widths (pt) of the title bar icons and the gap between them. The right-most one is narrower so its
#: glyph sits close to the window edge.
_ICON_WIDTH, _ICON_HEIGHT, _ICON_GAP = 36, 30, 2
#: Point size of the title bar's SF Symbol icons (the taller title bar has room for larger ones).
SYMBOL_POINTS = 16
#: Size (pt) of the folder's own picture.
FOLDER_POINTS = 19
#: The room (pt) between the right-hand icons' last hover box and what is to its right: the window's edge, or the side
#: panel's line while the panel is open.
_RIGHT_MARGIN = 8
#: How far (pt) the left-hand icons are moved right, clear of the larger window buttons.
_LEFT_NUDGE = 8


def add_titlebar_button(widget, callback: Callable[[], None], mini: bool = False,
                        platform: str | None = None, appkit=None,
                        extra: list[tuple] | None = None, symbol: str | None = None, tip: str = "",
                        hover: tuple | None = None, side: str = "right",
                        on_panel_close: Callable[[], None] | None = None) -> TitlebarButton | None:
    """Add the resize icon (and optionally more icons to its left) at the right of the native title bar (macOS).

    Args:
        widget: The top-level window.
        callback: Called, with no arguments, when the resize icon is clicked.
        mini: Whether the window is currently the mini view (chooses the icon).
        extra: More icons to place to the *left* of the main one, as
            ``(SF Symbol name, tooltip, callback)`` (for example the Settings icon); an entry may add
            ``hover_in, hover_out`` callbacks (run while the pointer is over the icon) after the callback.
        symbol, tip: Give the main icon its own symbol and tooltip instead of the resize icon's.
        hover: ``(hover_in, hover_out)`` for the main icon; its native tooltip is then left off.
        side: ``"right"`` (default) or ``"left"`` (beside the window's close / zoom buttons).
        on_panel_close: Called when the side panel's close button (drawn in the title bar) is pressed.

    Returns:
        The button, or None where this is not possible (other platforms, headless
        runs, no PyObjC), in which case the caller keeps an in-window button.
    """
    platform = platform or sys.platform
    appkit_given = appkit
    try:
        if platform != "darwin" or not _native_platform(platform):
            return None
        handle = int(widget.winId())
        if appkit is None:
            import AppKit as appkit                  # noqa: F811
            import objc
            view = objc.objc_object(c_void_p=handle)
            target_class = _target_class(appkit, objc)
            button_class = _button_class(appkit, objc)
        else:
            view = appkit.view_for(handle)
            target_class = appkit.TargetClass
            button_class = appkit.NSButton
        window = view.window()
        if window is None:
            return None
        appkit_real = appkit_given is None
        def make_button(action, width=_ICON_WIDTH, hover_in=None, hover_out=None):
            target = target_class.alloc().initWithCallback_(action)
            button = button_class.alloc().initWithFrame_(((0, 0), (width, _ICON_HEIGHT)))
            button.hover_in, button.hover_out = hover_in, hover_out    # (used by the pointer-tracking button class)
            button.setBordered_(False)
            try:
                button.setContentTintColor_(appkit.NSColor.labelColor())      # full strength, even while the window is inactive
            except Exception:
                pass
            button.setTarget_(target)
            button.setAction_("toggle:")
            return button, target

        hover_in, hover_out = hover or (None, None)
        button, target = make_button(callback, _ICON_WIDTH, hover_in, hover_out)
        if symbol:
            image = _symbol(appkit, symbol, tip)
            if image is not None:
                button.setImage_(image)
            if not hover:
                button.setToolTip_(tip)
        extras = []
        for entry in extra or []:
            name, label, action, *hovers = entry
            extra_button, extra_target = make_button(action, _ICON_WIDTH, *hovers)
            image = _symbol(appkit, name, label)
            if image is not None:
                extra_button.setImage_(image)
            if not hovers:
                extra_button.setToolTip_(label)
            extras.append((extra_button, extra_target))
        controller = appkit.NSTitlebarAccessoryViewController.alloc().init()
        views = [e[0] for e in extras] + [button]     # extra icons first (left), the main icon last (right)
        x = 0.0                                       # every icon gets the same 36 x 30 box (a stack view would shrink each to its picture)
        for view in views:
            view.setFrame_(((x, 0), (_ICON_WIDTH, _ICON_HEIGHT)))
            x += _ICON_WIDTH + _ICON_GAP
        width = x - _ICON_GAP
        row = appkit.NSView.alloc().initWithFrame_(((0, 0), (width, _ICON_HEIGHT)))
        for view in views:
            row.addSubview_(view)
        row_x = _LEFT_NUDGE if side == "left" else 0.0
        width += row_x if side == "left" else _RIGHT_MARGIN       # (room for the row's offset, or the margin on its right)
        holder = appkit.NSView.alloc().initWithFrame_(((0, 0), (width, _ICON_HEIGHT)))
        row.setFrameOrigin_((row_x, 0))
        holder.addSubview_(row)
        controller.setView_(holder)
        controller.setLayoutAttribute_(_NS_LAYOUT_LEFT if side == "left" else _NS_LAYOUT_RIGHT)
        window.addTitlebarAccessoryViewController_(controller)
        panel = _PanelChrome(appkit, window, on_panel_close, make_button) if side == "right" and appkit_real else None
        reference = window.standardWindowButton_(0) if appkit_real else None
        result = TitlebarButton(button, controller, target, appkit, extras, holder, row, row_x, width, panel, reference, window)
        if not symbol:
            result.set_mini(mini)
        if side == "right" and appkit_real and not symbol:
            widget._quill_titlebar = result                 # (so refresh_chrome can find it)
        if reference is not None:
            result.settle()                         # (icons level with the title, in this window and any other)
        return result
    except Exception:
        return None


_TARGET_CLASS = None
_BUTTON_CLASS = None
_DIVIDER_ID = "quillPanelDivider"


class _PanelChrome:
    """What the title bar draws for the side panel: its edge line, its title and its close button.

    All three live in the title bar's own view, hidden until the panel opens, and are placed from the window's right
    edge (the panel's width) so they follow the panel as it slides. The system may rebuild the title bar's views after
    they were added (when the window is first shown, or when a toolbar is attached), so the bar is looked up again at
    every placement and the three views are moved into the current one.
    """

    def __init__(self, appkit, window, on_close, make_button) -> None:
        self._appkit = appkit
        self._window = window
        height = self._reference().superview().bounds().size.height
        self.line = appkit.NSView.alloc().initWithFrame_(((0, 0), (1, height)))
        self.line.setIdentifier_(_DIVIDER_ID)
        self.line.setWantsLayer_(True)
        self.title = appkit.NSTextField.labelWithString_("")
        self.title.setFont_(appkit.NSFont.systemFontOfSize_weight_(TITLE_POINTS, 0.0))      # regular, not bold
        self.title.setTextColor_(appkit.NSColor.labelColor())
        self.close, self._target = make_button(on_close or (lambda: None), _ICON_WIDTH)
        image = _symbol(appkit, "xmark", "Close")
        if image is not None:
            self.close.setImage_(image)
        self.close.setToolTip_("Close")
        for view in (self.line, self.title, self.close):
            view.setAutoresizingMask_(1)                # keeps its distance from the right edge
            view.setHidden_(True)
        self.line.setAutoresizingMask_(1 | 8)           # (the line keeps its distance from the right edge and the top)
        self._attach()

    def _reference(self):
        """The window's close button: the title bar's own, wherever the system has put it now."""
        return self._window.standardWindowButton_(0)

    @property
    def bar(self):
        return self._reference().superview()

    def _attach(self) -> None:
        """Make sure the three views are in the title bar that is there now."""
        bar = self.bar
        for view in (self.line, self.title, self.close):
            if view.superview() is not bar:
                view.removeFromSuperview()
                bar.addSubview_(view)

    def place(self, points: float, reference=None) -> None:
        """Put the three pieces at a panel of width *points* (0 hides them)."""
        shown = points > 0
        for view in (self.line, self.title, self.close):
            view.setHidden_(not shown)
        if not shown:
            return
        self._attach()
        ref = self._reference()
        bar = ref.superview()
        width = bar.bounds().size.width
        bottom, height = bar_extent(self._window, bar)        # (the title bar, wherever it is in what holds the buttons)
        self.line.layer().setBackgroundColor_(muted_line_color(self._appkit, bar).CGColor())
        self.line.setFrame_(((width - points, bottom), (1, height)))
        middle = ref.frame().origin.y + ref.frame().size.height / 2
        size = self.title.frame().size
        self.title.setFrameOrigin_((width - points + 14, middle - size.height / 2))
        self.close.setFrameOrigin_((width - 8 - _ICON_WIDTH, middle - _ICON_HEIGHT / 2))


def _button_class(appkit, objc):
    """A title-bar button that shows the pointing-hand cursor and reports the pointer entering / leaving."""
    global _BUTTON_CLASS
    if _BUTTON_CLASS is None:
        class QuillIconButton(appkit.NSButton):
            def pointerInside(self):
                """Is the pointer really over this icon? (The enter / exit events can be missed when a click rearranges
                the title bar, which left a hover fill stuck on an icon.)"""
                try:
                    point = self.window().mouseLocationOutsideOfEventStream()
                    box = self.convertRect_toView_(self.bounds(), None)
                    return (box.origin.x <= point.x <= box.origin.x + box.size.width
                            and box.origin.y <= point.y <= box.origin.y + box.size.height)
                except Exception:
                    return True

            def refreshFill(self):
                """A muted rounded fill while the pointer is over the icon or its panel is open (like a flat button)."""
                self.setWantsLayer_(True)
                layer = self.layer()
                layer.setCornerRadius_(6)
                if (getattr(self, "_hover", False) and self.pointerInside()) or getattr(self, "_on", False):
                    dark = "Dark" in str(self.effectiveAppearance().name())
                    shade = appkit.NSColor.colorWithWhite_alpha_(1.0 if dark else 0.0, 0.14 if dark else 0.10)
                    layer.setBackgroundColor_(shade.CGColor())
                else:
                    layer.setBackgroundColor_(None)

            def resetCursorRects(self):
                self.addCursorRect_cursor_(self.bounds(), appkit.NSCursor.pointingHandCursor())

            def updateTrackingAreas(self):
                objc.super(QuillIconButton, self).updateTrackingAreas()
                old = getattr(self, "_tracking", None)
                if old is not None:
                    self.removeTrackingArea_(old)
                options = 0x01 | 0x80 | 0x200      # entered / exited, always active, the visible rectangle
                self._tracking = appkit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                    self.bounds(), options, self, None)
                self.addTrackingArea_(self._tracking)

            def mouseEntered_(self, event):
                self._hover = True
                self.refreshFill()
                if getattr(self, "hover_in", None):
                    self.hover_in()

            def mouseExited_(self, event):
                self._hover = False
                self.refreshFill()
                if getattr(self, "hover_out", None):
                    self.hover_out()

        _BUTTON_CLASS = QuillIconButton
    return _BUTTON_CLASS


def _target_class(appkit, objc):
    """The Objective-C object that receives the button's action and calls back into Python."""
    global _TARGET_CLASS
    if _TARGET_CLASS is None:
        class QuillTitlebarTarget(appkit.NSObject):
            def initWithCallback_(self, callback):
                self = objc.super(QuillTitlebarTarget, self).init()
                if self is None:
                    return None
                self._callback = callback
                return self

            @objc.IBAction
            def toggle_(self, sender):
                self._callback()

        _TARGET_CLASS = QuillTitlebarTarget
    return _TARGET_CLASS


class FileDialogWarmer:
    """Makes the system's file window appear at once the first time it is asked for.

    macOS starts the helper that draws that window only when the first one is shown, which takes about 1.5 seconds; later
    ones take under half a second. So one is shown invisibly (clear, in the temporary folder, no mouse) shortly after
    start-up and closed again, and the user's first Open File is as quick as the second. Nothing is shown or kept.
    """

    HOLD_MS = 1800

    def __init__(self) -> None:
        self._panel = None
        self.done = False

    def start(self, platform: str | None = None) -> bool:
        """Warm the system's file window (once). Returns True if it was started (False elsewhere, or on any failure)."""
        from PySide6.QtGui import QGuiApplication
        if self.done or (platform or sys.platform) != "darwin" or QGuiApplication.platformName() != "cocoa":
            return False                                           # (not macOS, or no real window system: headless runs)
        try:
            import AppKit
            panel = AppKit.NSOpenPanel.openPanel()
            panel.setDirectoryURL_(AppKit.NSURL.fileURLWithPath_(AppKit.NSTemporaryDirectory()))
            panel.setAlphaValue_(0.0)
            panel.setIgnoresMouseEvents_(True)
            panel.beginWithCompletionHandler_(lambda result: None)
            self._panel = panel
            self.done = True
            QTimer.singleShot(self.HOLD_MS, self.cancel)
            return True
        except Exception:
            return False

    def cancel(self) -> None:
        """Close the invisible window (also called before a real one is shown, so the two never meet)."""
        panel, self._panel = self._panel, None
        if panel is not None:
            try:
                panel.cancel_(None)
            except Exception:
                pass


def bring_app_forward(widget, platform: str | None = None, appkit=None) -> None:
    """Make Quill the frontmost application with *widget* in front (after another program was started and took the focus)."""
    try:
        widget.raise_()
        widget.activateWindow()
        platform = platform or sys.platform
        if platform == "darwin" and _native_platform(platform):
            if appkit is None:
                import AppKit as appkit                  # noqa: F811 (PyObjC, optional)
            appkit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# The Dock icon                                                                #
# --------------------------------------------------------------------------- #

#: NSApplicationActivationPolicy: a normal app (Dock icon, Cmd-Tab) or an accessory (menu bar only).
_POLICY_REGULAR, _POLICY_ACCESSORY = 0, 1


def set_dock_icon_visible(visible: bool, platform: str | None = None, appkit=None) -> bool:
    """Show or hide the app's Dock icon (macOS), without restarting.

    Hiding makes Quill a menu bar app: it is still reachable from its menu bar icon.

    Returns:
        True if the change was made; False elsewhere (other platforms, headless runs, no PyObjC).
    """
    platform = platform or sys.platform
    try:
        if platform != "darwin" or not _native_platform(platform):
            return False
        if appkit is None:
            import AppKit as appkit                      # noqa: F811 (PyObjC, optional)
        app = appkit.NSApplication.sharedApplication()
        ok = app.setActivationPolicy_(_POLICY_REGULAR if visible else _POLICY_ACCESSORY)
        app.activateIgnoringOtherApps_(True)             # changing the policy takes the focus away: take it back
        return bool(ok) if ok is not None else True
    except Exception:
        return False
