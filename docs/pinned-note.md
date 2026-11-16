# Pinned note and help text

This is the text Analecta posts for `@Analecta help` and the text to pin in the channel. It is generated from
`src/analecta/clearances.py` (print it with `python -m analecta pinned`); a test keeps this file in sync. This is the version with no owner name; if `BOT_OWNER` is set, the bot also
says who runs it, so print the note after setting it and pin that. The clearance behind each statement is in
[clearances.md](clearances.md). Before launch, post it and pin it, and tell the group.

---

**Analecta** answers Pathfinder 2e rules questions and questions about our campaign.

**How to use it:** mention me, or reply to one of my messages, in this channel. Reply to my answer to keep a conversation going. I ignore DMs and every other channel and server.

**What I can see:** the messages in the reply chain you start, the group's exported campaign notes (session notes and character, place and faction notes only; "Secret goals" sections, hidden comments, notes not yet met in play and notes marked `bot: false` are never exported), and live pages on Archives of Nethys. No Discord history, no transcripts, nothing else.

**Where questions go:** your question and the note passages needed to answer it are sent to OpenAI's API. OpenAI states that API data is not used to train its models by default and is kept for up to 30 days for abuse monitoring. I do not store your questions, except as described next.

**Fixing me:** if I misread the notes, react 👎 to my answer or reply to it with "wrong". I save that question and my answer, with your display name, in a review list for my owner; nothing else changes. If the notes themselves are wrong or missing something, reply to my answer with `/correct` and the fix, for example `/correct Mira is Tobin's sister, not his cousin`. I save it, with your display name and the date, as a table correction, use it ahead of the notes and say so. Both lists stay on the group's server and go to my owner's Mac for review; a table correction that bears on a question is sent to OpenAI along with the notes passages. Anyone in this channel can add one.

**Dice and character sheets:** `/roll 1d20+5` rolls dice, and `/roll Religion -2` rolls your saved character's Religion plus an extra modifier (skills, saves, Perception and Lores). Add `character:` to roll for someone else's character, `secret:` to see the result only yourself. To add your character, export it from Pathbuilder 2e as a JSON file and attach it to `/sheet add`; `/sheet help` has the steps. `/character register` links you (or, if you own the sheet or are a GM, another player) to a character, and `/character list` shows who is who. An eidolon has no sheet of its own: `/companion add` attaches one to a character with its six ability modifiers, and `/roll Athletics character:Ash` (or `companion:True` for your own) rolls it, using the summoner's proficiency and item bonuses. If your character has a companion, "my eidolon" or "my companion" in a question means it. These commands work only in this channel. I save the JSON file on the group's server, tied to your Discord account, and keep your last 10 uploads of it. Everyone in this channel can roll for and view any saved character; only its owner or a GM can update, export or delete it. `/sheet delete` erases it and every earlier version, and a GM can do the same on request. Sheets are never sent to OpenAI or any language model; the only thing taken from one is a companion's name and kind, sent with your question so I can find its note.

**Rules answers** come from live Archives of Nethys lookups and end with a link to the exact page. Check the page if it matters at the table.

**Licence:** Pathfinder Second Edition rules content belongs to Paizo Inc. and is shown via Archives of Nethys (2e.aonprd.com). Analecta is not published, endorsed, or specifically approved by Paizo. It is free to use and always will be. This product is licensed under the ORC License located at the Library of Congress at TX 9-307-067 and available online at https://paizo.com/orclicense and others. All warranties are disclaimed as set forth therein.

_Questions about Analecta: ask in this channel or tell its owner._
