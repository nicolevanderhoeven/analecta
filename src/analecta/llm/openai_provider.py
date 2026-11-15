"""OpenAI implementation of the provider interface, on the Responses API (stateless)."""
from __future__ import annotations

import json
from typing import Any

from .base import Message, ModelTurn, ProviderError, ToolCall, ToolSpec, Usage


class OpenAIProvider:
    def __init__(self, *, api_key: str, model: str, reasoning_effort: str = "low", client: Any = None):
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, timeout=90.0, max_retries=2)
        self._client = client
        self.model = model
        self.reasoning_effort = reasoning_effort

    async def step(self, *, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": to_input_items(messages),
            "store": False,  # keep nothing server-side beyond the API's standard abuse-log window
            "max_output_tokens": 2500,
        }
        if tools:
            kwargs["tools"] = [
                {"type": "function", "name": t.name, "description": t.description,
                 "parameters": t.parameters, "strict": False}
                for t in tools
            ]
        if self.reasoning_effort and self.reasoning_effort != "none":
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        try:
            resp = await self._client.responses.create(**kwargs)
        except Exception as exc:  # the SDK raises many types; surface a safe summary
            raise ProviderError(f"{type(exc).__name__}") from exc
        return from_response(resp)


def to_input_items(messages: list[Message]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "user":
            items.append({"role": "user", "content": m.text})
        elif m.role == "assistant":
            if m.text:
                items.append({"role": "assistant", "content": m.text})
            for c in m.tool_calls:
                items.append(
                    {"type": "function_call", "call_id": c.id, "name": c.name,
                     "arguments": json.dumps(c.arguments)}
                )
        elif m.role == "tool":
            items.append({"type": "function_call_output", "call_id": m.tool_call_id, "output": m.text})
        else:  # pragma: no cover
            raise ValueError(f"unknown role {m.role}")
    return items


def from_response(resp: Any) -> ModelTurn:
    texts: list[str] = []
    calls: list[ToolCall] = []
    for item in getattr(resp, "output", None) or []:
        kind = getattr(item, "type", "")
        if kind == "message":
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", "") == "output_text":
                    texts.append(part.text)
        elif kind == "function_call":
            try:
                args = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=item.call_id, name=item.name, arguments=args if isinstance(args, dict) else {}))
    u = getattr(resp, "usage", None)
    usage = Usage()
    if u is not None:
        details = getattr(u, "input_tokens_details", None)
        usage = Usage(
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            cached_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
        )
    return ModelTurn(text="\n".join(texts).strip(), tool_calls=calls, usage=usage)
