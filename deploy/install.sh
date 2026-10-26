#!/usr/bin/env bash
set -euo pipefail

if [[ $(id -u) -ne 0 ]]; then
  echo "Run as root on Ubuntu" >&2
  exit 1
fi

cd /opt/ai-hiking
if ! id hiking >/dev/null 2>&1; then
  useradd --system --home /opt/ai-hiking --shell /usr/sbin/nologin hiking
fi
python3 -m venv .venv
.venv/bin/pip install --disable-pip-version-check -r requirements.txt
chown -R hiking:hiking /opt/ai-hiking
cp deploy/ai-hiking.service /etc/systemd/system/ai-hiking.service
cp deploy/nginx.conf /etc/nginx/sites-available/ai-hiking
ln -sfn /etc/nginx/sites-available/ai-hiking /etc/nginx/sites-enabled/ai-hiking
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now ai-hiking
systemctl reload nginx
echo "Deployed AI Hiking Planner"
