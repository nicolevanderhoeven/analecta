# Operating Analecta

## Switches

| What | How |
|---|---|
| Stop rules lookups (if the Archives of Nethys endpoint changes) | Set `AON_ENABLED=false` in `/etc/analecta/analecta.env`, then `systemctl restart analecta`. The bot says lookups are off and does not guess rules. |
| Stop the bot | `systemctl stop analecta`, or remove its channel permission in Discord. To drop one server, delete its pair from `DISCORD_CHANNELS` and restart, or kick the bot from that server. |
| Change the model | Set `LLM_MODEL` (and `LLM_PROVIDER` once another provider is added), then restart. |
| Daily and per-person limits | `DAILY_QUESTION_LIMIT`, `USER_COOLDOWN_SECONDS`. |

## Corrections and flagged answers

Members correct the bot in the channel; the bot never edits the notes.

| Member does | Bot does |
|---|---|
| Replies to an answer with `/correct <the fix>` (`!correct` also works) | Appends it to `corrections.md` with their display name, the time and the question it was about, and replies "Saved as a table correction". Up to 500 characters. |
| Reacts 👎 to an answer, or replies to it with just "wrong" | Appends the question, the answer, who and when to `misreads.md` (once per answer) and replies "Logged for review". |

Only replies and reactions in the configured channels (and threads under them), on the bot's own messages, count.
Everything else is ignored. A `/correct` or "wrong" that is not a reply to an answer does nothing (a `/correct` that
mentions the bot gets a one-line hint).

Both files live in `CORRECTIONS_DIR` (default `/srv/analecta/corrections`), outside the notes folder, and are sent to
the Mac by the send-only Syncthing folder (see [deployment.md](deployment.md)). The format is plain Markdown, one
bullet per correction: `- [2026-11-12 14:03 UTC] **Name**: text`. Lines that do not match are ignored, so notes
typed into the file are harmless.

**How corrections reach answers.** Before the model's first turn the bot adds the table corrections to the
conversation as a `table_corrections` result, ahead of any note it reads. The system prompt tells the model to treat
a correction as true where the notes disagree, to say so with its date ("per a table correction from 12 Nov"), and to
let a later correction replace an earlier one. Names are not sent, only the date and the text. To keep the cost
bounded: while all corrections fit in 3,000 characters (about 750 tokens) they are all included; beyond that only
those sharing a word with the conversation are, newest first, up to that same cap. The file is re-read whenever it
changes, so an edit on the server takes effect on the next question. Removing a correction is manual; see
[deployment.md](deployment.md#reviewing-corrections-on-the-mac-and-removing-one).

If the folder cannot be written (wrong owner, folder missing), the bot answers "I could not save that just now" and
logs `could not save feedback` with no message text. `journalctl -u analecta` shows it.

## Spend cap

The hard cap is set on the OpenAI side: create a dedicated project for Analecta and set its monthly budget to 25 USD
in the OpenAI dashboard (Settings, Limits). The cap belongs to the key's project, not to this code. The bot's own
daily question limit is a second, softer guard. At the measured token use (see the evaluation section of the pull
request), a question costs a fraction of a cent on `gpt-6-luna`.

## Logs

`journalctl -u analecta -f`. Lines look like `answered turns=3 tools=grep_notes,read_note in=4860 cached=4293 out=130
secs=3.8`. They hold no message text.

## Notes freshness

The Mac exports hourly and Syncthing delivers it. The bot checks the notes folder at most once a minute and rebuilds
its digest when the files change, so a new session note is visible within about an hour and a minute.
`ls -l /srv/analecta/notes` on the server shows what arrived. Syncthing's simple versioning keeps the last five
versions of any file replaced or deleted, in `.stversions` inside that folder.

## Adding another model provider

Implement `analecta.llm.base.LLMProvider` (one `step` method: system prompt, neutral messages, tool specs in; text
and tool calls out), register it in `analecta/llm/__init__.py`, and select it with `LLM_PROVIDER`. The agent loop
and the tools do not change.

## Evaluating a model

`scripts/eval_questions.py` runs a private question list through the agent and prints aggregate results only. Keep
the questions and the answers file untracked (`*.local.*` is ignored by git).
