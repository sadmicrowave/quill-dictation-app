"""Tokenisation shared by the vocabulary, parser and keyword matcher."""

from __future__ import annotations
import re

_TOKEN = re.compile(r"\d+(?:\.\d+)?s?|[^\W\d_]+")


def tokenize(text: str) -> list[str]:
    """Lowercase *text*, drop apostrophes, and split into word/number tokens.

    Punctuation and hyphens separate tokens; apostrophes are removed so that
    the spoken form of a possessive matches its written form.

    Examples:
        ``"Levi's"`` -> ``["levis"]``; ``"T-Shirt"`` -> ``["t", "shirt"]``;
        ``"$25.50"`` -> ``["25.50"]``; ``"1990s"`` -> ``["1990s"]``.
    """
    text = text.lower().replace("'", "").replace("’", "")
    return _TOKEN.findall(text)


def display_name(term: str) -> str:
    """Spoken lowercase term -> list value: ``"hugo boss"`` -> ``"Hugo Boss"``."""
    return " ".join(word.capitalize() for word in term.split())
