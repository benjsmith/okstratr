#!/usr/bin/env bash
# Apply Phase 4 DeskSession SSOT (HTTP primary; status.json compat mirror) on Omarchy guest.
# Prefer: from Mac Mini `ssh -p 2222 benj@127.0.0.1` then run this, or gh checkout the PR.
set -euo pipefail
# Post-merge: defaults to main (override with OKSTRATR_BRANCH=…).
REPO="${OKSTRATR_SRC:-$HOME/src/okstratr}"
BRANCH="${OKSTRATR_BRANCH:-main}"
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
echo "--- /api/status status_channel ---"
curl -sS http://127.0.0.1:8767/api/status | python3 -c 'import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get("status_channel"), indent=2)); print("desk_session.schema=", (d.get("desk_session") or {}).get("schema"))' || true
echo
curl -sS http://127.0.0.1:8767/api/desk_session | head -c 400 || true
echo
okstratr tui --snapshot 2>/dev/null || true
echo "Phase 4 applied from $BRANCH @ $(git rev-parse --short HEAD)"
echo "Clients: prefer GET /api/status (DeskSession). status.json is compat mirror only."
echo "Panel Config → harness model field → POST /api/harness/set"
