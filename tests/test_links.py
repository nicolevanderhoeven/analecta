from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from analecta.agent import Agent, Asker
from analecta.aon import AonClient
from analecta.config import ConfigError, load_settings, parse_character_map
from analecta.llm.base import Message, ModelTurn
from analecta.notes import LinkPolicy, NotesStore
from analecta.prompts import build_system_prompt

KIN = Path(__file__).parent / "fixtures" / "kin_notes"


def titles(trail):
    return [n.info.title for n in trail.notes]


def follow(question="Who is Ilsa's family?", seeds=("Ilsa Marrow",), **policy):
    store = NotesStore(KIN)
    infos = {i.title: i for i in store.infos()}
    return store.follow_links([infos[s] for s in seeds], question, LinkPolicy(**policy))


def test_two_steps_reach_children_and_relative_but_skip_hubs():
    trail = follow()
    got = titles(trail)
    assert got[:2] == ["Ilsa Marrow", "Brann Vesk"]
    assert {"Tolly Dray", "Pip Dray", "Maren Oake", "Vexa's Crown"} <= set(got) - {"Brann Vesk"}
    assert "Garrick Holt" not in got  # three steps away
    assert not {"Harrow Pass", "Rusty Compass", "012_20240301 The Crossing"} & set(got)
    assert {"Harrow Pass", "Rusty Compass"} <= set(trail.skipped_hubs)
    maren = next(n for n in trail.notes if n.info.title == "Maren Oake")
    assert maren.depth == 2 and maren.via == "Brann Vesk" and "relative" in maren.text


def test_depth_limits_hold():
    assert titles(follow(depth=1)) == ["Ilsa Marrow", "Brann Vesk", "Vexa's Crown"]
    assert "Garrick Holt" in titles(follow(depth=3))
    assert titles(follow(depth=9)) == titles(follow(depth=3))  # never more than three steps
    assert titles(follow(depth=0)) == ["Ilsa Marrow"]


def test_note_budget_holds_and_reports_what_was_left():
    trail = follow(max_notes=4)
    assert len(trail.notes) == 4
    assert trail.over_budget and not set(trail.over_budget) & set(titles(trail))


def test_token_cap_holds():
    trail = follow(token_cap=1000)  # 4000 characters in all
    assert sum(len(n.text) for n in trail.notes) <= 4000
    tiny = follow(token_cap=250)
    assert tiny.over_budget


def test_hub_is_followed_when_the_question_names_it():
    got = titles(follow("Who lives near Harrow Pass in Ilsa's family?"))
    assert "Harrow Pass" in got


def test_stops_when_a_step_adds_nothing():
    trail = follow("Who is Garrick?", seeds=("Garrick Holt",))
    assert titles(trail) == ["Garrick Holt"] and not trail.over_budget


def test_find_character_by_name_alias_and_override():
    store = NotesStore(KIN)
    assert store.find_character(["ILSA"]).title == "Ilsa Marrow"  # alias, case-insensitive
    assert store.find_character(["Someone", "ilsa marrow"]).title == "Ilsa Marrow"
    assert store.find_character(["Brann Vesk"]) is None  # an NPC is not a player character
    assert store.find_character(["Ilsa M"]) is None
    assert store.find_character(["Someone"], override="Ilsa Marrow").title == "Ilsa Marrow"
    assert store.find_character(["Someone"], override="No Such Note") is None


class Scripted:
    def __init__(self, text="done"):
        self.seen, self.text = [], text

    async def step(self, *, system, messages, tools):
        self.seen.append(list(messages))
        return ModelTurn(self.text, [])


def make_agent(**kw):
    prov = Scripted()
    return Agent(prov, NotesStore(KIN), AonClient(enabled=False), build_system_prompt, 4, **kw), prov


def tool_texts(prov):
    return {m.tool_call_id: m.text for m in prov.seen[0] if m.role == "tool"}


def test_agent_answer_context_has_the_whole_family_and_a_notes_read_line():
    agent, prov = make_agent()
    res = asyncio.run(agent.answer([Message("user", "Who is Ilsa Marrow's family?")]))
    context = "\n".join(tool_texts(prov).values())
    for name in ("Brann Vesk", "Tolly Dray", "Pip Dray", "Maren Oake"):
        assert f"# {name}.md" in context
    assert "# Harrow Pass.md" not in context and "# Garrick Holt.md" not in context
    assert "follow_links" in res.tools_used
    assert res.text.endswith("Notes read: Ilsa Marrow, Brann Vesk, Vexa's Crown, Tolly Dray, Pip Dray, Maren Oake")
    assert "Harrow Pass" in tool_texts(prov)["links_summary"]  # listed as skipped, not read


def test_agent_does_not_follow_links_for_other_questions_or_when_disabled():
    agent, prov = make_agent()
    res = asyncio.run(agent.answer([Message("user", "What does Ilsa Marrow carry?")]))
    assert "follow_links" not in res.tools_used and "Notes read" not in res.text
    off, prov = make_agent(links=LinkPolicy(depth=0))
    res = asyncio.run(off.answer([Message("user", "Who is Ilsa Marrow's family?")]))
    assert res.tools_used == ["read_note"] and "Notes read" not in res.text


def test_my_family_uses_the_askers_character_by_nickname():
    agent, prov = make_agent()
    res = asyncio.run(agent.answer([Message("user", "Who is my family?")], Asker(5, ("ilsa", "Dana"))))
    texts = tool_texts(prov)
    assert "plays the player character Ilsa Marrow" in texts["asker1"]
    assert "# Maren Oake.md" in "\n".join(texts.values()) and res.text.endswith("Maren Oake")


def test_override_map_names_the_character_when_the_nickname_does_not_match():
    agent, prov = make_agent(character_map={42: "Ilsa Marrow"})
    asyncio.run(agent.answer([Message("user", "Who is my family?")], Asker(42, ("Dana",))))
    assert "Ilsa Marrow" in tool_texts(prov)["asker1"]
    agent, prov = make_agent(character_map={42: "Ilsa Marrow"})
    asyncio.run(agent.answer([Message("user", "Who is my family?")], Asker(43, ("Dana",))))
    assert "asker1" not in tool_texts(prov)  # no match: the model is told to ask which character


def test_notes_read_line_includes_notes_the_model_opened_itself():
    agent, _ = make_agent()
    assert agent.notes_read_line(["a/Bee.md", "Cee.md", "a/Bee.md"]) == "Notes read: Bee, Cee"


def test_config_defaults_env_overrides_and_character_map():
    base = {"DISCORD_TOKEN": "t", "DISCORD_GUILD_ID": "9", "DISCORD_CHANNEL_ID": "5", "OPENAI_API_KEY": "k",
            "NOTES_DIR": "/tmp/n"}
    s = load_settings(base)
    assert (s.links.depth, s.links.max_notes, s.links.token_cap) == (2, 12, 32000) and s.character_map == {}
    s = load_settings({**base, "LINK_DEPTH": "9", "LINK_NOTE_BUDGET": "6", "LINK_TOKEN_CAP": "20000",
                       "ANALECTA_CHARACTER_MAP": "123456789:Some Name, 987:Other"})
    assert (s.links.depth, s.links.max_notes, s.links.token_cap) == (3, 6, 20000)
    assert s.character_map == {123456789: "Some Name", 987: "Other"}
    with pytest.raises(ConfigError):
        parse_character_map("abc:Name")
    with pytest.raises(ConfigError):
        parse_character_map("123")


def test_display_text_alias_counts_as_standing_for_a_person(tmp_path):
    (tmp_path / "Vayle.md").write_text("---\ntype: pc\n---\nHer partner is [[Graveknight Armor|Sythra]].\n")
    (tmp_path / "Graveknight Armor.md").write_text("---\ntype: item\naliases: [Sythra]\n---\nSythra, a spirit.\n")
    store = NotesStore(tmp_path)
    infos = {i.title: i for i in store.infos()}
    trail = store.follow_links([infos["Vayle"]], "Who is Vayle's family?", LinkPolicy())
    assert "Graveknight Armor" in titles(trail)


def test_asker_character_seeded_only_for_ownership_or_no_entity_match():
    agent, prov = make_agent()
    asyncio.run(agent.answer([Message("user", "Tell me about Brann Vesk's family")], Asker(5, ("ilsa",))))
    assert "preread1" in tool_texts(prov) and "# Ilsa Marrow.md" not in tool_texts(prov)["preread1"]
    agent, prov = make_agent()
    asyncio.run(agent.answer([Message("user", "family of me")], Asker(5, ("ilsa",))))
    assert "# Ilsa Marrow.md" in tool_texts(prov)["preread1"]
