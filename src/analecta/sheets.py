"""Saved character sheets and the Discord-user to character registration (the single source of truth for both).

Plain files under one folder, never in the repository and never inside the notes folder:

    <dir>/<random id>/meta.json          display name, owner Discord id, times
    <dir>/<random id>/versions/<UTC>.json the exported JSON, untouched; the last MAX_VERSIONS are kept
    <dir>/registrations.json              {"<discord user id>": "<sheet id>"}

Nothing here is logged, and nothing here is sent to a language model. Messages in SheetError are safe to show.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import pf2e

MAX_VERSIONS = 10
MAX_SHEET_BYTES = 2 * 1024 * 1024
MAX_NAME_CHARS = 60
_ID = re.compile(r"[0-9a-f]{16}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁦-⁩]")


class SheetError(Exception):
    """Something a member can fix; the message is shown to them as is."""


@dataclass(frozen=True)
class SheetInfo:
    id: str
    name: str
    owner_id: int
    created: str
    updated: str


@dataclass(frozen=True)
class AddResult:
    info: SheetInfo
    created: bool
    versions: int
    registered: bool        # the uploader was registered to this character by the upload
    level: int
    class_name: str


def clean_name(value: object) -> str:
    text = _CONTROL.sub(" ", value) if isinstance(value, str) else ""
    return " ".join(text.split())[:MAX_NAME_CHARS].strip()


def _key(name: str) -> str:
    return clean_name(name).casefold()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, data: bytes, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def parse_sheet(raw: bytes) -> tuple[str, dict]:
    """Check an uploaded file is a Pathbuilder 2e JSON export; return (clean character name, parsed JSON)."""
    if len(raw) > MAX_SHEET_BYTES:
        raise SheetError(f"That file is too big ({MAX_SHEET_BYTES // (1024 * 1024)} MB at most).")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise SheetError("That file is not JSON. Export your character from Pathbuilder 2e as JSON "
                         "and attach that file (see `/sheet help`).") from None
    if not isinstance(data, dict) or data.get("success") is False:
        raise SheetError("That does not look like a Pathbuilder 2e export. See `/sheet help` for how to export one.")
    build = data.get("build")
    if not isinstance(build, dict) or not isinstance(build.get("abilities"), dict) or "level" not in build:
        raise SheetError("That JSON has no character in it (I expected a Pathbuilder 2e export with a `build` section).")
    name = clean_name(build.get("name"))
    if not name:
        raise SheetError("The character in that file has no name. Name it in Pathbuilder and export it again.")
    return name, data


class SheetStore:
    def __init__(self, root: str | os.PathLike[str], gm_ids: Iterable[int] = (), *,
                 max_versions: int = MAX_VERSIONS, clock: Callable[[], float] = time.time):
        self.root = Path(root)
        self.gm_ids = frozenset(gm_ids)
        self.max_versions = max_versions
        self._clock = clock

    # -- reading ---------------------------------------------------------------------------------------------
    def is_gm(self, user_id: int) -> bool:
        return user_id in self.gm_ids

    def list(self) -> list[SheetInfo]:
        out: list[SheetInfo] = []
        try:
            entries = sorted(self.root.iterdir())
        except OSError:
            return out
        for entry in entries:
            if not _ID.fullmatch(entry.name) or not entry.is_dir():
                continue
            try:
                meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
                out.append(SheetInfo(id=entry.name, name=clean_name(meta["name"]), owner_id=int(meta["owner_id"]),
                                     created=str(meta.get("created", "")), updated=str(meta.get("updated", ""))))
            except (OSError, ValueError, KeyError, TypeError):
                continue  # one bad sheet must not break the others
        return sorted(out, key=lambda i: i.name.casefold())

    def find(self, name: str) -> SheetInfo | None:
        wanted = _key(name)
        if not wanted:
            return None
        for info in self.list():
            if info.name.casefold() == wanted:
                return info
        return None

    def get(self, name: str) -> SheetInfo:
        info = self.find(name)
        if info is None:
            raise SheetError(f"I have no saved character called {pf2e.escape(clean_name(name)) or 'that'}. `/character list` shows who I know.")
        return info

    def _versions(self, info: SheetInfo) -> list[Path]:
        return sorted((self.root / info.id / "versions").glob("*.json"))

    def version_count(self, info: SheetInfo) -> int:
        return len(self._versions(info))

    def raw(self, info: SheetInfo) -> bytes:
        versions = self._versions(info)
        if not versions:
            raise SheetError("That character has no saved sheet file. Upload it again with `/sheet add`.")
        return versions[-1].read_bytes()

    def load(self, info: SheetInfo) -> dict:
        """The latest saved export, parsed. Returns the whole JSON object (with its `build`)."""
        try:
            data = json.loads(self.raw(info).decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            raise SheetError("The saved sheet for that character is damaged. Upload it again with `/sheet add`.") from None
        return data if isinstance(data, dict) else {}

    def build(self, info: SheetInfo) -> dict:
        return pf2e.build_of(self.load(info))

    # -- permissions -----------------------------------------------------------------------------------------
    def can_manage(self, actor_id: int, info: SheetInfo) -> bool:
        """The owner and the configured GMs may update, export, delete and register others."""
        return actor_id == info.owner_id or self.is_gm(actor_id)

    def _require_manage(self, actor_id: int, info: SheetInfo, what: str) -> None:
        if not self.can_manage(actor_id, info):
            raise SheetError(f"Only {pf2e.escape(info.name)}'s owner or a GM can {what}.")

    # -- writing sheets --------------------------------------------------------------------------------------
    def add(self, actor_id: int, raw: bytes) -> AddResult:
        name, data = parse_sheet(raw)
        existing = self.find(name)
        if existing is not None and not self.can_manage(actor_id, existing):
            raise SheetError(f"A character called {pf2e.escape(name)} is already saved and belongs to someone else. "
                             "Ask its owner or a GM to update it, or use a different character name.")
        stamp = _now()
        if existing is None:
            info = SheetInfo(id=secrets.token_hex(8), name=name, owner_id=actor_id, created=stamp, updated=stamp)
            created = True
        else:
            info = SheetInfo(id=existing.id, name=name, owner_id=existing.owner_id, created=existing.created, updated=stamp)
            created = False
        folder = self.root / info.id
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o750)
        (folder / "versions").mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o750)
        # The sheet file goes first: a failure leaves the previous meta in place.
        version = datetime.fromtimestamp(self._clock(), timezone.utc).strftime("%Y%m%dT%H%M%S%fZ.json")
        _atomic_write(folder / "versions" / version, raw)
        _atomic_write(folder / "meta.json", json.dumps({"name": info.name, "owner_id": info.owner_id,
                                                         "created": info.created, "updated": info.updated}).encode())
        for old in self._versions(info)[:-self.max_versions]:
            old.unlink(missing_ok=True)
        registered = False
        if created and self.registered_sheet_id(actor_id) is None:
            self._set_registration(actor_id, info.id)
            registered = True
        build = pf2e.build_of(data)
        return AddResult(info=info, created=created, versions=self.version_count(info), registered=registered,
                         level=pf2e.level(build), class_name=clean_name(build.get("class")))

    def delete(self, actor_id: int, name: str) -> SheetInfo:
        info = self.get(name)
        self._require_manage(actor_id, info, "delete it")
        shutil.rmtree(self.root / info.id)
        regs = {u: s for u, s in self._registrations().items() if s != info.id}
        self._write_registrations(regs)
        return info

    # -- registration: Discord user -> character -------------------------------------------------------------
    def _registrations(self) -> dict[int, str]:
        try:
            raw = json.loads((self.root / "registrations.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out: dict[int, str] = {}
        if isinstance(raw, dict):
            for user, sheet_id in raw.items():
                if isinstance(user, str) and user.isdigit() and isinstance(sheet_id, str) and _ID.fullmatch(sheet_id):
                    out[int(user)] = sheet_id
        return out

    def _write_registrations(self, regs: dict[int, str]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.root / "registrations.json",
                      json.dumps({str(u): s for u, s in sorted(regs.items())}).encode())

    def _set_registration(self, user_id: int, sheet_id: str) -> None:
        regs = self._registrations()
        regs[user_id] = sheet_id
        self._write_registrations(regs)

    def registered_sheet_id(self, user_id: int) -> str | None:
        sheet_id = self._registrations().get(user_id)
        return sheet_id if sheet_id and (self.root / sheet_id / "meta.json").is_file() else None

    def character_for(self, user_id: int) -> SheetInfo | None:
        sheet_id = self.registered_sheet_id(user_id)
        return next((i for i in self.list() if i.id == sheet_id), None) if sheet_id else None

    def character_name_for(self, user_id: int) -> str | None:
        """The character name a Discord user is registered to, for the notes link-follower; None if not registered."""
        info = self.character_for(user_id)
        return info.name if info else None

    def holders(self, info: SheetInfo) -> list[int]:
        return sorted(u for u, s in self._registrations().items() if s == info.id)

    def registrations(self) -> list[tuple[int, SheetInfo]]:
        by_id = {i.id: i for i in self.list()}
        return [(u, by_id[s]) for u, s in sorted(self._registrations().items()) if s in by_id]

    def register(self, actor_id: int, name: str, user_id: int | None = None) -> tuple[SheetInfo, int]:
        """Map a Discord user (the caller by default) to a saved character. Returns (character, user id).

        Someone may register themselves to a character nobody holds. Taking a held character from someone else, or
        registering another person, needs the character's owner or a GM.
        """
        target = actor_id if user_id is None else user_id
        info = self.get(name)
        holders = [h for h in self.holders(info) if h != target]
        if target != actor_id or holders:
            if not self.can_manage(actor_id, info):
                if target != actor_id:
                    raise SheetError(f"Only {pf2e.escape(info.name)}'s owner or a GM can register someone else to them.")
                raise SheetError(f"{pf2e.escape(info.name)} is already registered to someone else. Ask the owner or a GM to change it.")
        self._set_registration(target, info.id)
        return info, target

    def unregister(self, actor_id: int, user_id: int | None = None) -> SheetInfo:
        target = actor_id if user_id is None else user_id
        info = self.character_for(target)
        if info is None:
            raise SheetError("That person has no registered character." if target != actor_id
                             else "You have no registered character.")
        if target != actor_id:
            self._require_manage(actor_id, info, "unregister someone else")
        regs = self._registrations()
        regs.pop(target, None)
        self._write_registrations(regs)
        return info
