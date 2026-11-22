from __future__ import annotations

import json
from pathlib import Path

import pytest

import export_notes as ex

from conftest import SOURCE


def read_all(dest: Path) -> dict[str, str]:
    return {p.relative_to(dest).as_posix(): p.read_text() for p in dest.rglob("*.md")}


def test_exports_only_campaign_notes(exported: Path):
    files = read_all(exported)
    names = set(files)
    assert "Marta Quillon.md" in names
    assert "Unmet Stranger.md" not in names  # met: false
    assert "Private Plans.md" not in names  # bot: false
    assert not any(n.startswith(".obsidian") or "Granola" in n for n in names)
    assert len(names) == 7


def test_hidden_and_secret_content_is_gone(exported: Path):
    blob = "\n".join(read_all(exported).values())
    assert "%%" not in blob
    assert "GM prep" not in blob
    assert "secret drawing text" not in blob and "Excalidraw" not in blob
    assert "secret map" not in blob and "Secret goals" not in blob and "More about the secret" not in blob
    assert "Open Threads" in blob  # the section after the secret one survives
    assert "granola" not in blob.lower()


def test_emails_and_unlisted_frontmatter_removed(exported: Path):
    blob = "\n".join(read_all(exported).values())
    assert "@" not in blob
    assert "[email removed]" in blob
    assert "granola_id" not in blob and "attendees" not in blob
    assert "summary:" in blob and "aliases:" in blob


def test_frontmatter_list_aliases_kept(exported: Path):
    text = (exported / "Marta Quillon.md").read_text()
    assert "  - Old Quill" in text
    assert "met:" not in text  # only allowlisted keys survive


def test_manifest_and_stignore(exported: Path):
    manifest = json.loads((exported / ex.MANIFEST).read_text())
    assert "Marta Quillon.md" in manifest["files"]
    ignore = (exported / ".stignore").read_text()
    assert ex.TMP_PREFIX in ignore and ex.MANIFEST in ignore  # neither is synced to the server
    assert not list(exported.glob(f"{ex.TMP_PREFIX}*"))


def test_rerun_is_idempotent_and_removes_stale(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.md").write_text("---\ntype: npc\n---\nalpha\n")
    (src / "B.md").write_text("---\ntype: npc\n---\nbeta\n")
    dest = tmp_path / "out"
    assert ex.run_export(src, dest).exported == 2
    assert ex.run_export(src, dest).exported == 2
    (src / "B.md").write_text("---\nmet: false\n---\nbeta\n")  # now excluded
    r = ex.run_export(src, dest)
    assert r.removed == 1 and not (dest / "B.md").exists() and (dest / "A.md").exists()


def test_guard_refuses_foreign_file_and_writes_nothing(exported: Path):
    (exported / "Agenda from elsewhere.md").write_text("work notes")
    before = read_all(exported)
    with pytest.raises(ex.ExportRefused):
        ex.run_export(SOURCE, exported)
    assert read_all(exported) == before


def test_guard_refuses_non_empty_folder_without_manifest(tmp_path: Path):
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "stray.txt").write_text("x")
    with pytest.raises(ex.ExportRefused):
        ex.run_export(SOURCE, dest)


def test_guard_allows_syncthing_markers(exported: Path):
    (exported / ".stfolder").mkdir()
    (exported / ".stversions").mkdir()
    (exported / ".stversions" / "old~20240101.md").write_text("old")
    ex.run_export(SOURCE, exported)


def test_guard_refuses_dest_inside_vault_or_repo_or_source(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    with pytest.raises(ex.ExportRefused):
        ex.run_export(SOURCE, vault / "export")
    with pytest.raises(ex.ExportRefused):
        ex.run_export(SOURCE, ex.REPO_ROOT / "export-here")
    with pytest.raises(ex.ExportRefused):
        ex.run_export(SOURCE, SOURCE / "export")


def test_refuses_missing_source(tmp_path: Path):
    with pytest.raises(ex.ExportRefused):
        ex.run_export(tmp_path / "nope", tmp_path / "out")


def test_symlinks_are_not_followed(tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("private")
    src = tmp_path / "src"
    src.mkdir()
    (src / "Link.md").symlink_to(outside)
    (src / "Real.md").write_text("fine")
    ex.run_export(src, tmp_path / "out")
    assert not (tmp_path / "out" / "Link.md").exists()


def test_unmatched_comment_opener_hides_rest():
    clean, _, _ = ex.sanitize_note("---\ntype: npc\n---\nvisible\n%% never closed\nhidden")
    assert "visible" in clean and "hidden" not in clean


def test_secret_goals_inside_code_fence_still_dropped():
    clean, _, dropped = ex.sanitize_note("# T\n```\n## Secret goals\nhidden\n```\n## Next\nafter\n")
    assert dropped == 1 and "hidden" not in clean and "after" in clean


def test_secret_callout_dropped():
    clean, _, dropped = ex.sanitize_note("intro\n> [!note] Secret goals\n> hidden stuff\n\nnext")
    assert "hidden stuff" not in clean and "next" in clean and dropped == 1


def test_pronouns_frontmatter_kept():
    for value in ("they/them", "[she/her, they/them]"):
        clean, _, _ = ex.sanitize_note(f"---\ntype: npc\npronouns: {value}\nsecret: x\n---\nbody")
        assert f"pronouns: {value}" in clean and "secret:" not in clean


def test_bot_false_tag_variants():
    for tag in ("bot: false", "bot/false", "bot-false"):
        clean, reason, _ = ex.sanitize_note(f"---\ntags:\n  - {tag}\n---\nx")
        assert clean is None and reason == "bot-false"


def test_exclusions_survive_comments_case_and_unterminated_frontmatter():
    cases = {
        "---\nmet: false # not yet met\n---\nx": "met-false",
        "---\nbot: false # private\n---\nx": "bot-false",
        "---\nMet: false\n---\nx": "met-false",
        "---\nBOT: No\n---\nx": "bot-false",
        "---\nmet: false\ntype: npc\nbody never closed": "unterminated-frontmatter",
    }
    for text, why in cases.items():
        clean, reason, _ = ex.sanitize_note(text)
        assert clean is None and reason == why, text


def test_main_dry_run_writes_nothing(tmp_path: Path, capsys):
    out = tmp_path / "out"
    assert ex.main(["--source", str(SOURCE), "--dest", str(out), "--dry-run"]) == 0
    assert not out.exists()
    assert "exported=7" in capsys.readouterr().out


def test_main_reports_refusal(tmp_path: Path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / "stray.md").write_text("x")
    assert ex.main(["--source", str(SOURCE), "--dest", str(out)]) == 3
    assert "REFUSED" in capsys.readouterr().err
