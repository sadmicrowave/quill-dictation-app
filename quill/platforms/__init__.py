"""Operating-system specific code, one provider per system.

The rest of Quill never says ``if platform == "win32"``. It asks :func:`provider` for the system's provider and uses what
the provider offers, and does the plain thing (usually: nothing) where it offers nothing.

A provider is a package ``quill.platforms.<name>`` (``windows``). It may define any of these (all optional):

``NATIVE_QPA``
    Qt platform plugin name when Qt draws with the real window system (``"windows"``).
``QUIT_LABEL``
    Text of the Quit menu item (``"Exit"``).
``TRAY_CLICK_OPENS_MENU``
    True where a left click on the tray icon must pop the menu up itself.
``apply_chrome(handle, dark, colors, blur) -> bool``
    Tint the title bar and border; blur behind the window.
``set_topmost(handle, on) -> bool``
    Keep a window above the others.
``speak(text) -> None`` and ``render_clip(text, destination) -> bool``
    Say a phrase / write it to a WAV file with the system voice.
``new_live_bridge()``
    The live Excel bridge.
``open_file(path) -> None``
    Open a file in the system's default program.
``wrap_text(cell_api) -> None``, ``set_autofilter`` helpers
    Excel's own object model for the platform (see ``quill.bridge.grid``).
``spreadsheet_hosts``
    A provider-side object with ``running(apps, run)``, ``installed(program)``, ``launch(path, program)`` and
    ``documents(app, run)`` for finding and starting the spreadsheet programs.
``libreoffice``
    ``profile_scripts_dir(home)``, ``find_soffice()``, ``is_running()``.

The Windows provider (``quill/platforms/windows/``) is developed on its own branch, ``windows``, and is merged in once it has
been tested on Windows. Without it Quill still starts on Windows and works on spreadsheet files; the live Excel bridge and
the Windows look are simply not offered.
"""

from __future__ import annotations

import importlib
import logging
import sys
from types import ModuleType

log = logging.getLogger("quill.platforms")

#: ``sys.platform`` value -> provider package name.
NAMES = {"darwin": "macos", "win32": "windows"}


def provider(platform: str | None = None) -> ModuleType | None:
    """The provider module for *platform* (default: this system), or None when there is none (macOS code is still in place;
    a system without a provider, or a build without that provider's files)."""
    name = NAMES.get(platform or sys.platform)
    if name is None:
        return None
    try:
        return importlib.import_module(f"quill.platforms.{name}")
    except ImportError:
        return None


def offered(platform: str | None, what: str, default=None):
    """What the provider for *platform* offers under *what* (*default* when there is no provider or it offers nothing)."""
    module = provider(platform)
    return getattr(module, what, default) if module is not None else default
