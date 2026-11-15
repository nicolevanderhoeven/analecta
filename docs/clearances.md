# Clearances (checked before anything goes live)

Three checks from official pages, done 2026-11-15. None rules the plan out. Re-check them before launch if a
month or more has passed, because policies change.

| # | Question | Result | Rules out the plan? |
|---|---|---|---|
| 1 | Discord Developer Policy and Developer Terms: may a bot send message content to an AI provider? | Yes, as inference for the bot's own function. Not for model training. | No |
| 2 | OpenAI API data terms: training and retention | Not used for training by default. Abuse-monitoring logs up to 30 days. | No |
| 3 | ORC licence attribution wording | A notice and an attribution statement, no full licence text needed. | No |

## 1. Discord

Sources (official, read 2026-11-15; Discord's help centre blocks automated clients, so the text was read through a
public reader relay of the same pages and should be eyeballed once in a normal browser before launch):

- Discord Developer Policy, effective 2024-07-08, last updated 2024-06-06:
  <https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy>
- Discord Developer Terms of Service, effective 2024-07-08, last updated 2024-06-06:
  <https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service>

What they say that matters here:

- Policy rule 21: "Do not use message content obtained through the APIs to train machine learning or AI models
  (including large language models) unless express permission is granted by Discord." Analecta only asks a model to
  answer a question. It never trains or fine-tunes anything, and the OpenAI terms below say API data is not used
  for training by default. Keep it that way: never opt the OpenAI project in to data sharing.
- Policy rule 15: API Data may be used only as necessary to provide the application's stated functionality. The
  stated function is answering questions in one channel, which is exactly what the message text is used for.
- Policy rules 16, 17, 18, 20: no profiling of users, no data brokers, no selling, no scraping. Analecta does none.
  It keeps no message history and logs no message text or user IDs. The one exception is what a member chooses to
  flag or correct (see the note after this list).
- Developer Terms section 5(b): API Data may not be shared with third parties except a "Service Provider",
  defined as "a person or entity you use to provide you services to develop or operate your Application". OpenAI,
  the model provider the bot calls to answer, is such a provider. Nothing is shared with anyone else.
- Developer Terms section 5(a): the application needs a privacy policy that says what data goes to third parties,
  linked in the Developer Portal. That policy is [privacy.md](privacy.md). **Before launch:** paste its public URL
  into the application's "Privacy Policy URL" field in the Developer Portal.
- Developer Terms section 5(b) also requires deleting API Data when no longer needed. Analecta stores none, apart
  from the member-initiated flags and corrections described in the note after this list.
- Reading message text needs the privileged Message Content intent, switched on in the Developer Portal.

Conditions that keep this clearance valid: inference only, no training, no data-sharing opt-in on the OpenAI
project, privacy policy linked, the group told before launch.

**Not covered by the checks above (open item).** Table corrections and the misread list store member-chosen content
on the server: a flagged question and answer, or a correction, with the member's display name and the time. The
checks above were made before this feature. Before it goes live, re-read Discord's Developer Policy on storing
message content and confirm that saving only what a member explicitly flags or corrects, in a private channel the
group controls, is allowed; the group is told by the pinned note and [privacy.md](privacy.md). The saved text is
also sent to OpenAI inside the answer prompt, under the same terms as the notes.

## 2. OpenAI API data terms

Source (official, read 2026-11-15): <https://developers.openai.com/api/docs/guides/your-data>

- Training: "data sent to the OpenAI API is not used to train or improve OpenAI models" unless you explicitly opt in.
- Retention: abuse-monitoring logs are kept "for up to 30 days, unless longer retention is required by law."
- Stored objects: the Responses API keeps application state 30 days by default when `store` is true. Analecta
  sends `store: false`, so nothing is kept for later retrieval.
- Zero data retention exists for approved customers only; it is not assumed here.

The model is `gpt-6-luna` (Responses API, function calling supported, 1.05M token context window, $0.10 per million
input tokens and $0.50 per million output tokens), from <https://developers.openai.com/api/docs/models>.

## 3. ORC licence attribution

Sources (official): <https://paizo.com/orclicense> (read 2026-11-15) and <https://2e.aonprd.com> pages that carry
the licence notice.

The ORC licence asks, in "a reasonable manner based on the medium, means, and context", for:

- an ORC notice: "This product is licensed under the ORC License located at the Library of Congress at TX 9-307-067
  and available online at various locations including [domains] and others. All warranties are disclaimed as set
  forth therein."
- an attribution notice naming each licensor or creator of the licensed material used, in good faith.

The licence text itself need not be reproduced. Paizo's Community Use Policy (as read by the design scout on
2026-11-15) adds that the project must be free to use, non-commercial, and say it is "not published, endorsed, or
specifically approved by Paizo".

Where this appears: `HELP_NOTICE` in `src/analecta/clearances.py`, which becomes both the `@Analecta help` reply
and the pinned note ([pinned-note.md](pinned-note.md)). Analecta also quotes at most a sentence or two of rules text
and always links to the Archives of Nethys page, and never keeps a bulk copy of the site.

Known gap: Paizo does not publish a Pathfinder-specific notice template on the ORC page, so the attribution names
Paizo Inc. and Archives of Nethys in good faith. Adjust if Paizo asks for different wording.
