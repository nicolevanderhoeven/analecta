#!/usr/bin/env bash
# Configure the droplet's Syncthing: one receive-only folder with simple versioning, no discovery,
# no relays, no NAT traversal (the Mac connects to the droplet; the droplet never announces itself).
# Run as root on the droplet, after setup-droplet.sh. Safe to re-run.
#
#   MAC_DEVICE_ID=<id shown in the Mac's Syncthing> bash configure-syncthing.sh
#
# Syncthing's device ID is a public identifier, not a secret, but keep it out of this repository anyway.
set -euo pipefail

SVC_USER="${SVC_USER:-analecta}"
ST_HOME="${ST_HOME:-/home/$SVC_USER/.local/state/syncthing}"
FOLDER_ID="${FOLDER_ID:-analecta-notes}"
FOLDER_PATH="${FOLDER_PATH:-/srv/analecta/notes}"
KEEP_VERSIONS="${KEEP_VERSIONS:-5}"
MAC_DEVICE_ID="${MAC_DEVICE_ID:-}"
RUN_AS=()
if [ "$(id -u)" -eq 0 ]; then RUN_AS=(sudo -u "$SVC_USER"); fi
st() { "${RUN_AS[@]+"${RUN_AS[@]}"}" syncthing cli --home "$ST_HOME" "$@"; }

[ -n "$MAC_DEVICE_ID" ] || { echo "Set MAC_DEVICE_ID to the Mac's Syncthing device ID." >&2; exit 1; }

echo "== options: no discovery, no relays, no NAT, no usage reports (the GUI stays on localhost, its default)"
st config options global-ann-enabled set false
st config options local-ann-enabled set false
st config options relays-enabled set false
st config options natenabled set false
st config options uraccepted set -- -1

echo "== the Mac as a device (it dials in; this side never dials out)"
if ! st config devices list | grep -qx "$MAC_DEVICE_ID"; then
  st config devices add --device-id "$MAC_DEVICE_ID" --name analecta-mac --addresses dynamic
fi

echo "== the receive-only folder"
if ! st config folders list | grep -qx "$FOLDER_ID"; then
  st config folders add --id "$FOLDER_ID" --label "$FOLDER_ID" --path "$FOLDER_PATH" --type receiveonly
fi
st config folders "$FOLDER_ID" type set receiveonly
st config folders "$FOLDER_ID" versioning type set simple
st config folders "$FOLDER_ID" versioning params set keep "$KEEP_VERSIONS"
st config folders "$FOLDER_ID" versioning params set cleanoutDays 0
if ! st config folders "$FOLDER_ID" devices list | grep -qx "$MAC_DEVICE_ID"; then
  st config folders "$FOLDER_ID" devices add --device-id "$MAC_DEVICE_ID"
fi

echo "== the default folder is not wanted"
st config folders list | grep -qx default && st config folders default delete || true

echo "== summary"
st config folders "$FOLDER_ID" dump-json | python3 -c \
  'import sys,json; d=json.load(sys.stdin); print("type:", d["type"], "| versioning:", d["versioning"]["type"], d["versioning"]["params"])'
echo "This droplet's device ID (give it to the Mac's Syncthing):"
st show system | python3 -c 'import sys,json; print(json.load(sys.stdin)["myID"])'
