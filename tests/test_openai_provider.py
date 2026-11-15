from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace as NS

from analecta.llm.base import Message, ToolCall, ToolSpec
from analecta.llm.openai_provider import OpenAIProvider, from_response, to_input_items


def test_to_input_items_roundtrip_shape():
    items = to_input_items([
        Message("user", "hi"),
        Message("assistant", "thinking", [ToolCall("c1", "grep_notes", {"pattern": "x"})]),
        Message("tool", "result", tool_call_id="c1"),
        Message("assistant", "answer"),
    ])
    assert items[0] == {"role": "user", "content": "hi"}
    assert items[2]["type"] == "function_call" and json.loads(items[2]["arguments"]) == {"pattern": "x"}
    assert items[3] == {"type": "function_call_output", "call_id": "c1", "output": "result"}
    assert items[4]["role"] == "assistant"


def test_from_response_text_calls_usage():
    resp = NS(
        output=[
            NS(type="reasoning"),
            NS(type="message", content=[NS(type="output_text", text="Hello")]),
            NS(type="function_call", call_id="c9", name="aon_search", arguments='{"query":"grapple"}'),
            NS(type="function_call", call_id="c10", name="x", arguments="not json"),
        ],
        usage=NS(input_tokens=100, output_tokens=20, input_tokens_details=NS(cached_tokens=60)),
    )
    turn = from_response(resp)
    assert turn.text == "Hello"
    assert turn.tool_calls[0] == ToolCall("c9", "aon_search", {"query": "grapple"})
    assert turn.tool_calls[1].arguments == {}
    assert (turn.usage.input_tokens, turn.usage.cached_tokens, turn.usage.output_tokens) == (100, 60, 20)


def test_step_sends_stateless_request():
    captured = {}

    async def create(**kw):
        captured.update(kw)
        return NS(output=[NS(type="message", content=[NS(type="output_text", text="ok")])], usage=None)

    client = NS(responses=NS(create=create))
    p = OpenAIProvider(api_key="unused", model="gpt-6-luna", reasoning_effort="low", client=client)
    tool = ToolSpec("t", "d", {"type": "object", "properties": {}})
    turn = asyncio.run(p.step(system="sys", messages=[Message("user", "q")], tools=[tool]))
    assert turn.text == "ok"
    assert captured["store"] is False and captured["instructions"] == "sys"
    assert captured["model"] == "gpt-6-luna" and captured["reasoning"] == {"effort": "low"}
    assert captured["tools"][0]["type"] == "function" and captured["tools"][0]["name"] == "t"


def test_errors_become_provider_error():
    import pytest

    from analecta.llm.base import ProviderError

    async def create(**kw):
        raise RuntimeError("secret detail that should not leak")

    p = OpenAIProvider(api_key="unused", model="m", client=NS(responses=NS(create=create)))
    with pytest.raises(ProviderError) as e:
        asyncio.run(p.step(system="s", messages=[Message("user", "q")], tools=[]))
    assert "secret" not in str(e.value)
