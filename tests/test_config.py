from __future__ import annotations

import pytest

from analecta.config import ConfigError, load_env_file, load_settings

BASE = {"DISCORD_TOKEN": "t", "DISCORD_CHANNEL_ID": "5", "OPENAI_API_KEY": "k", "NOTES_DIR": "/tmp/n"}


def test_defaults_and_parsing():
    s = load_settings(BASE)
    assert s.model == "gpt-6-luna" and s.channel_id == 5 and s.guild_id is None
    assert s.aon_enabled and s.daily_limit == 150 and s.max_tool_turns == 8
    s = load_settings({**BASE, "AON_ENABLED": "false", "DISCORD_GUILD_ID": "9", "LLM_MODEL": "other"})
    assert not s.aon_enabled and s.guild_id == 9 and s.model == "other"


def test_placeholders_count_as_missing():
    with pytest.raises(ConfigError) as e:
        load_settings({**BASE, "DISCORD_TOKEN": "replace-with-bot-token"})
    assert "DISCORD_TOKEN" in str(e.value)


def test_unknown_numbers_rejected():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "DISCORD_CHANNEL_ID": "abc"})
    with pytest.raises(ConfigError):
        load_settings({**BASE, "USER_COOLDOWN_SECONDS": "soon"})


def test_env_file_does_not_override(tmp_path, monkeypatch):
    f = tmp_path / "e"
    f.write_text("# c\nFOO_TEST=from-file\nBAR_TEST='quoted'\n")
    monkeypatch.setenv("FOO_TEST", "real")
    monkeypatch.delenv("BAR_TEST", raising=False)
    load_env_file(f)
    import os

    assert os.environ["FOO_TEST"] == "real" and os.environ["BAR_TEST"] == "quoted"
