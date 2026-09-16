#!/usr/bin/env bash
# Run ON Mac Mini (machineId b0814ff0-…), then SSH into Omarchy guest.
# Applies fix/herdr-pane-seat-and-objective-rerun tip, restarts serve + shell.
set -euo pipefail
SHA="${1:-origin/fix/herdr-pane-seat-and-objective-rerun}"
ssh -o BatchMode=yes -o ConnectTimeout=20 -p 2222 benj@127.0.0.1 bash -s -- "$SHA" <<'GUEST'
set -euo pipefail
SHA="$1"
export PATH="$HOME/.local/bin:$PATH"
cd /home/benj/src/okstratr
git fetch origin
git checkout fix/herdr-pane-seat-and-objective-rerun 2>/dev/null || git checkout -B fix/herdr-pane-seat-and-objective-rerun
git reset --hard "$SHA"
pip install -e . -q 2>/dev/null || true
pkill -f 'okstratr serve' 2>/dev/null || true
sleep 1
nohup okstratr serve >/tmp/okstratr-serve.log 2>&1 &
sleep 1
curl -sS http://127.0.0.1:8767/health || true
echo
omarchy-restart-shell 2>&1 | head -5 || true
echo
echo "SMOKE: focus a Herdr shell pane, then Continue/Start a desk with objective."
echo "Expect: pane split → agent start --pane → activity; Stop then Start reuses objective."
echo "Dry-run: OKSTRATR_HERDR_DRY_RUN=1 okstratr herdr run-ready --limit 1"
mkdir -p /mnt/mac/Work/okbay-verify 2>/dev/null || mkdir -p "$HOME/Work/okbay-verify"
echo APPLIED
GUEST
