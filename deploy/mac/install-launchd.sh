#!/usr/bin/env bash
# Install (or remove) the hourly export job on the Mac.
#
#   ANALECTA_SOURCE_DIR="/path/to/campaign-notes-folder" \
#   ANALECTA_EXPORT_DIR="$HOME/Analecta-export" \
#   deploy/mac/install-launchd.sh            # install and run once now
#   deploy/mac/install-launchd.sh --remove   # uninstall
#
# The job runs a private copy of scripts/export_notes.py (plus the small frontmatter module it uses) from
# ~/Library/Application Support/Analecta, so it keeps working if this checkout moves. Re-run to update it.
# It exports every hour. It logs counts only (no note names or text)
# to ~/Library/Logs/analecta-export.log. The generated plist lives in ~/Library/LaunchAgents,
# outside this repository, because it holds your local paths.
set -euo pipefail

LABEL=com.analecta.export
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/analecta-export.log"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "--remove" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL."
  exit 0
fi

: "${ANALECTA_SOURCE_DIR:?Set ANALECTA_SOURCE_DIR to the campaign notes folder}"
DEST="${ANALECTA_EXPORT_DIR:-$HOME/Analecta-export}"
[ -d "$ANALECTA_SOURCE_DIR" ] || { echo "Source folder not found." >&2; exit 1; }
PY="$(command -v python3)"
APP="$HOME/Library/Application Support/Analecta"

echo "Checking the export (dry run)..."
ANALECTA_SOURCE_DIR="$ANALECTA_SOURCE_DIR" ANALECTA_EXPORT_DIR="$DEST" "$PY" "$REPO/scripts/export_notes.py" --dry-run

mkdir -p "$APP/scripts" "$APP/src/analecta"
cp "$REPO/scripts/export_notes.py" "$APP/scripts/export_notes.py"
cp "$REPO/src/analecta/__init__.py" "$REPO/src/analecta/frontmatter.py" "$APP/src/analecta/"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|__PYTHON__|$PY|" \
    -e "s|__SCRIPT__|$APP/scripts/export_notes.py|" \
    -e "s|__SOURCE__|$ANALECTA_SOURCE_DIR|" \
    -e "s|__DEST__|$DEST|" \
    -e "s|__LOG__|$LOG|g" \
    "$HERE/com.analecta.export.plist.template" > "$PLIST"
plutil -lint "$PLIST" >/dev/null

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl kickstart "$DOMAIN/$LABEL"
echo "Installed $LABEL (hourly). Log: $LOG"
