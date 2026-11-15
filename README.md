# Analecta

A Discord bot for a Pathfinder 2e gaming group. It answers rules questions with a link to the source on
[Archives of Nethys](https://2e.aonprd.com), and questions about the group's campaign from an exported folder of
Markdown notes.

Not published, endorsed, or specifically approved by Paizo.

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
- **Rules come live from Archives of Nethys** through the site's own search backend, with a link to the exact page,
  a short cache, a low request rate, a back-off on failures and a switch to turn it off (`AON_ENABLED=false`).
- **One channel, one audience.** The bot answers only in the one configured channel, only when mentioned or replied to,
  and ignores DMs and every other channel and server. Channel permissions are the access control. The reply chain is
  the conversation memory; nothing is stored.
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

- [docs/deployment.md](docs/deployment.md): droplet, Syncthing, Mac export job, Discord setup, go-live checklist.
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

No licence has been chosen for the code yet. Pathfinder rules content is Paizo's and is shown via Archives of
Nethys (see [docs/clearances.md](docs/clearances.md)).
