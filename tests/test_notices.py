from __future__ import annotations

from pathlib import Path

from analecta.clearances import HELP_NOTICE, ORC_NOTICE, PAIZO_NOTICE, PINNED_NOTE
from analecta.gating import DISCORD_LIMIT, split_message
from analecta.prompts import build_system_prompt

DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_pinned_note_doc_is_in_sync():
    assert PINNED_NOTE in (DOCS / "pinned-note.md").read_text()


def test_required_statements_present():
    for needle in ("TX 9-307-067", "not published, endorsed, or specifically approved by Paizo", "OpenAI",
                   "30 days", "not used to train", "Secret goals", "Archives of Nethys"):
        assert needle in PINNED_NOTE, needle
    assert ORC_NOTICE in HELP_NOTICE and PAIZO_NOTICE in HELP_NOTICE


def test_notice_fits_discord_in_few_messages():
    parts = split_message(PINNED_NOTE)
    assert 1 <= len(parts) <= 2 and all(len(p) < DISCORD_LIMIT for p in parts)


def test_system_prompt_includes_digest_and_help():
    p = build_system_prompt("DIGEST-MARKER")
    assert "DIGEST-MARKER" in p and "Archives of Nethys" in p and "{" not in p.replace("{}", "")
