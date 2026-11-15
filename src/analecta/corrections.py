"""Table corrections and the misread list: runtime data kept outside the repository and outside the notes folder.

Two append-only Markdown files live in the corrections directory (`CORRECTIONS_DIR`):

* `corrections.md` holds the group's table corrections, one bullet per correction:
  `- [2026-11-12 14:03 UTC] **Alex**: Mira is Tobin's sister, not his cousin.` (an optional indented
  `- re:` line names the question the correction was made about). The bot reads this file when answering and
  puts corrections ahead of the notes. Lines that do not match the bullet format are ignored.
* `misreads.md` is a review list of answers someone flagged as wrong (the notes had the answer, the bot misread
  it). The bot never reads it back, apart from skipping an answer that is already listed.

The bot never writes to the notes folder, and the corrections directory is refused if it overlaps it.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CORRECTIONS_FILE = "corrections.md"
MISREADS_FILE = "misreads.md"

MAX_CORRECTION_CHARS = 500   # longest correction accepted
MAX_SHOWN_CHARS = 600  # longest single correction shown to the model (hand-edited lines can be longer)
MAX_PROMPT_CHARS = 3000      # budget for corrections shown to the model on one question (about 750 tokens)
MAX_QUOTED_CHARS = 2000      # longest question or answer stored in the misread list
MAX_CONTEXT_CHARS = 200      # longest "re:" question stored with a correction
MAX_NAME_CHARS = 40

CORRECTION_HEADER = (
    "# Table corrections\n\n"
    "Added by the group by replying to an Analecta answer with `/correct ...`. Analecta uses these ahead of the\n"
    "notes and says so. This file is kept on the server and sent here read-only: to remove a correction, delete\n"
    "its line on the server (see docs/deployment.md). Fold the good ones into your notes.\n\n"
)
MISREAD_HEADER = (
    "# Misreads\n\n"
    "Answers someone flagged as wrong (a thumbs-down reaction, or a reply saying \"wrong\"). The notes may already\n"
    "have the right answer; nothing in the notes changed. Review these when tuning the bot, then delete them on the\n"
    "server.\n\n"
)

_ENTRY = re.compile(r"^- \[(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2}) UTC\] \*\*(.*?)\*\*: (.+?)\s*$")
_MENTION = re.compile(r"<(@[!&]?|#)\d+>")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_STOPWORDS = frozenset(
    "the and for was were who what when where why how which that this these those with from into about "
    "his her hers him she they them their theirs its has had have not but are you your did does done "
    "can could would should will tell say said any all there then than also".split()
)

# Kinds of feedback a reply can carry.
CORRECT = "correct"
WRONG = "wrong"

_CORRECT_RX = re.compile(r"^[/!]correct(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_WRONG_RX = re.compile(r"^wrong[\s.!?]*$", re.IGNORECASE)


def classify_reply(text: str) -> tuple[str | None, str]:
    """Is a reply (mention already stripped, whitespace collapsed) a correction, a misread flag, or neither?

    `/correct <text>` (or `!correct <text>`) is a correction; a bare "wrong" is a misread flag.
    Returns (kind, payload); payload is the correction text and empty for a misread flag.
    """
    text = text.strip()
    m = _CORRECT_RX.match(text)
    if m:
        return CORRECT, (m.group(1) or "").strip()
    if _WRONG_RX.match(text):
        return WRONG, ""
    return None, ""


def is_thumbs_down(emoji: object) -> bool:
    """A thumbs-down reaction, with or without a skin tone."""
    return str(emoji).startswith("\N{THUMBS DOWN SIGN}")


def scrub(text: str, limit: int) -> str:
    """One line, no Discord mention markup (it carries IDs), at most `limit` characters."""
    text = _MENTION.sub(lambda m: "#channel" if m.group(1) == "#" else "@someone", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[*`_~|<>\[\]\\]", "", " ".join(str(name).split())).strip()
    return cleaned[:MAX_NAME_CHARS].strip() or "someone"


@dataclass(frozen=True)
class Correction:
    day: str      # YYYY-MM-DD, UTC
    clock: str    # HH:MM, UTC
    by: str
    text: str

    @property
    def nice_date(self) -> str:
        """`12 Nov 2026`, so the model can say "per a table correction from 12 Nov"."""
        year, month, day = (int(p) for p in self.day.split("-"))
        return f"{day} {_MONTHS[month - 1]} {year}"


def _keywords(text: str) -> set[str]:
    words = set()
    for w in _WORD.findall(text.lower().replace("’", "'")):
        w = w.removesuffix("'s")
        if len(w) >= 3 and w not in _STOPWORDS:
            words.add(w)
    return words


def _line(c: Correction) -> str:
    text = c.text if len(c.text) <= MAX_SHOWN_CHARS else c.text[: MAX_SHOWN_CHARS - 1] + "…"
    return f"- ({c.nice_date}) {text}"


class CorrectionStore:
    def __init__(self, directory: str | os.PathLike[str], clock: Callable[[], datetime] | None = None):
        self.directory = Path(directory)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._cache: tuple[tuple[int, int], list[Correction]] | None = None

    @property
    def corrections_path(self) -> Path:
        return self.directory / CORRECTIONS_FILE

    @property
    def misreads_path(self) -> Path:
        return self.directory / MISREADS_FILE

    # -- writing ---------------------------------------------------------------------------------------------

    def _append(self, path: Path, header: str, text: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        fresh = not path.exists()
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            if fresh:
                fh.write(header)
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())

    def add_correction(self, text: str, by: str, about: str = "") -> Correction:
        """Append a table correction. Raises ValueError if it is empty or too long, OSError if it cannot be saved."""
        text = scrub(text, MAX_CORRECTION_CHARS + 1)
        if not text:
            raise ValueError("empty correction")
        if len(text) > MAX_CORRECTION_CHARS:
            raise ValueError("correction too long")
        now = self._clock().astimezone(timezone.utc)
        c = Correction(now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), safe_name(by), text)
        entry = f"- [{c.day} {c.clock} UTC] **{c.by}**: {c.text}\n"
        about = scrub(about, MAX_CONTEXT_CHARS)
        if about:
            entry += f"  - re: {about}\n"
        self._append(self.corrections_path, CORRECTION_HEADER, entry)
        return c

    def already_logged(self, message_id: int) -> bool:
        try:
            return f"<!-- id:{message_id} -->" in self.misreads_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False

    def log_misread(self, *, question: str, answer: str, by: str, how: str, message_id: int) -> bool:
        """Append a misread entry for an answer. Returns False (and writes nothing) if it is already listed."""
        if self.already_logged(message_id):
            return False
        now = self._clock().astimezone(timezone.utc)
        quoted = [ln for ln in answer.strip()[:MAX_QUOTED_CHARS].splitlines()] or [""]
        question = scrub(question, MAX_QUOTED_CHARS) or "(not available)"
        entry = (
            f"## {now.strftime('%Y-%m-%d %H:%M')} UTC · {how} · flagged by {safe_name(by)} <!-- id:{message_id} -->\n\n"
            f"**Question:** {question}\n\n"
            "**Answer:**\n" + "".join(f"> {ln}\n" for ln in quoted) + "\n"
        )
        self._append(self.misreads_path, MISREAD_HEADER, entry)
        return True

    # -- reading ---------------------------------------------------------------------------------------------

    def load(self) -> list[Correction]:
        """All corrections, oldest first. Re-read only when the file changes."""
        try:
            st = self.corrections_path.stat()
        except OSError:
            self._cache = None
            return []
        key = (st.st_mtime_ns, st.st_size)
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        try:
            lines = self.corrections_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        out: list[Correction] = []
        for ln in lines:
            m = _ENTRY.match(ln)
            if not m:
                continue
            year, month, day, clock, by, text = m.groups()
            if not 1 <= int(month) <= 12:
                continue
            out.append(Correction(f"{year}-{month}-{day}", clock, by, text))
        self._cache = (key, out)
        return out

    def select(self, context: str) -> list[Correction]:
        """The corrections to show the model: everything while it fits the budget, otherwise those that share
        a word with the conversation (newest first), cut to the budget and returned oldest first."""
        items = self.load()
        if sum(len(_line(c)) + 1 for c in items) <= MAX_PROMPT_CHARS:
            return items
        wanted = _keywords(context)
        scored = [(len(wanted & _keywords(c.text)), i) for i, c in enumerate(items)]
        picked: list[int] = []
        used = 0
        for score, i in sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], -s[1])):
            cost = len(_line(items[i])) + 1
            if used + cost > MAX_PROMPT_CHARS:
                continue
            picked.append(i)
            used += cost
        return [items[i] for i in sorted(picked)]

    def prompt_block(self, context: str) -> str:
        """Text for the model, or "" when there is nothing relevant. No names: only the date and the text."""
        chosen = self.select(context)
        if not chosen:
            return ""
        return (
            "Table corrections: the group's own fixes to the notes, oldest first. A later correction replaces an "
            "earlier one on the same point. They take precedence over the notes.\n"
            + "\n".join(_line(c) for c in chosen)
        )
