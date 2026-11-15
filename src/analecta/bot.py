"""Discord front end: configured channels, mention or reply to ask, reply chain is the conversation memory."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

import discord

from .agent import Agent
from .clearances import PINNED_NOTE
from .corrections import (CORRECT, MAX_CORRECTION_CHARS, WRONG, CorrectionStore, classify_reply, is_thumbs_down,
                          scrub)
from .gating import Limiter, is_addressed, is_allowed_location, split_message, strip_mention
from .llm.base import Message, ProviderError

log = logging.getLogger("analecta.bot")

MAX_CHAIN = 8
MAX_QUESTION_CHARS = 1500
HELP_WORDS = {"help", "about", "?", "what can you see", "what do you see"}

CORRECT_USAGE = "Reply to one of my answers with `/correct` and then the correction, for example `/correct Mira is Tobin's sister`."
SAVED_CORRECTION = "Saved as a table correction. I will use it ahead of the notes, and the notes themselves are unchanged."
LOGGED_MISREAD = "Logged for review, thanks. The notes are unchanged."
SAVE_FAILED = "I could not save that just now. Tell my owner."
_NOT_ANSWERS = frozenset({CORRECT_USAGE, SAVED_CORRECTION, LOGGED_MISREAD, SAVE_FAILED})  # our own acknowledgements


class AnalectaBot(discord.Client):
    def __init__(self, *, agent: Agent, locations: Iterable[tuple[int, int]], limiter: Limiter,
                 corrections: CorrectionStore | None = None):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.guild_reactions = True  # to see a thumbs-down on an answer (not a privileged intent)
        intents.message_content = True  # privileged: enable "Message Content Intent" in the developer portal
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.agent = agent
        self.locations = tuple(locations)
        self.limiter = limiter
        self.corrections = corrections
        self._slots = asyncio.Semaphore(2)

    async def on_ready(self) -> None:
        log.info("ready; watching %d configured channel(s)", len(self.locations))

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None:
            return
        if not is_allowed_location(message, self.locations):
            return
        question = strip_mention(message.content, self.user.id)
        if self.corrections is not None and await self._feedback(message, question):
            return
        if not is_addressed(message, self.user.id):
            return
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

    # -- feedback: misreads and table corrections --------------------------------------------------------------

    async def _feedback(self, message: discord.Message, text: str) -> bool:
        """Handle a reply to one of our answers that says "wrong" or starts with /correct. True if it was feedback."""
        kind, payload = classify_reply(text)
        if kind is None:
            return False
        answer = await self._bot_message_replied_to(message)
        if answer is None:
            if kind == CORRECT and is_addressed(message, self.user.id):
                await message.reply(CORRECT_USAGE, mention_author=False)
                return True
            return False  # not about one of our answers: nothing to flag or correct
        by = _display_name(message.author)
        question = await self._question_behind(answer)
        try:
            if kind == WRONG:
                self.corrections.log_misread(question=question, answer=answer.content, by=by,
                                             how="reply", message_id=answer.id)
                await message.reply(LOGGED_MISREAD, mention_author=False)
                return True
            if not payload:
                await message.reply(CORRECT_USAGE, mention_author=False)
            elif len(scrub(payload, MAX_CORRECTION_CHARS + 1)) > MAX_CORRECTION_CHARS:
                await message.reply(f"Please keep a correction under {MAX_CORRECTION_CHARS} characters.",
                                    mention_author=False)
            else:
                self.corrections.add_correction(payload, by, about=question)
                await message.reply(SAVED_CORRECTION, mention_author=False)
        except OSError:  # never log what was said
            log.exception("could not save feedback")
            await message.reply(SAVE_FAILED, mention_author=False)
        return True

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """A thumbs-down on one of our answers, in a configured channel, logs it to the misread list."""
        if self.corrections is None or self.user is None or payload.guild_id is None:
            return
        if payload.user_id == self.user.id or getattr(payload.member, "bot", False):
            return
        if not is_thumbs_down(payload.emoji):
            return
        if payload.guild_id not in {guild_id for guild_id, _ in self.locations}:
            return
        channel = self.get_channel(payload.channel_id)
        try:
            if channel is None:
                channel = await self.fetch_channel(payload.channel_id)
            # Check the place before fetching the message, so reactions elsewhere cost no extra request.
            if not is_allowed_location(_Place(getattr(channel, "guild", None), channel), self.locations):
                return
            answer = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        if answer.author.id != self.user.id or not is_allowed_location(answer, self.locations):
            return
        if answer.reference is None or answer.content in _NOT_ANSWERS:  # not an answer to anyone
            return
        member = payload.member
        by = _display_name(member) if member is not None else "someone"
        question = await self._question_behind(answer)
        try:
            new = self.corrections.log_misread(question=question, answer=answer.content, by=by,
                                               how="\N{THUMBS DOWN SIGN} reaction", message_id=answer.id)
            if new:
                await answer.reply(LOGGED_MISREAD, mention_author=False)
        except OSError:
            log.exception("could not save feedback")
            await answer.reply(SAVE_FAILED, mention_author=False)

    async def _bot_message_replied_to(self, message: discord.Message) -> discord.Message | None:
        """The bot's own message that `message` replies to (same channel only), or None."""
        parent = await self._referenced(message)
        if parent is None or getattr(getattr(parent, "author", None), "id", None) != self.user.id:
            return None
        if parent.content in _NOT_ANSWERS:
            return None
        return parent

    async def _question_behind(self, answer: discord.Message) -> str:
        """The text of the message our answer replied to, with mentions scrubbed; empty if it is not available."""
        parent = await self._referenced(answer)
        if parent is None:
            return ""
        return scrub(strip_mention(getattr(parent, "content", ""), self.user.id), 2000)

    async def _referenced(self, message: discord.Message) -> discord.Message | None:
        ref = getattr(message, "reference", None)
        if ref is None or getattr(ref, "message_id", None) is None:
            return None
        parent = getattr(ref, "resolved", None)
        if parent is None or not hasattr(parent, "author"):  # not cached, or deleted
            try:
                parent = await message.channel.fetch_message(ref.message_id)
            except discord.HTTPException:
                return None
        if getattr(getattr(parent, "channel", None), "id", None) != message.channel.id:
            return None
        return parent

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


class _Place:
    """A (server, channel) pair shaped like a message, for is_allowed_location."""

    def __init__(self, guild: object, channel: object):
        self.guild, self.channel = guild, channel


def _display_name(user: object) -> str:
    return str(getattr(user, "display_name", None) or getattr(user, "name", None) or "someone")


def _merge_roles(chain: list[Message]) -> list[Message]:
    """Collapse consecutive same-role messages so providers get an alternating conversation."""
    merged: list[Message] = []
    for m in chain:
        if merged and merged[-1].role == m.role:
            merged[-1] = Message(role=m.role, text=merged[-1].text + "\n" + m.text)
        else:
            merged.append(m)
    return merged
