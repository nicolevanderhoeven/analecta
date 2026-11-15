"""Settings come from environment variables only (an untracked env file in practice)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    pass


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key, "")
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a whole number") from exc


def _float(env: dict[str, str], key: str, default: float) -> float:
    raw = env.get(key, "")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc


# One allowed place: (server id, channel id).
Location = tuple[int, int]


def _snowflake(text: str, what: str) -> int:
    text = text.strip()
    if not text.isdigit() or int(text) <= 0:
        raise ConfigError(f"{what} must be a positive whole number, got {text!r}")
    return int(text)


def parse_channels(raw: str) -> list[Location]:
    """Parse DISCORD_CHANNELS: comma-separated `server_id:channel_id` pairs."""
    pairs: list[Location] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        guild_text, sep, channel_text = entry.partition(":")
        if not sep or ":" in channel_text:
            raise ConfigError(f"DISCORD_CHANNELS entry {entry!r} must look like server_id:channel_id")
        pairs.append((_snowflake(guild_text, "DISCORD_CHANNELS server id"),
                      _snowflake(channel_text, "DISCORD_CHANNELS channel id")))
    return pairs


@dataclass(frozen=True)
class Settings:
    discord_token: str
    channels: tuple[Location, ...]
    provider: str
    model: str
    api_key: str
    reasoning_effort: str
    max_tool_turns: int
    notes_dir: Path
    aon_enabled: bool
    aon_cache_seconds: int
    aon_min_interval: float
    aon_user_agent: str
    user_cooldown: float
    daily_limit: int


def load_env_file(path: str | os.PathLike[str]) -> None:
    """Load KEY=VALUE lines into os.environ without overriding real environment variables."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def load_settings(env: dict[str, str] | None = None, *, need_discord: bool = True) -> Settings:
    env = dict(os.environ if env is None else env)
    missing: list[str] = []

    def need(key: str) -> str:
        value = env.get(key, "").strip()
        if not value or value.startswith("replace-with"):
            missing.append(key)
        return value

    provider = env.get("LLM_PROVIDER", "openai").strip().lower()
    token = need("DISCORD_TOKEN") if need_discord else env.get("DISCORD_TOKEN", "")
    channels_raw = env.get("DISCORD_CHANNELS", "").strip()
    if channels_raw.startswith("replace-with"):
        channels_raw = ""
    channel = env.get("DISCORD_CHANNEL_ID", "").strip()
    if channel.startswith("replace-with"):
        channel = ""
    guild_raw = env.get("DISCORD_GUILD_ID", "").strip()
    if guild_raw.startswith("replace-with"):
        guild_raw = ""
    if need_discord and not channels_raw and not channel:
        missing.append("DISCORD_CHANNELS (or DISCORD_GUILD_ID and DISCORD_CHANNEL_ID)")
    api_key = need("OPENAI_API_KEY") if provider == "openai" else env.get("LLM_API_KEY", "")
    notes = need("NOTES_DIR")
    if missing:
        raise ConfigError("Missing required settings: " + ", ".join(sorted(set(missing))))

    channels = parse_channels(channels_raw) if need_discord else []
    if channel and need_discord:
        if not guild_raw:
            raise ConfigError("DISCORD_CHANNEL_ID needs DISCORD_GUILD_ID: every channel must be paired with its server")
        pair = (_snowflake(guild_raw, "DISCORD_GUILD_ID"), _snowflake(channel, "DISCORD_CHANNEL_ID"))
        if pair not in channels:
            channels.append(pair)
    if len(set(channels)) != len(channels):
        raise ConfigError("DISCORD_CHANNELS lists the same server and channel more than once")

    return Settings(
        discord_token=token,
        channels=tuple(channels),
        provider=provider,
        model=env.get("LLM_MODEL", "gpt-6-luna").strip(),
        api_key=api_key,
        reasoning_effort=env.get("LLM_REASONING_EFFORT", "low").strip(),
        max_tool_turns=_int(env, "LLM_MAX_TOOL_TURNS", 8),
        notes_dir=Path(notes).expanduser(),
        aon_enabled=_flag(env.get("AON_ENABLED"), True),
        aon_cache_seconds=_int(env, "AON_CACHE_SECONDS", 900),
        aon_min_interval=_float(env, "AON_MIN_INTERVAL_SECONDS", 2.0),
        aon_user_agent=env.get("AON_USER_AGENT", "analecta-discord-bot").strip(),
        user_cooldown=_float(env, "USER_COOLDOWN_SECONDS", 20.0),
        daily_limit=_int(env, "DAILY_QUESTION_LIMIT", 150),
    )
