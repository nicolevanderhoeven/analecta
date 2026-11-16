"""The registration store is the single source of truth for who plays which character, including for the
note link-follower: it is consulted before the ANALECTA_CHARACTER_MAP env override and the nickname match."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from analecta.agent import Agent, Asker
from analecta.aon import AonClient
from analecta.llm.base import Message, ModelTurn
from analecta.notes import NotesStore
from analecta.prompts import build_system_prompt
from analecta.sheets import SheetStore

KIN = Path(__file__).parent / "fixtures" / "kin_notes"
FIXTURE = Path(__file__).parent / "fixtures" / "sheets" / "synthetic_pathbuilder.json"


class Scripted:
    def __init__(self):
        self.seen = []

    async def step(self, *, system, messages, tools):
        self.seen.append(list(messages))
        return ModelTurn("done", [])


def sheet(store, owner, name):
    data = json.loads(FIXTURE.read_text())
    data["build"]["name"] = name
    return store.add(owner, json.dumps(data).encode())


def make_agent(store, **kw):
    prov = Scripted()
    agent = Agent(prov, NotesStore(KIN), AonClient(enabled=False), build_system_prompt, 4,
                  registered_character=store.character_name_for, **kw)
    return agent, prov


def asker_text(prov):
    return {m.tool_call_id: m.text for m in prov.seen[0] if m.role == "tool"}.get("asker1", "")


def ask(agent, user_id, names=("Dana",)):
    asyncio.run(agent.answer([Message("user", "Who is my family?")], Asker(user_id, names)))


def test_registered_character_is_used_when_nickname_does_not_match(tmp_path):
    store = SheetStore(tmp_path)
    sheet(store, 42, "Ilsa Marrow")
    agent, prov = make_agent(store)
    ask(agent, 42)
    assert "Ilsa Marrow" in asker_text(prov)


def test_registration_beats_the_env_map_and_the_nickname(tmp_path):
    store = SheetStore(tmp_path)
    sheet(store, 42, "Ilsa Marrow")
    agent, prov = make_agent(store, character_map={42: "Brann Vesk"})
    ask(agent, 42, ("Dana", "Pip Dray"))
    assert "Ilsa Marrow" in asker_text(prov) and "Brann Vesk" not in asker_text(prov)


def test_falls_back_to_env_map_when_the_registered_name_matches_no_note(tmp_path):
    store = SheetStore(tmp_path)
    sheet(store, 42, "Test Hero")                       # a sheet whose name is not a note
    agent, prov = make_agent(store, character_map={42: "Ilsa Marrow"})
    ask(agent, 42)
    assert "Ilsa Marrow" in asker_text(prov)


def test_unregistered_and_unmapped_users_still_fall_back_to_the_nickname(tmp_path):
    store = SheetStore(tmp_path)
    agent, prov = make_agent(store)
    ask(agent, 77, ("ilsa",))
    assert "Ilsa Marrow" in asker_text(prov)
    agent, prov = make_agent(store)
    ask(agent, 78)
    assert asker_text(prov) == ""


def test_unregistering_stops_the_link(tmp_path):
    store = SheetStore(tmp_path)
    sheet(store, 42, "Ilsa Marrow")
    store.unregister(42)
    agent, prov = make_agent(store)
    ask(agent, 42)
    assert asker_text(prov) == ""
