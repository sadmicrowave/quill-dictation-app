"""Which programs are running, without starting a process where the system can say so in-process.

Where that is not possible (no provider, or the tests' ``QUILL_NO_HOSTS``) the callers fall back to ``ps`` / ``tasklist``.
"""

from __future__ import annotations

import os
import sys

from quill import platforms


def running_executables() -> set[str] | None:
    """Lower-case executable names of the running applications (``"numbers"``, ``"soffice"``, ``"microsoft excel"`` ...), or
    None where the system list cannot be read (no provider offers it, or the tests' ``QUILL_NO_HOSTS``)."""
    read = platforms.offered(sys.platform, "running_executables")
    if read is None or os.environ.get("QUILL_NO_HOSTS"):
        return None
    return read()
