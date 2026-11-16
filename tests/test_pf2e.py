from __future__ import annotations

import json
from pathlib import Path

import pytest

from analecta import pf2e

FIXTURE = Path(__file__).parent / "fixtures" / "sheets" / "synthetic_pathbuilder.json"


@pytest.fixture()
def build():
    return pf2e.build_of(json.loads(FIXTURE.read_text()))


def total(build, name):
    check = pf2e.resolve(build, name)
    assert check is not None, name
    return check.total


def test_trained_expert_and_untrained_maths(build):
    assert total(build, "Religion") == 4 + 5 + 4 + 1       # expert + level + Wis + item bonus
    assert total(build, "Athletics") == 2 + 5 + 0           # trained + level + Str
    assert total(build, "Acrobatics") == 0 + 2              # untrained adds no level, only Dex


def test_item_mods_are_summed_and_penalties_count(build):
    assert total(build, "Stealth") == 0 + 2 + (-1 + 1)


def test_perception_and_saves(build):
    assert total(build, "Perception") == 2 + 5 + 4
    assert total(build, "Fortitude") == 2 + 5 + 1
    assert total(build, "Reflex") == 2 + 5 + 2
    assert total(build, "Will") == 4 + 5 + 4 + 1


def test_lores_by_several_spellings(build):
    assert total(build, "Dwarven Lore") == 2 + 5 + 0
    assert total(build, "dwarven") == 7 and total(build, "lore dwarven") == 7
    assert total(build, "Guild Lore") == 4 + 5 + 0
    assert pf2e.resolve(build, "Elven Lore") is None


def test_names_are_case_insensitive_with_aliases(build):
    assert total(build, "  RELIGION ") == total(build, "religion") == total(build, "relig")
    assert total(build, "fort") == total(build, "Fortitude") and total(build, "perc") == total(build, "perception")
    assert pf2e.resolve(build, "Bluffing") is None and pf2e.resolve(build, "") is None


def test_breakdown_parts_add_up(build):
    check = pf2e.resolve(build, "religion")
    assert sum(v for _, v in check.parts) == check.total
    assert "expert +4" in check.describe() and "level +5" in check.describe() and "Wis +4" in check.describe()


def test_ability_modifiers_round_down(build):
    assert [pf2e.ability_mod(build, a) for a in pf2e.ABILITIES] == [0, 2, 1, 0, 4, 1]
    assert pf2e.ability_mod({"abilities": {"str": 9}}, "str") == -1
    assert pf2e.ability_mod({"abilities": {"str": 8}}, "str") == -1


def test_ac_and_hit_points(build):
    assert pf2e.armour_class(build) == 20
    assert pf2e.hit_points(build) == 8 + (8 + 1) * 5


def test_defensive_reading_of_odd_data():
    odd = {"level": "7", "abilities": {"wis": "16", "str": None}, "proficiencies": {"religion": 3, "arcana": "4"},
           "mods": {"Religion": "2", "Arcana": {"x": "oops", "y": 1}}, "lores": ["bad", [1, 2], ["Sea", "x"]]}
    assert pf2e.level(odd) == 7
    assert pf2e.resolve(odd, "religion").total == 0 + 3 + 2          # rank 3 is not a rank: untrained
    assert pf2e.resolve(odd, "arcana").total == 4 + 7 + 0 + 1        # a numeric string rank is read
    assert pf2e.resolve(odd, "sea lore").total == 0 + 0
    assert pf2e.resolve({}, "stealth").total == 0
    assert pf2e.level({"level": 99}) == 20


def test_summary_is_readable_and_stays_short(build):
    text = pf2e.summary(build)
    assert "**Test Hero**" in text and "Level 5 Human Versatile Heritage Cleric" in text
    assert "HP 53" in text and "AC 20" in text and "Religion +14" in text and "Dwarven Lore +7" in text
    assert "Shield Block" in text and len(text) < 1800


def test_stat_names_include_lores(build):
    names = pf2e.stat_names(build)
    assert "Religion" in names and "Dwarven Lore" in names and "Guild Lore" in names and "Will" in names


def test_summary_escapes_markdown_and_mentions_from_every_sheet_field(build):
    build.update(name="**Bold** @everyone", ancestry="_Elf_", heritage="[x](http://e)", **{"class": "`Cleric`"},
                 background="~~Bg~~", deity="#Deity", feats=[["**Feat** <@1>", None]], lores=[["Dark*Lore", 2]])
    text = pf2e.summary(build)
    for raw in ("**Bold**", "@everyone", "_Elf_", "[x](http://e)", "`Cleric`", "~~Bg~~", "**Feat**", "Dark*Lore"):
        assert raw not in text
    assert "\\*\\*Bold\\*\\*" in text and "Dark\\*Lore" in text and "Deity: \\#Deity" in text
