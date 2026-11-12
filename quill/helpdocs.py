"""Quill's built-in help: Markdown pages in ``quill/help/`` read into topics.

Each ``NN-slug.md`` file is one topic. Its first ``# `` line is the topic's title and every ``## `` line
inside it is a section the help window lists under it. Adding a page is just adding a file (``images/``
beside the pages holds their pictures); nothing else needs to change.
"""

from __future__ import annotations
import pathlib
import re
import sys
from dataclasses import dataclass, field


#: The sidebar's headings and the pages under each (by slug), in the order a person meets them. A page named in no group goes under "More".
GROUPS = (
    ("Start here", ("welcome", "quick-start")),
    ("Set up", ("choose-spreadsheet", "use-a-file-directly", "data-starts", "microphone")),
    ("Dictate a row", ("first-row", "numbers-dates", "notes", "ids", "fix-mistake")),
    ("Words Quill misses", ("term-helper", "term-helper-voice", "teach-words")),
    ("Work the way you like", ("mini-view", "turns", "search", "sounds")),
    ("Reference", ("phrases", "icons", "settings", "menus", "privacy", "troubleshooting")),
)


def group_of(slug: str) -> str:
    """The sidebar heading *slug* sits under."""
    return next((name for name, slugs in GROUPS if slug in slugs), "More")


@dataclass
class Topic:
    """One help page."""

    slug: str                                   # "term-helper": what the ? icons ask for
    title: str                                  # "🧩 Term Helper"
    text: str                                   # the page's Markdown
    sections: list[str] = field(default_factory=list)      # its "## " headings, in order

    @property
    def group(self) -> str:
        """The sidebar heading this page is listed under."""
        return group_of(self.slug)

    def matches(self, query: str) -> bool:
        """True if *query* (case-insensitive) appears in the title or the text."""
        needle = query.strip().lower()
        return not needle or needle in self.title.lower() or needle in self.text.lower()


def help_dir() -> pathlib.Path:
    """The folder holding the help pages (works from source and from a PyInstaller build)."""
    bundle = getattr(sys, "_MEIPASS", None)
    base = pathlib.Path(bundle) / "quill" if bundle else pathlib.Path(__file__).resolve().parent
    return base / "help"


def load_topics(directory: pathlib.Path | None = None) -> list[Topic]:
    """Read every ``*.md`` page in *directory* (default: the bundled help), in file-name order."""
    topics = []
    for path in sorted((directory or help_dir()).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = next((m.group(1).strip() for m in re.finditer(r"(?m)^# (.+)$", text)), path.stem)
        sections = [m.group(1).strip() for m in re.finditer(r"(?m)^## (.+)$", text)]
        slug = re.sub(r"^\d+-", "", path.stem)
        topics.append(Topic(slug, title, text, sections))
    return topics
