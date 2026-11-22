#!/usr/bin/env python3
"""Export the campaign notes, and only those, to a dedicated folder that Syncthing shares.

Reads ONLY the source folder (the campaign notes). Writes ONLY into the export folder.
Exclusions: notes with `met: false`, notes with `bot: false`, "Secret goals" sections, hidden
`%% ... %%` blocks (this also removes Excalidraw drawing data), HTML comments, embeds of
transcripts, and e-mail addresses. Frontmatter is cut down to an allowlist of keys. Exclusion
keys match case-insensitively and ignore trailing `# comments`; a note whose frontmatter is never
closed is skipped rather than exported.

Guard: the script refuses to run, and changes nothing, if the export folder holds anything
that this script did not put there, or if the folder sits in a place where it should not be.

Standard library only, plus src/analecta/frontmatter.py from this repository.

Usage:
  scripts/export_notes.py [--source DIR] [--dest DIR] [--dry-run]
Defaults come from ANALECTA_SOURCE_DIR and ANALECTA_EXPORT_DIR (default ~/Analecta-export).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
from analecta import frontmatter  # noqa: E402

MANIFEST = ".analecta-export-manifest.json"
TMP_PREFIX = ".analecta-tmp-"
SYNCTHING_ENTRIES = {".stfolder", ".stignore", ".stversions"}
KEEP_KEYS = {"type", "aliases", "description", "summary", "date", "session", "tags", "pronouns"}
SKIP_DIR_NAMES = {"granola", "transcripts", "plugins"}

EXCALIDRAW = re.compile(r"\n(?:%%\n)?(?:# Excalidraw Data|#{1,3} Text Elements)")
COMMENT = re.compile(r"%%.*?%%", re.DOTALL)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
EMBED = re.compile(r"!?\[\[[^\]\n]*(?:granola|transcript)[^\]\n]*\]\]", re.IGNORECASE)
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
SECRET = re.compile(r"secret\s+goals?", re.IGNORECASE)


class ExportRefused(RuntimeError):
    """The guard tripped; nothing was written."""


@dataclass
class Report:
    exported: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    removed: int = 0
    secret_sections: int = 0

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


# -- sanitising one note ---------------------------------------------------------------
def _strip_hidden(text: str) -> str:
    m = EXCALIDRAW.search(text)
    if m:
        text = text[: m.start()]
    text = COMMENT.sub("", text)
    if "%%" in text:  # unmatched opener: Obsidian hides the rest of the note, so do we
        text = text[: text.index("%%")]
    return HTML_COMMENT.sub("", text)


def _drop_secret_sections(text: str) -> tuple[str, int]:
    out: list[str] = []
    skip_level: int | None = None
    dropped = 0
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HEADING.match(line)  # deliberately ignores code fences: when in doubt, drop
        if m:
            level = len(m.group(1))
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if skip_level is None and SECRET.search(m.group(2)):
                skip_level = level
                dropped += 1
                i += 1
                continue
        if skip_level is None and line.lstrip().startswith(">") and SECRET.search(line):
            # a callout block about secret goals: drop the whole block
            dropped += 1
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                i += 1
            continue
        if skip_level is None:
            out.append(line)
        i += 1
    return "\n".join(out), dropped


def _frontmatter_excludes(entries: list[frontmatter.Entry]) -> str | None:
    data = frontmatter.as_dict(entries)
    if frontmatter.is_false(data.get("met")):
        return "met-false"
    if frontmatter.is_false(data.get("bot")):
        return "bot-false"
    tags = data.get("tags")
    tag_list = tags if isinstance(tags, list) else str(tags or "").replace(",", " ").split()
    if any(t.strip().lower().replace(" ", "").replace("/", ":").replace("-", ":").replace("_", ":") == "bot:false"
           for t in tag_list):
        return "bot-false"
    return None


def sanitize_note(text: str) -> tuple[str | None, str, int]:
    """Return (clean text or None, reason if excluded, secret sections removed)."""
    text = text.replace("\r\n", "\n").lstrip("﻿")
    if frontmatter.is_unterminated(text):
        return None, "unterminated-frontmatter", 0
    entries, body = frontmatter.split(text)
    reason = _frontmatter_excludes(entries)
    if reason:
        return None, reason, 0
    body = _strip_hidden(body)
    body, dropped = _drop_secret_sections(body)
    body = EMBED.sub("", body)
    head = ""
    kept = [e for e in entries if e.key.lower() in KEEP_KEYS]
    if kept:
        head = "---\n" + "\n".join(ln for e in kept for ln in e.raw_lines) + "\n---\n"
    clean = EMAIL.sub("[email removed]", head + body.lstrip("\n"))
    _assert_clean(clean)
    return clean.rstrip() + "\n", "", dropped


def _assert_clean(clean: str) -> None:
    if "%%" in clean or "<!--" in clean:
        raise ExportRefused("hidden-comment markers survived sanitising")
    for line in clean.split("\n"):
        m = HEADING.match(line)
        if m and SECRET.search(m.group(2)):
            raise ExportRefused("a secret-goals heading survived sanitising")
    if EMAIL.search(clean):
        raise ExportRefused("an e-mail address survived sanitising")


# -- guards ----------------------------------------------------------------------------
def _within(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def check_locations(source: Path, dest: Path) -> None:
    if not source.is_dir():
        raise ExportRefused("source folder does not exist")
    if _within(dest, source) or _within(source, dest):
        raise ExportRefused("export folder and source folder must not contain each other")
    if _within(dest, REPO_ROOT):
        raise ExportRefused("export folder must be outside the repository")
    for parent in [dest, *dest.parents]:
        if (parent / ".obsidian").exists():
            raise ExportRefused("export folder is inside an Obsidian vault; choose a folder outside it")
    if dest.is_symlink():
        raise ExportRefused("export folder must not be a symlink")


def load_manifest(dest: Path) -> set[str]:
    p = dest / MANIFEST
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {str(x) for x in data["files"]}
    except (ValueError, KeyError, TypeError) as exc:
        raise ExportRefused("export manifest is unreadable") from exc


def check_dest_contents(dest: Path, known: set[str]) -> None:
    """Refuse if the export folder holds anything this script did not write."""
    if not dest.exists():
        return
    for p in sorted(dest.rglob("*")):
        rel = p.relative_to(dest)
        top = rel.parts[0]
        if top in SYNCTHING_ENTRIES or top == MANIFEST:
            continue
        if p.name.startswith(TMP_PREFIX) or p.name.startswith(".syncthing.") or p.name.startswith("~syncthing~"):
            continue
        if p.is_dir() and not p.is_symlink():
            continue
        if rel.as_posix() not in known:
            raise ExportRefused(
                "the export folder contains a file this script did not export "
                "(only campaign notes may be in it); move it out and run again"
            )


# -- the export ------------------------------------------------------------------------
def iter_source_notes(source: Path):
    for p in sorted(source.rglob("*.md")):
        rel = p.relative_to(source)
        if any(part.startswith(".") or part.lower() in SKIP_DIR_NAMES for part in rel.parts):
            continue
        if p.is_symlink() or not p.is_file() or not _within(p.resolve(), source):
            continue
        yield rel, p


def run_export(source: Path, dest: Path, *, dry_run: bool = False) -> Report:
    source = source.expanduser().resolve()
    dest = Path(os.path.abspath(dest.expanduser()))
    check_locations(source, dest)
    known = load_manifest(dest)
    check_dest_contents(dest, known)

    report = Report()
    outputs: dict[str, str] = {}
    for rel, path in iter_source_notes(source):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            report.skip("unreadable")
            continue
        clean, reason, dropped = sanitize_note(text)
        if clean is None:
            report.skip(reason)
            continue
        report.secret_sections += dropped
        outputs[rel.as_posix()] = clean
    report.exported = len(outputs)
    if dry_run:
        return report

    dest.mkdir(parents=True, exist_ok=True)
    (dest / ".stignore").write_text(f"{TMP_PREFIX}*\n{MANIFEST}\n", encoding="utf-8")
    for rel, clean in outputs.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f"{TMP_PREFIX}{target.name}"
        tmp.write_text(clean, encoding="utf-8")
        os.replace(tmp, target)
    for stale in sorted(known - set(outputs)):
        try:
            (dest / stale).unlink()
            report.removed += 1
        except FileNotFoundError:
            pass
    tmp = dest / f"{TMP_PREFIX}manifest"
    tmp.write_text(json.dumps({"files": sorted(outputs)}, indent=0), encoding="utf-8")
    os.replace(tmp, dest / MANIFEST)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=os.environ.get("ANALECTA_SOURCE_DIR"))
    ap.add_argument("--dest", default=os.environ.get("ANALECTA_EXPORT_DIR", "~/Analecta-export"))
    ap.add_argument("--dry-run", action="store_true", help="check and count, write nothing")
    args = ap.parse_args(argv)
    if not args.source:
        print("Set ANALECTA_SOURCE_DIR or pass --source.", file=sys.stderr)
        return 2
    try:
        report = run_export(Path(args.source), Path(args.dest), dry_run=args.dry_run)
    except ExportRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    skipped = ", ".join(f"{k}={v}" for k, v in sorted(report.skipped.items())) or "none"
    print(
        f"{'dry run: ' if args.dry_run else ''}exported={report.exported} removed={report.removed} "
        f"secret_sections_dropped={report.secret_sections} skipped: {skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
