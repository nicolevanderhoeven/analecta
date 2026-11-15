from __future__ import annotations

import pytest

from analecta.notes import NotesError, NotesStore


def test_grep_finds_alias_and_session(exported):
    s = NotesStore(exported)
    out = s.grep("Old Quill|Marta")
    assert "Marta Quillon.md" in out and "002_20240112" in out


def test_grep_no_match_is_explicit(exported):
    assert "No matches" in NotesStore(exported).grep("lich")


def test_grep_is_literal_not_regex(exported):
    s = NotesStore(exported)
    assert "No matches" in s.grep(".*")
    with pytest.raises(NotesError):
        s.grep("   |  ")


def test_read_is_path_jailed(exported, tmp_path):
    (tmp_path / "secret.md").write_text("outside")
    s = NotesStore(exported)
    for bad in ("../secret.md", "/etc/passwd", "Marta Quillon.txt", ".stignore", "nope.md", ".obsidian/x.md"):
        with pytest.raises(NotesError):
            s.read(bad)
    assert "retired cartographer" in s.read("Marta Quillon.md")


def test_read_paging(exported):
    out = NotesStore(exported).read("Marta Quillon.md", start_line=1, max_lines=3)
    assert "more lines follow" in out


def test_list_sessions_last(exported):
    out = NotesStore(exported).list_sessions(last=1)
    assert out.startswith("003 | 2024-01-19")
    assert "lantern" in out


def test_list_notes_by_alias_and_type(exported):
    s = NotesStore(exported)
    assert "Ashfen Hound.md" in s.list_notes(name_contains="ash dog")
    assert "Marta Quillon.md" in s.list_notes(note_type="npc")
    assert "001_" not in s.list_notes()


def test_digest_has_sessions_and_aliases(exported):
    d = NotesStore(exported).digest()
    assert "001 2024-01-05: The party left Mossbridge" in d
    assert "Old Quill" in d and "retired cartographer" in d


def test_digest_budget(exported):
    d = NotesStore(exported).digest(budget_chars=200)
    assert len(d) < 260 and d.endswith("[digest truncated]")


def test_missing_folder_is_empty_not_error(tmp_path):
    s = NotesStore(tmp_path / "nope")
    assert s.fingerprint() == (0, 0) and s.digest().startswith("SESSIONS")


def test_fingerprint_changes_with_files(exported):
    s = NotesStore(exported)
    before = s.fingerprint()
    (exported / "New.md").write_text("new")
    assert s.fingerprint() != before
