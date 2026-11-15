from __future__ import annotations

from types import SimpleNamespace as NS

from analecta.gating import Limiter, is_addressed, is_allowed_location, split_message, strip_mention

BOT = 7


def msg(*, guild=1, channel=10, parent=None, mentions=(), reply_to=None):
    ch = NS(id=channel, parent_id=parent)
    ref = NS(resolved=NS(author=NS(id=reply_to))) if reply_to else None
    return NS(guild=NS(id=guild) if guild else None, channel=ch,
              mentions=[NS(id=m) for m in mentions], reference=ref)


def test_only_configured_channel():
    assert is_allowed_location(msg(), channel_id=10, guild_id=1)
    assert not is_allowed_location(msg(channel=11), channel_id=10, guild_id=1)
    assert not is_allowed_location(msg(guild=None), channel_id=10, guild_id=1)  # DM
    assert not is_allowed_location(msg(guild=2), channel_id=10, guild_id=1)  # other server
    assert is_allowed_location(msg(channel=55, parent=10), channel_id=10, guild_id=1)  # thread under it
    assert not is_allowed_location(msg(channel=55, parent=11), channel_id=10, guild_id=1)
    assert is_allowed_location(msg(guild=2), channel_id=10, guild_id=None)


def test_addressed_by_mention_or_reply():
    assert is_addressed(msg(mentions=[BOT]), BOT)
    assert is_addressed(msg(reply_to=BOT), BOT)
    assert not is_addressed(msg(mentions=[99]), BOT)
    assert not is_addressed(msg(reply_to=99), BOT)
    assert not is_addressed(msg(), BOT)


def test_strip_mention():
    assert strip_mention("<@7>  who is   Quill? <@!7>", BOT) == "who is Quill?"


def test_split_message():
    assert split_message("") == []
    assert split_message("short") == ["short"]
    text = ("para one. " * 60 + "\n\n") * 5
    parts = split_message(text)
    assert all(len(p) <= 1900 for p in parts) and len(parts) > 1
    assert "".join(p.replace("\n", "").replace(" ", "") for p in parts) == text.replace("\n", "").replace(" ", "")
    assert all(len(p) <= 1900 for p in split_message("x" * 5000))


def test_limiter_cooldown_in_flight_daily():
    now = [1000.0]
    lim = Limiter(cooldown=20, daily_limit=2, clock=lambda: now[0])
    assert lim.check(1) is None
    lim.start(1)
    assert "still working" in lim.check(1)
    lim.finish(1)
    assert "before the next" in lim.check(1)
    now[0] += 25
    assert lim.check(1) is None
    lim.start(1); lim.finish(1)
    now[0] += 25
    assert "daily" in lim.check(2)
    now[0] += 86400
    assert lim.check(2) is None
