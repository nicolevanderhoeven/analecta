#!/usr/bin/env python3
"""Block private details from entering this public repository.

Finds: API keys and tokens (Discord, OpenAI, GitHub, AWS, Slack, private key blocks, credentials in
URLs), Discord IDs (long numeric snowflakes), IPv4 and IPv6 addresses, e-mail addresses, and any
name listed in the local denylist (real character, player and place names).

Usage:
  scripts/privacy_check.py            check files staged in git (the pre-commit hook runs this)
  scripts/privacy_check.py --all      check every file git tracks (CI runs this)
  scripts/privacy_check.py FILE...    check the named files
Options:
  --denylist PATH   names file (default: .privacy-denylist in the repo root, or env PRIVACY_DENYLIST_FILE;
                    env PRIVACY_DENYLIST holds names separated by newlines or ';', for CI secrets)

Allowed on purpose: documentation IP ranges (RFC 5737 / RFC 3849), example.com/.org/.net and
.invalid/.test addresses, loopback and unspecified addresses, and any line carrying the marker
`privacy-check: allow`. Findings never print the matched value, only file, line and kind.
Exit status 1 if anything is found.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKER = "privacy-check: allow"
MAX_BYTES = 2_000_000

TOKEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("discord-bot-token", re.compile(r"\b[MNO][A-Za-z0-9_\-]{23,27}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,40}\b")),
    ("discord-webhook", re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("digitalocean-token", re.compile(r"\bdop_v1_[a-f0-9]{40,}")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("credentials-in-url", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s:@]+@[^/\s]+", re.IGNORECASE)),
    (
        "secret-assignment",
        re.compile(
            r"""(?ix)\b(?:token|secret|password|passwd|api[_-]?key|auth)[A-Za-z_]*\s*[:=]\s*["']?
                (?!replace|your|example|changeme|placeholder|dummy|xxx|<|\$|\{|none|null|true|false|not\b|unset)
                [A-Za-z0-9_\-/+=.]{24,}"""
        ),
    ),
]
SNOWFLAKE = re.compile(r"(?<![\w.])\d{17,20}(?![\w.])")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)")
IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
ALLOWED_EMAIL_SUFFIXES = (".invalid", ".test", ".example", ".localhost")
ALLOWED_EMAIL_NOREPLY = {"noreply@github.com", "users.noreply.github.com"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}"


def _ip_allowed(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return True  # not an address (version number, time, ...)
    if ip.is_loopback or ip.is_unspecified:
        return True
    docs = [
        ipaddress.ip_network(n)
        for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
    ]
    return any(ip.version == n.version and ip in n for n in docs)


def _email_allowed(addr: str) -> bool:
    domain = addr.rsplit("@", 1)[1].lower()
    return (
        domain in ALLOWED_EMAIL_DOMAINS
        or domain.endswith(ALLOWED_EMAIL_SUFFIXES)
        or addr.lower() in ALLOWED_EMAIL_NOREPLY
        or domain.endswith("users.noreply.github.com")
    )


def load_denylist(path: Path | None) -> list[re.Pattern[str]]:
    names: list[str] = []
    candidates = [path] if path else []
    env_file = os.environ.get("PRIVACY_DENYLIST_FILE")
    if env_file:
        candidates.append(Path(env_file))
    candidates.append(REPO_ROOT / ".privacy-denylist")
    for c in candidates:
        if c and c.is_file():
            names += [ln.strip() for ln in c.read_text(encoding="utf-8").splitlines()]
            break
    names += [n.strip() for n in re.split(r"[\n;]", os.environ.get("PRIVACY_DENYLIST", ""))]
    pats = []
    for n in names:
        if n and not n.startswith("#"):
            pats.append(re.compile(r"(?<![\w])" + re.escape(n).replace(r"\ ", r"\s+") + r"(?![\w])", re.IGNORECASE))
    return pats


def scan_text(text: str, path: str, denylist: list[re.Pattern[str]]) -> list[Finding]:
    findings: list[Finding] = []
    for n, line in enumerate(text.split("\n"), 1):
        if MARKER in line:
            continue
        kinds: set[str] = set()
        for kind, rx in TOKEN_PATTERNS:
            if rx.search(line):
                kinds.add(kind)
        if SNOWFLAKE.search(line):
            kinds.add("discord-id-or-long-number")
        for m in EMAIL.finditer(line):
            if not _email_allowed(m.group(0)):
                kinds.add("email-address")
        for m in IPV4.finditer(line):
            if not _ip_allowed(m.group(0)):
                kinds.add("ip-address")
        for m in IPV6.finditer(line):
            if ":" in m.group(0) and not _ip_allowed(m.group(0)):
                kinds.add("ip-address")
        for rx in denylist:
            if rx.search(line):
                kinds.add("denylisted-name")
        findings.extend(Finding(path, n, k) for k in sorted(kinds))
    return findings


def scan_file(path: Path, rel: str, denylist: list[re.Pattern[str]]) -> list[Finding]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if len(data) > MAX_BYTES:
        return [Finding(rel, 0, "file-too-large-to-scan")]
    if b"\0" in data[:4096]:
        return [Finding(rel, 0, "binary-file")]
    return scan_text(data.decode("utf-8", errors="replace"), rel, denylist)


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True).stdout
    return [p for p in out.decode("utf-8", errors="replace").split("\0") if p]


def staged_blobs(denylist: list[re.Pattern[str]]) -> list[Finding]:
    """Scan the staged content (not the working tree) of every added or modified file."""
    findings: list[Finding] = []
    for rel in _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"):
        blob = subprocess.run(["git", "show", f":{rel}"], cwd=REPO_ROOT, capture_output=True)
        if blob.returncode != 0:
            continue
        data = blob.stdout
        if b"\0" in data[:4096]:
            findings.append(Finding(rel, 0, "binary-file"))
        elif len(data) > MAX_BYTES:
            findings.append(Finding(rel, 0, "file-too-large-to-scan"))
        else:
            findings += scan_text(data.decode("utf-8", errors="replace"), rel, denylist)
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true", help="scan every tracked file")
    ap.add_argument("--denylist", type=Path, default=None)
    args = ap.parse_args(argv)
    deny = load_denylist(args.denylist)

    if args.files:
        findings = [f for p in args.files for f in scan_file(Path(p), p, deny)]
    elif args.all:
        findings = [f for rel in _git("ls-files", "-z") for f in scan_file(REPO_ROOT / rel, rel, deny)]
    else:
        findings = staged_blobs(deny)

    if findings:
        print("privacy check FAILED. Remove or replace these before committing (values are not shown):", file=sys.stderr)
        for f in findings:
            print(f"  {f}", file=sys.stderr)
        print("Placeholders such as example.com or 192.0.2.1 are allowed. Add 'privacy-check: allow' to a "
              "line only if it is a harmless fake.", file=sys.stderr)
        return 1
    if not deny:
        print("privacy check passed (note: no local name denylist found, so real names were not checked)")
    else:
        print("privacy check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
