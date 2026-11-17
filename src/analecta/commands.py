"""Slash commands for dice and character sheets: /roll, /sheet (add, show, export, delete, help), /character
(register, list, unregister), /companion (add, show, remove) and /gm (add, remove, list).

`DiceCommands` holds the behaviour as plain async methods so tests can call them with a fake interaction;
`register_commands` wraps them as discord.py application commands. Sheet data is never logged and never sent to a
language model. Replies use no mentions, and everything from a sheet is escaped.
"""
from __future__ import annotations

import io
import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import discord
from discord import app_commands

from . import dice, pf2e
from .gating import is_allowed_interaction, split_message
from .rolling import escape, roll
from .sheets import KINDS, MAX_SHEET_BYTES, MAX_VERSIONS, Companion, SheetError, SheetStore

log = logging.getLogger("analecta.commands")

NO_MENTIONS = discord.AllowedMentions.none()
SAVE_FAILED = "I could not save or read that just now. Tell my owner."
WRONG_PLACE = "Dice and sheet commands only work in the channel I am set up for{where}."

SHEET_HELP = f"""\
**Adding your character sheet**
1. In Pathbuilder 2e, open your character, then the menu, then **Export**, and choose the **JSON** export that saves a file. (The wording differs a little between app versions. You want the character as a `.json` file, not the PDF and not the 6-digit number.)
2. Save the file somewhere you can find it on your phone or computer.
3. In this channel, run `/sheet add` and attach the file. Only you see my reply. Everyone in the channel can then roll for and view your character.

**Rolling:** `/roll 1d20+5` for plain dice. `/roll Religion -2` rolls your Religion skill plus an extra modifier (skills, saves, Perception and Lores work). Add `character:` to roll for someone else's character, and `secret:` to see the result only yourself.
**Companions:** an eidolon has no sheet of its own. `/companion add` attaches one to a character with its six ability modifiers; its saves, Perception and skills then use the summoner's proficiency and item bonuses. Roll for it with `/roll Athletics character:Ash`, or `companion:True` for your own character's. `/companion show` and `/companion remove` do the rest.
**Your character:** adding a sheet registers you to it if you have none. `/character register` links you to a different one (or links another player, if you own the sheet or are a GM); `/character list` shows who is who.
**GMs:** they may update, export and delete anyone's sheet. `/gm list` shows them; only my owner adds or removes one.
**Keeping it:** I save your sheet file on my server and keep your last {MAX_VERSIONS} uploads, so re-adding the same character updates it. `/sheet export` gives you the file back (this is a copy of the export, not something Pathbuilder can import). `/sheet delete` erases it and every earlier version. I do not send sheets to any language model.
**Limits:** totals are worked out from the file. Conditions, armour check penalties and temporary bonuses are not in it; put them in the extra modifier."""


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "character"


class DiceCommands:
    def __init__(self, store: SheetStore, locations: Iterable[tuple[int, int]], rng: dice.Rng | None = None,
                 is_owner: Callable[[int], Awaitable[bool]] | None = None):
        self.store = store
        self.locations = tuple(locations)
        self.rng = rng
        self.is_owner = is_owner  # who runs the bot; None means nobody, so /gm add and /gm remove always refuse

    # -- plumbing --------------------------------------------------------------------------------------------
    async def _send(self, interaction: Any, text: str, *, ephemeral: bool = True, **kw: Any) -> None:
        parts = split_message(text) or ["(nothing to show)"]
        for i, part in enumerate(parts):
            if i == 0 and not interaction.response.is_done():
                await interaction.response.send_message(part, ephemeral=ephemeral, allowed_mentions=NO_MENTIONS, **kw)
            else:
                await interaction.followup.send(part, ephemeral=ephemeral, allowed_mentions=NO_MENTIONS,
                                                **(kw if i == 0 else {}))

    async def _fail(self, interaction: Any, exc: Exception) -> None:
        if isinstance(exc, (SheetError, dice.DiceError)):
            await self._send(interaction, str(exc))
        else:
            log.error("sheet command failed (%s)", type(exc).__name__)  # never log what was in it
            await self._send(interaction, SAVE_FAILED)

    def wrong_place_text(self, guild_id: int | None) -> str:
        channels = [f"<#{c}>" for g, c in self.locations if g == guild_id]
        return WRONG_PLACE.format(where=f": {' or '.join(channels)}" if channels else "")

    def allowed(self, interaction: Any) -> bool:
        return is_allowed_interaction(interaction, self.locations)

    # -- /roll -----------------------------------------------------------------------------------------------
    async def roll(self, interaction: Any, what: str, character: str | None = None, secret: bool = False,
                   companion: bool = False) -> None:
        try:
            outcome = roll(self.store, interaction.user.id, what, character, self.rng, companion)
        except Exception as exc:  # SheetError is expected; anything else is reported without details
            await self._fail(interaction, exc)
            return
        if not secret:
            await self._send(interaction, outcome.text, ephemeral=False)
            return
        what_rolled = f"**{escape(outcome.character)}**" if outcome.character else "a roll"
        await self._send(interaction, f"\N{GAME DIE} {escape(_display(interaction.user))} rolled a secret check for "
                                      f"{what_rolled}.", ephemeral=False)
        await interaction.followup.send(outcome.text, ephemeral=True, allowed_mentions=NO_MENTIONS)

    # -- /sheet ----------------------------------------------------------------------------------------------
    async def sheet_help(self, interaction: Any) -> None:
        await self._send(interaction, SHEET_HELP)

    async def sheet_add(self, interaction: Any, file: Any) -> None:
        if getattr(file, "size", 0) > MAX_SHEET_BYTES:
            await self._send(interaction, f"That file is too big ({MAX_SHEET_BYTES // (1024 * 1024)} MB at most).")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            raw = await file.read()
            result = self.store.add(interaction.user.id, raw)
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        verb = "Saved" if result.created else "Updated"
        ident = f"level {result.level}" + (f" {escape(result.class_name)}" if result.class_name else "")
        lines = [f"{verb} **{escape(result.info.name)}**, {ident} (saved copies kept: {result.versions} of {MAX_VERSIONS})."]
        if result.suggest_eidolon:
            lines.append("Your export mentions an eidolon, but Pathbuilder does not export its stats. Add it with "
                         f"`/companion add character:{escape(result.info.name)} name: kind:eidolon` and its six ability "
                         "modifiers (see them in Pathbuilder's eidolon section); then you can roll for it.")
        if result.registered:
            lines.append("You are now registered to this character, so `/roll` uses it by default.")
        elif result.created:
            lines.append("Use `/character register` to make it your character.")
        lines.append("If that is not the character you meant, export the right one from Pathbuilder and add it again.")
        await self._send(interaction, "\n".join(lines))

    def _character_for(self, interaction: Any, character: str | None):
        if character and character.strip():
            return self.store.get(character)
        info = self.store.character_for(interaction.user.id)
        if info is None:
            raise SheetError("You have no registered character. Name one with the `character` option, "
                             "or use `/character register`.")
        return info

    async def sheet_show(self, interaction: Any, character: str | None = None) -> None:
        try:
            info = self._character_for(interaction, character)
            text = pf2e.summary(self.store.build(info))
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        await self._send(interaction, text)

    async def sheet_export(self, interaction: Any, character: str | None = None) -> None:
        try:
            info = self._character_for(interaction, character)
            if not self.store.can_manage(interaction.user.id, info):
                raise SheetError(f"Only {info.name}'s owner or a GM can export it.")
            raw = self.store.raw(info)
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        await self._send(interaction, f"The saved file for **{escape(info.name)}**.",
                         file=discord.File(io.BytesIO(raw), filename=f"{_slug(info.name)}.json"))

    async def sheet_delete(self, interaction: Any, character: str | None = None, confirm: bool = False) -> None:
        try:
            info = self._character_for(interaction, character)
            if not self.store.can_manage(interaction.user.id, info):
                raise SheetError(f"Only {info.name}'s owner or a GM can delete it.")
            if not confirm:
                await self._send(interaction, f"This erases **{escape(info.name)}** and all {self.store.version_count(info)} "
                                              "saved copies, and cannot be undone. Run the command again with `confirm` set to True.")
                return
            self.store.delete(interaction.user.id, info.name)
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        await self._send(interaction, f"Deleted **{escape(info.name)}** and every saved copy of it.")

    # -- /character ------------------------------------------------------------------------------------------
    async def character_register(self, interaction: Any, character: str, user: Any = None) -> None:
        try:
            info, target = self.store.register(interaction.user.id, character, getattr(user, "id", None))
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        who = "You are" if target == interaction.user.id else f"<@{target}> is"
        await self._send(interaction, f"{who} now registered to **{escape(info.name)}**. `/roll` uses that character by default.")

    async def character_unregister(self, interaction: Any, user: Any = None) -> None:
        try:
            info = self.store.unregister(interaction.user.id, getattr(user, "id", None))
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        target = getattr(user, "id", None)
        who = "You are" if target in (None, interaction.user.id) else f"<@{target}> is"
        await self._send(interaction, f"{who} no longer registered to **{escape(info.name)}**. The sheet is still saved.")

    async def character_list(self, interaction: Any) -> None:
        try:
            sheets = self.store.list()
            held: dict[str, list[int]] = {}
            for user_id, info in self.store.registrations():
                held.setdefault(info.id, []).append(user_id)
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        if not sheets:
            await self._send(interaction, "No characters are saved yet. See `/sheet help` to add yours.")
            return
        lines = ["**Saved characters**"]
        for info in sheets:
            players = ", ".join(f"<@{u}>" for u in held.get(info.id, [])) or "not registered to anyone"
            lines.append(f"- **{escape(info.name)}**: {players}")
        await self._send(interaction, "\n".join(lines))

    # -- /companion ------------------------------------------------------------------------------------------
    async def companion_add(self, interaction: Any, character: str, name: str, kind: str, str_: int, dex: int, con: int,
                            int_: int, wis: int, cha: int, ac: int | None = None) -> None:
        mods = dict(zip(pf2e.ABILITIES, (str_, dex, con, int_, wis, cha)))
        try:
            comp, created = self.store.add_companion(interaction.user.id, character, name, kind, mods, ac)
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        verb = "Added" if created else "Updated"
        await self._send(interaction, f"{verb} **{escape(comp.name)}**, {escape(comp.kind)} of **{escape(comp.character.name)}**. "
                                      f"Roll for it with `/roll Athletics character:{escape(comp.name)}`"
                                      + (f", or `/roll Athletics companion:True` as {escape(comp.character.name)}'s player." if created else "."))

    def _companions_of(self, interaction: Any, character: str | None) -> list[Companion]:
        text = character.strip() if character and character.strip() else ""
        if text:
            named = self.store.find_companions(text)
            if named:
                return named
        return self.store.companions(self._character_for(interaction, character))

    async def companion_show(self, interaction: Any, character: str | None = None) -> None:
        try:
            comps = self._companions_of(interaction, character)
            if not comps:
                await self._send(interaction, "That character has no companion saved. Add one with `/companion add`.")
                return
            lines = []
            for comp in comps:
                build = self.store.build(comp.character)
                lines.append(pf2e.companion_summary(build, comp.name, comp.kind, comp.character.name, comp.abilities, comp.ac))
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        await self._send(interaction, "\n\n".join(lines))

    async def companion_remove(self, interaction: Any, character: str | None = None, name: str | None = None) -> None:
        try:
            if name is None and character and self.store.find_companions(character):
                comp = self.store.find_companions(character)[0]
                character, name = comp.character.name, comp.name
            info = self._character_for(interaction, character)
            comp = self.store.remove_companion(interaction.user.id, info.name, name)
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        await self._send(interaction, f"Removed **{escape(comp.name)}** from **{escape(comp.character.name)}**.")

    # -- /gm -------------------------------------------------------------------------------------------------
    async def _owner_only(self, interaction: Any, what: str) -> bool:
        if self.is_owner is not None:
            try:
                if await self.is_owner(interaction.user.id):
                    return True
            except Exception as exc:  # could not tell who owns the bot: refuse
                log.error("owner check failed (%s)", type(exc).__name__)
        await self._send(interaction, f"Only the bot's owner can {what}.")
        return False

    async def gm_add(self, interaction: Any, user: Any) -> None:
        if not await self._owner_only(interaction, "add a GM"):
            return
        target = user.id
        if target in self.store.gm_ids:
            await self._send(interaction, f"<@{target}> is already a GM (set in the server's env file).")
            return
        try:
            added = self.store.add_gm(target)
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        await self._send(interaction, f"<@{target}> is now a GM." if added else f"<@{target}> is already a GM.")

    async def gm_remove(self, interaction: Any, user: Any) -> None:
        if not await self._owner_only(interaction, "remove a GM"):
            return
        target = user.id
        try:
            removed = self.store.remove_gm(target)
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        env = target in self.store.gm_ids
        if removed:
            text = f"<@{target}> is no longer a GM."
            if env:
                text += " They are still a GM because the server's env file lists them; only the server's owner can change that."
        elif env:
            text = (f"<@{target}> is a GM through the server's env file (`SHEETS_GM_USER_IDS`), so this command cannot "
                    "remove them. Edit the env file and restart the bot.")
        else:
            text = f"<@{target}> is not a GM."
        await self._send(interaction, text)

    async def gm_list(self, interaction: Any) -> None:
        try:
            added = sorted(self.store.added_gms() - self.store.gm_ids)
        except Exception as exc:
            await self._fail(interaction, exc)
            return
        env = sorted(self.store.gm_ids)
        if not env and not added:
            await self._send(interaction, "There are no GMs yet. The bot's owner can add one with `/gm add`.")
            return
        lines = ["**GMs** (may update, export and delete anyone's sheet)"]
        lines += [f"- <@{u}> (set in the server's env file)" for u in env]
        lines += [f"- <@{u}>" for u in added]
        await self._send(interaction, "\n".join(lines))

    # -- autocomplete ----------------------------------------------------------------------------------------
    async def character_and_companion_choices(self, interaction: Any, current: str) -> list[app_commands.Choice[str]]:
        if not self.allowed(interaction):
            return []
        try:
            names = [i.name for i in self.store.list()] + [c.name for c in self.store.all_companions()]
        except OSError:
            return []
        needle = current.strip().casefold()
        return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names if needle in n.casefold()][:25]

    async def character_choices(self, interaction: Any, current: str) -> list[app_commands.Choice[str]]:
        if not self.allowed(interaction):
            return []
        try:
            names = [i.name for i in self.store.list()]
        except OSError:
            return []
        needle = current.strip().casefold()
        return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names if needle in n.casefold()][:25]


def _display(user: Any) -> str:
    return str(getattr(user, "display_name", None) or getattr(user, "name", None) or "Someone")


class AnalectaTree(app_commands.CommandTree):
    """Keeps every slash command inside the configured channels (and their threads)."""

    def __init__(self, client: discord.Client, commands: DiceCommands):
        super().__init__(client)
        self.commands_impl = commands

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.commands_impl.allowed(interaction):
            return True
        await interaction.response.send_message(self.commands_impl.wrong_place_text(interaction.guild_id), ephemeral=True,
                                                allowed_mentions=NO_MENTIONS)
        return False


def register_commands(tree: app_commands.CommandTree, cmds: DiceCommands) -> None:
    """Attach /roll, /sheet and /character to `tree` (guild-only commands)."""

    @tree.command(name="roll", description="Roll dice (1d20+5) or a skill from your saved sheet (Religion -2)")
    @app_commands.describe(what="Dice such as 1d20+5, or a skill, save, Perception or Lore with an optional modifier",
                           character="Roll for this character or companion instead of your own character",
                           secret="Show the result only to you",
                           companion="Roll as your character's companion (for example your eidolon)")
    @app_commands.guild_only()
    async def roll_cmd(interaction: discord.Interaction, what: str, character: str | None = None, secret: bool = False,
                       companion: bool = False):
        await cmds.roll(interaction, what, character, secret, companion)

    roll_cmd.autocomplete("character")(cmds.character_and_companion_choices)

    sheet = app_commands.Group(name="sheet", description="Your saved character sheet", guild_only=True)

    @sheet.command(name="help", description="How to export your sheet from Pathbuilder 2e and add it here")
    async def sheet_help(interaction: discord.Interaction):
        await cmds.sheet_help(interaction)

    @sheet.command(name="add", description="Add or update a character from a Pathbuilder 2e JSON file")
    @app_commands.describe(file="The JSON file exported from Pathbuilder 2e")
    async def sheet_add(interaction: discord.Interaction, file: discord.Attachment):
        await cmds.sheet_add(interaction, file)

    @sheet.command(name="show", description="Show a saved character's summary")
    @app_commands.describe(character="Defaults to your own character")
    async def sheet_show(interaction: discord.Interaction, character: str | None = None):
        await cmds.sheet_show(interaction, character)

    @sheet.command(name="export", description="Get the saved JSON file for a character (owner or GM)")
    @app_commands.describe(character="Defaults to your own character")
    async def sheet_export(interaction: discord.Interaction, character: str | None = None):
        await cmds.sheet_export(interaction, character)

    @sheet.command(name="delete", description="Erase a saved character and every earlier version (owner or GM)")
    @app_commands.describe(character="Defaults to your own character", confirm="Set to True to really erase it")
    async def sheet_delete(interaction: discord.Interaction, character: str | None = None, confirm: bool = False):
        await cmds.sheet_delete(interaction, character, confirm)

    for name in ("show", "export", "delete"):
        sheet.get_command(name).autocomplete("character")(cmds.character_choices)

    character = app_commands.Group(name="character", description="Who plays which character", guild_only=True)

    @character.command(name="register", description="Link yourself (or, as owner or GM, another player) to a saved character")
    @app_commands.describe(character="The saved character", user="The player, if not you")
    async def character_register(interaction: discord.Interaction, character: str, user: discord.Member | None = None):
        await cmds.character_register(interaction, character, user)

    @character.command(name="unregister", description="Remove the link between a player and their character")
    @app_commands.describe(user="The player, if not you")
    async def character_unregister(interaction: discord.Interaction, user: discord.Member | None = None):
        await cmds.character_unregister(interaction, user)

    @character.command(name="list", description="Show saved characters and who plays them")
    async def character_list(interaction: discord.Interaction):
        await cmds.character_list(interaction)

    character.get_command("register").autocomplete("character")(cmds.character_choices)

    companion = app_commands.Group(name="companion", description="A character's eidolon or other companion", guild_only=True)
    kinds = [app_commands.Choice(name=k, value=k) for k in KINDS]

    @companion.command(name="add", description="Add or update a character's companion (owner or GM)")
    @app_commands.describe(character="The character it belongs to", name="The companion's name", kind="What it is",
                           str_="Strength modifier, such as 4", dex="Dexterity modifier", con="Constitution modifier",
                           int_="Intelligence modifier", wis="Wisdom modifier", cha="Charisma modifier",
                           ac="Armour Class, if you want it shown")
    @app_commands.rename(str_="str", int_="int")
    @app_commands.choices(kind=kinds)
    async def companion_add(interaction: discord.Interaction, character: str, name: str, kind: app_commands.Choice[str],
                            str_: int, dex: int, con: int, int_: int, wis: int, cha: int, ac: int | None = None):
        await cmds.companion_add(interaction, character, name, kind.value, str_, dex, con, int_, wis, cha, ac)

    @companion.command(name="show", description="Show a character's companions and their totals")
    @app_commands.describe(character="A character or companion; defaults to your own character")
    async def companion_show(interaction: discord.Interaction, character: str | None = None):
        await cmds.companion_show(interaction, character)

    @companion.command(name="remove", description="Remove a companion (owner or GM)")
    @app_commands.describe(character="The character (or the companion itself); defaults to your own", name="Which companion")
    async def companion_remove(interaction: discord.Interaction, character: str | None = None, name: str | None = None):
        await cmds.companion_remove(interaction, character, name)

    companion.get_command("add").autocomplete("character")(cmds.character_choices)
    for name in ("show", "remove"):
        companion.get_command(name).autocomplete("character")(cmds.character_and_companion_choices)

    gm = app_commands.Group(name="gm", description="Who may manage anyone's character sheet", guild_only=True)

    @gm.command(name="add", description="Make a member a GM (bot owner only)")
    @app_commands.describe(user="The member to make a GM")
    async def gm_add(interaction: discord.Interaction, user: discord.Member):
        await cmds.gm_add(interaction, user)

    @gm.command(name="remove", description="Stop a member being a GM (bot owner only)")
    @app_commands.describe(user="The member to remove")
    async def gm_remove(interaction: discord.Interaction, user: discord.Member):
        await cmds.gm_remove(interaction, user)

    @gm.command(name="list", description="Show who is a GM")
    async def gm_list(interaction: discord.Interaction):
        await cmds.gm_list(interaction)

    tree.add_command(sheet)
    tree.add_command(character)
    tree.add_command(companion)
    tree.add_command(gm)
