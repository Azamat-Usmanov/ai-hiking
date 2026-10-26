#!/usr/bin/env bash
# Runs as root only via the deploy user's forced SSH command and restricted sudo.
set -euo pipefail

umask 077
work=$(mktemp -d /tmp/ai-hiking-release.XXXXXXXX)
trap 'rm -rf "$work"' EXIT
cat > "$work/release.tar.gz"
mkdir "$work/staging"
python3 - "$work/release.tar.gz" "$work/staging" <<'PY'
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:gz") as archive:
    archive.extractall(sys.argv[2], filter="data")
PY

test -f "$work/staging/requirements.txt"
test -f "$work/staging/app/main.py"
test -f "$work/staging/data/routes.json"
test -f "$work/staging/.deploy-commit"

rsync -a --delete --chown=hiking:hiking \
  --exclude='.venv/' --exclude='.env' --exclude='.git/' \
  "$work/staging/" /opt/ai-hiking/
runuser -u hiking -- /opt/ai-hiking/.venv/bin/pip install --disable-pip-version-check -r /opt/ai-hiking/requirements.txt
runuser -u hiking -- /opt/ai-hiking/.venv/bin/python -m compileall -q /opt/ai-hiking/app
systemctl restart ai-hiking
systemctl is-active --quiet ai-hiking
echo "Deployed $(cat /opt/ai-hiking/.deploy-commit)"
