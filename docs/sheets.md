# Dice rolling and character sheets

Analecta has slash commands for rolling dice and for rolling from a saved character sheet. They are ordinary code:
no language model sees a sheet. They work only in the channel (or a thread under it) the bot is set up for; anywhere
else the bot answers privately with a pointer to the right channel.

## For players: adding your character

1. In **Pathbuilder 2e**, open your character, open the menu, choose **Export**, and pick the **JSON** export that
   gives you a file. (Menu wording differs a little between app versions. You want the character as a `.json`
   file, not the PDF and not the 6-digit number that some tools use.)
2. Save the file where you can find it, on your phone or computer.
3. In the channel, run `/sheet add` and attach the file. Only you see the reply: it says who it saved and at what
   level, so you can tell if you exported the wrong character.

Export again and re-run `/sheet add` whenever you level up or change anything. The same character name updates the
sheet; the last 10 uploads are kept. `/sheet help` shows these steps in Discord.

## Commands

| Command | What it does |
|---|---|
| `/roll what:1d20+5` | Plain dice. Several terms (`2d6+1d4-1`), keep highest or lowest (`4d6kh3`) and `d20` are fine. |
| `/roll what:Religion -2` | Your character's Religion skill, then an extra modifier (here -2). Skills, `Perception`, `Fortitude`/`Reflex`/`Will` and Lores (`Dwarven Lore`) work. |
| `/roll ... character:Name` | Roll for someone else's saved character (for example when their player is away). |
| `/roll ... secret:True` | The full result is shown only to you; the channel sees that a secret check was rolled. |
| `/sheet add file:` | Add or update a character from a Pathbuilder 2e JSON file. |
| `/sheet show [character]` | A readable summary (abilities, HP, AC, Perception, saves, skills, Lores, feats). |
| `/sheet export [character]` | Get the saved JSON file back (privately). It is a copy of the export, not something Pathbuilder can re-import. |
| `/sheet delete [character] confirm:True` | Erase the sheet and every earlier version. |
| `/character register character: [user:]` | Link yourself (or, if you own the sheet or are a GM, another player) to a saved character. |
| `/character unregister [user:]` | Remove that link; the sheet stays. |
| `/character list` | The saved characters and who plays each. |

Adding your first sheet registers you to it automatically. With a registered character you never need to name one:
`/roll Religion -2` uses yours. The roll always shows its working: the d20, the sheet total, the extra modifier,
and how the sheet total was made, labelled "from saved sheet".

## What the totals include

The Pathbuilder export holds the parts of a statistic (ability scores, proficiency ranks, item bonuses recorded under
`mods`, level), not the totals, so Analecta adds them up: proficiency (rank plus level, nothing if untrained) +
ability modifier + the recorded item and other bonuses. It does **not** know about conditions, circumstance or status
bonuses, armour check penalties, or proficiency that comes from unusual feats. Put the net effect in the extra
modifier (`/roll Athletics -1`). Variant rules such as proficiency without level are not supported.

## Who may do what

- Anyone in the channel can roll for, and view, any saved character.
- A sheet's **owner** (whoever added it) and the Discord user IDs in `SHEETS_GM_USER_IDS` may update, export and delete
  it, and register other players to it.
- Anyone may register themselves to a character nobody else holds. Taking a character someone else holds needs the
  owner or a GM.
- Two characters cannot share a name (case-insensitive). Uploading a name that belongs to someone else is refused.

## Where it lives

Plain JSON files under `SHEETS_DIR` (default `/var/lib/analecta/sheets`), outside the repository and outside the
notes and corrections folders: one folder per character with the owner's Discord ID, the character's name, and
the last 10 uploaded files untouched, plus `registrations.json` (which Discord user plays which character). The
folder is mode 750 and readable only by the bot's service account. Nothing about a sheet is logged. The bot is the only
reader: the same registration file tells the notes link-follower which note is a member's character (it passes
only the character's name to find the note, not the sheet). Backing the folder up is up to the person running the bot.
The privacy text is in [privacy.md](privacy.md).
