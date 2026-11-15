# Deployment

Placeholders: `<DROPLET_ADDRESS>` is the droplet's public address (look it up with
`doctl compute droplet get analecta --format PublicIPv4`; never write it into this repository),
`<MAC_DEVICE_ID>` and `<DROPLET_DEVICE_ID>` are Syncthing device IDs, `<SOURCE_DIR>` is the campaign notes folder.

## 0. What you create yourself

| Thing | Where it goes |
|---|---|
| Discord application, bot and token | Discord Developer Portal. The token goes only into `/etc/analecta/analecta.env` on the server. |
| OpenAI project, key and the 25 USD monthly budget | OpenAI dashboard. The key goes only into the server's env file (and a local untracked file for evaluation). |

Nothing in this repository creates accounts, applications or keys.

## 1. Mac: the export job

```sh
export ANALECTA_SOURCE_DIR="<SOURCE_DIR>"
export ANALECTA_EXPORT_DIR="$HOME/Analecta-export"      # outside the vault and outside this repository
python3 scripts/export_notes.py --dry-run                # counts only
deploy/mac/install-launchd.sh                            # installs the hourly job and runs it once
```

The guard refuses to run (exit status 3, nothing written) if the export folder is inside an Obsidian vault or this
repository, if it contains a file the script did not export, or if the source is missing. Syncthing's own markers
(`.stfolder`, `.stversions`, `.stignore`) are allowed. The job logs counts only to `~/Library/Logs/analecta-export.log`.
Remove it with `deploy/mac/install-launchd.sh --remove`.

## 2. Droplet

```sh
rsync -a --exclude .git --exclude .venv ./ root@<DROPLET_ADDRESS>:/root/analecta-src/    # or clone after merge
scp deploy/setup-droplet.sh root@<DROPLET_ADDRESS>:/root/
ssh root@<DROPLET_ADDRESS> ANALECTA_LOCAL_SRC=/root/analecta-src bash /root/setup-droplet.sh
```

After the code is merged you can use `ANALECTA_REPO_URL=https://github.com/<owner>/analecta.git` instead. The script
is safe to re-run to update the bot. It sets up:

- a non-root service user `analecta`; the bot runs as a hardened systemd service (`deploy/analecta.service`) with
  read-only access to the notes, write access to the corrections folder (`/srv/analecta/corrections`, see below)
  and no other file access;
- a firewall (ufw) that allows only SSH (22/tcp) and Syncthing sync (22000/tcp and udp); the Syncthing GUI listens
  on localhost only;
- automatic security updates (unattended-upgrades) and key-only SSH;
- Syncthing from the official apt repository, running as the service user.

### The env file (secrets live only here)

Create `/etc/analecta/analecta.env` (mode 640, owner root, group analecta) from `.env.example`. Do not paste secrets
into a terminal where they are echoed or logged. For the OpenAI key held in a local untracked file:

```sh
( set -a; . ~/.config/analecta/env; set +a
  printf 'OPENAI_API_KEY=%s\n' "$OPENAI_API_KEY" | ssh root@<DROPLET_ADDRESS> 'umask 077; cat >> /etc/analecta/analecta.env' )
```

Add the remaining lines (`DISCORD_CHANNELS` with the server and channel IDs, model, `NOTES_DIR=/srv/analecta/notes`,
optionally `CORRECTIONS_DIR` (default `/srv/analecta/corrections`; it must not be inside or around `NOTES_DIR`),
the Discord token the same way)
and then `chown root:analecta /etc/analecta/analecta.env && chmod 640 /etc/analecta/analecta.env`.

## 3. Syncthing

Two folders are shared, in opposite directions: the notes export (Mac to droplet) and the corrections (droplet to
Mac). Before pairing, list every folder the Mac's Syncthing already shares and confirm these shares add nothing
else. On the Mac:

```sh
syncthing cli config folders list     # every folder id; for each, `syncthing cli config folders <id> dump-json` shows path and devices
```

1. On the droplet: `MAC_DEVICE_ID=<MAC_DEVICE_ID> bash /opt/analecta/deploy/configure-syncthing.sh`. It makes the
   `analecta-notes` folder receive-only with simple versioning (keep 5), turns off discovery, relays and NAT
   traversal, removes the default folder, and prints `<DROPLET_DEVICE_ID>`.
2. On the Mac, add the droplet as a device with address `tcp://<DROPLET_ADDRESS>:22000` (the Mac dials the droplet;
   the droplet never dials out) and add one folder with id `analecta-notes`: path `~/Analecta-export`, type
   **Send Only**, shared with that device only. Never share the vault or any other folder. Syncthing's "default
   folder" setting can pre-share every new folder with other devices (check `syncthing cli config defaults folder
   dump-json`, field `devices`); after adding the folder, confirm with `syncthing cli config folders analecta-notes
   dump-json` that its devices are only the Mac and the droplet, and remove any other.
3. Accept the Mac's folder offer on the droplet if Syncthing asks, and check that `ls /srv/analecta/notes` fills in.
   The Mac's `.stignore` keeps temporary files out.
4. The corrections folder. `configure-syncthing.sh` (step 1) also adds the droplet's folder `analecta-corrections`
   (path `/srv/analecta/corrections`, the folder the bot writes into) as **Send Only**, shared with the Mac only, no
   versioning. On the Mac, accept the droplet's offer (or add a folder with the same id) at a path **outside the
   Obsidian vault and outside this repository**, for example `~/Analecta-corrections`, type **Receive Only**, shared
   with the droplet only. Confirm with `syncthing cli config folders analecta-corrections dump-json` that its
   devices are only the Mac and the droplet. Nothing from the Mac can reach the droplet through this folder, and the
   bot never writes into the notes folder.

The corrections folder holds `corrections.md` (table corrections) and `misreads.md` (answers flagged as wrong), both
plain Markdown. They appear after the first correction or flag. Because the Mac copy is receive-only, edits made
there do not flow back and Syncthing will show the folder as "locally changed"; "Revert Local Changes" restores the
server's copy. Copy a file elsewhere before annotating it.

### Reviewing corrections on the Mac, and removing one

Read `corrections.md` and `misreads.md` in the Mac folder. For each good table correction, fix the note itself in
your vault; the next export carries it to the bot, after which the correction is redundant. The server's file is
the bot's source of truth and a table correction stays in force until it is removed there. To remove one (or all):

```sh
ssh root@<DROPLET_ADDRESS>
sudo -u analecta nano /srv/analecta/corrections/corrections.md    # delete the bullet and its indented "re:" line
```

Edit as the `analecta` user so the bot can keep appending (a root-owned file would stop it saving). The bot re-reads
the file whenever it changes, so no restart is needed, and Syncthing sends the new version to the Mac. Deleting the
whole file is fine (the bot starts a new one); do the same with `misreads.md` once you have reviewed it.

If a note is excluded later (for example it becomes `met: false`), the next export deletes it from the Mac's export
folder; Syncthing deletes it on the server and keeps a copy in `.stversions`. Purge `.stversions` if that matters.

## 4. Discord

1. Developer Portal, your application, Bot: enable **Message Content Intent** (privileged). No other privileged
   intent is needed. Set the application's **Privacy Policy URL** to the public URL of `docs/privacy.md`
   (see [clearances.md](clearances.md)). Keep the bot private (not public, no listing).
2. Create a **private** channel for the group. Give the bot role only: View Channel, Send Messages, Read Message
   History. Invite the bot with scopes `bot` and no extra permissions. Anyone who can post in the channel may use
   it; channel permissions are the access control.
3. Put the server and channel IDs in the env file as `DISCORD_CHANNELS=<SERVER_ID>:<CHANNEL_ID>` (Discord Developer
   Mode, Copy ID). The older `DISCORD_GUILD_ID` plus `DISCORD_CHANNEL_ID` pair still works as one entry; `DISCORD_CHANNEL_ID` without
   `DISCORD_GUILD_ID` stops the bot at start.
4. Post the text from [pinned-note.md](pinned-note.md) in the channel and pin it. Tell the group before launch.

### Adding another server

The bot can answer in several servers at once, one channel per server pair. Repeat for each new server:

1. **Invite.** Someone with Manage Server permission on the new server opens the bot's invite link (scope `bot`, no
   extra permissions). If that person is not the application's owner, the application must allow it: Developer
   Portal, your application, Installation (or Bot) and turn on **Public Bot**, so other accounts can add it. Turn
   Public Bot off again afterwards if you want to stop strangers from inviting it. Until the bot has an allowed
   channel in a server it ignores that server entirely.
2. **Channel permissions.** In the new server, create a private channel and give the bot role only: View Channel,
   Send Messages, Read Message History (and Send Messages in Threads if threads are used). Channel permissions stay
   the access control.
3. **Settings.** Copy the new server's ID and the channel's ID and append the pair to the env file on the droplet,
   comma-separated, for example:
   `DISCORD_CHANNELS=<SERVER_ID_1>:<CHANNEL_ID_1>,<SERVER_ID_2>:<CHANNEL_ID_2>`.
   A channel must be paired with its own server; a malformed entry stops the bot at start with a clear error.
   If the old `DISCORD_GUILD_ID` and `DISCORD_CHANNEL_ID` lines are still there they count as one more pair.
4. `systemctl restart analecta`, then post the text from [pinned-note.md](pinned-note.md) in the new channel and pin
   it. Check that `@Analecta help` answers there and that other channels in both servers and DMs get no reply.

Keep real IDs in the env file only, never in this repository.

Reading reactions needs the bot's `guild_reactions` intent. That is not a privileged intent, so nothing changes in the
Developer Portal and the bot role needs no new permission: it replies with Send Messages and reads reactions and old
messages with View Channel and Read Message History. Anyone who can post in the channel can add a correction or flag an
answer; there is no separate allowlist.

## 5. Go live

```sh
ssh root@<DROPLET_ADDRESS> 'systemctl restart analecta && journalctl -u analecta -n 20 --no-pager'
```

Checklist: the three clearances re-read and unchanged (and the open item in [clearances.md](clearances.md) about
storing flagged answers and corrections settled); spend cap set on the OpenAI project; pinned note posted; group
told; `@Analecta help` answers; a rules question returns an Archives of Nethys link; a campaign question cites a
note; a message in another channel and a DM get no reply; a 👎 on an answer adds an entry to `misreads.md` and a reply
`/correct <fix>` adds one to `corrections.md` (on the server and, after a minute, in the Mac folder), and asking the same
question again cites it as a table correction.
