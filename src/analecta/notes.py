"""Read-only, path-jailed access to the exported campaign notes: list, grep, read, digest."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter

SESSION_RE = re.compile(r"^(\d{3,})_(\d{8})\s*(.*)\.md$")
MAX_READ_CHARS = 14000
MAX_GREP_LINES = 40
LINE_CLIP = 320
MAX_ENTITY_NOTES = 5
NOTE_CUT = "\n[truncated; call read_note again with a later start_line]"
MIN_ENTITY_NAME_CHARS = 3
CHARS_PER_TOKEN = 4  # rough, for the link-following token cap

# Note types (the frontmatter `type`) that are people, and the "hub" types that many notes link to.
PERSON_TYPES = frozenset({"pc", "npc", "character", "person", "player", "player character", "ally", "villain"})
PC_TYPES = frozenset({"pc", "player", "player character"})
HUB_TYPES = frozenset({
    "place", "location", "region", "city", "town", "settlement", "dungeon", "map", "item", "object", "artifact",
    "equipment", "session", "faction", "organization", "organisation",
})
RELATION_RE = re.compile(
    r"famil|parent|mother|father|\bmom\b|\bdad\b|child|\bkids?\b|\bson\b|daughter|sibling|brother|sister|spouse|"
    r"husband|\bwife\b|married|marriage|partner|lover|betroth|fianc|\ball(?:y|ies)\b|\benem(?:y|ies)\b|rival|friend|"
    r"relative|\bkin\b|descend|ancest|\bheirs?\b|cousin|uncle|aunt|niece|nephew|grand|bloodline|lineage|mentor|"
    r"\bwards?\b|sworn|related", re.IGNORECASE)
QUESTION_PEOPLE_RE = re.compile(RELATION_RE.pattern + r"|who (?:is|was|are|were)|relationship|connected|know", re.IGNORECASE)
FIRST_PERSON_RE = re.compile(r"(?<![\w'])(?:my|me|mine|myself|i)(?![\w])", re.IGNORECASE)
OWNERSHIP_RE = re.compile(r"(?<![\w'])(?:my|mine|myself)(?![\w])", re.IGNORECASE)
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]\[|#\n]+)(?:#[^\]|\n]*)?(?:\|([^\]\n]*))?\]\]")
DIGEST_CHAR_BUDGET = 40000  # roughly 10K tokens


@dataclass(frozen=True)
class LinkPolicy:
    """Limits for following [[wikilinks]] between notes. depth 0 turns link-following off."""
    depth: int = 2
    max_notes: int = 12
    token_cap: int = 32000

    @property
    def max_chars(self) -> int:
        return self.token_cap * CHARS_PER_TOKEN


MAX_LINK_DEPTH = 3


class NotesError(ValueError):
    """A tool call that cannot be served; the message is shown to the model."""


@dataclass
class LinkedNote:
    info: "NoteInfo"
    depth: int  # 0 for the notes the question names
    via: str  # title of the note whose link led here ("" for depth 0)
    text: str = ""  # what read() returned, cut to fit the budget


@dataclass
class LinkTrail:
    notes: list[LinkedNote] = field(default_factory=list)
    skipped_hubs: list[str] = field(default_factory=list)
    over_budget: list[str] = field(default_factory=list)

    @property
    def followed(self) -> list[LinkedNote]:
        return [n for n in self.notes if n.depth > 0]


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
    def note_type(self) -> str:
        value = self.meta.get("type")
        return value.strip().lower() if isinstance(value, str) else ""

    @property
    def names(self) -> list[str]:
        aliases = self.meta.get("aliases")
        extra = aliases if isinstance(aliases, list) else ([aliases] if isinstance(aliases, str) else [])
        return [self.title, *[a for a in extra if a.strip()]]

    @property
    def pronouns(self) -> str:
        """The `pronouns` frontmatter of a person note (a string or a list), joined with ", "; empty when absent."""
        if self.note_type not in PERSON_TYPES:
            return ""
        value = self.meta.get("pronouns")
        items = value if isinstance(value, list) else [value]
        return ", ".join(" ".join(v.split()) for v in items if isinstance(v, str) and v.strip())

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

    # -- people and links --------------------------------------------------------------
    def _name_index(self, infos: list[NoteInfo] | None = None) -> dict[str, NoteInfo]:
        index: dict[str, NoteInfo] = {}
        for info in infos if infos is not None else self.infos():
            for name in info.names:
                index.setdefault(name.strip().lower(), info)
        return index

    def find_character(self, display_names: list[str], override: str = "") -> NoteInfo | None:
        """The player character a Discord member plays: `override` (a note name or alias, from the operator's map)
        if it names a note, else the first display name that equals a PC note's title or alias (case-insensitive)."""
        infos = self.infos()
        if override.strip():
            hit = self._name_index(infos).get(override.strip().lower())
            if hit is not None and not hit.is_session:
                return hit
        pcs = self._name_index([i for i in infos if not i.is_session and i.note_type in PC_TYPES])
        for name in display_names:
            hit = pcs.get(" ".join(str(name).split()).lower())
            if hit is not None:
                return hit
        return None

    def follow_links(self, seeds: list[NoteInfo], question: str, policy: LinkPolicy, *,
                     seed_chars_used: int = 0, per_note_chars: int = 12000) -> LinkTrail:
        """Breadth-first walk of [[wikilinks]] from `seeds`, nearest notes first, within `policy`.

        Followed: person notes, and links on lines about family, partners, allies or enemies. Skipped: session notes
        and places, items, factions (hubs) unless the question names them; an item or faction linked on a family
        line is still followed when the link goes through one of its aliases (the note stands for a person). Stops
        when a step finds nothing new, at the depth, at `max_notes` notes in all or at the character budget.
        Seeds are not read here; only the linked notes (depth > 0) carry text.
        """
        depth = max(0, min(policy.depth, MAX_LINK_DEPTH))
        trail = LinkTrail()
        infos = self.infos()
        by_name = self._name_index(infos)
        visited = {s.path for s in seeds}
        trail.notes = [LinkedNote(s, 0, "") for s in seeds]
        used = seed_chars_used
        frontier = list(seeds)
        asked = question.lower()
        for level in range(1, depth + 1):
            found: list[tuple[int, int, NoteInfo, str]] = []  # (priority, order, target, via title)
            for src in frontier:
                try:
                    lines = self._resolve(src.path).read_text(encoding="utf-8", errors="replace").split("\n")
                except (NotesError, OSError):
                    continue
                for line in lines:
                    for m in WIKILINK_RE.finditer(line):
                        target_name = m.group(1).strip().rsplit("/", 1)[-1].strip()
                        target = by_name.get(target_name.lower())
                        if target is None or target.path in visited or any(f[2].path == target.path for f in found):
                            continue
                        shown = (m.group(2) or "").strip()
                        verdict = self._link_verdict(target, (target_name, shown), line, asked)
                        if verdict is None:
                            if target.title not in trail.skipped_hubs:
                                trail.skipped_hubs.append(target.title)
                            continue
                        found.append((verdict, len(found), target, src.title))
            if not found:
                break
            found.sort(key=lambda f: (f[0], f[1]))
            frontier = []
            for _, _, target, via in found:
                if len(trail.notes) >= policy.max_notes or used >= policy.max_chars - 400:
                    trail.over_budget.append(target.title)
                    continue
                try:
                    text = self.read(target.path, 1, 400)
                except (NotesError, OSError):
                    continue
                limit = min(per_note_chars, policy.max_chars - used)
                if len(text) > limit:
                    text = text[: max(0, limit - len(NOTE_CUT))] + NOTE_CUT
                used += len(text)
                visited.add(target.path)
                trail.notes.append(LinkedNote(target, level, via, text))
                frontier.append(target)
        trail.skipped_hubs = [h for h in trail.skipped_hubs if h not in {n.info.title for n in trail.notes}]
        return trail

    @staticmethod
    def _link_verdict(target: NoteInfo, written: tuple[str, ...], line: str, asked: str) -> int | None:
        """0 = follow first (person on a family line), 1 = follow (person elsewhere), 2 = follow last (other note on a
        family line), None = skip."""
        relation = bool(RELATION_RE.search(line))
        kind = target.note_type
        if target.is_session:
            return None if target.title.lower() not in asked else 1
        if kind in PERSON_TYPES:
            return 0 if relation else 1
        if any(n.strip().lower() in asked for n in target.names if len(n.strip()) >= MIN_ENTITY_NAME_CHARS):
            return 1  # the question names it, so it is not an incidental hub
        if kind in HUB_TYPES:
            stands_for_person = any(w.strip() and w.strip().lower() != target.title.lower() for w in written)
            return 2 if relation and stands_for_person and kind not in {"place", "location", "region", "city", "town",
                                                                      "settlement", "dungeon", "map"} else None
        return 2 if relation else None

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
        lines.append("NOTES (name [type] (aliases) (pronouns): description):")
        for i in entities:
            aliases = i.meta.get("aliases")
            alias_text = ""
            if isinstance(aliases, list) and aliases:
                alias_text = " (" + ", ".join(aliases[:6]) + ")"
            elif isinstance(aliases, str) and aliases:
                alias_text = f" ({aliases})"
            ntype = i.meta.get("type")
            tag = f" [{ntype}]" if isinstance(ntype, str) and ntype else ""
            pron = f" (pronouns: {i.pronouns})" if i.pronouns else ""
            desc = i.one_liner[:180]
            lines.append(f"{i.title}{tag}{alias_text}{pron}: {desc}".rstrip(": "))
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
