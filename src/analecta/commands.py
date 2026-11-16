"""Slash commands for dice and character sheets: /roll, /sheet (add, show, export, delete, help) and /character
(register, list, unregister).

`DiceCommands` holds the behaviour as plain async methods so tests can call them with a fake interaction;
`register_commands` wraps them as discord.py application commands. Sheet data is never logged and never sent to a
language model. Replies use no mentions, and everything from a sheet is escaped.
"""
from __future__ import annotations

import io
import logging
import re
from collections.abc import Iterable
from typing import Any

import discord
from discord import app_commands

from . import dice, pf2e
from .gating import is_allowed_interaction, split_message
from .rolling import escape, roll
from .sheets import MAX_SHEET_BYTES, MAX_VERSIONS, SheetError, SheetStore

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
**Your character:** adding a sheet registers you to it if you have none. `/character register` links you to a different one (or links another player, if you own the sheet or are a GM); `/character list` shows who is who.
**Keeping it:** I save your sheet file on my server and keep your last {MAX_VERSIONS} uploads, so re-adding the same character updates it. `/sheet export` gives you the file back (this is a copy of the export, not something Pathbuilder can import). `/sheet delete` erases it and every earlier version. I do not send sheets to any language model.
**Limits:** totals are worked out from the file. Conditions, armour check penalties and temporary bonuses are not in it; put them in the extra modifier."""


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "character"


class DiceCommands:
    def __init__(self, store: SheetStore, locations: Iterable[tuple[int, int]], rng: dice.Rng | None = None):
        self.store = store
        self.locations = tuple(locations)
        self.rng = rng

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
    async def roll(self, interaction: Any, what: str, character: str | None = None, secret: bool = False) -> None:
        try:
            outcome = roll(self.store, interaction.user.id, what, character, self.rng)
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

    # -- autocomplete ----------------------------------------------------------------------------------------
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
                           character="Roll for this character instead of your own",
                           secret="Show the result only to you")
    @app_commands.guild_only()
    async def roll_cmd(interaction: discord.Interaction, what: str, character: str | None = None, secret: bool = False):
        await cmds.roll(interaction, what, character, secret)

    roll_cmd.autocomplete("character")(cmds.character_choices)

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

    tree.add_command(sheet)
    tree.add_command(character)
