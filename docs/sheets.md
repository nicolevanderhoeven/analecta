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
| `/companion add character: name: kind:eidolon str: dex: con: int: wis: cha: [ac:]` | Attach an eidolon to a character (owner or GM). Giving an existing name updates it. |
| `/companion show [character]` | A companion's modifiers and the saves, Perception and skills it gets. `character` may be the character or the companion's name. |
| `/companion remove [character] [name]` | Remove a companion (owner or GM). |
| `/roll ... companion:True` | Roll as your own character's companion (`character:Ash` does the same by name). |

Adding your first sheet registers you to it automatically. With a registered character you never need to name one:
`/roll Religion -2` uses yours. The roll always shows its working: the d20, the sheet total, the extra modifier,
and how the sheet total was made, labelled "from saved sheet".

## Companions (eidolons)

Pathbuilder's export names an eidolon in the character's features but does **not** include its stats, so an eidolon
has no sheet of its own. Add it by hand, once: in Pathbuilder open the eidolon and read its six ability
**modifiers** (not the scores), then

    /companion add character:Zuhri name:Ash kind:eidolon str:4 dex:3 con:4 int:0 wis:1 cha:0

(`ac:` is optional and is only shown, never worked out.) `/sheet add` reminds you of this when the export mentions an
eidolon and none is saved. Re-run `/companion add` with the same name to change a modifier, for example at a level-up.

**The rule:** an eidolon uses its summoner's proficiency bonuses and item bonuses for every save, Perception and skill,
with its own ability modifiers. So each total is the eidolon's ability modifier + the summoner's proficiency (rank plus
level, nothing if untrained) + the summoner's item bonus for that statistic: Intimidation is 0 + 13 + 1 = 14 for an
eidolon with Cha +0 whose summoner has master Intimidation at level 7 and a +1 item. The totals follow the summoner's
saved sheet, so re-uploading the summoner updates the eidolon too. A companion has no Lores of its own, and its
Armour Class, HP and attacks are not worked out. Animal companions and familiars are not supported yet.

Roll for one with `/roll Athletics character:Ash`, or `/roll Athletics companion:True` for the companion of your own
registered character. The result is labelled "from saved sheet (eidolon of Zuhri)" and shows the working. Companion
names cannot repeat a character's or another companion's name (so rolls are never ambiguous), and a character has at
most four companions.

In questions, if your character has a companion, "my eidolon", "my companion" and the companion's name mean it: the bot
reads its campaign note (a note with that name or alias) and is told its name and kind, nothing else.

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
the last 10 uploaded files untouched, a `companions` folder with each companion (name, kind, ability modifiers, optional
AC) versioned the same way, plus `registrations.json` (which Discord user plays which character). The
folder is mode 750 and readable only by the bot's service account. Nothing about a sheet is logged. The bot is the only
reader: the same registration file tells the notes link-follower which note is a member's character (it passes
only the character's name to find the note, not the sheet). Backing the folder up is up to the person running the bot.
The privacy text is in [privacy.md](privacy.md).
