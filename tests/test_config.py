from __future__ import annotations

import pytest

from analecta.config import ConfigError, load_env_file, load_settings

BASE = {"DISCORD_TOKEN": "t", "DISCORD_GUILD_ID": "9", "DISCORD_CHANNEL_ID": "5", "OPENAI_API_KEY": "k", "NOTES_DIR": "/tmp/n"}


def test_defaults_and_parsing():
    s = load_settings(BASE)
    assert s.model == "gpt-6-luna" and s.channels == ((9, 5),)
    assert s.aon_enabled and s.daily_limit == 150 and s.max_tool_turns == 8
    s = load_settings({**BASE, "AON_ENABLED": "false", "LLM_MODEL": "other"})
    assert not s.aon_enabled and s.channels == ((9, 5),) and s.model == "other"


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


LIST = {k: v for k, v in BASE.items() if k not in {"DISCORD_CHANNEL_ID", "DISCORD_GUILD_ID"}}


def test_channel_list():
    s = load_settings({**LIST, "DISCORD_CHANNELS": "1:10, 2:20,"})
    assert s.channels == ((1, 10), (2, 20))


def test_single_pair_still_works_alongside_list():
    s = load_settings({**LIST, "DISCORD_CHANNELS": "1:10", "DISCORD_CHANNEL_ID": "20", "DISCORD_GUILD_ID": "2"})
    assert s.channels == ((1, 10), (2, 20))
    s = load_settings({**LIST, "DISCORD_CHANNELS": "1:10", "DISCORD_CHANNEL_ID": "10", "DISCORD_GUILD_ID": "1"})
    assert s.channels == ((1, 10),)  # same pair given twice is fine


def test_channel_without_server_rejected():
    with pytest.raises(ConfigError) as e:
        load_settings({**LIST, "DISCORD_CHANNEL_ID": "5"})
    assert "DISCORD_GUILD_ID" in str(e.value)
    with pytest.raises(ConfigError):
        load_settings({**LIST, "DISCORD_CHANNELS": "1:10", "DISCORD_CHANNEL_ID": "5"})


@pytest.mark.parametrize("bad", ["10", "1:", ":10", "1:2:3", "a:10", "1:b", "0:10", "1:10,1:10", "1;10"])
def test_malformed_channel_list_rejected(bad):
    with pytest.raises(ConfigError):
        load_settings({**LIST, "DISCORD_CHANNELS": bad})


def test_some_channel_setting_required():
    with pytest.raises(ConfigError) as e:
        load_settings(LIST)
    assert "DISCORD_CHANNELS" in str(e.value)
    with pytest.raises(ConfigError):
        load_settings({**LIST, "DISCORD_CHANNELS": "replace-with-pairs"})
    load_settings(LIST, need_discord=False)


def test_sheet_settings():
    s = load_settings(BASE)
    assert str(s.sheets_dir) == "/var/lib/analecta/sheets" and s.sheets_gm_ids == frozenset()
    s = load_settings({**BASE, "SHEETS_DIR": "/data/sheets", "SHEETS_GM_USER_IDS": "11, 22"})
    assert str(s.sheets_dir) == "/data/sheets" and s.sheets_gm_ids == frozenset({11, 22})
    assert load_settings({**BASE, "SHEETS_GM_USER_IDS": "replace-with-gm-user-id"}).sheets_gm_ids == frozenset()
    with pytest.raises(ConfigError):
        load_settings({**BASE, "SHEETS_GM_USER_IDS": "abc"})
    with pytest.raises(ConfigError):
        load_settings({**BASE, "SHEETS_DIR": "/tmp/n/sheets"})                                  # inside NOTES_DIR
    with pytest.raises(ConfigError):
        load_settings({**BASE, "CORRECTIONS_DIR": "/srv/c", "SHEETS_DIR": "/srv/c"})
