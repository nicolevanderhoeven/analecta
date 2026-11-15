"""Read-only, path-jailed access to the exported campaign notes: list, grep, read, digest."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import frontmatter

SESSION_RE = re.compile(r"^(\d{3,})_(\d{8})\s*(.*)\.md$")
MAX_READ_CHARS = 14000
MAX_GREP_LINES = 40
LINE_CLIP = 320
MAX_ENTITY_NOTES = 5
MIN_ENTITY_NAME_CHARS = 3
DIGEST_CHAR_BUDGET = 40000  # roughly 10K tokens


class NotesError(ValueError):
    """A tool call that cannot be served; the message is shown to the model."""


@dataclass(frozen=True)
class NoteInfo:
    path: str  # relative to the notes root, forward slashes
    title: str
    meta: dict[str, str | list[str]]
    session_number: int | None
    session_date: str | None

    @property
    def is_session(self) -> bool:
        return self.session_number is not None

    @property
    def one_liner(self) -> str:
        for key in ("summary", "description"):
            value = self.meta.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())
        return ""


class NotesStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    # -- discovery ---------------------------------------------------------------
    def _paths(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        out: list[Path] = []
        for p in self.root.rglob("*.md"):
            rel = p.relative_to(self.root)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if p.is_symlink() or not p.is_file():
                continue
            out.append(p)
        return sorted(out, key=lambda p: p.relative_to(self.root).as_posix().lower())

    def fingerprint(self) -> tuple[int, int]:
        """(file count, newest mtime in ns): changes whenever the synced export changes."""
        paths = self._paths()
        newest = 0
        for p in paths:
            try:
                newest = max(newest, p.stat().st_mtime_ns)
            except OSError:
                pass
        return len(paths), newest

    def infos(self) -> list[NoteInfo]:
        infos: list[NoteInfo] = []
        for p in self._paths():
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:6000]
            except OSError:
                continue
            entries, _ = frontmatter.split(head)
            meta = frontmatter.as_dict(entries)
            name = p.name
            m = SESSION_RE.match(name)
            infos.append(
                NoteInfo(
                    path=p.relative_to(self.root).as_posix(),
                    title=p.stem,
                    meta=meta,
                    session_number=int(m.group(1)) if m else None,
                    session_date=m.group(2) if m else None,
                )
            )
        return infos

    # -- tools -------------------------------------------------------------------
    def list_sessions(self, last: int | None = None, start: int | None = None, end: int | None = None) -> str:
        sessions = [i for i in self.infos() if i.is_session]
        sessions.sort(key=lambda i: (i.session_number, i.path))
        if start is not None:
            sessions = [i for i in sessions if i.session_number >= start]
        if end is not None:
            sessions = [i for i in sessions if i.session_number <= end]
        if last:
            sessions = sessions[-max(1, min(int(last), 60)) :]
        sessions = sessions[:80]
        if not sessions:
            return "No session notes matched."
        return "\n".join(
            f"{i.session_number:03d} | {_fmt_date(i.session_date)} | {i.path} | {i.one_liner[:200]}"
            for i in sessions
        )

    def list_notes(self, name_contains: str = "", note_type: str = "") -> str:
        needle = name_contains.strip().lower()
        wanted = note_type.strip().lower()
        rows = []
        for i in self.infos():
            if i.is_session:
                continue
            if needle:
                aliases = i.meta.get("aliases")
                alias_text = " ".join(aliases) if isinstance(aliases, list) else str(aliases or "")
                if needle not in i.path.lower() and needle not in alias_text.lower():
                    continue
            ntype = str(i.meta.get("type", "") or "")
            if wanted and wanted != ntype.lower():
                continue
            rows.append(f"{i.path} | {ntype} | {i.one_liner[:160]}")
        if not rows:
            return "No notes matched."
        more = f"\n(+{len(rows) - 60} more, narrow the filter)" if len(rows) > 60 else ""
        return "\n".join(rows[:60]) + more

    def grep(self, pattern: str, path_contains: str = "", max_lines: int = MAX_GREP_LINES) -> str:
        """Case-insensitive search. `|` separates alternatives; everything else is literal."""
        parts = [p.strip() for p in pattern.split("|") if p.strip()]
        if not parts:
            raise NotesError("pattern is empty")
        if len(pattern) > 200:
            raise NotesError("pattern too long (200 characters max)")
        rx = re.compile("|".join(re.escape(p) for p in parts), re.IGNORECASE)
        limit = max(1, min(int(max_lines), MAX_GREP_LINES))
        sub = path_contains.strip().lower()
        files_hit = 0
        total = 0
        shown = 0
        out: list[str] = []
        for p in self._paths():
            rel = p.relative_to(self.root).as_posix()
            if sub and sub not in rel.lower():
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").split("\n")
            except OSError:
                continue
            hits = [(n, ln) for n, ln in enumerate(lines, 1) if rx.search(ln)]
            name_hit = bool(rx.search(p.stem))
            if not hits and not name_hit:
                continue
            files_hit += 1
            total += len(hits)
            if shown >= limit:
                continue
            out.append(f"## {rel}" + (" (filename matches)" if name_hit else "") + f" [{len(hits)} line(s)]")
            for n, ln in hits[:6]:
                if shown >= limit:
                    break
                out.append(f"{n}: {_clip(ln)}")
                shown += 1
            if len(hits) > 6:
                out.append(f"... {len(hits) - 6} more line(s) in this file")
        if not files_hit:
            return "No matches. (Zero matches means the notes do not mention it. Try a spelling variant or an alias.)"
        out.append(f"-- {files_hit} file(s), {total} matching line(s) in total")
        return "\n".join(out)

    def read(self, path: str, start_line: int = 1, max_lines: int = 400) -> str:
        p = self._resolve(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")
        start = max(1, int(start_line))
        chunk = lines[start - 1 : start - 1 + max(1, min(int(max_lines), 1000))]
        body = "\n".join(chunk)
        note = ""
        if len(body) > MAX_READ_CHARS:
            body = body[:MAX_READ_CHARS]
            note = "\n[truncated; call read_note again with a later start_line]"
        elif start - 1 + len(chunk) < len(lines):
            note = f"\n[more lines follow; next start_line is {start + len(chunk)}]"
        return f"# {path} (lines {start}-{start + len(chunk) - 1} of {len(lines)})\n{body}{note}"

    def _resolve(self, path: str) -> Path:
        rel = Path(path.strip().lstrip("/"))
        if rel.suffix.lower() != ".md" or ".." in rel.parts or any(x.startswith(".") for x in rel.parts):
            raise NotesError("path must be a note path as listed, ending in .md")
        full = (self.root / rel).resolve()
        if self.root not in full.parents or not full.is_file():
            raise NotesError(f"no such note: {path}")
        return full

    # -- entity matching ---------------------------------------------------------
    def match_entities(self, question: str, limit: int = MAX_ENTITY_NOTES) -> list[NoteInfo]:
        """Non-session notes whose file name or frontmatter alias appears in the question as a whole word.

        Case-insensitive. Longer names win, and a name is skipped when it overlaps words already claimed by a
        longer matched name (so "Old Quill" does not also pull in a note called "Quill"). Results follow the
        order the names appear in the question.
        """
        found: list[tuple[int, NoteInfo]] = []
        spans: list[tuple[int, int]] = []
        candidates: list[tuple[str, NoteInfo]] = []
        for info in self.infos():
            if info.is_session:
                continue
            names = [info.title]
            aliases = info.meta.get("aliases")
            names += aliases if isinstance(aliases, list) else ([aliases] if isinstance(aliases, str) else [])
            candidates += [(n.strip(), info) for n in names if len(n.strip()) >= MIN_ENTITY_NAME_CHARS]
        for name, info in sorted(candidates, key=lambda c: -len(c[0])):
            if any(f[1].path == info.path for f in found):
                continue
            m = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", question, re.IGNORECASE)
            if not m or any(m.start() < e and s < m.end() for s, e in spans):
                continue
            spans.append((m.start(), m.end()))
            found.append((m.start(), info))
        found.sort(key=lambda f: f[0])
        return [f[1] for f in found[:limit]]

    # -- digest ------------------------------------------------------------------
    def digest(self, budget_chars: int = DIGEST_CHAR_BUDGET) -> str:
        """Session one-liners plus entity descriptions and aliases, for the cached system prompt."""
        infos = self.infos()
        sessions = sorted((i for i in infos if i.is_session), key=lambda i: i.session_number)
        entities = [i for i in infos if not i.is_session]
        lines = ["SESSIONS (number, date, one-line summary):"]
        for i in sessions:
            lines.append(f"{i.session_number:03d} {_fmt_date(i.session_date)}: {i.one_liner[:240]}")
        lines.append("")
        lines.append("NOTES (name [type] (aliases): description):")
        for i in entities:
            aliases = i.meta.get("aliases")
            alias_text = ""
            if isinstance(aliases, list) and aliases:
                alias_text = " (" + ", ".join(aliases[:6]) + ")"
            elif isinstance(aliases, str) and aliases:
                alias_text = f" ({aliases})"
            ntype = i.meta.get("type")
            tag = f" [{ntype}]" if isinstance(ntype, str) and ntype else ""
            desc = i.one_liner[:180]
            lines.append(f"{i.title}{tag}{alias_text}: {desc}".rstrip(": "))
        text = "\n".join(lines)
        if len(text) > budget_chars:
            text = text[:budget_chars].rsplit("\n", 1)[0] + "\n[digest truncated]"
        return text


def _fmt_date(raw: str | None) -> str:
    if raw and len(raw) == 8:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw or ""


def _clip(line: str) -> str:
    line = line.strip()
    return line if len(line) <= LINE_CLIP else line[: LINE_CLIP - 3] + "..."
