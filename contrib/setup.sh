#!/usr/bin/env bash
# Visible installer. omarchy plugin add never runs this.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${OKSTRATR_PREFIX:-$HOME/.local}"
BIN="$PREFIX/bin"
mkdir -p "$BIN" "$HOME/.local/state/okstratr" "$HOME/.config/okstratr"
cat > "$BIN/okstratr" <<WRAP
#!/usr/bin/env bash
export PYTHONPATH="$REPO_ROOT/src:\${PYTHONPATH:-}"
exec python3 -m okstratr "\$@"
WRAP
chmod +x "$BIN/okstratr"
mkdir -p "$HOME/.config/omarchy/plugins/benjsmith.okstratr"
for f in manifest.json BarWidget.qml Panel.qml Service.qml Model.js LICENSE README.md; do
  [ -f "$REPO_ROOT/$f" ] && cp "$REPO_ROOT/$f" "$HOME/.config/omarchy/plugins/benjsmith.okstratr/$f"
done
"$BIN/okstratr" status >/dev/null || true
echo "Okstratr setup complete. Health: http://127.0.0.1:8767/health"
echo "Optional: merge contrib/hypr-bindings.lua (Super+Shift+O) into Hyprland binds."
echo "Note: layout e2e is not done until a VM screenshot shows Herdr RUNNING AGENTS."
