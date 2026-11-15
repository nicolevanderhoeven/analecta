from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

from analecta.agent import AgentResult
from analecta.bot import AnalectaBot, _merge_roles
from analecta.clearances import PINNED_NOTE
from analecta.gating import Limiter
from analecta.llm.base import Message, ProviderError

BOT_ID, CHANNEL, GUILD = 7, 10, 1


class FakeAgent:
    def __init__(self, text="the answer", error=None):
        self.text, self.error, self.calls = text, error, []

    async def answer(self, history):
        self.calls.append(history)
        if self.error:
            raise self.error
        return AgentResult(text=self.text)


class Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def make_bot(agent=None, **limits):
    bot = AnalectaBot(agent=agent or FakeAgent(), channel_id=CHANNEL, guild_id=GUILD,
                      limiter=Limiter(limits.get("cooldown", 0), limits.get("daily", 100)))
    bot._connection.user = NS(id=BOT_ID)
    return bot


def make_msg(content="<@7> who is Old Quill?", *, channel=CHANNEL, guild=GUILD, author=99, is_bot=False,
             mentions=(BOT_ID,)):
    replies = []

    async def reply(text, **kw):
        replies.append(text)

    ch = NS(id=channel, parent_id=None, typing=lambda: Typing())
    return NS(author=NS(id=author, bot=is_bot), guild=NS(id=guild) if guild else None, channel=ch,
              content=content, mentions=[NS(id=m) for m in mentions], reference=None,
              reply=reply, replies=replies)


def run(bot, msg):
    asyncio.run(bot.on_message(msg))
    return msg.replies


def test_answers_in_channel_when_mentioned():
    agent = FakeAgent()
    bot = make_bot(agent)
    assert run(bot, make_msg()) == ["the answer"]
    assert agent.calls[0][-1].text == "who is Old Quill?"


def test_ignores_everything_else():
    agent = FakeAgent()
    bot = make_bot(agent)
    for msg in (
        make_msg(channel=11),            # other channel
        make_msg(guild=None),            # DM
        make_msg(guild=2),               # other server
        make_msg(is_bot=True),           # other bots
        make_msg(mentions=()),           # not addressed
    ):
        assert run(bot, msg) == []
    assert agent.calls == []


def test_help_gets_pinned_note_without_calling_model():
    agent = FakeAgent()
    bot = make_bot(agent)
    replies = run(bot, make_msg("<@7> help"))
    assert "".join(replies).replace("\n", "").startswith(PINNED_NOTE[:60].replace("\n", ""))
    assert agent.calls == []


def test_empty_question_also_shows_help():
    bot = make_bot()
    assert run(bot, make_msg("<@7>")) != []


def test_cooldown_and_daily_limit():
    bot = make_bot(cooldown=60)
    assert run(bot, make_msg()) == ["the answer"]
    assert "before the next" in run(bot, make_msg())[0]
    bot2 = make_bot(daily=0)
    assert "daily" in run(bot2, make_msg())[0]


def test_provider_error_message_and_limiter_released():
    bot = make_bot(FakeAgent(error=ProviderError("RateLimitError")))
    assert "could not reach" in run(bot, make_msg())[0]
    assert not bot.limiter._in_flight


def test_unexpected_error_does_not_leak_details():
    bot = make_bot(FakeAgent(error=RuntimeError("secret detail")))
    out = run(bot, make_msg())
    assert out == ["Something went wrong on my side."]


def test_very_long_question_rejected():
    agent = FakeAgent()
    bot = make_bot(agent)
    assert "too long" in run(bot, make_msg("<@7> " + "x" * 2000))[0]
    assert agent.calls == []


def test_merge_roles():
    merged = _merge_roles([Message("user", "a"), Message("user", "b"), Message("assistant", "c")])
    assert [(m.role, m.text) for m in merged] == [("user", "a\nb"), ("assistant", "c")]
