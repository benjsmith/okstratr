#!/usr/bin/env bash
# Apply Phase 1 CLI/TUI harness branch on Omarchy guest (Mac Mini SSH → guest).
# Prefer: from Mac `ssh -p 2222 benj@127.0.0.1` then run this, or gh checkout the PR.
set -euo pipefail
# Post-merge: defaults to main (override with OKSTRATR_BRANCH=…).
REPO="${OKSTRATR_SRC:-$HOME/src/okstratr}"
BRANCH="${OKSTRATR_BRANCH:-${1:-main}}"
cd "$REPO"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH" || true
# Editable install if venv present
if [[ -x .venv/bin/pip ]]; then
  .venv/bin/pip install -e '.[dev]' -q || .venv/bin/pip install -e . -q || true
fi
echo "Applied $BRANCH @ $(git rev-parse --short HEAD)"
echo "Try: okstratr harness list && okstratr tui --snapshot"
