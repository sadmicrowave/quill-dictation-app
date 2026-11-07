"""What a "mirror" answers: a program that can show the cells Quill writes (Numbers, LibreOffice) as they are written.

The mirrors themselves are provider code (macOS: Numbers; LibreOffice has its own module); this is the shared answer type and the
mirror used where there is no such program.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class MirrorResult:
    """How an attempt to show cells in a program (or to ask it something) went."""

    ok: bool
    reason: str = ""
    """``"ok"``, ``"notrunning"``, ``"nodoc"`` (the program has no such document open), ``"denied"`` (Quill may not control it),
    ``"disabled"`` (the system is not asked, as in tests) or ``"error"``."""
    detail: str = ""


class NullMirror:
    """The mirror of a system with no such program: nothing is open there, nothing can be shown."""

    installed_note = False

    def push(self, path: str | os.PathLike, changes: list, probe: bool = False, want_sheet: bool = False) -> MirrorResult:
        return MirrorResult(False, "notinstalled")

    def has_document(self, path: str | os.PathLike) -> bool:
        return False

    def active_sheet(self, path: str | os.PathLike) -> str | None:
        return None

    @staticmethod
    def document_name(path: str | os.PathLike) -> str:
        return pathlib.Path(path).stem
