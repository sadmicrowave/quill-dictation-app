"""A stand-in for the Numbers app that behaves the way the real one does where it matters to Quill, so a test can look at what is *open*
afterwards and not only at which commands were sent.

  * Opening a file always opens another document, even when the same file is already open (the real app does).
  * An imported ``.xlsx`` is named without its extension and reports no file; a ``.numbers`` document reports its file.
  * A document can have unsaved changes; closing without saving removes it.

It is a command runner (what ``MacHosts`` is given): it answers the fixed scripts Quill sends by comparing them with the module's own
constants, and ``open``.
"""
from __future__ import annotations

import pathlib

from quill.platforms.macos import hosts as mac_hosts


class FakeNumbers:
    def __init__(self) -> None:
        self.docs: list[dict] = []            # name, file, modified
        self.calls: list[list[str]] = []

    # -- the world, as a test sets it up and looks at it ----------------------------------------------
    def import_xlsx(self, path: str, modified: bool = False) -> None:
        """The user opened a workbook in Numbers: an untitled-style document named after the file, reporting no file."""
        self.docs.append({"name": pathlib.Path(path).stem, "file": "", "modified": modified})

    def open_numbers_document(self, path: str, modified: bool = False) -> None:
        self.docs.append({"name": pathlib.Path(path).stem, "file": path, "modified": modified})

    def count(self, name: str) -> int:
        """How many documents with this name are open."""
        return sum(1 for d in self.docs if d["name"] == name)

    # -- the commands Quill sends ----------------------------------------------------------------------
    def __call__(self, args: list[str]) -> str:
        self.calls.append(list(args))
        if args[0] == "open":                                           # ``open -g -a Numbers <path>``
            self.import_xlsx(args[-1])
            return ""
        if args[0] == "osascript":
            script, rest = args[4], args[5:]
            if script == mac_hosts._LIST_NUMBERS_FOR_RELOAD:
                return "".join(f"{d['name']}\t{d['file']}\t{'1' if d['modified'] else '0'}\t{i}\n" for i, d in enumerate(self.docs))
            if script == mac_hosts._CLOSE_NUMBERS:
                for position in (int(p) for p in rest):                 # (the real script closes in the order it is given)
                    del self.docs[position]
                return "ok"
        return ""
