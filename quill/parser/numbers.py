"""Spoken numbers, money amounts and dates.

Pure functions over token lists (see :func:`quill.parser.tokens.tokenize`).
Each ``parse_*`` function takes ``(tokens, i)`` and returns the parsed value
plus how many tokens it consumed, or ``(None, 0)`` when nothing parses.
"""

from __future__ import annotations
import datetime as dt
import re

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_ORDINAL_SUFFIXES = {"st", "nd", "rd", "th"}
_DIGITS = re.compile(r"\d+(?:\.\d+)?")


def parse_number(tokens: list[str], i: int) -> tuple[float | None, int]:
    """Read digits (``"25"``, ``"3.5"``) or spoken words (``"twenty five"``).

    Returns:
        ``(value, tokens_used)`` or ``(None, 0)``.
    """
    if i >= len(tokens):
        return None, 0
    if _DIGITS.fullmatch(tokens[i]):
        return float(tokens[i]), 1
    total, current, used = 0, 0, 0
    while i + used < len(tokens):
        word = tokens[i + used]
        if word in UNITS:
            current += UNITS[word]
        elif word in TENS:
            current += TENS[word]
        elif word == "hundred":
            current = (current or 1) * 100
        elif word == "thousand":
            total += (current or 1) * 1000
            current = 0
        else:
            break
        used += 1
    if used == 0:
        return None, 0
    return float(total + current), used


def parse_amount(tokens: list[str], i: int) -> tuple[float | None, int]:
    """Read a money amount.

    Handles ``"25"``, ``"25 dollars"``, ``"forty two dollars and fifty cents"``
    and ``"50 cents"``.

    Returns:
        ``(amount_rounded_to_cents, tokens_used)`` or ``(None, 0)``.
    """
    value, used = parse_number(tokens, i)
    if value is None:
        return None, 0
    j = i + used
    if j < len(tokens) and tokens[j] in ("dollar", "dollars", "bucks"):
        j += 1
        if j < len(tokens) and tokens[j] == "and":
            cents, c_used = parse_number(tokens, j + 1)
            end = j + 1 + c_used
            if cents is not None and end < len(tokens) and tokens[end] in ("cent", "cents"):
                return round(value + cents / 100, 2), end + 1 - i
        return round(value, 2), j - i
    if j < len(tokens) and tokens[j] in ("cent", "cents"):
        return round(value / 100, 2), j + 1 - i
    return round(value, 2), j - i


def parse_date(tokens: list[str], i: int, today: dt.date) -> tuple[dt.date | None, int]:
    """Read a spoken date.

    Understands ``today``, ``yesterday``, and ``<month> <day> [<year>]``
    (e.g. ``"october 30"``, ``"october thirty 2026"``, ``"march 3rd"``).
    A month-day without a year means the current year.

    Returns:
        ``(date, tokens_used)`` or ``(None, 0)``.
    """
    if i >= len(tokens):
        return None, 0
    word = tokens[i]
    if word == "today":
        return today, 1
    if word == "yesterday":
        return today - dt.timedelta(days=1), 1
    if word not in MONTHS:
        return None, 0

    day, used = parse_number(tokens, i + 1)
    if day is None or day != int(day):
        return None, 0
    end = i + 1 + used
    if end < len(tokens) and tokens[end] in _ORDINAL_SUFFIXES:
        end += 1
    year = today.year
    if end < len(tokens) and re.fullmatch(r"\d{4}", tokens[end]):
        year, end = int(tokens[end]), end + 1
    try:
        return dt.date(year, MONTHS[word], int(day)), end - i
    except ValueError:  # e.g. "february thirty"
        return None, 0
