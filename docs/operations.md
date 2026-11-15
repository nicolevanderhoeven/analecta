# Operating Analecta

## Switches

| What | How |
|---|---|
| Stop rules lookups (if the Archives of Nethys endpoint changes) | Set `AON_ENABLED=false` in `/etc/analecta/analecta.env`, then `systemctl restart analecta`. The bot says lookups are off and does not guess rules. |
| Stop the bot | `systemctl stop analecta`, or remove its channel permission in Discord. |
| Change the model | Set `LLM_MODEL` (and `LLM_PROVIDER` once another provider is added), then restart. |
| Daily and per-person limits | `DAILY_QUESTION_LIMIT`, `USER_COOLDOWN_SECONDS`. |

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
