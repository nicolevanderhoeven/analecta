from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path

import pytest

from analecta import pf2e, rolling
from analecta.agent import Agent, Asker
from analecta.aon import AonClient
from analecta.llm.base import Message, ModelTurn
from analecta.notes import NotesStore
from analecta.prompts import build_system_prompt
from analecta.sheets import MAX_VERSIONS, SheetError, SheetStore

FIXTURES = Path(__file__).parent / "fixtures"
SUMMONER = FIXTURES / "sheets" / "synthetic_summoner.json"
OTHER = FIXTURES / "sheets" / "synthetic_pathbuilder.json"
ALEX, BLAIR, GM = 1001, 1002, 9001
ASH = dict(str=4, dex=3, con=4, int=0, wis=1, cha=0)

# A synthetic summoner whose numbers equal the real eidolon's: every value from the owner's Pathbuilder screenshots.
EXPECTED = {
    "Fortitude": 15, "Reflex": 12, "Will": 12, "Perception": 12,
    "Acrobatics": 12, "Arcana": 0, "Athletics": 14, "Crafting": 0, "Deception": 9, "Diplomacy": 11,
    "Intimidation": 14, "Medicine": 11, "Nature": 10, "Occultism": 9, "Performance": 0, "Religion": 1,
    "Society": 0, "Stealth": 12, "Survival": 1, "Thievery": 3,
}


class Seq:
    def __init__(self, *values):
        self.values = list(values)

    def randint(self, a, b):
        return self.values.pop(0)


@pytest.fixture()
def store(tmp_path):
    s = SheetStore(tmp_path / "sheets", gm_ids=[GM])
    s.add(ALEX, SUMMONER.read_bytes())            # "Test Summoner", registered to ALEX
    return s


def with_ash(store, name="Ash"):
    return store.add_companion(ALEX, "Test Summoner", name, "eidolon", ASH, 25)[0]


def test_every_value_from_the_owners_pathbuilder_reproduces():
    build = json.loads(SUMMONER.read_text())["build"]
    assert pf2e.level(build) == 7
    got = {c.label: c.total for c in (pf2e.resolve(build, n, ASH) for n in EXPECTED)}
    assert got == EXPECTED


def test_the_eidolon_formula_shows_its_parts():
    build = json.loads(SUMMONER.read_text())["build"]
    check = pf2e.resolve(build, "intimidation", ASH)
    assert check.total == 14 and check.describe() == "master +6, level +7, Cha +0, item and other +1"
    assert pf2e.resolve(build, "will", ASH).total == 12 and pf2e.resolve(build, "religion", ASH).describe() == "untrained +0, Wis +1"
    assert pf2e.resolve(build, "dwarven lore", ASH) is None and pf2e.stat_names(build, True)[-1] == "Will"


def test_add_show_roll_remove(store):
    comp, created = store.add_companion(ALEX, "test summoner", "Ash", "Eidolon", ASH)
    assert created and comp.kind == "eidolon" and comp.ac is None and comp.character.name == "Test Summoner"
    assert [c.name for c in store.companions(store.get("Test Summoner"))] == ["Ash"]
    assert store.companions_for_user(ALEX) == [("Ash", "eidolon")]
    out = rolling.roll(store, BLAIR, "Intimidation", "ash", Seq(10))
    assert out.total == 24 and out.character == "Ash"
    assert "from saved sheet (eidolon of Test Summoner)" in out.text and "d20 [10] + 14 (Intimidation)" in out.text
    assert store.remove_companion(ALEX, "Test Summoner").name == "Ash"
    assert store.companions_for_user(ALEX) == []
    with pytest.raises(SheetError, match="no saved character or companion"):
        rolling.roll(store, ALEX, "Will", "Ash", Seq(1))


def test_companion_flag_rolls_the_callers_own_companion_and_takes_a_modifier(store):
    with pytest.raises(SheetError, match="no companion"):
        rolling.roll(store, ALEX, "Will", None, Seq(1), as_companion=True)
    with_ash(store)
    out = rolling.roll(store, ALEX, "Athletics -2", None, Seq(5), as_companion=True)
    assert out.total == 5 + 14 - 2 and out.character == "Ash" and "- 2 (extra modifier)" in out.text
    assert rolling.roll(store, ALEX, "Will", "Test Summoner", Seq(1), as_companion=True).character == "Ash"
    with pytest.raises(SheetError, match="no registered character"):
        rolling.roll(store, 5, "Will", None, Seq(1), as_companion=True)
    store.add_companion(ALEX, "Test Summoner", "Bo", "eidolon", ASH)
    with pytest.raises(SheetError, match="several companions"):
        rolling.roll(store, ALEX, "Will", None, Seq(1), as_companion=True)


def test_a_companion_has_no_lores_and_the_character_still_rolls_normally(store):
    with_ash(store)
    with pytest.raises(SheetError, match="Diplomacy"):
        rolling.roll(store, ALEX, "Dwarven Lore", "Ash", Seq(1))
    assert "from saved sheet)" in rolling.roll(store, ALEX, "Will", None, Seq(10)).text


def test_names_must_be_unique_and_ambiguous_names_are_refused(store, tmp_path):
    with_ash(store)
    store.add(BLAIR, OTHER.read_bytes())
    with pytest.raises(SheetError, match="already used"):
        store.add_companion(BLAIR, "Test Hero", "ash", "eidolon", ASH)
    with pytest.raises(SheetError, match="already used"):
        store.add_companion(BLAIR, "Test Hero", "Test Summoner", "eidolon", ASH)
    # a character uploaded later under the companion's name makes the name ambiguous: refuse to guess
    data = json.loads(OTHER.read_text())
    data["build"]["name"] = "Ash"
    store.add(GM, json.dumps(data).encode())
    with pytest.raises(SheetError, match="More than one"):
        rolling.roll(store, ALEX, "Will", "Ash", Seq(1))


@pytest.mark.parametrize("bad", [dict(ASH, str=18), dict(ASH, dex=-9), {k: v for k, v in ASH.items() if k != "cha"}, dict(ASH, wis=True)])
def test_ability_modifiers_are_validated(store, bad):
    with pytest.raises(SheetError, match="ability modifier"):
        store.add_companion(ALEX, "Test Summoner", "Ash", "eidolon", bad)
    assert store.companions(store.get("Test Summoner")) == []


def test_kind_ac_and_limits_are_validated(store):
    with pytest.raises(SheetError, match="kinds of companion"):
        store.add_companion(ALEX, "Test Summoner", "Ash", "dragon", ASH)
    with pytest.raises(SheetError, match="AC"):
        store.add_companion(ALEX, "Test Summoner", "Ash", "eidolon", ASH, 500)
    with pytest.raises(SheetError, match="needs a name"):
        store.add_companion(ALEX, "Test Summoner", "  ", "eidolon", ASH)
    for n in range(4):
        store.add_companion(ALEX, "Test Summoner", f"Buddy{n}", "eidolon", ASH)
    with pytest.raises(SheetError, match="already has 4"):
        store.add_companion(ALEX, "Test Summoner", "Extra", "eidolon", ASH)


def test_only_the_owner_or_a_gm_changes_companions(store):
    with pytest.raises(SheetError, match="owner or a GM"):
        store.add_companion(BLAIR, "Test Summoner", "Ash", "eidolon", ASH)
    with_ash(store)
    with pytest.raises(SheetError, match="owner or a GM"):
        store.remove_companion(BLAIR, "Test Summoner")
    store.add_companion(GM, "Test Summoner", "Ash", "eidolon", dict(ASH, str=5))
    assert store.companions(store.get("Test Summoner"))[0].abilities["str"] == 5
    store.remove_companion(GM, "Test Summoner", "Ash")


def test_updates_are_versioned_like_sheets_and_stay_private(store):
    for n in range(MAX_VERSIONS + 3):
        comp, created = store.add_companion(ALEX, "Test Summoner", "Ash", "eidolon", dict(ASH, str=n % 6), n)
        assert created == (n == 0)
    folder = store.root / comp.character.id / "companions" / comp.id
    assert len(list((folder / "versions").iterdir())) == MAX_VERSIONS
    assert store.companions(comp.character)[0].ac == MAX_VERSIONS + 2
    mode = lambda p: stat.S_IMODE(p.stat().st_mode)
    assert mode(folder) == 0o750 and all(mode(p) == 0o640 for p in (folder / "versions").iterdir())
    assert not any("Ash" in p.name for p in store.root.rglob("*"))


def test_deleting_the_character_deletes_its_companions(store):
    with_ash(store)
    store.delete(ALEX, "Test Summoner")
    assert store.all_companions() == [] and not [p for p in store.root.rglob("*.json") if p.name != "registrations.json"]


def test_a_damaged_companion_is_skipped(store):
    comp = with_ash(store)
    bad = store.root / comp.character.id / "companions" / ("0" * 16) / "versions"
    bad.mkdir(parents=True)
    (bad / "20240101T000000000000Z.json").write_text("{nope")
    assert [c.name for c in store.companions(comp.character)] == ["Ash"]


def test_sheet_add_suggests_adding_the_eidolon_until_there_is_one(store):
    assert store.add(ALEX, SUMMONER.read_bytes()).suggest_eidolon
    with_ash(store)
    assert not store.add(ALEX, SUMMONER.read_bytes()).suggest_eidolon
    assert not store.add(ALEX, OTHER.read_bytes()).suggest_eidolon


# -- questions ---------------------------------------------------------------------------------------------------

KIN = FIXTURES / "kin_notes"


class Scripted:
    def __init__(self):
        self.seen = []

    async def step(self, *, system, messages, tools):
        self.seen.append(list(messages))
        return ModelTurn("done", [])


def ask(store, question, user=ALEX, names=("Dana",)):
    prov = Scripted()
    agent = Agent(prov, NotesStore(KIN), AonClient(enabled=False), build_system_prompt, 4,
                  registered_character=store.character_name_for, registered_companions=store.companions_for_user)
    res = asyncio.run(agent.answer([Message("user", question)], Asker(user, names)))
    return {m.tool_call_id: m.text for m in prov.seen[0] if m.role == "tool"}, res


@pytest.fixture()
def kin_store(tmp_path):
    s = SheetStore(tmp_path / "sheets")
    data = json.loads(SUMMONER.read_text())
    data["build"]["name"] = "Ilsa Marrow"
    s.add(ALEX, json.dumps(data).encode())
    s.add_companion(ALEX, "Ilsa Marrow", "Garrick Holt", "eidolon", ASH)   # a name that has a note in the fixtures
    return s


def test_asker_context_names_the_companion_and_my_eidolon_reads_its_note(kin_store):
    texts, res = ask(kin_store, "What does my eidolon want?")
    assert "plays the player character Ilsa Marrow" in texts["asker1"]
    assert "Garrick Holt (eidolon)" in texts["asker1"] and "my eidolon" in texts["asker1"]
    assert "# Garrick Holt.md" in "\n".join(texts.values())
    texts, _ = ask(kin_store, "Tell me about my companion")
    assert "# Garrick Holt.md" in "\n".join(texts.values())


def test_the_companions_name_alone_finds_its_note_and_other_wording_is_untouched(kin_store):
    texts, _ = ask(kin_store, "Who is Garrick Holt?")
    assert "# Garrick Holt.md" in "\n".join(texts.values())
    texts, _ = ask(kin_store, "Who is my family?")
    assert "# Maren Oake.md" in "\n".join(texts.values()) and "# Garrick Holt.md" not in "\n".join(texts.values())
    texts, _ = ask(kin_store, "What does my familiar know?")   # not an eidolon: no companion is dragged in
    assert "# Garrick Holt.md" not in "\n".join(texts.values())


def test_other_askers_and_characters_without_companions_see_nothing_extra(kin_store):
    texts, _ = ask(kin_store, "What does my eidolon want?", user=77, names=("Dana",))
    assert "eidolon" not in " ".join(texts.values()).lower() and "asker_companion" not in texts
    kin_store.remove_companion(ALEX, "Ilsa Marrow")
    texts, _ = ask(kin_store, "Who is my family?")
    assert "companion" not in texts["asker1"]


def test_companion_is_still_noted_when_no_note_matches_the_character(tmp_path):
    s = SheetStore(tmp_path / "sheets")
    s.add(ALEX, SUMMONER.read_bytes())
    s.add_companion(ALEX, "Test Summoner", "Ash", "eidolon", ASH)
    texts, _ = ask(s, "What does my eidolon want?")
    assert "asker1" not in texts and "Ash (eidolon)" in texts["asker_companion"]


# -- slash commands ----------------------------------------------------------------------------------------------

from test_commands import Attachment, FakeInteraction, make as make_cmds, run  # noqa: E402


def test_companion_commands_end_to_end(tmp_path):
    store, cmds = make_cmds(tmp_path, Seq(10, 10))
    up = FakeInteraction(ALEX)
    run(cmds.sheet_add(up, Attachment(SUMMONER.read_bytes())))
    assert "/companion add" in up.texts[0] and "eidolon" in up.texts[0]
    mine = FakeInteraction(ALEX)
    run(cmds.companion_add(mine, "Test Summoner", "Ash", "eidolon", 4, 3, 4, 0, 1, 0, 25))
    assert mine.texts[0].startswith("Added **Ash**, eidolon of **Test Summoner**")
    again = FakeInteraction(ALEX)
    run(cmds.sheet_add(again, Attachment(SUMMONER.read_bytes())))
    assert "/companion add" not in again.texts[0]
    show = FakeInteraction(BLAIR)
    run(cmds.companion_show(show, "Ash"))
    assert "Perception +12" in show.texts[0] and "Intimidation +14" in show.texts[0] and "AC 25" in show.texts[0]
    roll = FakeInteraction(ALEX)
    run(cmds.roll(roll, "Will", None, False, True))
    assert "**Ash**" in roll.texts[0] and "eidolon of Test Summoner" in roll.texts[0] and "= **22**" in roll.texts[0]
    secret = FakeInteraction(ALEX)
    run(cmds.roll(secret, "Will", "Ash", True))
    assert "**Ash**" in secret.texts[0] and "= **22**" in secret.texts[1]
    stranger = FakeInteraction(BLAIR)
    run(cmds.companion_remove(stranger, "Test Summoner", "Ash"))
    assert "owner or a GM" in stranger.texts[0] and store.companions_for_user(ALEX)
    gone = FakeInteraction(ALEX)
    run(cmds.companion_remove(gone, "Ash"))
    assert "Removed **Ash**" in gone.texts[0] and not store.companions_for_user(ALEX)
    none = FakeInteraction(ALEX)
    run(cmds.companion_show(none, None))
    assert "no companion saved" in none.texts[0]


def test_companion_add_reports_bad_input(tmp_path):
    store, cmds = make_cmds(tmp_path)
    run(cmds.sheet_add(FakeInteraction(ALEX), Attachment(SUMMONER.read_bytes())))
    it = FakeInteraction(ALEX)
    run(cmds.companion_add(it, "Test Summoner", "Ash", "eidolon", 18, 3, 4, 0, 1, 0))
    assert "ability modifier" in it.texts[0]
    it = FakeInteraction(ALEX)
    run(cmds.companion_add(it, "Nobody", "Ash", "eidolon", 4, 3, 4, 0, 1, 0))
    assert "no saved character" in it.texts[0]
