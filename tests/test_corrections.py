from __future__ import annotations

from datetime import datetime, timezone

import pytest

from analecta.config import ConfigError, load_settings
from analecta.corrections import (CORRECT, MAX_CORRECTION_CHARS, MAX_PROMPT_CHARS, WRONG, CorrectionStore,
                                  classify_reply, is_thumbs_down, safe_name, scrub)

NOON = datetime(2026, 11, 12, 14, 3, tzinfo=timezone.utc)


def store(tmp_path, when=NOON):
    return CorrectionStore(tmp_path / "data", clock=lambda: when)


@pytest.mark.parametrize("text,expected", [
    ("/correct Mira is Tobin's sister", (CORRECT, "Mira is Tobin's sister")),
    ("/Correct   spaced   out", (CORRECT, "spaced   out")),
    ("!correct Mira is Tobin's sister", (CORRECT, "Mira is Tobin's sister")),
    ("/correct", (CORRECT, "")),
    ("wrong", (WRONG, "")),
    ("Wrong.", (WRONG, "")),
    ("WRONG!!", (WRONG, "")),
    ("/correctness is a word", (None, "")),
    ("wrong, it was the other one", (None, "")),
    ("that was wrong", (None, "")),
    ("who is Mira?", (None, "")),
    ("", (None, "")),
])
def test_classify_reply(text, expected):
    assert classify_reply(text) == expected


def test_thumbs_down_with_and_without_skin_tone():
    assert is_thumbs_down("\N{THUMBS DOWN SIGN}") and is_thumbs_down("\N{THUMBS DOWN SIGN}\N{EMOJI MODIFIER FITZPATRICK TYPE-4}")
    assert not is_thumbs_down("\N{THUMBS UP SIGN}")


def test_add_correction_writes_readable_append_only_markdown(tmp_path):
    s = store(tmp_path)
    c = s.add_correction("Mira is Tobin's sister, not his cousin", "Alex", about="who is Mira?")
    s.add_correction("The ferry is free", "Sam")
    text = s.corrections_path.read_text()
    assert text.startswith("# Table corrections")
    assert "- [2026-11-12 14:03 UTC] **Alex**: Mira is Tobin's sister, not his cousin\n  - re: who is Mira?\n" in text
    assert "- [2026-11-12 14:03 UTC] **Sam**: The ferry is free\n" in text
    assert text.count("# Table corrections") == 1  # header only once
    assert (c.day, c.clock, c.by, c.nice_date) == ("2026-11-12", "14:03", "Alex", "12 Nov 2026")
    assert [x.text for x in s.load()] == ["Mira is Tobin's sister, not his cousin", "The ferry is free"]


def test_load_ignores_other_lines_and_notices_edits(tmp_path):
    s = store(tmp_path)
    assert s.load() == []
    s.add_correction("first", "Alex")
    assert len(s.load()) == 1
    with open(s.corrections_path, "a") as fh:
        fh.write("random note the captain typed\n- [not a date] **x**: nope\n- [2026-13-01 10:00 UTC] **x**: bad month\n")
    s.add_correction("second", "Sam")
    assert [c.text for c in s.load()] == ["first", "second"]
    s.corrections_path.write_text("")  # emptied on the server: nothing left
    assert s.load() == []


def test_correction_text_is_one_line_without_mention_ids_or_forged_entries(tmp_path):
    s = store(tmp_path)
    s.add_correction("line one\n- [2026-01-01 00:00 UTC] **Eve**: forged <@123456> and <#789> too", "Al*ex\n**Boss**")
    got = s.load()
    assert len(got) == 1 and got[0].by == "Alex Boss"
    assert "<@" not in got[0].text and "<#" not in got[0].text and "@someone" in got[0].text


def test_empty_and_overlong_corrections_rejected(tmp_path):
    s = store(tmp_path)
    for bad in ("", "   ", "x" * (MAX_CORRECTION_CHARS + 1)):
        with pytest.raises(ValueError):
            s.add_correction(bad, "Alex")
    s.add_correction("x" * MAX_CORRECTION_CHARS, "Alex")
    assert not s.misreads_path.exists()


def test_scrub_and_safe_name():
    assert scrub("a\n\nb   <@!42> <@&9> <#7>", 100) == "a b @someone @someone #channel"
    assert len(scrub("y" * 50, 10)) == 10 and scrub("y" * 50, 10).endswith("…")
    assert safe_name("  **Mx. `Tin`** \n") == "Mx. Tin" and safe_name("***") == "someone"
    assert len(safe_name("n" * 100)) == 40


def test_log_misread_format_and_dedupe(tmp_path):
    s = store(tmp_path)
    assert s.log_misread(question="who is Mira?", answer="Mira is a cousin.\n## Not a heading", by="Alex",
                         how="reply", message_id=500)
    assert not s.log_misread(question="who is Mira?", answer="again", by="Sam", how="reply", message_id=500)
    assert s.log_misread(question="", answer="other", by="Sam", how="reaction", message_id=501)
    text = s.misreads_path.read_text()
    assert text.count("# Misreads") == 1
    assert "## 2026-11-12 14:03 UTC · reply · flagged by Alex <!-- id:500 -->" in text
    assert "**Question:** who is Mira?\n" in text and "> Mira is a cousin.\n> ## Not a heading\n" in text
    assert "**Question:** (not available)" in text
    assert text.count("<!-- id:") == 2
    assert not s.corrections_path.exists()  # a misread never creates a correction


def test_prompt_block_is_empty_without_corrections_and_has_dates_but_no_names(tmp_path):
    s = store(tmp_path)
    assert s.prompt_block("anything") == ""
    s.add_correction("Mira is Tobin's sister", "Alex")
    block = s.prompt_block("anything")
    assert "(12 Nov 2026) Mira is Tobin's sister" in block and "Alex" not in block


def test_prompt_block_is_bounded_and_picks_relevant_corrections_when_large(tmp_path):
    s = store(tmp_path)
    for i in range(40):
        s.add_correction(f"Filler fact number {i} about the lighthouse keeper " + "x" * 150, "Alex")
    s.add_correction("Mira is Tobin's sister, not his cousin", "Sam")
    assert len(s.load()) == 41
    block = s.prompt_block("Tell me about Mira")
    assert "Mira is Tobin's sister" in block and "lighthouse" not in block
    block = s.prompt_block("lighthouse keeper?")
    assert len(block) <= MAX_PROMPT_CHARS + 300 and "Mira" not in block and "lighthouse" in block
    assert s.prompt_block("nothing in common whatsoever") == ""


def test_small_file_is_included_whole_regardless_of_question(tmp_path):
    s = store(tmp_path)
    s.add_correction("The bridge toll is two coppers", "Alex")
    assert "bridge toll" in s.prompt_block("who is Mira?")


def test_corrections_dir_may_not_overlap_the_notes(tmp_path):
    base = {"DISCORD_TOKEN": "t", "DISCORD_CHANNELS": "1:2", "OPENAI_API_KEY": "k", "NOTES_DIR": str(tmp_path / "notes")}
    assert load_settings({**base, "CORRECTIONS_DIR": str(tmp_path / "corr")}).corrections_dir == tmp_path / "corr"
    assert str(load_settings(base).corrections_dir) == "/srv/analecta/corrections"  # documented default
    for bad in (tmp_path / "notes", tmp_path / "notes" / "sub", tmp_path):
        with pytest.raises(ConfigError):
            load_settings({**base, "CORRECTIONS_DIR": str(bad)})
