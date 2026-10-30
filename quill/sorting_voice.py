"""Voice sorting: answer the Needs-sorting list by talking, hands-free.

While voice sorting is on, everything Quill hears is read as a *chain of
sort commands* applied, in order, to the first term in the list. Each command
resolves that term, it leaves the list, the next one moves up, and the chain
continues, so you can say several answers in one breath:

    "yes   same as <value>   color   ignore"

Commands (any of the listed words):

  yes / add / ok ...............  add the term to its suggested column
  <column name> ................  add the term to that column ("color")
  add to <column> ..............  same, spelled out
  <column> same as <value> .....  alias within that column ("size same as XL");
                                   if the value isn't in that column, the column word
                                   means add and "same as" starts the next term
  same as <value> ..............  the term is another name for an existing value
  same ... (then the value) ....  wait for the value in the next phrase
  ignore / no / drop ...........  forget the term
  later / skip / pass / next ...  keep it, move it to the end of the list
  add all / ignore all .........  every term (add all: those with a column)
  undo / oops ..................  take back the last answer ("undo 3" takes back three)
  stop / done ..................  leave voice sorting

This module is pure: it only calls ``Controller.resolve_term`` and
``Controller.defer_term``; the window refreshes from the resulting events.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from quill.parser.commands import YES_WORDS
from quill.parser.numbers import parse_number
from quill.parser.tokens import display_name, tokenize
from quill.session import Decision

ADD_WORDS = YES_WORDS
IGNORE_WORDS = frozenset({"no", "nope", "nah", "ignore", "cancel", "drop", "dont", "forget",
                          "discard", "delete", "remove"})
DEFER_WORDS = frozenset({"later", "skip", "pass", "next"})
STOP_WORDS = frozenset({"stop", "done", "finished", "finish", "exit", "quit"})
SAME_WORDS = frozenset({"same", "alias", "means"})
UNDO_WORDS = frozenset({"undo", "oops", "revert"})
ALL_WORD = "all"

#: Little words ignored between commands ("same AS the <value>", "add TO color").
FILLERS = frozenset({"as", "a", "an", "the", "to", "in", "is", "it", "its", "this", "that",
                     "one", "term", "and", "then", "also", "thanks", "thank", "you"})

#: Tokens tried when a spoken letter pair should read as one value ("x l" -> "xl").
_SPELLED_MAX = 3


@dataclass
class VoiceSortResult:
    """What one spoken phrase did."""

    messages: list[str] = field(default_factory=list)
    """Plain-language outcomes, in order ("Added ‘teal’ to Color")."""
    resolved: int = 0
    """How many terms left the list."""
    finished: bool = False
    """True if the user said stop/done or the list is empty."""
    problem: bool = False
    """True if something was not understood or could not be done (plays the error cue)."""


class VoiceSorter:
    """Applies spoken command chains to the controller's pending terms.

    Args:
        controller: Anything with ``pending_terms()``, ``resolve_term(key,
            decision)``, ``defer_term(key)`` and a ``vocab`` attribute.
    """

    def __init__(self, controller) -> None:
        self._ctl = controller
        self._awaiting_value = False   # said "same" without a value; next words supply it

    # ------------------------------------------------------------------ #

    def handle(self, text: str) -> VoiceSortResult:
        """Run one recognised phrase as a chain of commands."""
        result = VoiceSortResult()
        tokens = tokenize(text)
        if self._awaiting_value and tokens and not self._is_command(tokens[0]):
            tokens = ["same", "as", *tokens]
        self._awaiting_value = False

        i = 0
        heard_command = False
        while i < len(tokens):
            pending = self._ctl.pending_terms()
            if tokens[i] in UNDO_WORDS:       # works even after the last term was answered
                heard_command = True
                i = self._undo(tokens, i + 1, result)
                continue
            if not pending:
                break
            key = pending[0]
            step = self._command(tokens, i, key, result)
            if step is None:        # not a command word: skip it
                i += 1
                continue
            heard_command = True
            i = step
            if result.finished:
                break

        if not self._ctl.pending_terms():
            result.finished = True
        if not heard_command and not result.messages:
            result.problem = True
            result.messages.append(
                "Didn't catch a command. Say yes, a column name, same as …, ignore, later, undo or done."
            )
        return result

    # ------------------------------------------------------------------ #

    def _undo(self, tokens: list[str], j: int, result: VoiceSortResult) -> int:
        """Handle "undo" or "undo <n>": step back through the answers just given."""
        count, used = parse_number(tokens, j)
        count = int(count) if count is not None and count >= 1 else 1
        messages = self._ctl.undo(count)
        result.problem = result.problem or messages == ["Nothing to undo"]
        result.messages += messages
        result.resolved -= sum(1 for m in messages if m.startswith("Undid"))
        return j + used

    def _is_command(self, word: str) -> bool:
        return (word in UNDO_WORDS or word in ADD_WORDS or word in IGNORE_WORDS or word in DEFER_WORDS
                or word in STOP_WORDS or word in SAME_WORDS or word == ALL_WORD)

    def _list_column_at(self, tokens: list[str], i: int):
        """``(column, length)`` if a *list* column's name is spoken at ``tokens[i]``."""
        hit = self._ctl.vocab.field_at(tokens, i)
        if hit and self._ctl.vocab.is_list_column(hit[0]):
            return hit
        return None

    def _command(self, tokens: list[str], i: int, key, result: VoiceSortResult) -> int | None:
        """Run the command starting at ``tokens[i]``; return the next index, or None."""
        word, (suggested, term) = tokens[i], key

        if word in STOP_WORDS:
            result.finished = True
            result.messages.append("Done sorting by voice")
            return len(tokens)

        if word in (*IGNORE_WORDS, *ADD_WORDS) and i + 1 < len(tokens) and tokens[i + 1] == ALL_WORD:
            self._bulk(add=word in ADD_WORDS, result=result)
            return i + 2

        if word in IGNORE_WORDS:
            self._ctl.resolve_term(key, Decision.ignore())
            result.resolved += 1
            result.messages.append(f"Ignored ‘{term}’")
            return i + 1

        if word in DEFER_WORDS:
            self._ctl.defer_term(key)
            result.messages.append(f"Left ‘{term}’ for later")
            return i + 1

        if word in ADD_WORDS:
            j = i + 1
            while j < len(tokens) and tokens[j] in FILLERS:
                j += 1
            named = self._list_column_at(tokens, j) if j < len(tokens) else None
            column = named[0] if named else suggested
            used = named[1] if named else 0
            self._add(key, column, result)
            return j + used if named else i + 1

        column_hit = self._list_column_at(tokens, i)
        if column_hit:
            column, length = column_hit
            if self._is_alias_in_column(tokens, i + length, column):   # "size same as xl"
                return self._same(tokens, i + length + 1, key, column, result)
            self._add(key, column, result)          # "color" (then perhaps a new "same as …")
            return i + length

        if word in SAME_WORDS:
            return self._same(tokens, i + 1, key, suggested, result)
        return None

    # ------------------------------------------------------------------ #

    def _is_alias_in_column(self, tokens: list[str], j: int, column: str) -> bool:
        """True if ``tokens[j:]`` reads "same as <a value of *column*>".

        Disambiguates "color same as 1990s": if 1990s isn't a Color value, the
        column word meant *add*, and "same as 1990s" is for the next term.
        """
        if j >= len(tokens) or tokens[j] not in SAME_WORDS:
            return False
        k = j + 1
        while k < len(tokens) and tokens[k] in FILLERS:
            k += 1
        return k < len(tokens) and self._match_value(tokens, k, column) is not None

    def _add(self, key, column: str | None, result: VoiceSortResult) -> None:
        term = key[1]
        if not column:
            result.problem = True
            result.messages.append(f"Which column is ‘{term}’? Say a column name.")
            return
        self._ctl.resolve_term(key, Decision.add(column, display_name(term)))
        result.resolved += 1
        result.messages.append(f"Added ‘{term}’ to {column}")

    def _same(self, tokens: list[str], j: int, key, column: str | None,
              result: VoiceSortResult) -> int:
        """Handle "same as <value>" starting after the keyword at ``tokens[j-1]``."""
        term = key[1]
        while j < len(tokens) and tokens[j] in FILLERS:
            j += 1
        if j >= len(tokens):
            self._awaiting_value = True
            result.messages.append(f"‘{term}’ is the same as which value? Say it now.")
            return j
        found = self._match_value(tokens, j, column)
        if found is None:
            result.problem = True
            where = f" in {column}" if column else ""
            result.messages.append(f"I don't have ‘{' '.join(tokens[j:j + 2])}’{where}. "
                                   "Try again, or say ignore.")
            return len(tokens)
        found_column, canonical, used = found
        self._ctl.resolve_term(key, Decision.alias(found_column, canonical))
        result.resolved += 1
        result.messages.append(f"‘{term}’ now means {canonical} ({found_column})")
        return j + used

    def _match_value(self, tokens: list[str], j: int, column: str | None):
        """Find an existing list value spoken at ``tokens[j]``.

        Restricted to *column* when known; otherwise it must belong to exactly
        one column. Also reads spelled letters (a spoken "x l" becomes "xl") and number words.
        """
        vocab = self._ctl.vocab
        candidates: list[tuple[str, str, int]] = list(vocab.matches_at(tokens, j))
        for n in range(2, _SPELLED_MAX + 1):
            span = tokens[j:j + n]
            if len(span) == n and all(len(t) <= 2 for t in span):
                candidates += [(c, v, n) for c, v, _ in vocab.matches_at(["".join(span)], 0)]
        number, used = parse_number(tokens, j)
        if number is not None:
            text = str(int(number)) if number == int(number) else str(number)
            for col in vocab.columns():
                for value in vocab.values_for(col):
                    if value.lower() == text:
                        candidates.append((col, value, used))
        if column:
            candidates = [c for c in candidates if c[0] == column]
        if not candidates:
            return None
        best = max(c[2] for c in candidates)
        top = [c for c in candidates if c[2] == best]
        return top[0] if len({c[0] for c in top}) == 1 else None

    def _bulk(self, add: bool, result: VoiceSortResult) -> None:
        count = 0
        with self._ctl.batch("Added terms" if add else "Ignored terms"):   # one undo for all
            for key in list(self._ctl.pending_terms()):
                if add and not key[0]:
                    continue
                decision = Decision.add(key[0], display_name(key[1])) if add else Decision.ignore()
                self._ctl.resolve_term(key, decision)
                count += 1
        result.resolved += count
        result.messages.append(f"{'Added' if add else 'Ignored'} {count} term{'s' if count != 1 else ''}")
