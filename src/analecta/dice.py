"""Plain dice notation: `2d6+3`, `d20-1`, `4d6kh3`, `1d20+1d4+2`. A small whitelist grammar, never eval.

Pure functions with an injectable random source (anything with `randint(a, b)`), so tests are deterministic.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Protocol

MAX_EXPR_CHARS = 100
MAX_TERMS = 10
MAX_DICE = 100
MAX_SIDES = 1000
MAX_FLAT = 100_000


class DiceError(ValueError):
    """The expression cannot be rolled; the message is safe to show to a member."""


class Rng(Protocol):
    def randint(self, a: int, b: int) -> int: ...


_TERM = re.compile(r"(?:(?P<count>\d*)d(?P<sides>\d+)(?:k(?P<keep>[hl])(?P<keepn>\d*))?|(?P<flat>\d+))", re.IGNORECASE)
# A whole expression: terms joined by + or -, with optional spaces, and at least one die checked separately.
_WHOLE = re.compile(r"\s*[+-]?\s*(?:\d*d\d+(?:k[hl]\d*)?|\d+)(?:\s*[+-]\s*(?:\d*d\d+(?:k[hl]\d*)?|\d+))*\s*", re.IGNORECASE)
_HAS_DIE = re.compile(r"\d*d\d+", re.IGNORECASE)


def looks_like_dice(text: str) -> bool:
    """True when the whole text is dice notation with at least one die (so `Religion -2` is not)."""
    return bool(_WHOLE.fullmatch(text)) and bool(_HAS_DIE.search(text))


@dataclass
class Term:
    sign: int
    count: int = 0            # 0 for a flat number
    sides: int = 0
    flat: int = 0
    keep: str = ""            # "h" or "l" or ""
    keep_n: int = 0
    rolls: list[int] = field(default_factory=list)
    dropped: list[bool] = field(default_factory=list)

    @property
    def value(self) -> int:
        if not self.count:
            return self.sign * self.flat
        return self.sign * sum(r for r, d in zip(self.rolls, self.dropped) if not d)

    @property
    def is_die(self) -> bool:
        return self.count > 0


@dataclass
class DiceResult:
    expression: str
    terms: list[Term]
    total: int

    def breakdown(self) -> str:
        """`2d6 [4, 2] + 3`, with dropped dice struck through."""
        out: list[str] = []
        for i, t in enumerate(self.terms):
            if t.is_die:
                shown = ", ".join(f"~~{r}~~" if d else str(r) for r, d in zip(t.rolls, t.dropped))
                label = f"{t.count}d{t.sides}" + (f"k{t.keep}{t.keep_n}" if t.keep else "")
                body = f"{label} [{shown}]"
            else:
                body = str(t.flat)
            if i == 0:
                out.append(body if t.sign > 0 else f"-{body}")
            else:
                out.append(f"{'+' if t.sign > 0 else '-'} {body}")
        return " ".join(out)


def parse(expression: str) -> list[Term]:
    text = " ".join(expression.split())
    if not text:
        raise DiceError("Give me something to roll, for example `1d20+5`.")
    if len(text) > MAX_EXPR_CHARS:
        raise DiceError(f"That expression is too long ({MAX_EXPR_CHARS} characters at most).")
    if not _WHOLE.fullmatch(text):
        raise DiceError("I can only roll dice notation such as `1d20+5`, `2d6+1d4-1` or `4d6kh3`.")
    terms: list[Term] = []
    sign = 1
    pos = 0
    text = text.replace(" ", "")
    while pos < len(text):
        if text[pos] in "+-":
            sign = 1 if text[pos] == "+" else -1
            pos += 1
        m = _TERM.match(text, pos)
        if not m:  # unreachable after _WHOLE, but never loop forever
            raise DiceError("I could not read that dice expression.")
        pos = m.end()
        if m.group("flat") is not None:
            flat = int(m.group("flat"))
            if flat > MAX_FLAT:
                raise DiceError("That number is too large.")
            terms.append(Term(sign=sign, flat=flat))
        else:
            count = int(m.group("count") or 1)
            sides = int(m.group("sides"))
            if count < 1 or sides < 1:
                raise DiceError("Dice need at least one die with at least one side.")
            if sides > MAX_SIDES:
                raise DiceError(f"Dice can have at most {MAX_SIDES} sides.")
            term = Term(sign=sign, count=count, sides=sides)
            if m.group("keep"):
                term.keep = m.group("keep").lower()
                term.keep_n = int(m.group("keepn") or 1)
                if not 1 <= term.keep_n <= count:
                    raise DiceError(f"You can only keep between 1 and {count} of {count} dice.")
            terms.append(term)
        sign = 1
    if len(terms) > MAX_TERMS:
        raise DiceError(f"Use at most {MAX_TERMS} terms.")
    if sum(t.count for t in terms) > MAX_DICE:
        raise DiceError(f"Roll at most {MAX_DICE} dice at once.")
    return terms


def roll(expression: str, rng: Rng | None = None) -> DiceResult:
    rng = rng or random.SystemRandom()
    terms = parse(expression)
    for t in terms:
        if not t.is_die:
            continue
        t.rolls = [rng.randint(1, t.sides) for _ in range(t.count)]
        t.dropped = [False] * t.count
        if t.keep:
            order = sorted(range(t.count), key=lambda i: t.rolls[i], reverse=(t.keep == "h"))
            for i in order[t.keep_n:]:
                t.dropped[i] = True
    return DiceResult(expression=" ".join(expression.split()), terms=terms, total=sum(t.value for t in terms))


def roll_d20(rng: Rng | None = None) -> int:
    return (rng or random.SystemRandom()).randint(1, 20)
