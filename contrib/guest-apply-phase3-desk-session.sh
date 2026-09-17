#!/usr/bin/env bash
# Apply Phase 3 DeskSession + thin Panel harness editor on Omarchy guest.
# Prefer: from Mac Mini `ssh -p 2222 benj@127.0.0.1` then run this, or gh checkout the PR.
set -euo pipefail
REPO="${OKSTRATR_SRC:-$HOME/src/okstratr}"
BRANCH="${OKSTRATR_BRANCH:-feat/phase3-thin-panel-desk-session}"
cd "$REPO"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH" || true
if command -v pipx >/dev/null 2>&1; then
  pipx install -e "$REPO" --force 2>/dev/null || pip install -e "$REPO[dev]"
else
  pip install -e "$REPO[dev]" --user
fi
# Restart user daemon if present
systemctl --user restart okstratr.service 2>/dev/null || true
systemctl --user restart okstratr-serve.service 2>/dev/null || true
okstratr harness list || true
curl -sS http://127.0.0.1:8767/api/harness | head -c 400 || true
echo
curl -sS http://127.0.0.1:8767/api/desk_session | head -c 400 || true
echo
okstratr tui --snapshot 2>/dev/null || true
echo "Phase 3 applied from $BRANCH @ $(git rev-parse --short HEAD)"
echo "Try Config → harness toggles in Panel; or: curl -X POST http://127.0.0.1:8767/api/harness/enable -d '{\"id\":\"claude\"}' -H 'Content-Type: application/json'"
