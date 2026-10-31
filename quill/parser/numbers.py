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


WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
    "twentieth": 20, "thirtieth": 30,
}
_DAY_PART_WORDS = frozenset({"morning", "afternoon", "evening", "night"})   # "yesterday morning": same day
_UNITS_OF_TIME = {"day": 1, "days": 1, "week": 7, "weeks": 7, "month": "month", "months": "month",
                  "year": "year", "years": "year"}
_SMALL_COUNTS = {"a": 1, "an": 1, "one": 1, "a couple of": 2, "couple": 2}
#: A spoken date more than this many days ahead, with no year said, is taken to be last year's (inventory
#: is logged after the fact: "december 25" said in October means the one that has passed).
_FUTURE_GRACE_DAYS = 30


def parse_ordinal(tokens: list[str], i: int) -> tuple[int | None, int]:
    """Read a day of the month said as an ordinal ("third", "twenty first", "3rd") or a plain number ("3").

    Returns:
        ``(day, tokens_used)`` or ``(None, 0)``. Only 1 to 31 are accepted.
    """
    if i >= len(tokens):
        return None, 0
    word = tokens[i]
    glued = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)", word)
    if glued:
        day, used = int(glued.group(1)), 1
    elif word in _ORDINAL_WORDS:
        day, used = _ORDINAL_WORDS[word], 1
    elif word in ("twenty", "thirty") and i + 1 < len(tokens) and tokens[i + 1] in _ORDINAL_WORDS \
            and _ORDINAL_WORDS[tokens[i + 1]] < 10:
        day, used = TENS[word] + _ORDINAL_WORDS[tokens[i + 1]], 2           # "twenty first"
    else:
        number, used = parse_number(tokens, i)
        if number is None or number != int(number):
            return None, 0
        day = int(number)
        if i + used < len(tokens) and tokens[i + used] in _ORDINAL_SUFFIXES:
            used += 1
    return (day, used) if 1 <= day <= 31 else (None, 0)


def parse_year(tokens: list[str], i: int) -> tuple[int | None, int]:
    """Read a year: ``"2026"``, ``"twenty twenty six"``, ``"nineteen ninety nine"``, ``"two thousand and five"``."""
    if i >= len(tokens):
        return None, 0
    if re.fullmatch(r"(19|20)\d{2}", tokens[i]):
        return int(tokens[i]), 1
    if tokens[i] == "two" and i + 1 < len(tokens) and tokens[i + 1] == "thousand":
        j = i + 2
        if j < len(tokens) and tokens[j] == "and":
            j += 1
        rest, used = parse_number(tokens, j)
        if rest is not None and rest < 100:
            return 2000 + int(rest), j + used - i
        return 2000, 2
    if tokens[i] in ("nineteen", "twenty"):
        century = 1900 if tokens[i] == "nineteen" else 2000
        if i + 1 < len(tokens) and tokens[i + 1] in TENS:                    # "twenty twenty six", "nineteen ninety"
            tens = TENS[tokens[i + 1]]
            ones = 0
            used = 2
            if i + 2 < len(tokens) and tokens[i + 2] in UNITS and UNITS[tokens[i + 2]] < 10:
                ones, used = UNITS[tokens[i + 2]], 3
            return century + tens + ones, used
        if i + 1 < len(tokens) and tokens[i + 1] in UNITS and tokens[i + 1] != "zero" and UNITS[tokens[i + 1]] >= 1:
            return century + UNITS[tokens[i + 1]], 2                          # "twenty five" is rarely a year; keep strict
    return None, 0


def _shift_months(day: dt.date, months: int) -> dt.date:
    """*day* moved by *months* calendar months, the day of the month trimmed to fit ("31 march" - 1 month = 28/29 feb)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31,
            30, 31][month - 1]
    return dt.date(year, month, min(day.day, last))


def _with_year_rule(month: int, day: int, today: dt.date) -> dt.date | None:
    """A month and day said without a year: this year, or last year if that would be well in the future."""
    for year in (today.year, today.year - 1):
        try:
            candidate = dt.date(year, month, day)
        except ValueError:
            continue
        if year == today.year and (candidate - today).days > _FUTURE_GRACE_DAYS:
            continue
        return candidate
    return None


def parse_date(tokens: list[str], i: int, today: dt.date) -> tuple[dt.date | None, int]:
    """Read a spoken date and give the real date.

    Understands:

    * ``today``, ``tonight``, ``yesterday``, ``tomorrow``, ``day before yesterday``, ``day after tomorrow``
      (a following "morning / afternoon / evening / night" is part of it);
    * ``<n> days / weeks / months / years ago`` ("three weeks ago", "a month ago", "a couple of days ago");
    * ``last / next / this`` + a weekday ("last friday") or ``week / month / year``;
    * a bare weekday ("friday": the most recent one, today included);
    * ``<month> <day> [year]`` ("october thirty", "march 3rd 2026") and ``<day> [of] <month> [year]``
      ("the third of march", "twenty first june twenty twenty five").

    A month and day with no year mean this year, or last year when that date is more than a month ahead.

    Returns:
        ``(date, tokens_used)`` or ``(None, 0)``.
    """
    if i >= len(tokens):
        return None, 0
    word = tokens[i]
    day, used = _relative_day(tokens, i, today)
    if day is None:
        day, used = _relative_span(tokens, i, today)
    if day is None:
        day, used = _weekday(tokens, i, today)
    if day is None:
        day, used = _calendar_date(tokens, i, today)
    if day is None:
        return None, 0
    if i + used < len(tokens) and tokens[i + used] in _DAY_PART_WORDS and word != "this":
        used += 1                                                          # "yesterday morning"
    return day, used


def _relative_day(tokens: list[str], i: int, today: dt.date) -> tuple[dt.date | None, int]:
    """today / yesterday / tomorrow and the "day before / after" forms."""
    word = tokens[i]
    if word in ("today", "tonight"):
        return today, 1
    if word == "yesterday":
        return today - dt.timedelta(days=1), 1
    if word == "tomorrow":
        return today + dt.timedelta(days=1), 1
    if tokens[i:i + 3] == ["day", "before", "yesterday"]:
        return today - dt.timedelta(days=2), 3
    if tokens[i:i + 3] == ["day", "after", "tomorrow"]:
        return today + dt.timedelta(days=2), 3
    return None, 0


def _relative_span(tokens: list[str], i: int, today: dt.date) -> tuple[dt.date | None, int]:
    """"three weeks ago", "a month ago", "last month", "next friday", "this week" ..."""
    word = tokens[i]
    if word in ("last", "next", "this") and i + 1 < len(tokens):
        unit = tokens[i + 1]
        sign = {"last": -1, "next": 1, "this": 0}[word]
        if unit in WEEKDAYS:
            if word == "this":
                return _nearest_weekday(today, WEEKDAYS[unit], forward=True), 2
            return _nearest_weekday(today, WEEKDAYS[unit], forward=sign > 0, strict=True), 2
        if unit in ("week", "month", "year"):
            if unit == "week":
                return today + dt.timedelta(days=7 * sign), 2
            return _shift_months(today, sign * (12 if unit == "year" else 1)), 2
        return None, 0
    count, used = None, 0
    if tokens[i:i + 3] == ["a", "couple", "of"]:
        count, used = 2, 3
    elif word in ("a", "an", "couple"):
        count, used = (2, 1) if word == "couple" else (1, 1)
    else:
        number, n = parse_number(tokens, i)
        if number is not None and number == int(number):
            count, used = int(number), n
    if count is None:
        return None, 0
    if i + used + 1 < len(tokens) and tokens[i + used] in _UNITS_OF_TIME and tokens[i + used + 1] == "ago":
        unit = _UNITS_OF_TIME[tokens[i + used]]
        end = used + 2
        if unit == 1 or unit == 7:
            return today - dt.timedelta(days=count * (7 if tokens[i + used].startswith("week") else 1)), end
        return _shift_months(today, -count * (12 if unit == "year" else 1)), end
    return None, 0


def _nearest_weekday(today: dt.date, weekday: int, forward: bool, strict: bool = False) -> dt.date:
    """The closest date with *weekday* going forward or back from *today* (*strict*: not today itself)."""
    step = 1 if forward else -1
    day = today + dt.timedelta(days=step if strict else 0)
    while day.weekday() != weekday:
        day += dt.timedelta(days=step)
    return day


def _weekday(tokens: list[str], i: int, today: dt.date) -> tuple[dt.date | None, int]:
    """A bare weekday: the most recent one (today counts)."""
    if tokens[i] in WEEKDAYS:
        return _nearest_weekday(today, WEEKDAYS[tokens[i]], forward=False), 1
    return None, 0


def _calendar_date(tokens: list[str], i: int, today: dt.date) -> tuple[dt.date | None, int]:
    """"october thirty [2026]", "the third of march", "3 march 2026"."""
    word = tokens[i]
    if word in MONTHS:                                          # month first
        day, used = parse_ordinal(tokens, i + 1)
        if day is None:
            return None, 0
        end = i + 1 + used
        year, y_used = parse_year(tokens, end)
        return _build(MONTHS[word], day, year, y_used, i, end, today)
    day, used = parse_ordinal(tokens, i)                        # day first
    if day is None:
        return None, 0
    end = i + used
    if end < len(tokens) and tokens[end] == "of":
        end += 1
    if end < len(tokens) and tokens[end] in MONTHS:
        month = MONTHS[tokens[end]]
        end += 1
        year, y_used = parse_year(tokens, end)
        return _build(month, day, year, y_used, i, end, today)
    return None, 0


def _build(month: int, day: int, year: int | None, year_used: int, start: int, end: int,
           today: dt.date) -> tuple[dt.date | None, int]:
    """Make the date from its parts (a missing year follows the "this year or last" rule)."""
    try:
        if year is not None:
            return dt.date(year, month, day), end + year_used - start
        found = _with_year_rule(month, day, today)
        return (found, end - start) if found else (None, 0)
    except ValueError:                                           # e.g. "february thirty"
        return None, 0
