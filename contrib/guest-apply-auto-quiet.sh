#!/usr/bin/env bash
# Run ON Mac Mini (machineId b0814ff0-…), then SSH into Omarchy guest.
# Applies PR tip, quiets stuck desks, restarts serve + shell.
set -euo pipefail
SHA="${1:-origin/fix/desk-auto-quiet-when-finished}"
ssh -o BatchMode=yes -o ConnectTimeout=20 -p 2222 benj@127.0.0.1 bash -s -- "$SHA" <<'GUEST'
set -euo pipefail
SHA="$1"
export PATH="$HOME/.local/bin:$PATH"
cd /home/benj/src/okstratr
git fetch origin
git checkout fix/desk-auto-quiet-when-finished 2>/dev/null || git checkout -B fix/desk-auto-quiet-when-finished
git reset --hard "$SHA"
# Prefer stop→quiet for stuck working desks (preserves DAG)
python3 - <<'PY'
from pathlib import Path
import json, os
os.environ.setdefault("OKSTRATR_STATE_DIR", str(Path.home()/".local/state/okstratr"))
from okstratr import desks
reg = desks.default_registry(force_reload=True)
for d in list(reg.standing()):
    if d.state == "working":
        print("stopping", d.id, d.kind, d.objective)
        print(desks.stop(d.id))
print("standing after:")
for row in desks.default_standing_rows():
    print(row["kind"], row["state"], row.get("objective",""))
PY
# Restart serve
pkill -f 'okstratr serve' 2>/dev/null || true
sleep 1
nohup okstratr serve >/tmp/okstratr-serve.log 2>&1 &
sleep 1
curl -sS http://127.0.0.1:8767/health || true
# QML Panel change → restart shell
omarchy-restart-shell 2>&1 | head -5 || true
# Optional screenshot dir
mkdir -p /mnt/mac/Work/okbay-verify 2>/dev/null || mkdir -p "$HOME/Work/okbay-verify"
echo APPLIED
GUEST
