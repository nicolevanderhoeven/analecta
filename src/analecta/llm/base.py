"""Provider-neutral model interface. The agent loop only ever sees these types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # assistant messages
    tool_call_id: str = ""  # tool messages


@dataclass
class Usage:
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.cached_tokens += other.cached_tokens
        self.output_tokens += other.output_tokens


@dataclass
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage = field(default_factory=Usage)


class LLMProvider(Protocol):
    async def step(self, *, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        """Run one model call and return its text and any tool calls."""
        ...


class ProviderError(RuntimeError):
    """The provider could not be reached or refused the call (message is safe to log)."""
