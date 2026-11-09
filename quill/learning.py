"""Learned links: which column a word means, taught by the user and remembered between runs.

When a value is spoken without its column's name, Quill has to choose a column. The spreadsheet's own headings
settle some cases ("departed" near a "Departure Date" column); nothing built in can settle the rest, because what
"sold" or "spotted" means depends on the user's sheet. The user is the only source, so Quill learns from them: a
**link** is *word -> column*, taught by changing a line's column or by saying "<word> means <column>".

This module is pure (no Qt, no files): the :class:`LinkStore` is saved and loaded through the settings file.

Rules (see ``Learned Links Design.md``):

* A link only ever *chooses between columns that already fit the value*; it never creates a value.
* A word is stored as its stem ("sold" and "selling" are one).
* A correction counts once. The link is used when it has been taught ``learn_after`` times, or at once when it was
  said outright (``taught``). A later correction to a different column lowers the old one; at zero it is dropped.
* Every link remembers the files it was learned in (path and name, with a count each) so the list can be shown for
  one file, and so a file's words can be cleared without touching the rest.
* The store is capped; the links used least recently are dropped first.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from quill.parser.fillers import is_link_stopword
from quill.parser.numbers import parse_number
from quill.parser.sounds import stem
from quill.parser.tokens import tokenize

#: Most links kept (the least recently used go first).
MAX_LINKS = 200
#: Fewest letters a word needs to become a link.
MIN_WORD_LETTERS = 3
#: Words kept per link's file list.
MAX_SOURCES = 20
#: Allowed range of the "learn after" setting.
LEARN_AFTER_RANGE = (1, 5)


@dataclass
class Source:
    """A file a link was learned in."""

    path: str
    name: str
    count: int = 1
    last: float = 0.0                           # when something was last learned in this file (seconds since 1970; 0 = unknown)


@dataclass
class Link:
    """One word that means one column."""

    word: str                                   # the stem
    column: str
    shown: str = ""                             # the word as it was last spoken ("spotted"), for the list
    count: int = 1                              # times it was taught
    taught: bool = False                        # said outright ("<word> means <column>"): used at once
    used: int = 0                               # times it chose a column
    serial: int = 0                             # when it was last taught or used (higher is later)
    sources: list[Source] = field(default_factory=list)

    def is_active(self, learn_after: int) -> bool:
        return self.taught or self.count >= learn_after


def link_word(word: str) -> str | None:
    """The stem of *word* if it can be a link, else None (too short, a number, a filler)."""
    tokens = tokenize(word)
    if len(tokens) != 1:
        return None
    token = tokens[0]
    if (len(token) < MIN_WORD_LETTERS or any(ch.isdigit() for ch in token) or is_link_stopword(token)
            or parse_number([token], 0)[0] is not None):
        return None
    return stem(token)


class LinkStore:
    """All learned links. Starts empty: nothing about any subject is built in."""

    def __init__(self) -> None:
        self._links: dict[tuple[str, str], Link] = {}
        self._serial = 0

    # ------------------------------------------------------------------ #
    # Reading                                                              #
    # ------------------------------------------------------------------ #

    def __len__(self) -> int:
        return len(self._links)

    def links(self) -> list[Link]:
        """Every link, in no particular order (callers sort)."""
        return list(self._links.values())

    def for_file(self, path: str, columns: list[str] | None = None) -> list[Link]:
        """The links that belong to the file at *path*: learned in it, or for a column it has (*columns*)."""
        if not path:
            return []
        have = set(columns or [])
        return [link for link in self._links.values() if link.column in have or any(s.path == path for s in link.sources)]

    def get(self, word: str, column: str) -> Link | None:
        key = link_word(word)
        return self._links.get((key, column)) if key else None

    def choose(self, words: list[str], columns: list[str], learn_after: int) -> tuple[str, str] | None:
        """The column one of *words* (nearest first) is linked to among *columns*, as ``(column, word)``, or None.

        Only links that are in force count. A word with links to several of *columns* uses the best taught.
        """
        for word in words:
            key = link_word(word)
            if key is None:
                continue
            found = [link for (w, c), link in self._links.items() if w == key and c in columns and link.is_active(learn_after)]
            if found:
                best = max(found, key=lambda link: (link.taught, link.count, link.serial))
                best.used += 1
                best.serial = self._tick()
                return best.column, word
        return None

    # ------------------------------------------------------------------ #
    # Teaching                                                             #
    # ------------------------------------------------------------------ #

    def teach(self, word: str, column: str, path: str = "", name: str = "") -> Link | None:
        """The user said it outright: *word* means *column*, in force at once. None if *word* cannot be a link."""
        link = self._count(word, column, path, name)
        if link is not None:
            link.taught = True
        return link

    def observe(self, word: str, column: str, path: str = "", name: str = "") -> Link | None:
        """A correction put *word*'s value in *column*: count it (it takes effect after enough of them).

        A link from the same word to another column loses one count (and is dropped at zero), so a changed mind
        is followed rather than argued with.
        """
        link = self._count(word, column, path, name)
        if link is None:
            return None
        for other in [other_link for (w, c), other_link in self._links.items() if w == link.word and c != column and not other_link.taught]:
            other.count -= 1
            if other.count <= 0:
                del self._links[(other.word, other.column)]
        return link

    def unobserve(self, word: str, column: str, path: str = "") -> bool:
        """Take back one :meth:`observe` (the correction was undone): the count drops by one and the link is dropped at zero.

        A link that was said outright (``taught``) is left alone. The count the correction took from another column
        is not given back (a changed mind that was itself changed back costs nothing worth tracking). True if a count was removed.
        """
        key = link_word(word)
        link = self._links.get((key, column)) if key else None
        if link is None or link.taught:
            return False
        link.count -= 1
        for source in list(link.sources):
            if path and source.path == path:
                source.count -= 1
                if source.count <= 0:
                    link.sources.remove(source)
        if link.count <= 0:
            del self._links[(link.word, link.column)]
        return True

    def _count(self, word: str, column: str, path: str, name: str) -> Link | None:
        key = link_word(word)
        if key is None or not column:
            return None
        link = self._links.get((key, column))
        if link is None:
            link = self._links[(key, column)] = Link(key, column, count=0)
        link.shown = tokenize(word)[0]
        link.count += 1
        link.serial = self._tick()
        for source in link.sources:
            if path and source.path == path:
                source.count += 1
                source.name = name or source.name
                source.last = time.time()
                break
        else:
            if path or name:
                link.sources.append(Source(path, name or path, last=time.time()))
        del link.sources[:-MAX_SOURCES]
        self._trim()
        return link

    def _tick(self) -> int:
        self._serial += 1
        return self._serial

    def _trim(self) -> None:
        if len(self._links) <= MAX_LINKS:
            return
        for key, _ in sorted(self._links.items(), key=lambda item: item[1].serial)[:len(self._links) - MAX_LINKS]:
            del self._links[key]

    # ------------------------------------------------------------------ #
    # Forgetting                                                           #
    # ------------------------------------------------------------------ #

    def forget(self, word: str, column: str) -> bool:
        """Drop one link (*word* is the stored stem or any form of it). True if there was one."""
        key = link_word(word) or word
        return self._links.pop((key, column), None) is not None

    def forget_many(self, links: list[Link]) -> int:
        """Drop every one of *links*; returns how many were there."""
        return sum(1 for link in links if self._links.pop((link.word, link.column), None) is not None)

    def forget_all(self) -> int:
        count = len(self._links)
        self._links.clear()
        return count

    def forget_file(self, path: str) -> int:
        """Forget what was learned in the file at *path* (links learned only there are dropped; others lose that file)."""
        removed = 0
        for key, link in list(self._links.items()):
            if any(s.path == path for s in link.sources):
                link.sources = [s for s in link.sources if s.path != path]
                if not link.sources:
                    del self._links[key]
                    removed += 1
        return removed

    # ------------------------------------------------------------------ #
    # Saving                                                               #
    # ------------------------------------------------------------------ #

    def to_list(self) -> list[dict]:
        """Plain data for the settings file, oldest first."""
        out = []
        for link in sorted(self._links.values(), key=lambda each: each.serial):
            out.append({
                "word": link.word, "shown": link.shown, "column": link.column, "count": link.count, "taught": link.taught,
                "used": link.used,
                "sources": [{"path": s.path, "name": s.name, "count": s.count, "last": s.last} for s in link.sources],
            })
        return out

    @classmethod
    def from_list(cls, data: object) -> "LinkStore":
        """Rebuild from :meth:`to_list` data; anything malformed is skipped (a damaged file never stops Quill)."""
        store = cls()
        if not isinstance(data, list):
            return store
        for entry in data[:MAX_LINKS]:
            if not isinstance(entry, dict):
                continue
            word, column = entry.get("word"), entry.get("column")
            if not isinstance(word, str) or not isinstance(column, str) or not word or not column:
                continue
            sources = []
            for raw in entry.get("sources", []) if isinstance(entry.get("sources"), list) else []:
                if isinstance(raw, dict) and isinstance(raw.get("path"), str) and isinstance(raw.get("name"), str):
                    count, last = raw.get("count"), raw.get("last")
                    sources.append(Source(raw["path"], raw["name"], count if isinstance(count, int) and count > 0 else 1,
                                          float(last) if isinstance(last, (int, float)) and not isinstance(last, bool) and last > 0 else 0.0))
            count, used = entry.get("count"), entry.get("used")
            shown = entry.get("shown")
            link = Link(word, column, shown=shown if isinstance(shown, str) and shown else word, count=count if isinstance(count, int) and count > 0 else 1,
                        taught=entry.get("taught") is True, used=used if isinstance(used, int) and used >= 0 else 0,
                        serial=store._tick(), sources=sources[:MAX_SOURCES])
            store._links[(word, column)] = link
        return store
