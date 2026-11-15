from __future__ import annotations

import asyncio

from analecta.agent import Agent
from analecta.aon import AonClient
from analecta.llm.base import Message, ModelTurn, ToolCall, Usage
from analecta.notes import NotesStore
from analecta.prompts import build_system_prompt


class Scripted:
    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    async def step(self, *, system, messages, tools):
        self.seen.append((system, list(messages), list(tools)))
        return self.turns.pop(0)


def make_agent(exported, turns, max_turns=4):
    prov = Scripted(turns)
    aon = AonClient(enabled=False)
    return Agent(prov, NotesStore(exported), aon, build_system_prompt, max_turns), prov


def call(i, name, **args):
    return ToolCall(id=f"c{i}", name=name, arguments=args)


def test_tool_loop_runs_tools_and_answers(exported):
    turns = [
        ModelTurn("", [call(1, "grep_notes", pattern="Old Quill")], Usage(10, 0, 5)),
        ModelTurn("Marta Quillon is a retired cartographer (Marta Quillon.md).", [], Usage(20, 8, 7)),
    ]
    agent, prov = make_agent(exported, turns)
    res = asyncio.run(agent.answer([Message("user", "Who is Old Quill?")]))
    assert "cartographer" in res.text and res.tools_used == ["read_note", "grep_notes"] and res.turns == 2
    assert res.usage.input_tokens == 30 and res.usage.cached_tokens == 8
    tool_msg = prov.seen[1][1][-1]
    assert tool_msg.role == "tool" and "Marta Quillon.md" in tool_msg.text
    assert "Old Quill" in prov.seen[0][0]  # digest is in the system prompt


def test_unknown_tool_and_bad_args_do_not_crash(exported):
    turns = [
        ModelTurn("", [call(1, "rm_rf"), call(2, "read_note"), call(3, "read_note", path="../x.md")]),
        ModelTurn("done", []),
    ]
    agent, prov = make_agent(exported, turns)
    asyncio.run(agent.answer([Message("user", "q")]))
    outputs = [m.text for m in prov.seen[1][1] if m.role == "tool"]
    assert outputs[0].startswith("Unknown tool")
    assert outputs[1].startswith("Error: bad arguments")
    assert outputs[2].startswith("Error:")


def test_turn_cap_forces_final_answer_without_tools(exported):
    looping = ModelTurn("", [call(1, "list_sessions", last=1)])
    turns = [looping, looping, ModelTurn("final", [])]
    agent, prov = make_agent(exported, turns, max_turns=3)
    res = asyncio.run(agent.answer([Message("user", "q")]))
    assert res.text == "final"
    assert prov.seen[-1][2] == []  # last turn offers no tools


def test_empty_answer_gets_fallback(exported):
    agent, _ = make_agent(exported, [ModelTurn("", [])])
    res = asyncio.run(agent.answer([Message("user", "q")]))
    assert res.truncated and "could not finish" in res.text


def test_aon_off_message_reaches_model(exported):
    turns = [ModelTurn("", [call(1, "aon_search", query="grapple")]), ModelTurn("ok", [])]
    agent, prov = make_agent(exported, turns)
    asyncio.run(agent.answer([Message("user", "q")]))
    assert "switched off" in prov.seen[1][1][-1].text


def test_system_prompt_rebuilds_when_notes_change(exported):
    agent, _ = make_agent(exported, [])
    first = agent.system
    assert "Zed Novelty" not in first
    (exported / "Zed Novelty.md").write_text("---\ndescription: brand new\n---\nx")
    agent._checked = 0  # skip the once-a-minute throttle
    assert "Zed Novelty" in agent.system


# -- entity notes are read before the model answers ---------------------------------------------------
def _add_entity(exported):
    (exported / "Pip Tarn.md").write_text(
        "---\ntype: npc\naliases:\n  - Little Pip\ndescription: A young lamplighter.\n---\n"
        "## Session 7\nPip rescued the ferry cat from the Drowned Chapel.\n\n## Session 9\nPip owes Odo Pell a favour.\n"
    )


def _seen_reads(prov):
    """Tool results the model saw on its first turn."""
    return [m.text for m in prov.seen[0][1] if m.role == "tool"]


def test_named_entity_note_is_read_before_the_first_model_turn(exported):
    _add_entity(exported)
    agent, prov = make_agent(exported, [ModelTurn("Pip rescued the ferry cat.", [])])
    res = asyncio.run(agent.answer([Message("user", "Who is Pip Tarn?")]))
    reads = _seen_reads(prov)
    assert len(reads) == 1 and "rescued the ferry cat" in reads[0] and "owes Odo Pell" in reads[0]
    assistant = [m for m in prov.seen[0][1] if m.role == "assistant"][0]
    assert assistant.tool_calls[0].name == "read_note" and assistant.tool_calls[0].arguments == {"path": "Pip Tarn.md"}
    assert prov.seen[0][1][-1].tool_call_id == assistant.tool_calls[0].id
    assert res.tools_used == ["read_note"]


def test_alias_and_multiple_names_match_whole_words_case_insensitively(exported):
    _add_entity(exported)
    agent, prov = make_agent(exported, [ModelTurn("ok", [])])
    asyncio.run(agent.answer([Message("user", "who are little pip and old quill?")]))
    joined = "\n".join(_seen_reads(prov))
    assert "ferry cat" in joined and "avoid the Bridge of Teeth" in joined
    assert len(_seen_reads(prov)) == 2


def test_partial_words_do_not_match(exported):
    _add_entity(exported)
    agent, prov = make_agent(exported, [ModelTurn("ok", [])])
    asyncio.run(agent.answer([Message("user", "What is a pipsqueak tarnished by martas?")]))
    assert _seen_reads(prov) == []


def test_question_without_entity_reads_nothing_extra(exported):
    agent, prov = make_agent(exported, [ModelTurn("ok", [])])
    res = asyncio.run(agent.answer([Message("user", "How does grapple work?")]))
    assert _seen_reads(prov) == [] and res.tools_used == []


def test_preread_is_bounded_and_uses_latest_user_message(exported):
    for i in range(8):
        (exported / f"Big Person{i}.md").write_text("---\ndescription: d\n---\n" + ("long history. " * 3000))
    agent, prov = make_agent(exported, [ModelTurn("ok", [])])
    asyncio.run(agent.answer([
        Message("user", "Who is Marta?"), Message("assistant", "A cartographer."),
        Message("user", " ".join(f"Big Person{i}" for i in range(8)))]))
    reads = _seen_reads(prov)
    assert 0 < len(reads) <= 5 and sum(len(r) for r in reads) <= 24000
    assert not any("Bridge of Teeth" in r for r in reads)


def test_system_prompt_forbids_claiming_absence_without_reading_and_grepping(exported):
    agent, _ = make_agent(exported, [])
    system = agent.system
    assert "read its own note" in system
    assert "never say the notes give no more detail" in system.lower()
    assert "grepped the session notes" in system


def test_digest_description_alone_is_not_the_only_source(exported):
    """Regression: the digest only has the one-line description; the note body must also reach the model."""
    _add_entity(exported)
    agent, prov = make_agent(exported, [ModelTurn("ok", [])])
    asyncio.run(agent.answer([Message("user", "Who is Pip Tarn?")]))
    assert "A young lamplighter." in prov.seen[0][0]
    assert "ferry cat" not in prov.seen[0][0]
    assert any("ferry cat" in t for t in _seen_reads(prov))
