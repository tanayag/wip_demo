#!/usr/bin/env bash
# Fresh Ubuntu EC2 box -> running Refund Bot behind HTTPS.
# Usage: sudo bash deploy/setup_ec2.sh refund.example.com
set -euo pipefail
HOST="${1:?hostname}"
DIR=/home/ubuntu/wip_demo

apt-get update -y
apt-get install -y python3-venv python3-pip debian-keyring debian-archive-keyring apt-transport-https curl
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y && apt-get install -y caddy
fi

sudo -u ubuntu bash -c "cd $DIR && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt"
test -f "$DIR/.env" || { echo "create $DIR/.env first (see .env.example)"; exit 1; }

install -m 644 "$DIR/deploy/refund-bot.service" /etc/systemd/system/refund-bot.service
systemctl daemon-reload
systemctl enable --now refund-bot

sed "s/refund.example.com/$HOST/" "$DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy
echo "done: https://$HOST"
