"""Turn `/roll` input into a result: plain dice, or a skill, save or Perception check from a saved sheet.

Pure apart from reading the sheet store. Returns text safe to post (names are cleaned and markdown is escaped).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import dice, pf2e
from .pf2e import escape
from .sheets import Companion, SheetError, SheetInfo, SheetStore

_TRAILING_MOD = re.compile(r"^(?P<stat>.*?)\s*(?P<mod>[+-]\s*\d+)\s*$")
MAX_EXTRA_MODIFIER = 1000


@dataclass(frozen=True)
class RollOutcome:
    text: str
    kind: str                      # "dice" or "sheet"
    total: int
    character: str = ""


def split_stat_and_modifier(what: str) -> tuple[str, int]:
    """`Religion -2` -> ("Religion", -2); `Dwarven Lore +1` -> ("Dwarven Lore", 1); `Will` -> ("Will", 0)."""
    text = " ".join(what.split())
    m = _TRAILING_MOD.match(text)
    if not m:
        return text, 0
    mod = int(m.group("mod").replace(" ", ""))
    if abs(mod) > MAX_EXTRA_MODIFIER:
        raise SheetError("That extra modifier is too large.")
    return m.group("stat").strip(), mod


def _signed(value: int) -> str:
    return f"+ {value}" if value >= 0 else f"- {-value}"


def roll_dice(expression: str, rng: dice.Rng | None = None) -> RollOutcome:
    result = dice.roll(expression, rng)
    return RollOutcome(f"\N{GAME DIE} `{result.expression}`: {result.breakdown()} = **{result.total}**", "dice", result.total)


def pick_character(store: SheetStore, caller_id: int, character: str | None) -> SheetInfo:
    """The named character, or else the one the caller is registered to."""
    if character and character.strip():
        return store.get(character)
    info = store.character_for(caller_id)
    if info is None:
        raise SheetError("You have no registered character. Register one with `/character register`, add your sheet with "
                         "`/sheet add`, or name a character with the `character` option.")
    return info


def pick_target(store: SheetStore, caller_id: int, character: str | None,
                as_companion: bool = False) -> tuple[SheetInfo, Companion | None]:
    """Who is rolling: a character, or a companion (named in `character`, or the caller's own with `as_companion`)."""
    named = character.strip() if character and character.strip() else ""
    if named:
        sheet = store.find(named)
        comps = store.find_companions(named)
        if len(comps) + (1 if sheet else 0) > 1:
            raise SheetError(f"More than one saved character or companion is called {escape(named)}. "
                             "Ask a GM to rename one of them.")
        if comps:
            return comps[0].character, comps[0]
        if sheet is None:
            raise SheetError(f"I have no saved character or companion called {escape(named)}. "
                             "`/character list` shows who I know.")
        info = sheet
    else:
        info = pick_character(store, caller_id, None)
    if not as_companion:
        return info, None
    comps = store.companions(info)
    if not comps:
        raise SheetError(f"{escape(info.name)} has no companion saved. Add one with `/companion add`.")
    if len(comps) > 1:
        raise SheetError(f"{escape(info.name)} has several companions ({', '.join(escape(c.name) for c in comps)}). "
                         "Roll for one by name with the `character` option.")
    return info, comps[0]


def roll_sheet(store: SheetStore, caller_id: int, what: str, character: str | None = None,
               rng: dice.Rng | None = None, as_companion: bool = False) -> RollOutcome:
    stat_text, extra = split_stat_and_modifier(what)
    info, companion = pick_target(store, caller_id, character, as_companion)
    build = store.build(info)
    check = pf2e.resolve(build, stat_text, companion.abilities if companion else None)
    who = companion or info
    if check is None:
        sample = ", ".join(pf2e.stat_names(build, companion is not None)[:24])
        raise SheetError(f"I do not know a roll called {escape(stat_text) or 'that'} for {escape(who.name)}. "
                         f"Try dice such as `1d20+5`, or one of: {sample}.")
    die = dice.roll_d20(rng)
    total = die + check.total + extra
    pieces = [f"d20 [{die}] {_signed(check.total)} ({check.label})"]
    if extra:
        pieces.append(f"{_signed(extra)} (extra modifier)")
    note = ""
    if die == 20:
        note = " \N{SPARKLES} natural 20"
    elif die == 1:
        note = " natural 1"
    source = (f"from saved sheet ({escape(companion.kind)} of {escape(info.name)})" if companion
              else "(from saved sheet)")
    text = (f"\N{GAME DIE} **{escape(who.name)}** \u00b7 {escape(check.label)} _{source}_\n"
            f"{' '.join(pieces)} = **{total}**{note}\n"
            f"_{escape(check.label)} {check.total:+d}: {check.describe()}_")
    return RollOutcome(text, "sheet", total, who.name)


def roll(store: SheetStore, caller_id: int, what: str, character: str | None = None,
         rng: dice.Rng | None = None, as_companion: bool = False) -> RollOutcome:
    what = " ".join((what or "").split())
    if not what:
        raise SheetError("Tell me what to roll: dice such as `1d20+5`, or a skill such as `Religion -2`.")
    if dice.looks_like_dice(what):
        try:
            return roll_dice(what, rng)
        except dice.DiceError as exc:
            raise SheetError(str(exc)) from None
    return roll_sheet(store, caller_id, what, character, rng, as_companion)

