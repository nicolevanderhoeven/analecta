# Analecta privacy policy

Analecta is a small Discord bot for one Pathfinder 2e gaming group. This is what it does with data.

**What it reads.** Only messages in the channels it is set up for (one per server it has been added to) that mention it or reply to it, and the
earlier messages in that reply chain. It ignores direct messages and every other channel and server.

**What it sends to a third party.** To answer, it sends the question, the reply chain, and the passages of the
group's campaign notes it looks up to OpenAI's API. OpenAI states that API data is not used to train its models
by default and is kept for up to 30 days for abuse monitoring. Analecta asks OpenAI not to store the exchange
(`store: false`). Rules questions also cause lookups on Archives of Nethys, which receive search words, not
people's details.

**What it stores.** Nothing about people. It keeps no database, no message history and no user list. Its logs hold
counts and timings only: no message text and no user or channel IDs. A short in-memory cache of Archives of Nethys
lookups disappears when the bot restarts.

**Campaign notes.** The bot reads an export of the group's own notes. The export leaves out "Secret goals"
sections, notes not yet met in play, notes marked `bot: false`, hidden comments and any email addresses.

**Deleting data.** There is nothing stored to delete on Analecta's side. Delete a Discord message in Discord as
usual. To ask about anything else, contact the person who runs the bot in the channel.

**Changes.** Changes to this policy are made in this repository and announced in the channel.
