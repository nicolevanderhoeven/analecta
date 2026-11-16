from __future__ import annotations

import json
from pathlib import Path

import pytest

from analecta import rolling
from analecta.sheets import SheetError, SheetStore

FIXTURE = Path(__file__).parent / "fixtures" / "sheets" / "synthetic_pathbuilder.json"
ALEX, BLAIR = 1001, 1002


class Seq:
    def __init__(self, *values):
        self.values = list(values)

    def randint(self, a, b):
        return self.values.pop(0)


@pytest.fixture()
def store(tmp_path):
    s = SheetStore(tmp_path / "sheets")
    s.add(ALEX, FIXTURE.read_bytes())          # "Test Hero", registered to ALEX
    other = json.loads(FIXTURE.read_text())
    other["build"].update(name="Second Hero", level=1)
    s.add(BLAIR, json.dumps(other).encode())
    return s


def test_plain_dice(store):
    out = rolling.roll(store, ALEX, "1d20+5", None, Seq(14))
    assert out.kind == "dice" and out.total == 19 and "1d20 [14] + 5" in out.text and "**19**" in out.text
    assert "saved sheet" not in out.text


def test_dice_do_not_need_a_character(tmp_path):
    out = rolling.roll(SheetStore(tmp_path), 5, "2d6 + 3", None, Seq(1, 6))
    assert out.total == 10


def test_skill_roll_with_negative_modifier_uses_own_character_by_default(store):
    out = rolling.roll(store, ALEX, "Religion -2", None, Seq(10))
    assert out.kind == "sheet" and out.character == "Test Hero"
    assert out.total == 10 + 14 - 2
    for part in ("from saved sheet", "d20 [10] + 14 (Religion)", "- 2 (extra modifier)", "**22**", "expert +4", "level +5", "Wis +4"):
        assert part in out.text, part


def test_skill_roll_without_modifier_and_with_positive_and_spaced_modifier(store):
    assert rolling.roll(store, ALEX, "Will", None, Seq(1)).total == 1 + 14
    assert rolling.roll(store, ALEX, "athletics +3", None, Seq(5)).total == 5 + 7 + 3
    assert rolling.roll(store, ALEX, "Athletics - 1", None, Seq(5)).total == 5 + 7 - 1
    assert rolling.roll(store, ALEX, "Dwarven Lore +1", None, Seq(5)).total == 5 + 7 + 1


def test_natural_20_and_1_are_noted(store):
    assert "natural 20" in rolling.roll(store, ALEX, "Stealth", None, Seq(20)).text
    assert "natural 1" in rolling.roll(store, ALEX, "Stealth", None, Seq(1)).text
    assert "natural" not in rolling.roll(store, ALEX, "Stealth", None, Seq(7)).text


def test_rolling_for_someone_elses_character(store):
    out = rolling.roll(store, ALEX, "Religion", "second hero", Seq(10))
    assert out.character == "Second Hero" and out.total == 10 + (4 + 1 + 4 + 1)    # level 1 now


def test_no_registered_character_and_unknown_character_are_explained(store):
    with pytest.raises(SheetError, match="no registered character"):
        rolling.roll(store, 555, "Religion", None, Seq(1))
    with pytest.raises(SheetError, match="no saved character"):
        rolling.roll(store, ALEX, "Religion", "Nobody", Seq(1))
    assert rolling.roll(store, 555, "Religion", "Test Hero", Seq(1)).character == "Test Hero"   # naming one is enough


def test_unknown_roll_names_and_bad_dice_give_helpful_errors(store):
    with pytest.raises(SheetError, match="do not know a roll called Bluffing"):
        rolling.roll(store, ALEX, "Bluffing +2", None, Seq(1))
    with pytest.raises(SheetError, match="at most"):
        rolling.roll(store, ALEX, "1d1001", None, Seq(1))
    with pytest.raises(SheetError, match="Tell me what to roll"):
        rolling.roll(store, ALEX, "   ", None, Seq(1))
    with pytest.raises(SheetError, match="too large"):
        rolling.roll(store, ALEX, "Religion +99999", None, Seq(1))


def test_split_stat_and_modifier():
    assert rolling.split_stat_and_modifier("Religion -2") == ("Religion", -2)
    assert rolling.split_stat_and_modifier("Dwarven Lore") == ("Dwarven Lore", 0)
    assert rolling.split_stat_and_modifier("Will+4") == ("Will", 4)


def test_output_escapes_markdown_and_mentions_from_sheet_text(tmp_path):
    s = SheetStore(tmp_path)
    data = json.loads(FIXTURE.read_text())
    data["build"]["name"] = "**Bold** @everyone _x_"
    data["build"]["lores"] = [["<@123> `code`", 2]]
    s.add(ALEX, json.dumps(data).encode())
    out = rolling.roll(s, ALEX, "Religion", None, Seq(3)).text
    assert "@everyone" not in out and "**Bold**" not in out and "\\*\\*Bold" in out
    lore = rolling.roll(s, ALEX, "<@123> `code` lore", None, Seq(3)).text
    assert "`code`" not in lore.split("\n")[0]


def test_system_randomness_is_used_when_no_rng_is_given(store):
    totals = {rolling.roll(store, ALEX, "Stealth").total - 2 for _ in range(200)}
    assert totals <= set(range(1, 21)) and len(totals) > 5
