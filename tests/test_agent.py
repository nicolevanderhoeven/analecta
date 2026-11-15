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
    assert "cartographer" in res.text and res.tools_used == ["grep_notes"] and res.turns == 2
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
