"""Tiny YAML-frontmatter reader for Obsidian notes (stdlib only, top-level keys only).

Shared by the bot (digest and tools) and the export script, so both read notes the same way.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_COMMENT = re.compile(r"(?:^|\s)#.*$")
_KEY = re.compile(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$")


@dataclass
class Entry:
    key: str
    raw_lines: list[str] = field(default_factory=list)  # exact source lines, key line first

    @property
    def value(self) -> str | list[str]:
        first = _COMMENT.sub("", self.raw_lines[0].partition(":")[2]).strip()
        rest = [ln for ln in self.raw_lines[1:] if ln.strip()]
        items = [ln.strip()[2:].strip() for ln in rest if ln.strip().startswith("- ")]
        if items and not first:
            return [_unquote(i) for i in items]
        if first.startswith("[") and first.endswith("]"):
            return [_unquote(i.strip()) for i in first[1:-1].split(",") if i.strip()]
        if rest and not items:
            first = " ".join([first] + [ln.strip() for ln in rest]).strip()
        return _unquote(first)


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def is_unterminated(text: str) -> bool:
    """True when the text opens a frontmatter block that never closes."""
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return False
    return not any(ln.strip() in {"---", "..."} for ln in lines[1:])


def split(text: str) -> tuple[list[Entry], str]:
    """Return (frontmatter entries, body). No frontmatter gives ([], text)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return [], text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in {"---", "..."}:
            end = i
            break
    if end is None:
        return [], text
    entries: list[Entry] = []
    for ln in lines[1:end]:
        m = _KEY.match(ln) if not ln.startswith((" ", "\t", "-")) else None
        if m:
            entries.append(Entry(m.group(1), [ln]))
        elif entries:
            entries[-1].raw_lines.append(ln)
    return entries, "\n".join(lines[end + 1 :])


def as_dict(entries: list[Entry]) -> dict[str, str | list[str]]:
    return {e.key.lower(): e.value for e in entries}


def is_false(value: str | list[str] | None) -> bool:
    if value is None or isinstance(value, list):
        return False
    return value.strip().lower() in {"false", "no", "off", "0"}
