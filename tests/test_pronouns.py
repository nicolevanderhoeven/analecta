from __future__ import annotations

import asyncio

from analecta.agent import Agent, Asker
from analecta.aon import AonClient
from analecta.llm.base import Message
from analecta.notes import NotesStore
from analecta.prompts import build_system_prompt

from test_links import Scripted, tool_texts


def _store(tmp_path):
    (tmp_path / "Ilsa Marrow.md").write_text("---\ntype: pc\npronouns: they/them\nsummary: A ranger.\n---\nIlsa.\n")
    (tmp_path / "Brann Vesk.md").write_text("---\ntype: npc\npronouns: [he/him, they/them]\n---\nBrann.\n")
    (tmp_path / "Tolly Dray.md").write_text("---\ntype: npc\nsummary: A boy.\n---\nTolly.\n")
    (tmp_path / "Harrow Pass.md").write_text("---\ntype: place\npronouns: it/its\n---\nA pass.\n")
    return NotesStore(tmp_path)


def test_digest_shows_pronouns_string_and_list_and_leaves_other_notes_unchanged(tmp_path):
    digest = _store(tmp_path).digest()
    assert "Ilsa Marrow [pc] (pronouns: they/them): A ranger." in digest
    assert "Brann Vesk [npc] (pronouns: he/him, they/them)" in digest
    assert "Tolly Dray [npc]: A boy." in digest
    assert "Harrow Pass [place]" in digest and "it/its" not in digest


def test_asker_context_carries_the_characters_pronouns(tmp_path):
    prov = Scripted()
    agent = Agent(prov, _store(tmp_path), AonClient(enabled=False), build_system_prompt, 4)
    asyncio.run(agent.answer([Message("user", "Who is my family?")], Asker(5, ("Ilsa Marrow",))))
    assert "pronouns are they/them" in tool_texts(prov)["asker1"]


def test_prompt_has_the_pronoun_rule():
    assert "PRONOUNS." in build_system_prompt("digest")
