from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import discord
import pytest

from analecta.agent import AgentResult
from analecta.bot import AnalectaBot, _merge_roles
from analecta.clearances import PINNED_NOTE
from analecta.corrections import CorrectionStore
from analecta.gating import Limiter
from analecta.llm.base import Message, ProviderError

BOT_ID, CHANNEL, GUILD = 7, 10, 1
OTHER_CHANNEL, OTHER_GUILD = 20, 2
LOCATIONS = [(GUILD, CHANNEL), (OTHER_GUILD, OTHER_CHANNEL)]


MESSAGES: dict[int, NS] = {}  # messages a fake channel can fetch by id; cleared before each test


@pytest.fixture(autouse=True)
def _clear_messages():
    MESSAGES.clear()


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


def make_bot(agent=None, corrections=None, **limits):
    bot = AnalectaBot(agent=agent or FakeAgent(), locations=LOCATIONS, corrections=corrections,
                      limiter=Limiter(limits.get("cooldown", 0), limits.get("daily", 100)))
    bot._connection.user = NS(id=BOT_ID)
    return bot


def make_msg(content="<@7> who is Old Quill?", *, channel=CHANNEL, guild=GUILD, author=99, is_bot=False,
             mentions=(BOT_ID,), reference=None, msg_id=1, name="Alex"):
    replies = []

    async def reply(text, **kw):
        replies.append(text)

    async def fetch_message(message_id):
        return MESSAGES[message_id]

    g = NS(id=guild) if guild else None
    ch = NS(id=channel, parent_id=None, typing=lambda: Typing(), guild=g, fetch_message=fetch_message)
    msg = NS(id=msg_id, author=NS(id=author, bot=is_bot, display_name=name), guild=g,
             channel=ch, content=content, mentions=[NS(id=m) for m in mentions], reference=reference,
             reply=reply, replies=replies)
    if msg_id > 1:
        MESSAGES[msg_id] = msg
    return msg


def run(bot, msg):
    asyncio.run(bot.on_message(msg))
    return msg.replies


def test_answers_in_channel_when_mentioned():
    agent = FakeAgent()
    bot = make_bot(agent)
    assert run(bot, make_msg()) == ["the answer"]
    assert agent.calls[0][-1].text == "who is Old Quill?"


def test_answers_in_second_server_too():
    agent = FakeAgent()
    bot = make_bot(agent)
    assert run(bot, make_msg(channel=OTHER_CHANNEL, guild=OTHER_GUILD)) == ["the answer"]
    assert len(agent.calls) == 1


def test_ignores_everything_else():
    agent = FakeAgent()
    bot = make_bot(agent)
    for msg in (
        make_msg(channel=11),            # other channel
        make_msg(guild=None),            # DM
        make_msg(guild=3),               # unlisted server
        make_msg(guild=OTHER_GUILD),     # listed server, but this channel belongs to the first one
        make_msg(channel=OTHER_CHANNEL), # second server's channel id in the first server
        make_msg(channel=21, guild=OTHER_GUILD),  # other channel in the second server
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


# -- misreads (thumbs-down, "wrong") and table corrections (/correct) ------------------------------------------

NOON = datetime(2026, 11, 12, 14, 3, tzinfo=timezone.utc)


@pytest.fixture()
def store(tmp_path):
    return CorrectionStore(tmp_path / "data", clock=lambda: NOON)


def make_answer(text="Mira is Tobin's cousin.", *, channel=CHANNEL, guild=GUILD, question="<@7> who is Mira?",
                answer_id=500, author=BOT_ID):
    """One of Analecta's answers, replying to a player's question."""
    q = make_msg(question, channel=channel, guild=guild, msg_id=400, name="Pat")
    a = make_msg(text, channel=channel, guild=guild, author=author, is_bot=True, mentions=(), msg_id=answer_id,
                 reference=NS(message_id=400, resolved=q))
    return a


def reply_to(answer, content, **kw):
    return make_msg(content, mentions=kw.pop("mentions", ()), reference=NS(message_id=answer.id, resolved=answer), **kw)


def reaction(answer, emoji="\N{THUMBS DOWN SIGN}", *, user=99, guild=GUILD, bot_member=False):
    return NS(guild_id=guild, channel_id=answer.channel.id, message_id=answer.id, user_id=user, member=NS(bot=bot_member, display_name="Sam"),
              emoji=discord.PartialEmoji(name=emoji))


def react(bot, answer, payload):
    bot.get_channel = lambda cid: answer.channel if cid == answer.channel.id else None
    asyncio.run(bot.on_raw_reaction_add(payload))
    return answer.replies


def test_wrong_reply_logs_question_and_answer_without_calling_the_model(store):
    agent = FakeAgent()
    bot = make_bot(agent, store)
    answer = make_answer()
    msg = reply_to(answer, "<@7> Wrong!", mentions=(BOT_ID,))
    assert run(bot, msg) == ["Logged for review, thanks. The notes are unchanged."]
    text = store.misreads_path.read_text()
    assert "reply · flagged by Alex" in text and "**Question:** who is Mira?" in text
    assert "> Mira is Tobin's cousin." in text
    assert agent.calls == [] and not store.corrections_path.exists()


def test_thumbs_down_reaction_logs_once_and_acknowledges(store):
    bot = make_bot(corrections=store)
    answer = make_answer()
    assert react(bot, answer, reaction(answer)) == ["Logged for review, thanks. The notes are unchanged."]
    text = store.misreads_path.read_text()
    assert "\N{THUMBS DOWN SIGN} reaction · flagged by Sam" in text and "**Question:** who is Mira?" in text
    assert "> Mira is Tobin's cousin." in text
    assert react(bot, answer, reaction(answer, user=98)) == answer.replies  # same answer again: no new entry or reply
    assert len(answer.replies) == 1 and store.misreads_path.read_text().count("<!-- id:500 -->") == 1


def test_thumbs_down_works_in_the_second_server_and_in_a_thread(store):
    bot = make_bot(corrections=store)
    other = make_answer(channel=OTHER_CHANNEL, guild=OTHER_GUILD)
    assert len(react(bot, other, reaction(other, guild=OTHER_GUILD))) == 1
    thread = make_answer(answer_id=501)
    thread.channel.id, thread.channel.parent_id = 55, CHANNEL
    assert len(react(bot, thread, reaction(thread))) == 1


def test_correct_reply_is_saved_with_who_and_when_and_acknowledged(store):
    agent = FakeAgent()
    bot = make_bot(agent, store)
    answer = make_answer()
    msg = reply_to(answer, "/correct Mira is Tobin's sister, not his cousin", name="Alex")
    assert run(bot, msg) == ["Saved as a table correction. I will use it ahead of the notes, and the notes themselves are unchanged."]
    saved = store.corrections_path.read_text()
    assert "- [2026-11-12 14:03 UTC] **Alex**: Mira is Tobin's sister, not his cousin\n  - re: who is Mira?\n" in saved
    assert agent.calls == [] and not store.misreads_path.exists()
    assert [c.text for c in store.load()] == ["Mira is Tobin's sister, not his cousin"]


def test_correct_without_text_or_too_long_is_not_saved(store):
    bot = make_bot(corrections=store)
    answer = make_answer()
    assert "`/correct`" in run(bot, reply_to(answer, "/correct"))[0]
    assert "under 500 characters" in run(bot, reply_to(answer, "/correct " + "x" * 600))[0]
    assert not store.corrections_path.exists()


def test_correct_with_a_mention_but_no_reply_gets_a_hint_and_saves_nothing(store):
    bot = make_bot(corrections=store)
    assert "Reply to one of my answers" in run(bot, make_msg("<@7> /correct Mira is a sister"))[0]
    assert not store.corrections_path.exists()


def test_feedback_ignored_outside_configured_channels_and_when_not_replying_to_analecta(store):
    agent = FakeAgent()
    bot = make_bot(agent, store)
    elsewhere = [
        make_answer(channel=11),                                   # other channel, our server
        make_answer(guild=3),                                      # unlisted server
        make_answer(guild=OTHER_GUILD),                            # channel belongs to the first server
        make_answer(channel=OTHER_CHANNEL),                        # second server's channel in the first server
    ]
    for answer in elsewhere:
        assert run(bot, reply_to(answer, "/correct Mira is a sister", channel=answer.channel.id, guild=answer.guild.id)) == []
        assert run(bot, reply_to(answer, "wrong", channel=answer.channel.id, guild=answer.guild.id)) == []
        assert react(bot, answer, reaction(answer, guild=answer.guild.id)) == []
    dm = reply_to(make_answer(), "/correct x", guild=None)
    assert run(bot, dm) == []
    # In the right channel, but not a reply to Analecta:
    someone = make_answer(author=77)                                # another member's message, not ours
    assert run(bot, reply_to(someone, "/correct Mira is a sister")) == []
    assert run(bot, reply_to(someone, "wrong")) == []
    assert run(bot, make_msg("/correct Mira is a sister", mentions=())) == []   # plain message, no reply
    assert run(bot, make_msg("wrong", mentions=())) == []
    assert react(bot, someone, reaction(someone)) == []
    assert agent.calls == [] and not store.corrections_path.exists() and not store.misreads_path.exists()


def test_other_reactions_other_reactors_and_non_answers_are_ignored(store):
    bot = make_bot(corrections=store)
    answer = make_answer()
    assert react(bot, answer, reaction(answer, "\N{THUMBS UP SIGN}")) == []
    assert react(bot, answer, reaction(answer, bot_member=True)) == []          # another bot
    assert react(bot, answer, reaction(answer, user=BOT_ID)) == []              # ourselves
    ack = make_answer("Logged for review, thanks. The notes are unchanged.", answer_id=502)
    assert react(bot, ack, reaction(ack)) == []                                 # our own acknowledgement
    assert run(bot, reply_to(ack, "/correct x")) != [] and not store.corrections_path.exists()  # hint only
    assert not store.misreads_path.exists()


def test_reaction_in_other_channel_does_not_fetch_anything(store):
    bot = make_bot(corrections=store)
    answer = make_answer(channel=11)
    calls = []

    async def fetch(_):
        calls.append(1)
        return answer
    answer.channel.fetch_message = fetch
    bot.get_channel = lambda cid: answer.channel
    asyncio.run(bot.on_raw_reaction_add(reaction(answer)))
    assert calls == [] and not store.misreads_path.exists()


def test_save_failure_is_reported_without_details(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a folder")
    bot = make_bot(corrections=CorrectionStore(blocked / "data"))
    answer = make_answer()
    assert run(bot, reply_to(answer, "/correct Mira is a sister")) == ["I could not save that just now. Tell my owner."]
    assert run(bot, reply_to(answer, "wrong")) == ["I could not save that just now. Tell my owner."]


def test_a_normal_reply_to_an_answer_is_still_a_question(store):
    agent = FakeAgent()
    bot = make_bot(agent, store)
    answer = make_answer()
    assert run(bot, reply_to(answer, "and who is her brother?")) == ["the answer"]
    assert agent.calls and not store.misreads_path.exists() and not store.corrections_path.exists()
