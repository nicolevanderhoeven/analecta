# Analecta privacy policy

Analecta is a small Discord bot for one Pathfinder 2e gaming group. This is what it does with data.

**What it reads.** Only messages in the channels it is set up for (one per server it has been added to) that mention it or reply to it, and the
earlier messages in that reply chain. It ignores direct messages and every other channel and server.

**What it sends to a third party.** To answer, it sends the question, the reply chain, and the passages of the
group's campaign notes it looks up to OpenAI's API. OpenAI states that API data is not used to train its models
by default and is kept for up to 30 days for abuse monitoring. Analecta asks OpenAI not to store the exchange
(`store: false`). Rules questions also cause lookups on Archives of Nethys, which receive search words, not
people's details.

**What it stores.** No message history and no database. Its logs hold counts and timings only: no
message text, no sheet contents and no user or channel IDs. A short in-memory cache of Archives of Nethys lookups disappears when the
bot restarts. It stores only what a member asks it to keep, on the group's server:

- a **review list** of answers a member flagged as wrong (a thumbs-down reaction on the answer, or a reply to it
  saying "wrong"): the question, the answer, the member's display name and the time;
- **table corrections**, which a member adds by replying to an answer with `/correct` and the fix: the correction,
  the question it was made about, the member's display name and the time.

- **character sheets**, when a member adds one with `/sheet add`: the Pathbuilder 2e JSON file they uploaded, the
  Discord user ID of the person who uploaded it (its owner), the character's name and the times it was added. The
  bot keeps the last 10 uploads of each sheet, so an update does not lose the one before. It also keeps a list of
  which Discord user ID plays which character (`/character register`), which the bot also uses to know which
  campaign note is a member's character when answering questions about the notes. These are plain files in a
  folder (`/var/lib/analecta/sheets` by default) that only the bot's service account can read. They are
  **not** copied anywhere else by the bot, **not** part of the notes export, and **never sent to OpenAI or any
  language model**: dice and skill totals are worked out by ordinary code. Everyone in the channel can roll for and
  view a saved character; only its owner, or a GM the person running the bot has named, can update, export or
  delete it.

The review list and corrections are copied to the owner's own computer, read-only on that side, so the owner can fold good corrections
into the notes and delete the rest. When answering, the bot uses the table corrections that bear on the question
ahead of the notes, so the text of those corrections goes to OpenAI along with the note passages (without the
member's name).

**Campaign notes.** The bot reads an export of the group's own notes. The export leaves out "Secret goals"
sections, notes not yet met in play, notes marked `bot: false`, hidden comments and any email addresses.

**Deleting data.** A sheet's owner can erase it, with every earlier version, at any time with `/sheet delete` (and
`/character unregister` removes the link between a Discord account and a character). A GM named by the person running
the bot can do the same. Ask the person who runs the bot to remove a correction or a review-list entry; they delete it
from the server's file (deleting the Discord message does not remove a saved correction). Delete a Discord message in
Discord as usual. To ask about anything else, contact the person who runs the bot in the channel.

**Changes.** Changes to this policy are made in this repository and announced in the channel.
