"""Who and where the bot answers. Pure functions so the privacy boundary is easy to test."""
from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

DISCORD_LIMIT = 2000


def is_allowed_location(message: Any, locations: Iterable[tuple[int, int]]) -> bool:
    """Only configured (server, channel) pairs, or a thread directly under one. No DMs, no other servers."""
    guild = getattr(message, "guild", None)
    if guild is None:
        return False  # DMs and group DMs
    channel = message.channel
    ids = {channel.id, getattr(channel, "parent_id", None)} - {None}
    return any(
        guild.id == guild_id and channel_id in ids
        for guild_id, channel_id in locations
    )


def is_addressed(message: Any, bot_user_id: int) -> bool:
    """Answer only when mentioned or when replying to one of the bot's own messages."""
    if any(getattr(u, "id", None) == bot_user_id for u in getattr(message, "mentions", [])):
        return True
    ref = getattr(message, "reference", None)
    resolved = getattr(ref, "resolved", None) if ref else None
    return getattr(getattr(resolved, "author", None), "id", None) == bot_user_id


def strip_mention(content: str, bot_user_id: int) -> str:
    for token in (f"<@{bot_user_id}>", f"<@!{bot_user_id}>"):
        content = content.replace(token, " ")
    return " ".join(content.split())


def split_message(text: str, limit: int = DISCORD_LIMIT - 100) -> list[str]:
    """Split on paragraph, then line, then hard boundaries, under Discord's 2000-character cap."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    parts: list[str] = []
    while len(text) > limit:
        cut = max(text.rfind("\n\n", 0, limit), text.rfind("\n", 0, limit), text.rfind(" ", 0, limit))
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


class Limiter:
    """Per-user cooldown plus a daily question cap. Keeps no message content."""

    def __init__(self, cooldown: float, daily_limit: int, clock=time.time):
        self.cooldown = cooldown
        self.daily_limit = daily_limit
        self._clock = clock
        self._last: dict[int, float] = {}
        self._day = self._today()
        self._count = 0
        self._in_flight: set[int] = set()
        self._per_user: dict[int, int] = defaultdict(int)

    def _today(self) -> int:
        return int(self._clock() // 86400)

    def check(self, user_id: int) -> str | None:
        """Return None if allowed, or a short reason to show the user."""
        if self._today() != self._day:
            self._day = self._today()
            self._count = 0
            self._per_user.clear()
        if user_id in self._in_flight:
            return "I am still working on your last question."
        wait = self.cooldown - (self._clock() - self._last.get(user_id, -1e12))
        if wait > 0:
            return f"Give me {int(wait) + 1}s before the next question."
        if self._count >= self.daily_limit:
            return "The daily question limit is used up. Try again tomorrow."
        return None

    def start(self, user_id: int) -> None:
        self._in_flight.add(user_id)
        self._last[user_id] = self._clock()
        self._count += 1

    def finish(self, user_id: int) -> None:
        self._in_flight.discard(user_id)
