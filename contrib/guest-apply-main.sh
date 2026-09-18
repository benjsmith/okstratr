#!/usr/bin/env bash
# Pull main on Omarchy guest, reinstall editable, restart serve + omarchy-restart-shell.
# Prefer from Mac Mini: ssh -p 2222 benj@127.0.0.1 'bash -s' < contrib/guest-apply-main.sh
set -euo pipefail
REPO="${OKSTRATR_SRC:-$HOME/src/okstratr}"
BRANCH="${OKSTRATR_BRANCH:-main}"
cd "$REPO"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
if command -v pipx >/dev/null 2>&1; then
  pipx install -e "$REPO" --force 2>/dev/null || pip install -e "$REPO[dev]" --user
elif [[ -x .venv/bin/pip ]]; then
  .venv/bin/pip install -e '.[dev]' -q || .venv/bin/pip install -e . -q || true
else
  pip install -e "$REPO[dev]" --user
fi
# Restart serve (user service or loose process)
systemctl --user restart okstratr.service 2>/dev/null || true
systemctl --user restart okstratr-serve.service 2>/dev/null || true
# Common manual serve restart if no unit
if pgrep -f 'okstratr serve' >/dev/null 2>&1; then
  pkill -f 'okstratr serve' 2>/dev/null || true
  sleep 0.5
fi
export PYTHONPATH="${PYTHONPATH:-}:$REPO/src"
nohup okstratr serve >/tmp/okstratr-serve.log 2>&1 &
# Refresh Omarchy quickshell panel
if command -v omarchy-restart-shell >/dev/null 2>&1; then
  omarchy-restart-shell || true
elif command -v qs >/dev/null 2>&1; then
  qs -c restart 2>/dev/null || true
fi
echo "guest-apply-main: $BRANCH @ $(git rev-parse --short HEAD)"
curl -sS http://127.0.0.1:8767/api/status | head -c 200 || true
echo
okstratr status 2>/dev/null | head -40 || true
