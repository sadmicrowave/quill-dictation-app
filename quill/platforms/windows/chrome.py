"""Windows 11 window look: the title bar and border in the theme's colours, rounded corners, acrylic blur, always-on-top.

Everything goes through the DWM / user32 APIs with ``ctypes``. It is cosmetic and best-effort: an old Windows build or any
error leaves the standard frame. The platform calls are injectable so the logic is testable on any machine.
"""

from __future__ import annotations

import contextlib
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


def _native() -> bool:
    """True only when Qt is really drawing with Windows' own window system (not under the offscreen test plugin, where
    ``winId()`` is not a real window)."""
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.platformName() == "windows"


def apply_chrome(widget, dark: bool, colors: dict[str, str], platform: str | None = None,
                 opacity: int = 100, blur: int = 0) -> str | None:
    """What :func:`quill.ui.chrome.apply_chrome` asks of a provider: tint *widget*'s title bar. ``"windows"`` when applied."""
    try:
        if not _native():
            return None
        return "windows" if windows_chrome(int(widget.winId()), dark, colors, blur=blur) else None
    except Exception:
        return None


def set_always_on_top(widget, on: bool, platform: str | None = None, user32=None, **unused) -> bool:
    """Keep the window above the others (or stop), in place, without recreating it. False if the caller must use Qt's flag."""
    try:
        if not _native():
            return False
        import ctypes
        user32 = user32 or ctypes.windll.user32
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
        user32.SetWindowPos(ctypes.c_void_p(int(widget.winId())), ctypes.c_void_p(HWND_TOPMOST if on else HWND_NOTOPMOST),
                            0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        return True
    except Exception:
        return False
