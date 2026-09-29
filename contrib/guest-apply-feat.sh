#!/usr/bin/env bash
# Live-sync Okstratr PR branch onto Omarchy guest + plugin tree.
# From Mac Mini: ssh omarchy 'bash -s' < contrib/guest-apply-feat.sh
# Or: OKSTRATR_BRANCH=feat/skill-shell-rationalization bash contrib/guest-apply-feat.sh
set -euo pipefail
BRANCH="${OKSTRATR_BRANCH:-feat/skill-shell-rationalization}"
# Prefer ~/Dev/okstratr (Mac Mini / guest convention); fall back to ~/src/okstratr.
if [[ -d "${HOME}/Dev/okstratr/.git" ]]; then
  REPO="${OKSTRATR_SRC:-$HOME/Dev/okstratr}"
elif [[ -d "${HOME}/src/okstratr/.git" ]]; then
  REPO="${OKSTRATR_SRC:-$HOME/src/okstratr}"
else
  REPO="${OKSTRATR_SRC:-$HOME/Dev/okstratr}"
  mkdir -p "$(dirname "$REPO")"
  if [[ ! -d "$REPO/.git" ]]; then
    git clone https://github.com/benjsmith/okstratr.git "$REPO"
  fi
fi
cd "$REPO"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
echo "REPO_HEAD=$(git rev-parse HEAD)"
git log -1 --oneline

# Editable install (observer HTML/JS come from package)
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
if command -v pipx >/dev/null 2>&1; then
  pipx install -e "$REPO" --force 2>/dev/null || pip install -e "$REPO[dev]" --user || true
elif [[ -x .venv/bin/pip ]]; then
  .venv/bin/pip install -e '.[dev]' -q || .venv/bin/pip install -e . -q || true
else
  pip install -e "$REPO[dev]" --user 2>/dev/null || pip install -e "$REPO" --user || true
fi

# Plugin QML twin (Panel + DeskRail + ConfigHarnessEditor + Model.js)
bash "$REPO/contrib/setup.sh"

PLUGIN="$HOME/.config/omarchy/plugins/benjsmith.okstratr"
echo "PLUGIN=$PLUGIN"
ls -la "$PLUGIN"/*.qml "$PLUGIN"/Model.js 2>/dev/null || true
# Confirm no free-text queryInput remains in live Panel
if rg -n "id: queryInput|Desk objective" "$PLUGIN/Panel.qml" >/dev/null 2>&1; then
  echo "WARN: queryInput still present in plugin Panel.qml" >&2
else
  echo "OK: no queryInput / Desk objective bar in plugin Panel.qml"
fi
rg -n "workspacePicker|loadConversation|blackboardGroupsForDesk|Flickable" "$PLUGIN/Panel.qml" | head -20 || true

# Restart serve
systemctl --user restart okstratr.service 2>/dev/null || true
systemctl --user restart okstratr-serve.service 2>/dev/null || true
if pgrep -f "okstratr serve" >/dev/null 2>&1; then
  pkill -f "okstratr serve" 2>/dev/null || true
  sleep 0.5
fi
export PYTHONPATH="${PYTHONPATH:-}:$REPO/src"
nohup okstratr serve >/tmp/okstratr-serve.log 2>&1 &
sleep 1

if command -v omarchy-restart-shell >/dev/null 2>&1; then
  omarchy-restart-shell || true
elif command -v qs >/dev/null 2>&1; then
  qs -c restart 2>/dev/null || true
fi

echo "guest-apply-feat: $BRANCH @ $(git rev-parse --short HEAD)"
curl -sS http://127.0.0.1:8767/health 2>/dev/null || true
echo
# Observer markers (desk UX)
curl -fsS http://127.0.0.1:8767/observer/ 2>/dev/null | rg -n "workspace-switcher|conversation-panel|edit-objective|No chat/objective" | head -20 || true
curl -fsS http://127.0.0.1:8767/observer/observer.js 2>/dev/null | rg -n "renderWorkspaceSwitcher|renderConversation|blackboardGroupsForDesk|standingObjectiveForKind" | head -20 || true
echo APPLIED
