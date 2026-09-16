#!/usr/bin/env bash
# Run ON Mac Mini (machineId b0814ff0-a404-4f05-8280-1a140324bbff), then SSH into Omarchy guest.
# Applies fix/desk-robustness-focus-dedupe-stubs tip, restarts serve + shell.
set -euo pipefail
SHA="${1:-origin/fix/desk-robustness-focus-dedupe-stubs}"
ssh -o BatchMode=yes -o ConnectTimeout=20 -p 2222 benj@127.0.0.1 bash -s -- "$SHA" <<'GUEST'
set -euo pipefail
SHA="$1"
export PATH="$HOME/.local/bin:$PATH"
cd /home/benj/src/okstratr
git fetch origin
git checkout fix/desk-robustness-focus-dedupe-stubs 2>/dev/null || git checkout -B fix/desk-robustness-focus-dedupe-stubs
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
echo "SMOKE: focus a quiet standing desk — query + status.objective + dag root should match."
echo "SMOKE: start same kind twice without reset — one live desk; dedupe dismisses twins."
echo "SMOKE: panel close → confirm dialog → quiet_standing then close; cancel stays open."
echo APPLIED
GUEST
