"""Which programs are running on a Mac, without starting a process: the system's own list of running applications is read
in-process (under a millisecond), instead of starting ``ps`` (about 80 ms and a child process every time) on every check."""

from __future__ import annotations

import logging

log = logging.getLogger("quill.processes")


def running_executables() -> set[str] | None:
    """Lower-case executable names of the running applications (``"numbers"``, ``"soffice"``, ``"microsoft excel"`` ...), or
    None where the list cannot be read (no pyobjc)."""
    try:
        from AppKit import NSWorkspace                              # type: ignore[import-not-found]
        names: set[str] = set()
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            url = app.executableURL()
            if url is not None:
                names.add(str(url.lastPathComponent()).lower())
        return names
    except Exception:                                               # (a helper never stops a look)
        log.debug("could not read the running applications", exc_info=True)
        return None
