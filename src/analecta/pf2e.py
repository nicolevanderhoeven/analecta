"""Pathbuilder 2e sheet maths: read an exported build defensively and work out skill, save and Perception totals.

The export holds components only (ability scores, proficiency ranks 0/2/4/6/8, item bonuses in `mods`, level), so the
totals are worked out here. Conditions, circumstance or status bonuses, armour check penalties and proficiency
from unusual feats are not in the file and are not applied; the roller types them as an extra modifier.
Everything is read with defaults: a field that is missing or of an odd type counts as zero, never an error.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
SKILLS: dict[str, str] = {
    "acrobatics": "dex", "arcana": "int", "athletics": "str", "crafting": "int", "deception": "cha",
    "diplomacy": "cha", "intimidation": "cha", "medicine": "wis", "nature": "wis", "occultism": "int",
    "performance": "cha", "religion": "wis", "society": "int", "stealth": "dex", "survival": "wis",
    "thievery": "dex",
}
SAVES: dict[str, str] = {"fortitude": "con", "reflex": "dex", "will": "wis"}
ALIASES = {"fort": "fortitude", "ref": "reflex", "perc": "perception", "acro": "acrobatics", "athl": "athletics",
           "dipl": "diplomacy", "intim": "intimidation", "occ": "occultism", "perf": "performance",
           "relig": "religion", "soc": "society", "thiev": "thievery", "surv": "survival", "med": "medicine",
           "decep": "deception", "craft": "crafting"}
RANK_NAMES = {0: "untrained", 2: "trained", 4: "expert", 6: "master", 8: "legendary"}
_RANK_STEPS = (0, 2, 4, 6, 8)


def escape(text: str) -> str:
    """Neutralise markdown and mentions in free text that came from a sheet or a member."""
    out = re.sub(r"([\\*_`~|>\[\]()#])", r"\\\1", text)
    return out.replace("@", "@\u200b")


def as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return default
    return default


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def build_of(sheet: dict) -> dict:
    return _dict(sheet.get("build"))


def level(build: dict) -> int:
    return max(1, min(20, as_int(build.get("level"), 1)))


def ability_mod(build: dict, ability: str) -> int:
    score = as_int(_dict(build.get("abilities")).get(ability), 10)
    return (score - 10) // 2


def rank_of(build: dict, key: str) -> int:
    raw = as_int(_dict(build.get("proficiencies")).get(key))
    return raw if raw in _RANK_STEPS else 0


def lores(build: dict) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    raw = build.get("lores")
    for row in raw if isinstance(raw, list) else []:
        if isinstance(row, (list, tuple)) and len(row) >= 2 and isinstance(row[0], str) and _text(row[0]):
            rank = as_int(row[1])
            out.append((_text(row[0]), rank if rank in _RANK_STEPS else 0))
    return out


def item_bonus(build: dict, *names: str) -> int:
    """Sum of every numeric value recorded under `mods` for the stat (item bonuses, and penalties if recorded)."""
    wanted = {n.lower() for n in names}
    total = 0
    for key, sources in _dict(build.get("mods")).items():
        if isinstance(key, str) and key.strip().lower() in wanted:
            if isinstance(sources, dict):
                total += sum(as_int(v) for v in sources.values())
            else:
                total += as_int(sources)
    return total


@dataclass(frozen=True)
class Check:
    label: str                       # "Religion", "Will", "Dwarven Lore"
    total: int
    parts: tuple[tuple[str, int], ...]

    def describe(self) -> str:
        return ", ".join(f"{name} {value:+d}" for name, value in self.parts)


def _check(build: dict, label: str, rank: int, ability: str, extra_names: tuple[str, ...]) -> Check:
    lvl = level(build)
    prof = rank + lvl if rank > 0 else 0
    mod = ability_mod(build, ability)
    item = item_bonus(build, *extra_names)
    parts = [(RANK_NAMES[rank], rank)]
    if rank > 0:
        parts.append(("level", lvl))
    parts.append((ability.capitalize(), mod))
    if item:
        parts.append(("item and other", item))
    return Check(label, prof + mod + item, tuple(parts))


def _normal(text: str) -> str:
    return " ".join(text.lower().replace("_", " ").split())


def resolve(build: dict, text: str) -> Check | None:
    """The check a typed name refers to: a skill, Perception, a save, or a Lore (`Dwarven Lore`, `lore dwarven`)."""
    name = _normal(text)
    if not name:
        return None
    name = ALIASES.get(name, name)
    if name in SKILLS:
        return _check(build, name.capitalize(), rank_of(build, name), SKILLS[name], (name,))
    if name == "perception":
        return _check(build, "Perception", rank_of(build, "perception"), "wis", ("perception",))
    if name in SAVES:
        return _check(build, name.capitalize(), rank_of(build, name), SAVES[name], (name,))
    bare = re.sub(r"^lore\s+|\s+lore$", "", name).strip()
    matches = [(n, r) for n, r in lores(build) if re.sub(r"\s+lore$", "", _normal(n)) == bare]
    if matches and bare:
        lore_name, rank = matches[0]
        label = lore_name if lore_name.lower().endswith("lore") else f"{lore_name} Lore"
        return _check(build, label, rank, "int", (lore_name, label))
    return None


def stat_names(build: dict) -> list[str]:
    """Every stat that can be rolled, for help text and autocomplete."""
    names = [s.capitalize() for s in SKILLS] + ["Perception"] + [s.capitalize() for s in SAVES]
    for lore_name, _ in lores(build):
        names.append(lore_name if lore_name.lower().endswith("lore") else f"{lore_name} Lore")
    return names


def armour_class(build: dict) -> int | None:
    ac = _dict(build.get("acTotal")).get("acTotal")
    return as_int(ac) if ac is not None else None


def hit_points(build: dict) -> int:
    attrs = _dict(build.get("attributes"))
    lvl = level(build)
    per_level = as_int(attrs.get("classhp")) + as_int(attrs.get("bonushpPerLevel")) + ability_mod(build, "con")
    return as_int(attrs.get("ancestryhp")) + per_level * lvl + as_int(attrs.get("bonushp"))


def summary(build: dict) -> str:
    """A readable sheet summary (plain markdown, no mentions)."""
    name = escape(_text(build.get("name")) or "Unnamed")
    ident = " ".join(p for p in (f"Level {level(build)}", escape(_text(build.get("ancestry"))), escape(_text(build.get("heritage"))),
                                 escape(_text(build.get("class")))) if p)
    lines = [f"**{name}** — {ident}"]
    background = escape(_text(build.get("background")))
    deity = escape(_text(build.get("deity")))
    extra = [p for p in (f"Background: {background}" if background else "", f"Deity: {deity}" if deity and deity.lower() != "not set" else "") if p]
    if extra:
        lines.append(" · ".join(extra))
    lines.append("Abilities: " + ", ".join(f"{a.capitalize()} {as_int(_dict(build.get('abilities')).get(a), 10)} ({ability_mod(build, a):+d})" for a in ABILITIES))
    ac = armour_class(build)
    lines.append(f"HP {hit_points(build)}" + (f" · AC {ac}" if ac is not None else ""))
    perception = resolve(build, "perception")
    saves = [resolve(build, s) for s in SAVES]
    lines.append("Perception " + f"{perception.total:+d}" + " · " + ", ".join(f"{c.label} {c.total:+d}" for c in saves if c))
    trained = [c for c in (resolve(build, s) for s in SKILLS) if c and rank_of(build, c.label.lower()) > 0]
    if trained:
        lines.append("Skills: " + ", ".join(f"{c.label} {c.total:+d}" for c in trained))
    lore_checks = [c for c in (resolve(build, n) for n, _ in lores(build)) if c]
    if lore_checks:
        lines.append("Lores: " + ", ".join(f"{escape(c.label)} {c.total:+d}" for c in lore_checks))
    feats = [_text(row[0]) for row in build.get("feats", []) if isinstance(row, (list, tuple)) and row and isinstance(row[0], str)] if isinstance(build.get("feats"), list) else []
    if feats:
        lines.append("Feats: " + ", ".join(escape(f) for f in feats if f))
    lines.append("_Totals are worked out from the saved sheet; conditions, armour check penalties and temporary bonuses are not included._")
    return "\n".join(lines)
