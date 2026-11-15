"""Provider-neutral agent loop: model step, run tools, repeat, answer."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .aon import AonClient
from .corrections import CorrectionStore
from .llm.base import LLMProvider, Message, ModelTurn, ToolCall, ToolSpec, Usage
from .notes import NotesError, NotesStore

log = logging.getLogger("analecta.agent")

MAX_TOOL_RESULT_CHARS = 12000
PREREAD_CUT = "\n[truncated; call read_note again with a later start_line]"
MAX_PREREAD_CHARS = 24000  # total across all notes read up front

TOOLS: list[ToolSpec] = [
    ToolSpec(
        "grep_notes",
        "Search the campaign notes (case-insensitive). Use | to give alternatives, e.g. 'Name|Alias'. "
        "Returns matching lines with file and line number. Zero matches means the notes do not mention it.",
        {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path_contains": {"type": "string", "description": "Only files whose path contains this text."},
            "max_lines": {"type": "integer"}}, "required": ["pattern"]},
    ),
    ToolSpec(
        "read_note",
        "Read a campaign note by the path shown in list or grep results.",
        {"type": "object", "properties": {
            "path": {"type": "string"}, "start_line": {"type": "integer"}, "max_lines": {"type": "integer"}},
         "required": ["path"]},
    ),
    ToolSpec(
        "list_sessions",
        "List session notes in order with date and one-line summary. Use last=1 for 'last session'.",
        {"type": "object", "properties": {
            "last": {"type": "integer"}, "start": {"type": "integer"}, "end": {"type": "integer"}}},
    ),
    ToolSpec(
        "list_notes",
        "List non-session notes (people, places, factions, items...) filtered by name/alias text or type.",
        {"type": "object", "properties": {
            "name_contains": {"type": "string"}, "note_type": {"type": "string"}}},
    ),
    ToolSpec(
        "aon_search",
        "Search Archives of Nethys for Pathfinder 2e rules. Optional category such as action, spell, feat, "
        "condition, creature, equipment, trait, rules. Returns ids, sources and exact page URLs.",
        {"type": "object", "properties": {
            "query": {"type": "string"}, "category": {"type": "string"}, "size": {"type": "integer"}},
         "required": ["query"]},
    ),
    ToolSpec(
        "aon_get",
        "Fetch the text of one Archives of Nethys entry by the id from aon_search.",
        {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    ),
]


@dataclass
class AgentResult:
    text: str
    usage: Usage = field(default_factory=Usage)
    tools_used: list[str] = field(default_factory=list)
    turns: int = 0
    seconds: float = 0.0
    truncated: bool = False


class Agent:
    def __init__(self, provider: LLMProvider, notes: NotesStore, aon: AonClient,
                 system_builder: Callable[[str], str], max_turns: int = 8,
                 corrections: CorrectionStore | None = None):
        self.provider = provider
        self.notes = notes
        self.corrections = corrections
        self.aon = aon
        self.max_turns = max_turns
        self._system_builder = system_builder
        self._system = ""
        self._fingerprint: tuple[int, int] | None = None
        self._checked = 0.0
        self._dispatch: dict[str, Callable[..., Awaitable[str] | str]] = {
            "grep_notes": lambda a: self.notes.grep(a["pattern"], a.get("path_contains", ""), a.get("max_lines", 40)),
            "read_note": lambda a: self.notes.read(a["path"], a.get("start_line", 1), a.get("max_lines", 400)),
            "list_sessions": lambda a: self.notes.list_sessions(a.get("last"), a.get("start"), a.get("end")),
            "list_notes": lambda a: self.notes.list_notes(a.get("name_contains", ""), a.get("note_type", "")),
            "aon_search": lambda a: self.aon.search(a["query"], a.get("category", ""), a.get("size", 5)),
            "aon_get": lambda a: self.aon.get(a["id"]),
        }

    @property
    def system(self) -> str:
        """Rebuild the digest-bearing system prompt when the exported notes change (checked at most once a minute)."""
        now = time.monotonic()
        if self._fingerprint is None or now - self._checked > 60:
            self._checked = now
            fp = self.notes.fingerprint()
            if fp != self._fingerprint:
                self._fingerprint = fp
                self._system = self._system_builder(self.notes.digest())
        return self._system

    async def run_tool(self, name: str, args: dict[str, Any]) -> str:
        fn = self._dispatch.get(name)
        if fn is None:
            return f"Unknown tool {name}."
        try:
            out = fn(args)
            if hasattr(out, "__await__"):
                out = await out
        except NotesError as exc:
            return f"Error: {exc}"
        except (KeyError, TypeError, ValueError) as exc:
            return f"Error: bad arguments ({type(exc).__name__})."
        out = str(out)
        if len(out) > MAX_TOOL_RESULT_CHARS:
            out = out[:MAX_TOOL_RESULT_CHARS] + "\n[result truncated]"
        return out

    def preread_messages(self, history: list[Message]) -> list[Message]:
        """Already-made tool calls and results placed before the model's first turn.

        First the group's table corrections that bear on the conversation (they take precedence over the notes, so
        they come ahead of them), then the notes named in the latest user question as read_note results. The model
        otherwise tends to answer from the one-line digest description and never open the note.
        """
        calls: list[ToolCall] = []
        outputs: list[Message] = []
        context = " ".join(m.text for m in history if m.role in ("user", "assistant"))
        block = self.corrections.prompt_block(context) if self.corrections else ""
        if block:
            call = ToolCall(id="corrections1", name="table_corrections", arguments={})
            calls.append(call)
            outputs.append(Message(role="tool", text=block, tool_call_id=call.id))
        question = next((m.text for m in reversed(history) if m.role == "user"), "")
        try:
            infos = self.notes.match_entities(question)
        except OSError:
            infos = []
        budget = MAX_PREREAD_CHARS
        for n, info in enumerate(infos, 1):
            if budget <= 0:
                break
            try:
                out = self.notes.read(info.path, 1, 400)
            except (NotesError, OSError):
                continue
            limit = min(budget, MAX_TOOL_RESULT_CHARS)
            if len(out) > limit:
                out = out[: max(0, limit - len(PREREAD_CUT))] + PREREAD_CUT
            budget -= len(out)
            call = ToolCall(id=f"preread{n}", name="read_note", arguments={"path": info.path})
            calls.append(call)
            outputs.append(Message(role="tool", text=out, tool_call_id=call.id))
        if not calls:
            return []
        return [Message(role="assistant", text="", tool_calls=calls), *outputs]

    async def answer(self, history: list[Message]) -> AgentResult:
        started = time.monotonic()
        messages = list(history)
        result = AgentResult(text="")
        pre = self.preread_messages(history)
        if pre:
            messages.extend(pre)
            result.tools_used.extend(c.name for c in pre[0].tool_calls)
        for turn_no in range(1, self.max_turns + 1):
            last = turn_no == self.max_turns
            turn: ModelTurn = await self.provider.step(
                system=self.system, messages=messages, tools=[] if last else TOOLS
            )
            result.usage.add(turn.usage)
            result.turns = turn_no
            if not turn.tool_calls:
                result.text = turn.text
                break
            messages.append(Message(role="assistant", text=turn.text, tool_calls=turn.tool_calls))
            for call in turn.tool_calls:
                result.tools_used.append(call.name)
                output = await self.run_tool(call.name, call.arguments)
                messages.append(Message(role="tool", text=output, tool_call_id=call.id))
        else:
            result.truncated = True
        if not result.text:
            result.truncated = True
            result.text = "I could not finish looking that up. Try a narrower question."
        result.seconds = time.monotonic() - started
        log.info(
            "answered turns=%d tools=%s in=%d cached=%d out=%d secs=%.1f",
            result.turns, ",".join(result.tools_used) or "-", result.usage.input_tokens,
            result.usage.cached_tokens, result.usage.output_tokens, result.seconds,
        )
        return result
