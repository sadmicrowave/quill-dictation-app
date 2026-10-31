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
            return "macos" if mac_chrome(handle, dark, colors, opacity=opacity, blur=blur) else None
    except Exception:
        return None
    return None


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
    try:
        set_attribute(*args)
    except Exception:
        pass     # an attribute this Windows build doesn't know


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
    # The title bar area is painted by the window itself, not by Quill's content, so it follows the
    # opacity setting here (fully solid at 100). The content fades itself (see theme.apply_opacity).
    alpha = max(0, min(100, opacity)) / 100
    window.setBackgroundColor_(appkit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha))
    name = "NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua"
    window.setAppearance_(appkit.NSAppearance.appearanceNamed_(name))
    _set_blur(view, appkit, strength)
    window.invalidateShadow()               # the shadow follows the visible shape
    return True


def _set_blur(view, appkit, strength: float) -> None:
    """Add, fade or remove a vibrancy view behind Qt's content view (*strength* 0 to 1)."""
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
_NS_LAYOUT_RIGHT = 2


class TitlebarButton:
    """A borderless icon button placed at the right end of a macOS title bar.

    Created by :func:`add_titlebar_button`; keeps the Cocoa objects alive and
    swaps the icon with :meth:`set_mini`.
    """

    def __init__(self, button, controller, target, appkit) -> None:
        self._button, self._controller, self._target, self._appkit = button, controller, target, appkit

    def set_mini(self, mini: bool) -> None:
        """Show the "back to full" icon while in the mini view, "shrink" otherwise."""
        name = SYMBOL_FULL if mini else SYMBOL_MINI
        text = "Back to the Full Window" if mini else "Mini View"
        image = self._appkit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, text)
        if image is not None:
            self._button.setImage_(image)
        self._button.setToolTip_(text)

    def click(self) -> None:
        """Press the button (used by tests)."""
        self._button.performClick_(None)

    def remove(self) -> None:
        self._controller.removeFromParentViewController()


def add_titlebar_button(widget, callback: Callable[[], None], mini: bool = False,
                        platform: str | None = None, appkit=None) -> TitlebarButton | None:
    """Add a resize icon to the right of the window's native title bar (macOS).

    Args:
        widget: The top-level window.
        callback: Called, with no arguments, when the icon is clicked.
        mini: Whether the window is currently the mini view (chooses the icon).

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
        else:
            view = appkit.view_for(handle)
            target_class = appkit.TargetClass
        window = view.window()
        if window is None:
            return None
        target = target_class.alloc().initWithCallback_(callback)
        button = appkit.NSButton.alloc().initWithFrame_(((0, 0), (34, 24)))
        button.setBordered_(False)
        button.setTarget_(target)
        button.setAction_("toggle:")
        controller = appkit.NSTitlebarAccessoryViewController.alloc().init()
        controller.setView_(button)
        controller.setLayoutAttribute_(_NS_LAYOUT_RIGHT)
        window.addTitlebarAccessoryViewController_(controller)
        result = TitlebarButton(button, controller, target, appkit)
        result.set_mini(mini)
        return result
    except Exception:
        return None


_TARGET_CLASS = None


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
