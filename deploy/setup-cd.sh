#!/usr/bin/env bash
# One-time root setup: bash deploy/setup-cd.sh /path/to/deploy-key.pub
set -euo pipefail

if [[ $(id -u) -ne 0 || $# -ne 1 ]]; then
  echo "Usage as root: bash deploy/setup-cd.sh /path/to/deploy-key.pub" >&2
  exit 1
fi
key=$(cat "$1")
case "$key" in
  ssh-ed25519\ *) ;;
  *) echo "Expected an Ed25519 public key" >&2; exit 1 ;;
esac

if ! id deploy >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash deploy
fi
install -o deploy -g deploy -m 700 -d /home/deploy/.ssh
printf 'restrict,command="sudo -n /usr/local/sbin/deploy-ai-hiking" %s\n' "$key" > /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
install -o root -g root -m 755 deploy/receive-release.sh /usr/local/sbin/deploy-ai-hiking
printf 'deploy ALL=(root) NOPASSWD: /usr/local/sbin/deploy-ai-hiking\n' > /etc/sudoers.d/ai-hiking-deploy
chmod 440 /etc/sudoers.d/ai-hiking-deploy
visudo -cf /etc/sudoers.d/ai-hiking-deploy
echo "Restricted CD account ready"
