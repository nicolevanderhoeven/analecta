from __future__ import annotations

import pytest

from analecta import dice


class Seq:
    """Returns the given numbers in order, then 1s."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = []

    def randint(self, a, b):
        self.calls.append((a, b))
        return self.values.pop(0) if self.values else 1


def test_simple_and_multiple_terms():
    r = dice.roll("1d20+5", Seq(14))
    assert r.total == 19 and r.breakdown() == "1d20 [14] + 5"
    r = dice.roll("2d6 + 1d4 - 1", Seq(4, 2, 3))
    assert r.total == 4 + 2 + 3 - 1
    assert r.breakdown() == "2d6 [4, 2] + 1d4 [3] - 1"


def test_d20_shorthand_and_negative_leading_term():
    r = dice.roll("d20", Seq(7))
    assert r.total == 7 and r.terms[0].count == 1
    assert dice.roll("-1d4+10", Seq(3)).total == 7


def test_rng_gets_the_right_bounds():
    rng = Seq()
    dice.roll("3d8", rng)
    assert rng.calls == [(1, 8)] * 3


def test_keep_highest_and_lowest_drop_the_rest():
    r = dice.roll("4d6kh3", Seq(1, 5, 6, 3))
    assert r.total == 14 and "~~1~~" in r.breakdown()
    r = dice.roll("2d20kl1", Seq(18, 4))
    assert r.total == 4
    assert dice.roll("4d6kh", Seq(1, 5, 6, 3)).total == 6      # keep defaults to 1


@pytest.mark.parametrize("bad", ["", "abc", "1d", "d0", "0d6", "1d20+", "1d20 5", "2d6*3", "__import__('os')",
                                 "1d1001", "101d6", "4d6kh5", "4d6kh0", "1+" * 60 + "1"])
def test_bad_expressions_are_refused_without_rolling(bad):
    with pytest.raises(dice.DiceError):
        dice.roll(bad, Seq())


def test_too_many_terms():
    with pytest.raises(dice.DiceError):
        dice.roll("+".join(["1d4"] * 11), Seq())


def test_looks_like_dice_tells_skills_from_dice():
    assert dice.looks_like_dice("1d20+5") and dice.looks_like_dice("d20") and dice.looks_like_dice(" 2d6 + 3 ")
    assert not dice.looks_like_dice("Religion -2") and not dice.looks_like_dice("5") and not dice.looks_like_dice("Will")
    assert not dice.looks_like_dice("Dwarven Lore +1")


def test_system_rng_is_used_by_default_and_in_range():
    for _ in range(50):
        assert 1 <= dice.roll("1d20").total <= 20
