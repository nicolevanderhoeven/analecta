from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import privacy_check as pc

NO_DENY: list = []


def kinds(text: str, deny=NO_DENY) -> set[str]:
    return {f.kind for f in pc.scan_text(text, "f.txt", deny)}


# Fake secrets are assembled at runtime so this file itself stays clean.
def fake_discord_token() -> str:
    return "M" + "A" * 23 + "." + "B" * 6 + "." + "C" * 27


def fake_openai_key() -> str:
    return "sk" + "-" + "proj" + "0" * 30


def test_discord_token_and_openai_key_detected():
    assert "discord-bot-token" in kinds(f"x = '{fake_discord_token()}'")
    assert "openai-key" in kinds(f"OPENAI_API_KEY={fake_openai_key()}")


def test_other_tokens_detected():
    assert "github-token" in kinds("t = " + "ghp" + "_" + "a" * 36)
    assert "aws-access-key" in kinds("k = " + "AKIA" + "A" * 16)
    assert "private-key-block" in kinds("-----BEGIN " + "RSA PRIVATE KEY-----")
    assert "credentials-in-url" in kinds("postgres://user:" + "hunter22" + "@db.internal/x")
    assert "secret-assignment" in kinds("password = " + "a1b2c3d4e5f6g7h8i9j0k1l2m3")


def test_snowflakes_detected_but_short_numbers_ok():
    assert "discord-id-or-long-number" in kinds("channel = " + "1" * 18)
    assert not kinds("count = 1234567890123")  # 13 digits: a timestamp, not a snowflake
    assert not kinds("version 3.12.3")


def test_ip_addresses():
    assert "ip-address" in kinds("host 8.8.8.8 here")  # privacy-check: allow
    assert "ip-address" in kinds("ssh root@" + "138.68.1.2")  # privacy-check: allow
    assert "ip-address" in kinds("addr 2606:4700:4700::1111")  # privacy-check: allow
    assert "ip-address" in kinds("addr " + ":".join(["2001", "0db9", "0", "0", "0", "0", "0", "1"]))  # privacy-check: allow
    assert not kinds("docs 192.0.2.10 and 198.51.100.7 and 203.0.113.9 and 127.0.0.1 and 0.0.0.0")
    assert not kinds("doc v6 2001:db8::1 and loopback ::1")
    assert not kinds("time 12:30:45 and ratio 1:2:3 and version 1.2.3.4.5")


def test_emails():
    assert "email-address" in kinds("mail " + "someone" + "@" + "gmail.com")
    assert not kinds("mail someone@example.com or x@y.invalid")


def test_denylist_names_case_insensitive_and_word_bounded(tmp_path: Path):
    f = tmp_path / "deny"
    f.write_text("# comment\nMade Up Name\nSolo\n")
    deny = pc.load_denylist(f)
    assert "denylisted-name" in kinds("we met made   up name today", deny)
    assert "denylisted-name" in kinds("Solo!", deny)
    assert not kinds("Soloist and Resolo", deny)


def test_env_denylist(monkeypatch):
    monkeypatch.setenv("PRIVACY_DENYLIST", "Alpha One;Beta Two")
    deny = pc.load_denylist(None)
    assert "denylisted-name" in kinds("hello beta two", deny)


def test_marker_allows_a_line():
    assert not kinds("host 8.8.8.8  # privacy-check: allow")


def test_findings_never_contain_the_value():
    secret = fake_openai_key()
    out = [str(f) for f in pc.scan_text(f"key={secret}", "a.py", NO_DENY)]
    assert out and all(secret not in line for line in out)


def test_scan_file_binary_and_large(tmp_path: Path):
    b = tmp_path / "b.bin"
    b.write_bytes(b"\0\1\2")
    assert pc.scan_file(b, "b.bin", NO_DENY)[0].kind == "binary-file"


def test_repository_itself_is_clean():
    """The same check CI runs: every tracked and every to-be-added file."""
    root = Path(pc.REPO_ROOT)
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root, capture_output=True, text=True
    ).stdout.split("\n")
    bad = [str(f) for rel in files if rel and (root / rel).is_file()
           for f in pc.scan_file(root / rel, rel, NO_DENY)]
    assert not bad, bad


def test_cli_exit_codes(tmp_path: Path):
    clean = tmp_path / "c.txt"
    clean.write_text("nothing here")
    dirty = tmp_path / "d.txt"
    dirty.write_text("addr 8.8.4.4")  # privacy-check: allow
    script = str(Path(pc.__file__))
    assert subprocess.run([sys.executable, script, str(clean)], capture_output=True).returncode == 0
    r = subprocess.run([sys.executable, script, str(dirty)], capture_output=True, text=True)
    assert r.returncode == 1 and "8.8.4.4" not in r.stderr and "ip-address" in r.stderr  # privacy-check: allow
