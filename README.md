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
- **Rules come live from Archives of Nethys** through the site's own search backend, with a link to the exact page,
  a short cache, a low request rate, a back-off on failures and a switch to turn it off (`AON_ENABLED=false`).
- **Dice and character sheets.** Slash commands in the same channel: `/roll 1d20+5` for plain dice, and
  `/roll Religion -2` for a skill, save, Perception or Lore from a character sheet the player imported with
  `/sheet add` (a Pathbuilder 2e JSON file), plus an extra modifier. Each player is registered to a character
  (`/character register`), so a roll uses their own by default, and anyone can roll for another character with
  `character:`. Plain code, no language model: sheets are never sent to OpenAI. See [docs/sheets.md](docs/sheets.md).
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
