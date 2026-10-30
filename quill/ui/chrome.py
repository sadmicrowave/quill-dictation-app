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


def apply_chrome(widget, dark: bool, colors: dict[str, str], platform: str | None = None) -> str | None:
    """Tint *widget*'s native title bar to match the theme.

    Args:
        widget: A top-level QWidget (its native window is created if needed).
        dark: Whether the dark theme is active.
        colors: The theme colours (``bg``, ``text``, ``border``).
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
            return "windows" if windows_chrome(handle, dark, colors) else None
        if platform == "darwin":
            return "macos" if mac_chrome(handle, dark, colors) else None
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
                   set_attribute: DwmSetter | None = None) -> bool:
    """Apply the Windows 11 title bar look through DWM; True if the calls were made."""
    if set_attribute is None:
        set_attribute = _dwm_setter()
        if set_attribute is None:
            return False
    set_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
    for attribute, key in ((DWMWA_CAPTION_COLOR, "bg"), (DWMWA_TEXT_COLOR, "text"),
                           (DWMWA_BORDER_COLOR, "border")):
        _quietly(set_attribute, hwnd, attribute, colorref(colors[key]))   # Windows 11 only
    _quietly(set_attribute, hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    return True


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


def mac_chrome(view_id: int, dark: bool, colors: dict[str, str], appkit=None) -> bool:
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
    window.setBackgroundColor_(appkit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0))
    name = "NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua"
    window.setAppearance_(appkit.NSAppearance.appearanceNamed_(name))
    return True
