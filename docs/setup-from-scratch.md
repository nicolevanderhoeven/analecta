# Set up your own Analecta from scratch

This guide takes you from nothing to a working copy of the bot for your own group. It assumes you have never seen
the original setup. It covers the parts [deployment.md](deployment.md) does not (creating the server, the Discord
application, installing Syncthing, the notes format) and links into deployment.md for the steps it already spells out.

Vendor pages were read on **2026-11-16**; sizes, prices and menu names change, so check the linked page if
something looks different.

## What you are building, and what it costs

Read this first. If one of these does not fit, stop here.

- **Pathfinder 2e only.** Rules answers come live from [Archives of Nethys](https://2e.aonprd.com) (the Pathfinder 2e
  rules site), with a link to the page. There is no other game system.
- **OpenAI only.** The model calls go to the OpenAI API. The code is provider-neutral
  (`analecta.llm.base.LLMProvider`), but OpenAI is the only provider written. You need an OpenAI API account.
- **Notes come from a Mac.** Your campaign notes are Obsidian-style Markdown files on a Mac. A small script on the Mac
  exports the notes the bot may see, and Syncthing copies that export to the server. Nothing in this guide covers
  Windows or Linux as the notes machine.
- **One small server.** The bot runs on a DigitalOcean droplet (a Linux virtual server) that `deploy/setup-droplet.sh`
  provisions for you. The script is written for Ubuntu 24.04.
- **Discord, in channels you choose.** It answers only in the server and channel pairs you configure, when
  mentioned or replied to.

Running cost has two parts:

| Part | What | Example, as of 2026-11-16 |
|---|---|---|
| Droplet | A small always-on droplet. The setup script needs Ubuntu 24.04 and enough memory for a Python virtual environment and Syncthing; this guide uses 1 GiB, the smallest size above DigitalOcean's 512 MiB entry plan. | Basic, 1 GiB / 1 vCPU / 25 GiB disk, **$6.00 per month** ([DigitalOcean Droplet pricing](https://www.digitalocean.com/pricing/droplets)). Billing is per second from 2026-01-01, capped at the monthly price. |
| OpenAI API | Pay per token. The default model `gpt-6-luna` costs $0.10 per million input tokens, $0.01 per million cached input tokens and $0.50 per million output tokens ([model page](https://developers.openai.com/api/docs/models/gpt-6-luna)). | Illustration, with assumed numbers: 20 questions a day, each using about 50,000 input tokens (the notes digest plus tool results, over several turns) and 1,000 output tokens, is 600 questions a month: 600 × (50,000 × $0.10 / 1M + 1,000 × $0.50 / 1M) ≈ **$3.30 a month**. Your numbers will differ. |

The bot caps itself with `USER_COOLDOWN_SECONDS` and `DAILY_QUESTION_LIMIT` (see [`.env.example`](../.env.example)),
and you should also set a monthly budget on the OpenAI project (step 7). The original owner uses 25 USD a month as
the cap; that is a ceiling, not a typical bill. Plan on roughly the droplet price plus a few dollars.

## The steps, in order

1. [Accounts and tools you need](#1-accounts-and-tools-you-need)
2. [Get the code](#2-get-the-code)
3. [Write your notes the way the export expects](#3-write-your-notes-the-way-the-export-expects)
4. [Syncthing on the Mac](#4-syncthing-on-the-mac)
5. [Create the droplet](#5-create-the-droplet)
6. [Create the Discord application](#6-create-the-discord-application)
7. [Create the OpenAI key and budget](#7-create-the-openai-key-and-budget)
8. [Deploy](#8-deploy)
9. [Check it works](#9-check-it-works)

Keep every secret (the Discord token, the OpenAI key, the droplet's address, Discord server and channel IDs, real
notes) out of the repository. The repository is built to be public; see the README's
[public repository section](../README.md#public-repository-no-private-information).

## 1. Accounts and tools you need

- A [DigitalOcean](https://www.digitalocean.com) account (a payment method is required).
- A [Discord](https://discord.com) account that can create a server, or Manage Server permission on an existing one.
- An [OpenAI platform](https://platform.openai.com) account with an API project.
- On the Mac: Python 3.11 or newer (`python3 --version`), `git`, [Homebrew](https://brew.sh), and a terminal.
- Optional: `doctl`, DigitalOcean's command-line tool, which [deployment.md](deployment.md) mentions for looking up the
  droplet's address. The control panel shows the same address.

## 2. Get the code

```sh
git clone https://github.com/<owner>/analecta.git ~/analecta     # or a fork of your own
cd ~/analecta
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                                                  # should pass before you continue
scripts/install-hooks.sh                                          # optional: privacy check on every commit
```

The code is licensed under the [GNU AGPL-3.0](../LICENSE). If you change it and let other people use your copy over a
network (as a Discord bot does), section 13 of the licence asks you to offer them the source of your version.

## 3. Write your notes the way the export expects

The bot never reads your vault. `scripts/export_notes.py` copies a cleaned subset of it into an export folder, and
only that folder is synced to the server. So the notes need to be plain Markdown in the shape the script understands.

### File layout

- A folder of `.md` files (subfolders are fine). Everything else is ignored.
- Folders or files whose name starts with `.` are skipped, as are folders named `granola`, `transcripts` and `plugins`.
- **Session notes** are named `NNN_YYYYMMDD Title.md`, for example `001_20260110 The Lost Lantern.md`: at least three
  digits, an underscore, an eight-digit date, then an optional title. They let the bot list sessions in order and
  answer "what happened in session 3". Every other note counts as a regular note (a character, place, faction, item).

### Frontmatter the export keeps

A note may start with a YAML block between `---` lines. The export keeps only these keys and drops all others
(for example Obsidian plugin settings), so private metadata does not travel:

| Key | Use |
|---|---|
| `type` | What kind of note it is, for example `npc`, `place`, `session`. Used to filter note lists. |
| `aliases` | Other names for the thing (a list). The bot also matches a question that names the note by an alias. |
| `description` | One sentence about the note. Goes into the digest the bot always carries. |
| `summary` | A one-line summary, preferred over `description` for the digest. Session notes should have one. |
| `date`, `session` | Date and session number, kept as written. |
| `tags` | Kept. A tag `bot/false` (or `bot:false`) excludes the note, see below. |

The digest is the list of one-liners the bot reads before it searches, so a good `summary` or `description` on every
note makes answers noticeably better.

### What the export leaves out

| To exclude | Write this | Result |
|---|---|---|
| A whole note the characters have not met yet | `met: false` in the frontmatter | Note is not exported. |
| A whole note the bot must never see | `bot: false` in the frontmatter, or the tag `bot/false` | Note is not exported. |
| Part of a note | A heading containing "Secret goals" (for example `## Secret goals`), or a callout block (lines starting with `>`) mentioning secret goals | The heading's section down to the next heading of the same or higher level, or the callout block, is removed. |
| An aside | `%% text %%` Obsidian comments, and `<!-- text -->` | Removed. An unclosed `%%` hides the rest of the note. Excalidraw drawing data is removed too. |
| Transcripts | Embeds like `![[... transcript ...]]` or `[[...granola...]]` | The link is removed. |
| Email addresses | Any | Replaced with `[email removed]`. |

`false`, `no`, `off` and `0` all count as false for `met` and `bot`, in any case, and a trailing `# comment` on the
line is ignored. A note whose frontmatter is opened with `---` but never closed is skipped rather than exported. When in
doubt the script removes more rather than less. These rules are what protect spoilers and private details; the bot's
prompt is not relied on for that.

### A small made-up example

A source folder:

```
Campaign/
  001_20260110 The Lost Lantern.md
  002_20260117 Smoke on the Quay.md
  NPCs/Captain Marrowind.md
  NPCs/The Pale Cartographer.md
  Places/Saltmere.md
```

`Campaign/001_20260110 The Lost Lantern.md`:

````markdown
---
type: session
session: 1
date: 2026-01-10
summary: The party meets in Saltmere and agrees to find the lantern stolen from the lighthouse.
---

# Session 1: The Lost Lantern

The party met at the Gull and Anchor. [[Captain Marrowind]] offered 50 gp for the lantern's return.

%% Marrowind is lying about the payment; remind the table next time. %%
````

`Campaign/NPCs/Captain Marrowind.md`:

````markdown
---
type: npc
aliases: [Marrowind, The Captain]
description: Harbour master of Saltmere, gruff and fair, who hired the party.
tags: [npc, saltmere]
---

# Captain Marrowind

Harbour master of [[Saltmere]]. Pays on time, dislikes magic aboard ships.

## Secret goals

He sold the lantern himself and needs it recovered before the audit.
````

`Campaign/NPCs/The Pale Cartographer.md` (not yet met, so not exported):

````markdown
---
type: npc
met: false
description: Mapmaker who appears in session 5.
---

Contact: pale.cartographer@example.com
````

`Campaign/Places/Saltmere.md` (for the table only, never for the bot):

````markdown
---
type: place
bot: false
---

Notes on the layout of the harbour for the GM to remember.
````

After the export you get the two session notes and Marrowind's note, with the `%% ... %%` aside and the "Secret goals"
section gone. The Cartographer and Saltmere notes are not exported. Check this on your own notes without writing
anything:

```sh
ANALECTA_SOURCE_DIR="$HOME/path/to/Campaign" python3 scripts/export_notes.py --dry-run
# dry run: exported=3 removed=0 secret_sections_dropped=1 skipped: bot-false=1, met-false=1
```

(The counts above are for the example; you will see your own.) Then drop the real export step into the pipeline as in
[deployment.md section 1](deployment.md#1-mac-the-export-job). The export folder must be outside your vault and outside
this repository, and the script refuses to run otherwise or if the folder contains anything it did not write.

## 4. Syncthing on the Mac

[Syncthing](https://syncthing.net) copies files between your devices directly, without a cloud service. You install it
on the Mac now, because the droplet setup in step 8 needs the Mac's device ID. Sources:
[Getting Started](https://docs.syncthing.net/intro/getting-started.html),
[Starting Syncthing Automatically](https://docs.syncthing.net/users/autostart.html) and
[Homebrew's formula](https://formulae.brew.sh/formula/syncthing) (current version 2.1.7 on 2026-11-16).

```sh
brew install syncthing
brew services start syncthing        # runs it now and at every login
```

Syncthing's own page also describes a macOS application bundle if you prefer an app with a menu bar icon; this guide
uses the command-line build because the pairing steps in [deployment.md](deployment.md) use `syncthing cli`.

First run:

1. Open the web interface at <http://127.0.0.1:8384>. It listens on this Mac only. Syncthing may ask you to set a GUI
   username and password; do it, since any local user could otherwise open it.
2. Syncthing created a folder called **Default Folder** (in `~/Sync`) shared with nobody. Remove it from the web
   interface (Edit, then Remove) so the only shares on this Mac are the ones you add for Analecta.
3. Click **Actions, Show ID** and copy this Mac's device ID. That is your `<MAC_DEVICE_ID>`. It is a public identifier,
   not a secret, but keep it out of the repository.

Then continue with step 8; the pairing itself is [deployment.md section 3](deployment.md#3-syncthing).

## 5. Create the droplet

Sources: [How to create Droplets](https://docs.digitalocean.com/products/droplets/how-to/create/) (last verified 6 Nov
2026) and [How to add SSH keys](https://docs.digitalocean.com/products/droplets/how-to/add-ssh-keys/) (last verified 13
Jul 2026).

### Make an SSH key (once)

If you do not already have one, make a key pair on the Mac and show the public half:

```sh
ssh-keygen -t ed25519 -f ~/.ssh/analecta_droplet -C "analecta droplet"
cat ~/.ssh/analecta_droplet.pub
```

Only the `.pub` file is ever shared. The setup script later turns off password logins, so this key is how you get in.

### Create it

In the DigitalOcean control panel choose **Create, Droplets**, then:

| Setting | Choose | Why |
|---|---|---|
| Region | The datacentre nearest to you. | The bot only makes outbound calls (Discord, OpenAI, Archives of Nethys) and receives Syncthing from your Mac, so any region works; nearer is just quicker. |
| Image | Under **OS**, **Ubuntu 24.04 (LTS) x64**. | `deploy/setup-droplet.sh` is written for it. Do not pick a Marketplace or Docker image. |
| Size | **Basic** (shared CPU), **Regular**, **1 GiB / 1 vCPU / 25 GiB**, $6.00 a month on 2026-11-16. | Nothing here is heavy: one Python process and Syncthing. The notes are small text files. Pricing: [DigitalOcean](https://www.digitalocean.com/pricing/droplets). |
| Additional storage, backups | Leave off. | The notes live on your Mac, and the corrections come back to it. |
| Authentication | **SSH key**, then **Add SSH Key**, paste the contents of `analecta_droplet.pub`, give it a name. | DigitalOcean recommends keys over passwords. |
| Hostname | `analecta` | Matches the `doctl compute droplet get analecta` example in [deployment.md](deployment.md). |

Create it, wait for it to start, and copy its public address from the panel. That is `<DROPLET_ADDRESS>` in the rest of
the docs. Test the login (the first time you will be asked to trust the server's fingerprint):

```sh
ssh -i ~/.ssh/analecta_droplet root@<DROPLET_ADDRESS>     # then exit
```

If you use a different key file, add `-i <key>` to every `ssh`, `scp` and `rsync` command in the other docs, or add an
entry to `~/.ssh/config`.

## 6. Create the Discord application

Source: Discord's developer documentation on the
[OAuth2 invite link](https://discord.com/developers/docs/topics/oauth2) and the
[Gateway and privileged intents](https://discord.com/developers/docs/events/gateway), and the Developer Portal itself
(<https://discord.com/developers/applications>). Discord changes the portal layout from time to time, so the labels
below are the ones to look for, not a guarantee.

1. **New application.** Open the portal, choose **New Application**, name it (the name users see, for example
   "Analecta"), accept the terms and create it. The **General Information** page shows the **Application ID**; copy it,
   it goes into the invite link below. The same page has the **Privacy Policy URL** field, which
   [deployment.md section 4](deployment.md#4-discord) and [clearances.md](clearances.md) tell you to fill in with the
   public URL of [privacy.md](privacy.md).
2. **The Bot tab.** In the left menu choose **Bot**. Every application has a bot user.
   - Under **Token** choose **Reset Token**, confirm, and copy the token that appears. Discord shows it once; reset
     again if you lose it. This is `DISCORD_TOKEN`. Treat it as a password: it goes only into the server's env file,
     never into the repository, a chat or a screenshot.
   - Turn **Public Bot** off if you only invite the bot yourself (see
     [deployment.md, Adding another server](deployment.md#adding-another-server) for when to turn it on).
   - Under **Privileged Gateway Intents** turn on **Message Content Intent** and save. Analecta reads the text of
     messages that mention it or reply to it, and Discord only delivers message text to bots with this intent. No other
     privileged intent is needed.
3. **Build the invite link.** Take the Application ID and put it in this address:

   ```
   https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot&permissions=0
   ```

   `scope=bot` adds the bot user to a server, and `permissions=0` asks for no server-wide permissions; you give the
   bot access to one channel in the next step. (The Developer Portal's **OAuth2** page has a URL generator that builds
   the same link: tick `bot`, tick no permissions.) Do not share this link publicly; with **Public Bot** off, only you
   can use it.
4. **Invite it.** Open the link in a browser where you are signed in to Discord, choose your server (you need Manage
   Server permission on it) and **Authorize**. The bot appears in the member list, offline. It ignores the server until
   you configure a channel.
5. **A private channel.** Create a private text channel for the group. On that channel, give the bot's role only:
   **View Channel**, **Send Messages**, **Read Message History** (and Send Messages in Threads if the group uses
   threads). Channel permissions are the access control: anyone who can post there may use the bot.
6. **Copy the IDs.** In Discord, User Settings, Advanced, turn on **Developer Mode**. Right-click the server and the
   channel and choose **Copy ID**. The env file needs them as `DISCORD_CHANNELS=<SERVER_ID>:<CHANNEL_ID>`. Keep the real
   IDs out of the repository.

## 7. Create the OpenAI key and budget

In the [OpenAI platform](https://platform.openai.com), create a project for Analecta, create an API key inside it and
copy it (this is `OPENAI_API_KEY`), and set a **monthly budget** on the project so a mistake cannot run up a bill.
Do not opt the project in to any data sharing; [clearances.md](clearances.md) explains why that matters for Discord's
rules. The model name and the other settings are in [`.env.example`](../.env.example).

## 8. Deploy

Each of these is spelled out in [deployment.md](deployment.md); do them in this order, with the placeholders from steps
4 and 5:

1. **Server setup.** [deployment.md section 2](deployment.md#2-droplet): copy the code to the droplet and run
   `deploy/setup-droplet.sh`. It creates the service user and folders, the firewall (SSH and Syncthing only),
   automatic security updates, key-only SSH, Syncthing and the systemd service. The service stays stopped until the env
   file exists.
2. **The env file.** Create `/etc/analecta/analecta.env` from [`.env.example`](../.env.example) as described in
   [deployment.md, The env file](deployment.md#the-env-file-secrets-live-only-here). The values you collected:
   `DISCORD_TOKEN` (step 6), `DISCORD_CHANNELS` (step 6), `OPENAI_API_KEY` (step 7). `NOTES_DIR=/srv/analecta/notes` is
   already the default. Optionally set `BOT_OWNER=<your name>` so the help text and pinned note say who runs the bot
   (run `python -m analecta pinned` to print the note with it). Do not type secrets into a terminal where they would be logged.
3. **Syncthing pairing.** On the droplet run `deploy/configure-syncthing.sh` with `MAC_DEVICE_ID` (step 4), note the
   droplet's device ID it prints, then add the droplet and the `analecta-notes` folder on the Mac and accept the
   corrections folder, all as in [deployment.md section 3](deployment.md#3-syncthing).
4. **The export job.** [deployment.md section 1](deployment.md#1-mac-the-export-job): `deploy/mac/install-launchd.sh`
   installs an hourly export from your notes folder into `~/Analecta-export`, the folder Syncthing sends.
5. **Go live.** Post and pin the text from [pinned-note.md](pinned-note.md), then
   [deployment.md section 5](deployment.md#5-go-live) (restart the service, run the checklist).

## 9. Check it works

- On the droplet, `systemctl status analecta` shows it running and `ls /srv/analecta/notes` shows your exported notes.
- In the channel, `@Analecta help` answers.
- A rules question (for example, "what does the Grapple action do?") returns an Archives of Nethys link.
- A campaign question cites one of your notes, and a question about a `met: false` or secret-goals detail finds nothing.
- A message in another channel and a direct message get no reply.

If the bot does not start, `journalctl -u analecta -n 50 --no-pager` on the droplet says why; a missing or malformed
setting stops it at start with a clear error. Day-to-day settings, the spend cap, logs and corrections are in
[operations.md](operations.md).
