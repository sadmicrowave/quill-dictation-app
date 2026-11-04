# ruff: noqa: SIM905  (the word lists are easier to read and edit as text blocks)
"""Words that are part of how people talk, never a value worth adding to a list.

The speech recogniser hears everything, so "got it yesterday" arrives with the useful words. Anything in
:data:`FILLER_WORDS` is skipped when Quill looks for *new* values to sort, so the Term Helper is not asked
about "got" or "really". The list is deliberately only function words, everyday verbs, adverbs and time
words: adjectives and nouns (and words that can be a condition or a status, such as "used", "worn" or "sold") are never here, because they are exactly what a new list value looks like
("teal", "vintage"). A word that *is* in the workbook is matched before this list is consulted.
"""

from __future__ import annotations

#: Pronouns, articles, prepositions, conjunctions and other small words.
_FUNCTION_WORDS = """
a an the and or but nor so yet for of to in on at by from with without within into onto upon over under
above below across along around about against between through during before after since until while as
than that this these those there here it its it's i me my mine we us our you your he him his she her they
them their what which who whom whose when where why how if then else because though although unless
whether both either neither each every any some all most more less much many few several other another
such own same only just even also still already again once twice ever never always often sometimes
usually maybe perhaps probably actually really very quite rather pretty too enough almost nearly
up down out off away back apart together forward ahead aside inside outside
exactly mainly mostly roughly around approximately basically simply totally completely
""".split()

#: Everyday verbs and their forms (what a speaker says *about* the item, not a property of it).
_COMMON_VERBS = """
be am is are was were been being have has had having do does did done doing get gets got gotten getting
go goes went gone going come comes came coming make makes made making take takes took taken taking give
gives gave given giving put puts putting let lets see sees saw seen seeing look looks
looked looking seem seems seemed find finds found finding keep keeps kept know knows knew known think
thinks thought want wants wanted need needs needed use uses using try tries tried say says said tell
tells told call calls called ask asks asked show shows showed shown turn turns turned bring brings brought
buy buys bought picked pick picks pickup grab grabbed grabs receive received
purchase purchased acquire acquired sell sells selling add added adding mean means meant like likes
liked love loved hate wear wears wore feel feels felt leave leaves become becomes became send sent write wrote read reads can could may might must shall should will would
""".split()

#: Time and place words that say nothing about the item itself. Words that name a *date* (yesterday, today,
#: tomorrow, weekdays, months, "ago", week / month / year) are deliberately not here: the date parser reads
#: them and the value goes into a date column (see :func:`quill.parser.numbers.parse_date`).
_TIME_AND_PLACE = """
now morning afternoon evening night later soon recently earlier lately here there somewhere anywhere everywhere
""".split()

#: Conversation noise.
_NOISE = """
um uh er hmm okay ok yeah yes no nope yep well so anyway like actually literally honestly
please thanks thank sure alright oh ah
""".split()

FILLER_WORDS: frozenset[str] = frozenset(_FUNCTION_WORDS + _COMMON_VERBS + _TIME_AND_PLACE + _NOISE)


def is_filler(word: str) -> bool:
    """True if *word* (lowercase) is everyday speech that is never a new list value."""
    return word in FILLER_WORDS


#: Verbs that only help another verb ("was", "have", "will"): never worth learning as a column.
_HELPER_VERBS = frozenset("""
be am is are was were been being have has had having do does did done doing can could may might must shall should will would
""".split())

#: Words a learned link can never be made from: the small function words, noise and time words, and helper verbs. Everyday
#: verbs are *not* here: "sold", "bought" and "spotted" are exactly what tells a date column apart.
LINK_STOPWORDS: frozenset[str] = frozenset(_FUNCTION_WORDS + _NOISE + _TIME_AND_PLACE) | _HELPER_VERBS


def is_link_stopword(word: str) -> bool:
    """True if *word* (lowercase) can never be learned as meaning a column."""
    return word in LINK_STOPWORDS
