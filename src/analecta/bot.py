"""Discord front end: one channel, mention or reply to ask, reply chain is the conversation memory."""
from __future__ import annotations

import asyncio
import logging

import discord

from .agent import Agent
from .clearances import PINNED_NOTE
from .gating import Limiter, is_addressed, is_allowed_location, split_message, strip_mention
from .llm.base import Message, ProviderError

log = logging.getLogger("analecta.bot")

MAX_CHAIN = 8
MAX_QUESTION_CHARS = 1500
HELP_WORDS = {"help", "about", "?", "what can you see", "what do you see"}


class AnalectaBot(discord.Client):
    def __init__(self, *, agent: Agent, channel_id: int, guild_id: int | None, limiter: Limiter):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True  # privileged: enable "Message Content Intent" in the developer portal
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.agent = agent
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.limiter = limiter
        self._slots = asyncio.Semaphore(2)

    async def on_ready(self) -> None:
        log.info("ready; watching one configured channel")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None:
            return
        if not is_allowed_location(message, channel_id=self.channel_id, guild_id=self.guild_id):
            return
        if not is_addressed(message, self.user.id):
            return
        question = strip_mention(message.content, self.user.id)
        if not question or question.lower().strip(" ?!.") in HELP_WORDS:
            for part in split_message(PINNED_NOTE):
                await message.reply(part, mention_author=False)
            return
        if len(question) > MAX_QUESTION_CHARS:
            await message.reply("That is too long for me. Please shorten the question.", mention_author=False)
            return
        uid = message.author.id
        reason = self.limiter.check(uid)
        if reason:
            await message.reply(reason, mention_author=False)
            return
        self.limiter.start(uid)
        try:
            history = await self._history(message, question)
            async with self._slots, message.channel.typing():
                result = await self.agent.answer(history)
            for part in split_message(result.text):
                await message.reply(part, mention_author=False)
        except ProviderError as exc:
            log.warning("provider error: %s", exc)
            await message.reply("I could not reach my language model just now. Try again shortly.", mention_author=False)
        except Exception:  # never leave a question hanging, never log its content
            log.exception("unexpected error while answering")
            await message.reply("Something went wrong on my side.", mention_author=False)
        finally:
            self.limiter.finish(uid)

    async def _history(self, message: discord.Message, question: str) -> list[Message]:
        """Walk the reply chain upward (bounded) to rebuild the conversation."""
        chain: list[Message] = [Message(role="user", text=question)]
        current = message
        for _ in range(MAX_CHAIN):
            ref = current.reference
            if ref is None or ref.message_id is None:
                break
            parent = ref.resolved if isinstance(ref.resolved, discord.Message) else None
            if parent is None:
                try:
                    parent = await current.channel.fetch_message(ref.message_id)
                except discord.HTTPException:
                    break
            if parent.channel.id != message.channel.id:
                break
            if parent.author.id == self.user.id:
                chain.append(Message(role="assistant", text=parent.content[:3000]))
            else:
                text = strip_mention(parent.content, self.user.id)[:MAX_QUESTION_CHARS]
                chain.append(Message(role="user", text=text))
            current = parent
        chain.reverse()
        return _merge_roles(chain)


def _merge_roles(chain: list[Message]) -> list[Message]:
    """Collapse consecutive same-role messages so providers get an alternating conversation."""
    merged: list[Message] = []
    for m in chain:
        if merged and merged[-1].role == m.role:
            merged[-1] = Message(role=m.role, text=merged[-1].text + "\n" + m.text)
        else:
            merged.append(m)
    return merged
