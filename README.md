# Analecta

A Discord bot for a Pathfinder 2e gaming group. It answers rules questions with a link to the source on
[Archives of Nethys](https://2e.aonprd.com), and questions about the group's campaign from an exported folder of
Markdown notes.

Not published, endorsed, or specifically approved by Paizo.

> **Want your own copy?** Start with the **[set-up-from-scratch guide](docs/setup-from-scratch.md)**. It says up front
> what this is for (Pathfinder 2e only, OpenAI only, notes exported from a Mac to a DigitalOcean droplet, and what it
> costs to run) and walks through the server, the Discord application, Syncthing and the notes format.

## How it works

```
 Mac                                         Droplet
 campaign notes (Obsidian folder)            /srv/analecta/notes  (Syncthing receive-only, simple versioning)
   |  hourly: scripts/export_notes.py                |
   v                                                 v
 ~/Analecta-export  ---- Syncthing send-only ---->  analecta.service (the bot)
                                                     |-- tools: grep_notes, read_note, list_sessions, list_notes
 Discord channel (mention or reply) <--------------> |-- tools: aon_search, aon_get  (live Archives of Nethys)
                                                     '-- model: OpenAI (provider-neutral loop; gpt-6-luna)
```

- **Plain search, no RAG.** The agent greps and reads the notes. A digest of session one-liners and note
  descriptions (about 10K tokens) sits in the cached system prompt so nicknames and aliases resolve before searching.
  When a question names a note (by file name or alias), the bot reads that note before answering instead of relying on
  the digest's short description.
- **Relationship questions follow links.** For questions about people ("who is my family", "who are Mira's allies"),
  the bot also reads the notes the named notes link to with `[[wikilinks]]`, breadth first: two steps by default, three
  at most, within a budget of 12 notes and about 32K tokens, nearest notes first. It follows person notes (frontmatter
  `type` of `pc`, `npc`, `character`...) and links on lines about family, partners, allies or enemies; it skips
  session, place, item and faction notes unless the question names them, stops when a step finds nothing new, and
  ends such answers with a "Notes read" line. Tune it with `LINK_DEPTH`, `LINK_NOTE_BUDGET` and `LINK_TOKEN_CAP`
  (see [docs/operations.md](docs/operations.md)).
- **It knows which character is asking.** If the asker's server nickname or display name equals a player character
  note's name or alias (type `pc`, case-insensitive), "my", "me" and "I" mean that character; otherwise it asks which.
  `ANALECTA_CHARACTER_MAP` maps Discord user IDs to character notes for members whose names do not match.
- **It respects pronouns.** Add `pronouns: they/them` (or a list) to a character note's frontmatter (PCs and NPCs
  alike). The digest, the asker's character and the notes it reads carry them, and the bot uses them for that
  character; a note with no `pronouns` gets the character's name, never a guessed pronoun.
- **Rules come live from Archives of Nethys** through the site's own search backend, with a link to the exact page,
  a short cache, a low request rate, a back-off on failures and a switch to turn it off (`AON_ENABLED=false`).
- **Dice and character sheets.** Slash commands in the same channel, in plain code with no language model: sheets are
  never sent to OpenAI (only a companion's name and kind go with a question). See [Commands](#commands) and
  [docs/sheets.md](docs/sheets.md).
- **The group can correct it.** Reply to an answer with `/correct <the fix>` and it is saved as a *table correction*
  (with who and when) in `corrections.md`; later answers use those ahead of the notes and say so. A 👎 on an answer,
  or a reply saying "wrong", logs the question and answer to a review list, `misreads.md`. Both live outside the
  notes folder and go back to the Mac for review through a second, send-only Syncthing folder. The server's copy of the
  notes is never changed. See [docs/operations.md](docs/operations.md).
- **Named channels only.** The bot answers only in the configured server and channel pairs (`DISCORD_CHANNELS`, or the older
  `DISCORD_GUILD_ID` plus `DISCORD_CHANNEL_ID`; each channel is tied to its own server), only when mentioned or replied to, and ignores DMs and every other channel and server. Channel permissions are the access control. The reply chain is
  the conversation memory; the only things stored are the corrections and flags members choose to add.
- **Provider-neutral.** `analecta.llm.base.LLMProvider` is the only thing the agent loop knows. OpenAI is the one
  implementation; the model is configuration (`LLM_MODEL`).
- **What the bot can see is decided by the export, not by prompts.** The export script writes only campaign notes and
  drops "Secret goals" sections, notes with `met: false`, notes with `bot: false`, `%% hidden %%` blocks (and drawing
  data), transcript embeds and email addresses. It refuses to run if the export folder holds anything it did not put
  there.

## Commands

Everything is used in the configured channel (or a thread under it); elsewhere the bot answers privately with a pointer
to the right channel. Slash-command replies are private to the person who ran them, except `/roll`, which the channel
sees. `[x]` marks an optional option. Details, rules and storage are in [docs/sheets.md](docs/sheets.md).

**Who may use what:** *anyone* in the channel; *sheet owner* (whoever added that sheet); *GM* (a member listed in
`SHEETS_GM_USER_IDS` or added with `/gm add`); *bot owner* (owner of the bot's Discord application).

### Questions

| Use | What it does | Who |
|---|---|---|
| `@Analecta <question>` (or reply to one of its messages) | Answers a rules or campaign question; reply again to continue. | Anyone |
| `@Analecta help` | Posts the help text (the [pinned note](docs/pinned-note.md)). | Anyone |
| Reply to an answer with `/correct <the fix>` (`!correct` also works) | Saves a table correction, up to 500 characters. Not a registered slash command: it only works as a reply to one of the bot's answers. A 👎 or a reply saying "wrong" flags a misread instead. | Anyone |

### Dice and sheets

| Command | Options | What it does | Who |
|---|---|---|---|
| `/roll` | `what`; `[character]`; `[secret]`; `[companion]` | Rolls dice (`1d20+5`, `4d6kh3`) or a skill, save, Perception or Lore from a saved sheet with an extra modifier (`Religion -2`). `character` rolls for another character or companion; `secret:True` shows the result only to you; `companion:True` rolls as your own character's companion. | Anyone |
| `/sheet help` | none | Steps to export from Pathbuilder 2e and add the file. | Anyone |
| `/sheet add` | `file` | Adds or updates a character from a Pathbuilder 2e JSON file. Registers you to it if you have none. | Anyone (becomes the sheet's owner); updating needs the owner or a GM |
| `/sheet show` | `[character]` | A readable summary: abilities, HP, AC, Perception, saves, skills, Lores, feats. | Anyone |
| `/sheet export` | `[character]` | Returns the saved JSON file. | Sheet owner or GM |
| `/sheet delete` | `[character]`; `confirm` | Erases the sheet and every earlier version. Needs `confirm:True`. | Sheet owner or GM |

```
/roll what:1d20+5
/roll what:Religion -2 secret:True
/roll what:Athletics character:Ash
/sheet add file:<attach your .json>
```

`character` defaults to your own registered character in `/sheet` commands.

### Characters

| Command | Options | What it does | Who |
|---|---|---|---|
| `/character register` | `character`; `[user]` | Links you (or `user`) to a saved character, so `/roll` uses it by default. | Anyone for themselves and for a character nobody holds; otherwise the sheet owner or a GM |
| `/character unregister` | `[user]` | Removes the link; the sheet stays. | You; for someone else, the sheet owner or a GM |
| `/character list` | none | Saved characters and who plays each. | Anyone |

### Companions (eidolons)

| Command | Options | What it does | Who |
|---|---|---|---|
| `/companion add` | `character`; `name`; `kind` (`eidolon`); `str`, `dex`, `con`, `int`, `wis`, `cha` (modifiers); `[ac]` | Attaches an eidolon, or updates it if the name exists. Its saves, Perception and skills use the summoner's proficiency and item bonuses. Up to four per character. | Sheet owner or GM |
| `/companion show` | `[character]` | The companions and their totals. `character` may be a character or a companion's name. | Anyone |
| `/companion remove` | `[character]`; `[name]` | Removes a companion. | Sheet owner or GM |

```
/companion add character:Zuhri name:Ash kind:eidolon str:4 dex:3 con:4 int:0 wis:1 cha:0
/roll what:Athletics character:Ash
/roll what:Athletics companion:True
```

### GMs

| Command | Options | What it does | Who |
|---|---|---|---|
| `/gm list` | none | Who the GMs are; those set in the env file are marked. | Anyone |
| `/gm add` | `user` | Makes a member a GM. | Bot owner |
| `/gm remove` | `user` | Stops a member being a GM. A GM listed in `SHEETS_GM_USER_IDS` stays one: edit the env file and restart. | Bot owner |

### Admin (not slash commands)

- `python -m analecta pinned` prints the help text to pin; `BOT_OWNER` adds the owner's name to it.
- Settings such as `SHEETS_GM_USER_IDS`, `SHEETS_DIR`, the spend cap and the switches are in
  [docs/operations.md](docs/operations.md).

## Public repository, no private information

This repository is public. It holds code, docs and made-up test notes only. Settings, keys, IDs, the droplet's
address, real names and the real notes never enter it.

- All settings come from an untracked env file; [`.env.example`](.env.example) has placeholders only.
- `scripts/privacy_check.py` blocks tokens and keys, Discord IDs, IP addresses, email addresses and a local list of
  real names. It runs on every commit (`scripts/install-hooks.sh` installs the hook) and in CI.
  The real-name list lives in an untracked `.privacy-denylist`; [the example](.privacy-denylist.example) shows the format.
- `.gitignore` is an allowlist: everything is ignored unless listed.

## Documentation

- [docs/setup-from-scratch.md](docs/setup-from-scratch.md): the start-to-finish guide for a new owner: scope and cost,
  notes format, Syncthing on the Mac, creating the droplet and the Discord application.
- [docs/deployment.md](docs/deployment.md): droplet, Syncthing (notes out, corrections back), Mac export job, Discord setup, go-live checklist.
- [docs/sheets.md](docs/sheets.md): dice and character sheets: how a player adds a sheet, the commands, permissions, storage.
- [docs/clearances.md](docs/clearances.md): Discord, OpenAI and ORC checks, with sources.
- [docs/pinned-note.md](docs/pinned-note.md): the help text and the pinned note.
- [docs/privacy.md](docs/privacy.md): the privacy policy for the group.
- [docs/operations.md](docs/operations.md): switches, spend cap, logs, adding a provider.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
scripts/install-hooks.sh        # privacy check on every commit
```

Run the bot locally with a `.env` copied from `.env.example` (`python -m analecta`). Export the notes with
`ANALECTA_SOURCE_DIR=... scripts/export_notes.py` (add `--dry-run` to only count).

## Licence

The code is licensed under the [GNU Affero General Public License v3.0](LICENSE) (`AGPL-3.0-only`). If you modify it
and let others interact with it over a network, the licence asks you to offer them your version's source.

Pathfinder rules content is Paizo's, not covered by this licence, and is shown via Archives of Nethys (see
[docs/clearances.md](docs/clearances.md)).
