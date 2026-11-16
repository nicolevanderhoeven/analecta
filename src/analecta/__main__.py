"""Entry point: `python -m analecta` runs the bot; `python -m analecta pinned` prints the pinned note."""
from __future__ import annotations

import logging
import os
import sys
from functools import partial

from .config import ConfigError, load_env_file, load_settings


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["pinned"]:
        from .clearances import pinned_note

        load_env_file(os.environ.get("ANALECTA_ENV_FILE", ".env"))
        print(pinned_note(os.environ.get("BOT_OWNER", "")))
        return 0
    load_env_file(os.environ.get("ANALECTA_ENV_FILE", ".env"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration problem: {exc}", file=sys.stderr)
        return 2
    # Imports after settings so a config error is reported before heavy imports.
    from .agent import Agent
    from .aon import AonClient
    from .bot import AnalectaBot
    from .corrections import CorrectionStore
    from .gating import Limiter
    from .llm import make_provider
    from .notes import NotesStore
    from .prompts import build_system_prompt

    notes = NotesStore(settings.notes_dir)
    digest = notes.digest()
    if len(digest) < 100:
        print("Warning: the notes folder looks empty; is Syncthing delivering the export?", file=sys.stderr)
    aon = AonClient(
        enabled=settings.aon_enabled,
        cache_seconds=settings.aon_cache_seconds,
        min_interval=settings.aon_min_interval,
        user_agent=settings.aon_user_agent,
    )
    corrections = CorrectionStore(settings.corrections_dir)
    try:
        settings.corrections_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        print(f"Warning: cannot create the corrections folder {settings.corrections_dir}; "
              "saving corrections and flags will fail until it exists and is writable.", file=sys.stderr)
    agent = Agent(make_provider(settings), notes, aon, partial(build_system_prompt, owner=settings.bot_owner), settings.max_tool_turns,
                  corrections=corrections)
    bot = AnalectaBot(
        agent=agent,
        corrections=corrections,
        locations=settings.channels,
        limiter=Limiter(settings.user_cooldown, settings.daily_limit),
        owner=settings.bot_owner,
    )
    bot.run(settings.discord_token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
