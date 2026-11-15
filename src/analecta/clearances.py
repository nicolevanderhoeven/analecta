"""User-facing notices. Wording is backed by the official-page checks in docs/clearances.md.

Do not state a clearance here that docs/clearances.md has not confirmed from an official page.
"""
from __future__ import annotations

ORC_NOTICE = (
    "This product is licensed under the ORC License located at the Library of Congress at TX 9-307-067 "
    "and available online at https://paizo.com/orclicense and others. All warranties are disclaimed as set forth therein."
)
PAIZO_NOTICE = (
    "Pathfinder Second Edition rules content belongs to Paizo Inc. and is shown via Archives of Nethys (2e.aonprd.com). "
    "Analecta is not published, endorsed, or specifically approved by Paizo. It is free to use and always will be."
)

HELP_NOTICE = """\
**Analecta** answers Pathfinder 2e rules questions and questions about our campaign.

**How to use it:** mention me, or reply to one of my messages, in this channel. Reply to my answer to keep a conversation going. I ignore DMs and every other channel and server.

**What I can see:** the messages in the reply chain you start, the group's exported campaign notes (session notes and character, place and faction notes only; "Secret goals" sections, hidden comments, notes not yet met in play and notes marked `bot: false` are never exported), and live pages on Archives of Nethys. No Discord history, no transcripts, nothing else.

**Where questions go:** your question and the note passages needed to answer it are sent to OpenAI's API. OpenAI states that API data is not used to train its models by default and is kept for up to 30 days for abuse monitoring. I do not store your questions.

**Rules answers** come from live Archives of Nethys lookups and end with a link to the exact page. Check the page if it matters at the table.

**Licence:** {paizo} {orc}
""".format(paizo=PAIZO_NOTICE, orc=ORC_NOTICE)

PINNED_NOTE = HELP_NOTICE + "\n_Questions about Analecta: ask in this channel or tell its owner._"
