#!/usr/bin/env bash
# Provision a fresh Ubuntu 24.04 droplet for Analecta. Run as root on the droplet. Safe to re-run.
#
#   scp deploy/setup-droplet.sh root@<DROPLET_ADDRESS>:/root/
#   ssh root@<DROPLET_ADDRESS> ANALECTA_REPO_URL=https://github.com/<owner>/analecta.git bash /root/setup-droplet.sh
#   (before the code is merged: rsync a copy to /root/analecta-src and use ANALECTA_LOCAL_SRC=/root/analecta-src instead)
#
# What it does: a non-root service user, Python venv with the bot, a hardened systemd service,
# a firewall that allows only SSH and Syncthing's sync port, automatic security updates, and
# Syncthing (running as the service user, GUI on localhost only).
# The corrections folder (/srv/analecta/corrections) is separate from the notes: the bot writes table corrections
# and flagged answers there, and configure-syncthing.sh sends it to the Mac (send-only).
# What it does NOT do: put any secret on the box. Create /etc/analecta/analecta.env yourself (see docs/deployment.md).
set -euo pipefail

# Either clone the public repository (ANALECTA_REPO_URL, optional ANALECTA_REPO_REF) or, before the code is
# merged, upload a copy with rsync and point ANALECTA_LOCAL_SRC at it (the bot's own files only, no .env).
REPO_URL="${ANALECTA_REPO_URL:-}"
REPO_REF="${ANALECTA_REPO_REF:-main}"
LOCAL_SRC="${ANALECTA_LOCAL_SRC:-}"
[ -n "$REPO_URL" ] || [ -n "$LOCAL_SRC" ] || { echo "Set ANALECTA_REPO_URL or ANALECTA_LOCAL_SRC." >&2; exit 1; }
SVC_USER=analecta
APP_DIR=/opt/analecta
NOTES_DIR=/srv/analecta/notes
CORRECTIONS_DIR=/srv/analecta/corrections
ENV_DIR=/etc/analecta

[ "$(id -u)" -eq 0 ] || { echo "Run as root." >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "== packages"
apt-get update -y
apt-get install -y --no-install-recommends python3 python3-venv python3-pip git ufw unattended-upgrades \
  ca-certificates curl gnupg apt-transport-https rsync

echo "== automatic security updates"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
systemctl enable --now unattended-upgrades

echo "== service user and folders"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir "/home/$SVC_USER" --shell /usr/sbin/nologin "$SVC_USER"
install -d -o "$SVC_USER" -g "$SVC_USER" -m 750 "$NOTES_DIR"
install -d -o "$SVC_USER" -g "$SVC_USER" -m 750 "$CORRECTIONS_DIR"   # the bot writes here; Syncthing sends it to the Mac
install -d -o root -g "$SVC_USER" -m 750 "$ENV_DIR"

echo "== firewall: SSH and Syncthing sync only"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'ssh'
ufw allow 22000/tcp comment 'syncthing sync'
ufw allow 22000/udp comment 'syncthing sync (quic)'
ufw --force enable
ufw status verbose

echo "== ssh: keys only"
install -d /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/10-analecta.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
sshd -t && systemctl reload ssh

echo "== syncthing (official apt repo)"
if [ ! -f /etc/apt/keyrings/syncthing-archive-keyring.gpg ]; then
  install -d /etc/apt/keyrings
  curl -fsSL https://syncthing.net/release-key.gpg -o /etc/apt/keyrings/syncthing-archive-keyring.gpg
fi
echo "deb [signed-by=/etc/apt/keyrings/syncthing-archive-keyring.gpg] https://apt.syncthing.net/ syncthing stable-v2" \
  > /etc/apt/sources.list.d/syncthing.list
apt-get update -y
apt-get install -y syncthing
systemctl enable --now "syncthing@${SVC_USER}.service"

echo "== the bot"
if [ -n "$LOCAL_SRC" ]; then
  install -d "$APP_DIR"
  rsync -a --delete --exclude .git --exclude .venv --exclude '.env*' "$LOCAL_SRC"/ "$APP_DIR"/
elif [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin "$REPO_REF"
  git -C "$APP_DIR" checkout --quiet FETCH_HEAD
else
  git clone --quiet "$REPO_URL" "$APP_DIR"
  git -C "$APP_DIR" checkout --quiet "$REPO_REF"
fi
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet "$APP_DIR"
install -m 644 "$APP_DIR/deploy/analecta.service" /etc/systemd/system/analecta.service
systemctl daemon-reload
systemctl enable analecta.service

if [ -f "$ENV_DIR/analecta.env" ]; then
  chown root:"$SVC_USER" "$ENV_DIR/analecta.env"; chmod 640 "$ENV_DIR/analecta.env"
  systemctl restart analecta.service
  echo "analecta.service restarted"
else
  echo "No $ENV_DIR/analecta.env yet: the service is enabled but not started. See docs/deployment.md."
fi
echo "Done. Next: deploy/configure-syncthing.sh, then docs/deployment.md."
