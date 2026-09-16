#!/usr/bin/env bash
# Run ON Mac Mini (machineId b0814ff0-…), then SSH into Omarchy guest.
# Applies fix/start-drive-herdr tip, restarts serve + shell.
set -euo pipefail
SHA="${1:-origin/fix/start-drive-herdr}"
ssh -o BatchMode=yes -o ConnectTimeout=20 -p 2222 benj@127.0.0.1 bash -s -- "$SHA" <<'GUEST'
set -euo pipefail
SHA="$1"
export PATH="$HOME/.local/bin:$PATH"
cd /home/benj/src/okstratr
git fetch origin
git checkout fix/start-drive-herdr 2>/dev/null || git checkout -B fix/start-drive-herdr
git reset --hard "$SHA"
# Editable install if needed
pip install -e . -q 2>/dev/null || true
# Restart serve
pkill -f 'okstratr serve' 2>/dev/null || true
sleep 1
nohup okstratr serve >/tmp/okstratr-serve.log 2>&1 &
sleep 1
curl -sS http://127.0.0.1:8767/health || true
echo
# QML Panel change → restart shell
omarchy-restart-shell 2>&1 | head -5 || true
echo
echo "NOTE: Re-Start the drug-report objective from the query box — Start now sends drive_herdr and runs seats."
echo "Existing Idle desk with that objective: Start again (or Start on auto rail) to drive."
mkdir -p /mnt/mac/Work/okbay-verify 2>/dev/null || mkdir -p "$HOME/Work/okbay-verify"
echo APPLIED
GUEST
