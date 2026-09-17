#!/usr/bin/env bash
# Apply Phase 2 direct-CLI / TUI / rungs branch on Omarchy guest (Mac Mini SSH → guest).
# Prefer: from Mac `ssh -p 2222 benj@127.0.0.1` then run this, or gh checkout the PR.
set -euo pipefail
# Post-merge: defaults to main (override with OKSTRATR_BRANCH=…).
REPO="${OKSTRATR_SRC:-$HOME/src/okstratr}"
BRANCH="${OKSTRATR_BRANCH:-main}"
cd "$REPO"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH" || true
# Editable install for CLI
if command -v pipx >/dev/null 2>&1; then
  pipx install -e "$REPO" --force 2>/dev/null || pip install -e "$REPO[dev]"
else
  pip install -e "$REPO[dev]" --user
fi
okstratr harness list || true
okstratr model list || true
okstratr tui --snapshot || true
echo "Phase 2 applied from $BRANCH @ $(git rev-parse --short HEAD)"
