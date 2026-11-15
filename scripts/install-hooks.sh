#!/bin/sh
# Point this clone at the repository's hooks so the privacy check runs on every commit.
set -e
root="$(git rev-parse --show-toplevel)"
chmod +x "$root/.githooks/pre-commit"
git -C "$root" config core.hooksPath .githooks
echo "Pre-commit privacy check installed (core.hooksPath=.githooks)."
echo "Optional: copy .privacy-denylist.example to .privacy-denylist and list real names; it stays untracked."
