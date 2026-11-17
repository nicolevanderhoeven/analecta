from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS

import discord

from analecta.bot import AnalectaBot
from analecta.commands import AnalectaTree, DiceCommands, SHEET_HELP, register_commands
from analecta.gating import Limiter, is_allowed_interaction
from analecta.sheets import SheetStore

FIXTURE = Path(__file__).parent / "fixtures" / "sheets" / "synthetic_pathbuilder.json"
GUILD, CHANNEL, THREAD = 1, 10, 55
ALEX, BLAIR, GM = 1001, 1002, 9001


class Seq:
    def __init__(self, *v):
        self.v = list(v)

    def randint(self, a, b):
        return self.v.pop(0)


class FakeInteraction:
    def __init__(self, user=ALEX, *, guild=GUILD, channel=CHANNEL, parent=None):
        self.user = NS(id=user, display_name=f"user{user}")
        self.guild_id = guild
        self.channel_id = channel
        self.channel = NS(id=channel, parent_id=parent)
        self.sent: list[dict] = []
        self.done = False
        self.response = NS(is_done=lambda: self.done, send_message=self._send, defer=self._defer)
        self.followup = NS(send=self._follow)

    async def _send(self, text, **kw):
        self.done = True
        self.sent.append({"text": text, **kw})

    async def _defer(self, **kw):
        self.done = True

    async def _follow(self, text, **kw):
        self.sent.append({"text": text, **kw})

    @property
    def texts(self):
        return [s["text"] for s in self.sent]


class Attachment:
    def __init__(self, data: bytes, size: int | None = None):
        self.data, self.size = data, len(data) if size is None else size

    async def read(self):
        return self.data


def make(tmp_path, rng=None):
    store = SheetStore(tmp_path / "sheets", gm_ids=[GM])
    return store, DiceCommands(store, [(GUILD, CHANNEL)], rng)


def run(coro):
    return asyncio.run(coro)


def add(cmds, user=ALEX, data=None):
    it = FakeInteraction(user)
    run(cmds.sheet_add(it, Attachment(data or FIXTURE.read_bytes())))
    return it


def test_sheet_add_is_private_registers_and_confirms(tmp_path):
    store, cmds = make(tmp_path)
    it = add(cmds)
    assert it.sent[0]["ephemeral"] is True
    assert "Saved **Test Hero**, level 5 Cleric" in it.texts[0] and "registered" in it.texts[0]
    assert store.character_name_for(ALEX) == "Test Hero"
    again = add(cmds)
    assert "Updated **Test Hero**" in again.texts[0] and "2 of 10" in again.texts[0]


def test_sheet_add_refusals_are_explained_and_save_nothing(tmp_path):
    store, cmds = make(tmp_path)
    add(cmds)
    clash = add(cmds, BLAIR)
    assert "belongs to someone else" in clash.texts[0] and store.get("Test Hero").owner_id == ALEX
    assert "not JSON" in add(cmds, BLAIR, b"hello").texts[0]
    big = FakeInteraction(BLAIR)
    run(cmds.sheet_add(big, Attachment(b"{}", size=10 * 1024 * 1024)))
    assert "too big" in big.texts[0]


def test_unexpected_errors_are_reported_without_details(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("a file, not a folder")
    cmds = DiceCommands(SheetStore(blocked / "sheets"), [(GUILD, CHANNEL)])
    it = add(cmds)
    assert it.texts == ["I could not save or read that just now. Tell my owner."]


def test_roll_dice_and_skill_are_public_and_labelled(tmp_path):
    store, cmds = make(tmp_path, Seq(14, 10))
    add(cmds)
    plain = FakeInteraction()
    run(cmds.roll(plain, "1d20+5"))
    assert plain.sent[0]["ephemeral"] is False and "**19**" in plain.texts[0]
    skill = FakeInteraction()
    run(cmds.roll(skill, "Religion -2"))
    assert "from saved sheet" in skill.texts[0] and "**22**" in skill.texts[0] and skill.sent[0]["ephemeral"] is False


def test_roll_for_another_character_by_name(tmp_path):
    store, cmds = make(tmp_path, Seq(10))
    add(cmds)
    it = FakeInteraction(BLAIR)
    run(cmds.roll(it, "Will", "test hero"))
    assert "Test Hero" in it.texts[0] and "**24**" in it.texts[0]


def test_secret_roll_is_ephemeral_with_a_public_line(tmp_path):
    store, cmds = make(tmp_path, Seq(10))
    add(cmds)
    it = FakeInteraction()
    run(cmds.roll(it, "Will", None, True))
    public, private = it.sent
    assert public["ephemeral"] is False and "secret check" in public["text"] and "**24**" not in public["text"]
    assert private["ephemeral"] is True and "**24**" in private["text"]
    assert public["allowed_mentions"].everyone is False


def test_roll_errors_are_ephemeral(tmp_path):
    store, cmds = make(tmp_path)
    it = FakeInteraction()
    run(cmds.roll(it, "Religion"))
    assert it.sent[0]["ephemeral"] is True and "no registered character" in it.texts[0]


def test_show_export_delete_permissions(tmp_path):
    store, cmds = make(tmp_path)
    add(cmds)
    show = FakeInteraction(BLAIR)
    run(cmds.sheet_show(show, "Test Hero"))
    assert "**Test Hero**" in show.texts[0]                              # anyone may view
    export = FakeInteraction(BLAIR)
    run(cmds.sheet_export(export, "Test Hero"))
    assert "owner or a GM" in export.texts[0] and "file" not in export.sent[0]
    mine = FakeInteraction(ALEX)
    run(cmds.sheet_export(mine))
    assert mine.sent[0]["ephemeral"] is True and mine.sent[0]["file"].filename == "test-hero.json"
    assert json.loads(mine.sent[0]["file"].fp.read())["build"]["name"] == "Test Hero"
    gm = FakeInteraction(GM)
    run(cmds.sheet_export(gm, "test hero"))
    assert "file" in gm.sent[0]
    nope = FakeInteraction(BLAIR)
    run(cmds.sheet_delete(nope, "Test Hero", True))
    assert "owner or a GM" in nope.texts[0] and store.find("Test Hero")


def test_delete_needs_confirmation_then_erases(tmp_path):
    store, cmds = make(tmp_path)
    add(cmds)
    ask = FakeInteraction()
    run(cmds.sheet_delete(ask))
    assert "confirm" in ask.texts[0] and store.find("Test Hero")
    done = FakeInteraction()
    run(cmds.sheet_delete(done, None, True))
    assert "Deleted" in done.texts[0] and store.find("Test Hero") is None and store.character_name_for(ALEX) is None


def test_character_register_list_unregister(tmp_path):
    store, cmds = make(tmp_path)
    add(cmds)
    reg = FakeInteraction(GM)
    run(cmds.character_register(reg, "Test Hero", NS(id=BLAIR)))
    assert "<@1002> is now registered" in reg.texts[0] and reg.sent[0]["allowed_mentions"].users is False
    refused = FakeInteraction(555)
    run(cmds.character_register(refused, "Test Hero"))
    assert "already registered" in refused.texts[0]
    listing = FakeInteraction()
    run(cmds.character_list(listing))
    assert "**Test Hero**" in listing.texts[0] and "<@1001>" in listing.texts[0] and "<@1002>" in listing.texts[0]
    un = FakeInteraction(BLAIR)
    run(cmds.character_unregister(un))
    assert "no longer registered" in un.texts[0] and store.character_name_for(BLAIR) is None
    empty = DiceCommands(SheetStore(tmp_path / "empty"), [(GUILD, CHANNEL)])
    it = FakeInteraction()
    run(empty.character_list(it))
    assert "No characters" in it.texts[0]


def test_help_explains_export_and_deletion():
    for word in ("Pathbuilder", "/sheet add", "/roll 1d20+5", "/roll Religion -2", "/sheet delete", "language model"):
        assert word in SHEET_HELP
    assert len(SHEET_HELP) < 2000


def test_channel_gate_for_interactions():
    locs = [(GUILD, CHANNEL)]
    assert is_allowed_interaction(FakeInteraction(), locs)
    assert is_allowed_interaction(FakeInteraction(channel=THREAD, parent=CHANNEL), locs)       # a thread under it
    assert not is_allowed_interaction(FakeInteraction(channel=11), locs)
    assert not is_allowed_interaction(FakeInteraction(channel=THREAD, parent=11), locs)
    assert not is_allowed_interaction(FakeInteraction(guild=2), locs)                           # another server
    assert not is_allowed_interaction(FakeInteraction(guild=None), locs)                        # DMs


def test_other_channels_get_an_ephemeral_pointer_and_no_autocomplete(tmp_path):
    store, cmds = make(tmp_path)
    add(cmds)
    tree = AnalectaTree(_client(), cmds)
    elsewhere = FakeInteraction(channel=11)
    assert run(tree.interaction_check(elsewhere)) is False
    assert elsewhere.sent[0]["ephemeral"] is True and "<#10>" in elsewhere.texts[0]
    assert run(tree.interaction_check(FakeInteraction())) is True
    assert run(cmds.character_choices(elsewhere, "")) == []
    assert [c.value for c in run(cmds.character_choices(FakeInteraction(), "hero"))] == ["Test Hero"]
    assert run(cmds.character_choices(FakeInteraction(), "zzz")) == []


def _client():
    return discord.Client(intents=discord.Intents.none())


def test_bot_registers_the_commands_and_syncs_only_to_configured_servers(tmp_path):
    store, _ = make(tmp_path)
    bot = AnalectaBot(agent=None, locations=[(GUILD, CHANNEL), (2, 20)], limiter=Limiter(0, 10), sheets=store)
    names = {c.name for c in bot.tree.get_commands()}
    assert names == {"roll", "sheet", "character", "companion", "gm"}
    assert {c.name for c in bot.tree.get_command("gm").commands} == {"add", "remove", "list"}
    sheet = bot.tree.get_command("sheet")
    assert {c.name for c in sheet.commands} == {"help", "add", "show", "export", "delete"}
    assert {c.name for c in bot.tree.get_command("character").commands} == {"register", "list", "unregister"}
    synced = []

    async def fake_sync(*, guild=None):
        synced.append(guild.id)
        return []
    bot.tree.sync = fake_sync
    run(bot.setup_hook())
    assert synced == [GUILD, 2]
    assert all(cmd.guild_only for cmd in bot.tree.get_commands())


def test_without_a_sheet_store_there_are_no_slash_commands():
    bot = AnalectaBot(agent=None, locations=[(GUILD, CHANNEL)], limiter=Limiter(0, 10))
    assert bot.tree is None
    run(bot.setup_hook())


def test_register_commands_roll_option_names():
    cmds = DiceCommands(SheetStore("/nonexistent/analecta-test"), [(GUILD, CHANNEL)])
    tree = AnalectaTree(_client(), cmds)
    register_commands(tree, cmds)
    roll = tree.get_command("roll")
    assert [p.name for p in roll.parameters] == ["what", "character", "secret", "companion"]
    assert [p.required for p in roll.parameters] == [True, False, False, False]


# -- /gm ---------------------------------------------------------------------------------------------------
OWNER, NEWGM = 7001, 7002


def make_gm(tmp_path, owner=OWNER):
    store = SheetStore(tmp_path / "sheets", gm_ids=[GM])

    async def is_owner(uid):
        return uid == owner
    return store, DiceCommands(store, [(GUILD, CHANNEL)], None, is_owner)


def test_gm_add_is_owner_only_and_persists(tmp_path):
    store, cmds = make_gm(tmp_path)
    nope = FakeInteraction(ALEX)
    run(cmds.gm_add(nope, NS(id=NEWGM)))
    assert "Only the bot's owner" in nope.texts[0] and nope.sent[0]["ephemeral"] is True
    assert not store.is_gm(NEWGM)
    ok = FakeInteraction(OWNER)
    run(cmds.gm_add(ok, NS(id=NEWGM)))
    assert "now a GM" in ok.texts[0] and ok.sent[0]["ephemeral"] is True
    assert store.is_gm(NEWGM)
    again = SheetStore(tmp_path / "sheets")  # a fresh store reads it back from disk
    assert again.is_gm(NEWGM) and not again.is_gm(ALEX)
    dup = FakeInteraction(OWNER)
    run(cmds.gm_add(dup, NS(id=NEWGM)))
    assert "already a GM" in dup.texts[0]


def test_gm_added_from_discord_can_manage_sheets(tmp_path):
    store, cmds = make_gm(tmp_path)
    add(cmds, ALEX)
    blocked = FakeInteraction(NEWGM)
    run(cmds.sheet_export(blocked, "test hero"))
    assert "file" not in blocked.sent[0]
    run(cmds.gm_add(FakeInteraction(OWNER), NS(id=NEWGM)))
    allowed = FakeInteraction(NEWGM)
    run(cmds.sheet_export(allowed, "test hero"))
    assert "file" in allowed.sent[0]


def test_gm_remove_is_owner_only_and_keeps_env_gms(tmp_path):
    store, cmds = make_gm(tmp_path)
    run(cmds.gm_add(FakeInteraction(OWNER), NS(id=NEWGM)))
    nope = FakeInteraction(GM)
    run(cmds.gm_remove(nope, NS(id=NEWGM)))
    assert "Only the bot's owner" in nope.texts[0] and store.is_gm(NEWGM)
    ok = FakeInteraction(OWNER)
    run(cmds.gm_remove(ok, NS(id=NEWGM)))
    assert "no longer a GM" in ok.texts[0] and not store.is_gm(NEWGM)
    env = FakeInteraction(OWNER)
    run(cmds.gm_remove(env, NS(id=GM)))
    assert "env file" in env.texts[0] and store.is_gm(GM)
    none = FakeInteraction(OWNER)
    run(cmds.gm_remove(none, NS(id=ALEX)))
    assert "not a GM" in none.texts[0]


def test_gm_env_gm_is_not_stored_by_add(tmp_path):
    store, cmds = make_gm(tmp_path)
    ix = FakeInteraction(OWNER)
    run(cmds.gm_add(ix, NS(id=GM)))
    assert "env file" in ix.texts[0] and not (tmp_path / "sheets" / "gms.json").exists()


def test_gm_list_is_open_to_anyone_and_labels_env_gms(tmp_path):
    store, cmds = make_gm(tmp_path)
    run(cmds.gm_add(FakeInteraction(OWNER), NS(id=NEWGM)))
    ix = FakeInteraction(ALEX)
    run(cmds.gm_list(ix))
    text = ix.texts[0]
    assert f"<@{GM}> (set in the server's env file)" in text and f"- <@{NEWGM}>" in text
    assert ix.sent[0]["ephemeral"] is True
    empty = DiceCommands(SheetStore(tmp_path / "other"), [(GUILD, CHANNEL)])
    ix2 = FakeInteraction(ALEX)
    run(empty.gm_list(ix2))
    assert "no GMs" in ix2.texts[0]


def test_gm_owner_check_fails_closed(tmp_path):
    store = SheetStore(tmp_path / "sheets")

    async def broken(uid):
        raise RuntimeError("discord down")
    for cmds in (DiceCommands(store, [(GUILD, CHANNEL)]), DiceCommands(store, [(GUILD, CHANNEL)], None, broken)):
        ix = FakeInteraction(OWNER)
        run(cmds.gm_add(ix, NS(id=NEWGM)))
        assert "Only the bot's owner" in ix.texts[0] and not store.is_gm(NEWGM)


def test_corrupt_gms_file_means_no_added_gms(tmp_path):
    store = SheetStore(tmp_path, gm_ids=[GM])
    (tmp_path / "gms.json").write_text('{"user_ids": ["x", true, -1, 5, 7.5]}')
    assert store.added_gms() == frozenset({5})
    (tmp_path / "gms.json").write_text("not json")
    assert store.added_gms() == frozenset() and store.is_gm(GM)


def test_bot_app_owner_check(tmp_path):
    store, _ = make(tmp_path)
    bot = AnalectaBot(agent=None, locations=[(GUILD, CHANNEL)], limiter=Limiter(0, 10), sheets=store)
    calls = []

    async def info():
        calls.append(1)
        return NS(owner=NS(id=OWNER), team=None)
    bot.application_info = info
    assert run(bot._is_app_owner(OWNER)) is True and run(bot._is_app_owner(ALEX)) is False
    assert len(calls) == 1  # looked up once, then cached

    async def team_info():
        return NS(owner=NS(id=1), team=NS(owner_id=OWNER))
    bot2 = AnalectaBot(agent=None, locations=[(GUILD, CHANNEL)], limiter=Limiter(0, 10), sheets=store)
    bot2.application_info = team_info
    assert run(bot2._is_app_owner(OWNER)) is True and run(bot2._is_app_owner(1)) is False
