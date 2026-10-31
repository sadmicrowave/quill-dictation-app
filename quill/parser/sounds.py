"""Sound-alike and short-form matching, so a mis-heard word still finds the value it was meant to be.

The speech recogniser writes the *sound* it heard, so "waist" often arrives as "waste". Two helpers:

* :func:`sound_key`: a rough phonetic fingerprint (consonant skeleton with common spelling rules applied)
  that is the same for words that sound alike.
* :func:`initials_match`: whether a short code such as "M" or "XL" is the abbreviation of a spoken word or
  phrase ("medium", "extra large").

Both are only used when nothing matched exactly, and both are conservative: a wrong guess means a wrong
value written to somebody's spreadsheet.
"""

from __future__ import annotations
import difflib
import re

_VOWELS = "aeiou"

#: Spelling rules applied in order before the vowels are dropped (a small Metaphone).
_RULES = (
    (r"^kn|^gn|^pn|^wr", lambda m: m.group()[1]),
    (r"igh", "i"), (r"ph", "f"), (r"gh(?=t)", ""), (r"ck", "k"), (r"dg", "j"), (r"tch", "ch"),
    (r"sch", "sk"), (r"c(?=[eiy])", "s"), (r"c", "k"), (r"q", "k"), (r"x", "ks"),
    (r"z", "s"), (r"wh", "w"), (r"mb$", "m"),
)


def sound_key(word: str) -> str:
    """A phonetic fingerprint: ``sound_key("waist") == sound_key("waste") == "wst"``."""
    text = re.sub(r"[^a-z]", "", word.lower())
    if not text:
        return ""
    for pattern, repl in _RULES:
        text = re.sub(pattern, repl, text)
    head, rest = text[0], text[1:]
    rest = re.sub(r"[aeiouyhw]", "", rest)             # vowels and the weak letters carry little of the sound
    key = head + rest
    return re.sub(r"(.)\1+", r"\1", key)               # a doubled letter sounds like one


def sounds_like(heard: str, known: str, min_length: int = 4) -> bool:
    """True if *heard* is probably a mis-hearing of *known*.

    Both words must have at least *min_length* letters (short words are too easily confused). They match
    when they share a phonetic key and also look reasonably alike, or when they are very close in spelling.
    """
    a, b = heard.lower(), known.lower()
    if a == b or len(a) < min_length or len(b) < min_length:
        return False
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if ratio >= 0.9 or (ratio >= 0.85 and min(len(a), len(b)) >= 6):
        return True
    return sound_key(a) == sound_key(b) and ratio >= 0.7


def closest_choice(heard: str, choices: list[str]) -> str | None:
    """Which of a short list of *choices* a heard word was probably meant to be, or None.

    The choices are what the user can see on screen (the Choose Column list), so the answer is far more
    likely to be one of them than a random word: "sighs" is "Size" there. The bar is lower than for an open
    guess, but the winner must be clearly ahead of the runner-up and nothing is chosen on a tie.
    """
    spoken = re.sub(r"[^a-z]", "", heard.lower())
    if len(spoken) < 3:
        return None
    scored = []
    for choice in choices:
        # the whole name, and each word of it ("depart" for Departure Date)
        parts = [re.sub(r"[^a-z]", "", choice.lower())] + [re.sub(r"[^a-z]", "", w) for w in choice.lower().split()]
        best = 0.0
        for letters in {p for p in parts if p}:
            spelling = difflib.SequenceMatcher(None, spoken, letters).ratio()
            key_a, key_b = sound_key(spoken), sound_key(letters)
            sound = difflib.SequenceMatcher(None, key_a, key_b).ratio() * 0.95
            best = max(best, max(spelling, sound) + (0.15 if key_a == key_b else 0.0))
        scored.append((best, choice))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < 0.8:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.15:
        return None
    return scored[0][1]


#: Endings removed to find a word's stem, longest first ("migrated", "migration" and "migrates" all give "migrat").
_SUFFIXES = ("ations", "ation", "ings", "ing", "ions", "ion", "ied", "ies", "ed", "es", "s")


def stem(word: str) -> str:
    """A crude stem: ``stem("purchased") == stem("purchase") == "purchas"``, ``stem("migration") == "migrat"``.

    Used to tell that a spoken word is about the same thing as a column name ("observed" and "Observation
    Date"), without any list of words for any particular subject.
    """
    text = re.sub(r"[^a-z]", "", word.lower())
    for suffix in _SUFFIXES:
        if text.endswith(suffix) and len(text) - len(suffix) >= 3:
            text = text[:-len(suffix)]
            break
    return text[:-1] if text.endswith("e") and len(text) > 3 else text


def same_subject(spoken: str, header_word: str) -> bool:
    """True if *spoken* and *header_word* look like forms of one word ("departed" / "Departure")."""
    a, b = stem(spoken), stem(header_word)
    if len(a) < 4 or len(b) < 4:
        return a == b and len(a) >= 3
    return a == b or a.startswith(b) or b.startswith(a)


def initials_match(code: str, words: list[str]) -> bool:
    """True if *code* (letters only, up to three) is the abbreviation of *words*.

    ``initials_match("XL", ["extra", "large"])`` and ``initials_match("M", ["medium"])`` are true. Each word
    contributes its first letter, except that "extra" is written X as in XL and XXL.
    """
    letters = code.lower()
    if not 1 <= len(letters) <= 3 or not letters.isalpha() or not words:
        return False
    if any(len(w) < 3 for w in words):
        return False
    return "".join("x" if w == "extra" else w[0] for w in words) == letters
