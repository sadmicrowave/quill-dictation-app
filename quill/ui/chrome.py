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

from PySide6.QtCore import QEvent, QObject, QTimer
import contextlib
import sys
from typing import Callable

# DwmSetWindowAttribute attribute ids (Windows 10 build 19041+ / Windows 11).
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
BACKDROP_NONE, BACKDROP_ACRYLIC = 1, 3
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWCP_ROUND = 2

#: ``set_attribute(hwnd, attribute_id, int_value)``.
DwmSetter = Callable[[int, int, int], None]


def colorref(hex_color: str) -> int:
    """``"#RRGGBB"`` as a Windows COLORREF (``0x00BBGGRR``)."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return r | (g << 8) | (b << 16)


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
        if platform == "win32":
            return "windows" if windows_chrome(handle, dark, colors, blur=blur) else None
        if platform == "darwin":
            if not mac_chrome(handle, dark, colors, opacity=opacity, blur=blur):
                return None
            plain_title(widget)
            return "macos"
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


class _TitleFilter(QObject):
    """Re-applies the plain title whenever its window is shown (the native window may be rebuilt on show)."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Show:
            for delay in (0, 250):                                   # again once the system has finished laying the bar out
                QTimer.singleShot(delay, lambda: plain_title(obj))
        return False


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
            label.setFont_(AppKit.NSFont.systemFontOfSize_weight_(13, 0.0))
            label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
            label.setAutoresizingMask_(13)                           # centred sideways, fixed distance from the top
            bar.addSubview_(label)
            window.setTitleVisibility_(1)                            # hide the bold system title
            widget.windowTitleChanged.connect(lambda text, v=label, c=close: _retitle(v, c, text))
        _retitle(label, close, widget.windowTitle())
        return True
    except Exception:
        return False


def _retitle(label, close, text: str) -> None:
    """Set the label's text and centre it across the window, level with the close button."""
    label.setStringValue_(text)
    label.sizeToFit()
    size, bounds, button = label.frame().size, close.superview().bounds().size, close.frame()
    label.setFrameOrigin_(((bounds.width - size.width) / 2,
                           button.origin.y + (button.size.height - size.height) / 2))


def _native_platform(platform: str) -> bool:
    """True only when Qt is really drawing with the OS's windowing system.

    Handing a fake window id to PyObjC would crash the process, so this check
    matters: under the ``offscreen`` plugin (tests, servers) nothing is applied.
    """
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.platformName() in {"darwin": ("cocoa",), "win32": ("windows",)}.get(platform, ())


def windows_chrome(hwnd: int, dark: bool, colors: dict[str, str],
                   set_attribute: DwmSetter | None = None, blur: int = 0,
                   extend_frame: Callable[[int], None] | None = None) -> bool:
    """Apply the Windows 11 title bar look (and acrylic blur) through DWM.

    Returns:
        True if the calls were made. The acrylic backdrop needs Windows 11 22H2 or
        later; on an older build it is silently skipped.
    """
    if set_attribute is None:
        set_attribute = _dwm_setter()
        if set_attribute is None:
            return False
    set_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
    for attribute, key in ((DWMWA_CAPTION_COLOR, "bg"), (DWMWA_TEXT_COLOR, "text"),
                           (DWMWA_BORDER_COLOR, "border")):
        _quietly(set_attribute, hwnd, attribute, colorref(colors[key]))   # Windows 11 only
    _quietly(set_attribute, hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    _quietly(set_attribute, hwnd, DWMWA_SYSTEMBACKDROP_TYPE, BACKDROP_ACRYLIC if blur > 0 else BACKDROP_NONE)
    if blur > 0:                          # the backdrop shows only where the frame is extended into the window
        _quietly(extend_frame or _extend_frame, hwnd)
    return True


def _extend_frame(hwnd: int) -> None:
    import ctypes

    class Margins(ctypes.Structure):
        _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]

    margins = Margins(-1, -1, -1, -1)
    ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(ctypes.c_void_p(hwnd), ctypes.byref(margins))


def _quietly(set_attribute: DwmSetter, *args) -> None:
    with contextlib.suppress(Exception):     # an attribute this Windows build doesn't know
        set_attribute(*args)


def _dwm_setter() -> DwmSetter | None:
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi          # only exists on Windows

        def set_attribute(hwnd: int, attribute: int, value: int) -> None:
            data = ctypes.c_int(value)
            result = dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attribute,
                                               ctypes.byref(data), ctypes.sizeof(data))
            if result != 0:
                raise OSError(f"DwmSetWindowAttribute({attribute}) -> {result}")
        return set_attribute
    except Exception:
        return None


#: Identifier of the blur view Quill adds, so it can be found and removed again.
BLUR_ID = "quillBlur"

#: NSVisualEffectView settings: Sidebar material, blend with what is behind the window, always active.
_MATERIAL_SIDEBAR, _BEHIND_WINDOW, _STATE_ACTIVE = 7, 0, 1
_NS_WINDOW_BELOW = -1
_NS_VIEW_SIZABLE = 2 | 16                  # width and height


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
    strength = max(0, min(100, blur)) / 100
    window.setOpaque_(not (strength > 0 or opacity < 100))   # a see-through window must not be marked opaque
    # The window fades as a whole (theme.apply_opacity); its blur is the window server's own (see _set_blur).
    # No blur: the window fades as a whole (theme.apply_opacity) over a solid backing. Blur: the backing is
    # clear, so the vibrancy layer (the blurred desktop) is what shows through the see-through background.
    alpha = 0.0 if strength > 0 and opacity < 100 else 1.0
    window.setBackgroundColor_(appkit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha))
    name = "NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua"
    window.setAppearance_(appkit.NSAppearance.appearanceNamed_(name))
    _set_blur(view, appkit, strength, window)
    window.invalidateShadow()               # the shadow follows the visible shape
    return True


def _set_blur(view, appkit, strength: float, window=None) -> None:
    """Blur the desktop behind the window by *strength* (0 to 1; 0 = off).

    A vibrancy view is added, faded or removed behind Qt's content view. It shows through wherever the
    content's own background is see-through (see ``theme.backdrop_alpha``).
    """
    holder = view.superview()
    if holder is None:
        return
    existing = [v for v in holder.subviews() if v.identifier() == BLUR_ID]
    if strength <= 0:
        for v in existing:
            v.removeFromSuperview()
        return
    if existing:
        existing[0].setAlphaValue_(strength)
        return
    effect = appkit.NSVisualEffectView.alloc().initWithFrame_(view.frame())
    effect.setIdentifier_(BLUR_ID)
    effect.setMaterial_(_MATERIAL_SIDEBAR)
    effect.setBlendingMode_(_BEHIND_WINDOW)
    effect.setState_(_STATE_ACTIVE)
    effect.setAutoresizingMask_(_NS_VIEW_SIZABLE)
    effect.setAlphaValue_(strength)          # fades the blur in: 0 = none, 1 = full
    holder.addSubview_positioned_relativeTo_(effect, _NS_WINDOW_BELOW, view)


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
        if platform == "win32":
            import ctypes
            user32 = user32 or ctypes.windll.user32
            HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
            user32.SetWindowPos(ctypes.c_void_p(handle), ctypes.c_void_p(HWND_TOPMOST if on else HWND_NOTOPMOST),
                                0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
            return True
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
_NS_LAYOUT_LEFT, _NS_LAYOUT_RIGHT = 1, 2


class TitlebarButton:
    """A borderless icon button placed at the right end of a macOS title bar.

    Created by :func:`add_titlebar_button`; keeps the Cocoa objects alive and
    swaps the icon with :meth:`set_mini`.
    """

    def __init__(self, button, controller, target, appkit, extras=()) -> None:
        self._button, self._controller, self._target, self._appkit = button, controller, target, appkit
        self._extras = list(extras)                # (button, target) pairs kept alive beside the main one

    def set_mini(self, mini: bool) -> None:
        """Show the "back to full" icon while in the mini view, "shrink" otherwise."""
        name = SYMBOL_FULL if mini else SYMBOL_MINI
        text = "Back to the Full Window" if mini else "Mini View"
        image = self._appkit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, text)
        if image is not None:
            self._button.setImage_(image)
        self._button.setToolTip_(text)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or grey out the main icon."""
        self._button.setEnabled_(enabled)

    def set_extra_enabled(self, index: int, enabled: bool) -> None:
        """Enable or grey out the *index*-th extra icon (counting from the left)."""
        self._extras[index][0].setEnabled_(enabled)

    def click(self) -> None:
        """Press the button (used by tests)."""
        self._button.performClick_(None)

    def remove(self) -> None:
        """Take the icons out of the title bar."""
        self._controller.removeFromParentViewController()


#: Widths (pt) of the title bar icons and the gap between them. The right-most one is narrower so its
#: glyph sits close to the window edge.
_ICON_WIDTH, _LAST_ICON_WIDTH, _ICON_GAP = 30, 22, 14


def add_titlebar_button(widget, callback: Callable[[], None], mini: bool = False,
                        platform: str | None = None, appkit=None,
                        extra: list[tuple] | None = None, symbol: str | None = None, tip: str = "",
                        hover: tuple | None = None, side: str = "right") -> TitlebarButton | None:
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

    Returns:
        The button, or None where this is not possible (other platforms, headless
        runs, no PyObjC), in which case the caller keeps an in-window button.
    """
    platform = platform or sys.platform
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
        def make_button(action, width=_ICON_WIDTH, hover_in=None, hover_out=None):
            target = target_class.alloc().initWithCallback_(action)
            button = button_class.alloc().initWithFrame_(((0, 0), (width, 24)))
            button.hover_in, button.hover_out = hover_in, hover_out    # (used by the pointer-tracking button class)
            button.setBordered_(False)
            button.setTarget_(target)
            button.setAction_("toggle:")
            return button, target

        hover_in, hover_out = hover or (None, None)
        button, target = make_button(callback, _LAST_ICON_WIDTH, hover_in, hover_out)   # right-most: close to the edge
        if symbol:
            image = appkit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, tip)
            if image is not None:
                button.setImage_(image)
            if not hover:
                button.setToolTip_(tip)
        extras = []
        for entry in extra or []:
            name, label, action, *hovers = entry
            extra_button, extra_target = make_button(action, _ICON_WIDTH, *hovers)
            image = appkit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, label)
            if image is not None:
                extra_button.setImage_(image)
            if not hovers:
                extra_button.setToolTip_(label)
            extras.append((extra_button, extra_target))
        controller = appkit.NSTitlebarAccessoryViewController.alloc().init()
        if extras:                                    # extra icons first (left), the resize icon last (right)
            views = [e[0] for e in extras] + [button]
            row = appkit.NSStackView.stackViewWithViews_(views)
            row.setSpacing_(_ICON_GAP)
            width = _ICON_WIDTH * len(extras) + _LAST_ICON_WIDTH + _ICON_GAP * len(extras)
            row.setFrame_(((0, 0), (width, 24)))    # an accessory view needs a size of its own
            controller.setView_(row)
        else:
            controller.setView_(button)
        controller.setLayoutAttribute_(_NS_LAYOUT_LEFT if side == "left" else _NS_LAYOUT_RIGHT)
        window.addTitlebarAccessoryViewController_(controller)
        result = TitlebarButton(button, controller, target, appkit, extras)
        if not symbol:
            result.set_mini(mini)
        return result
    except Exception:
        return None


_TARGET_CLASS = None
_BUTTON_CLASS = None


def _button_class(appkit, objc):
    """A title-bar button that shows the pointing-hand cursor and reports the pointer entering / leaving."""
    global _BUTTON_CLASS
    if _BUTTON_CLASS is None:
        class QuillIconButton(appkit.NSButton):
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
                if getattr(self, "hover_in", None):
                    self.hover_in()

            def mouseExited_(self, event):
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
