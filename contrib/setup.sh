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
mkdir -p "$HOME/.config/omarchy/extensions" "$HOME/.config/omarchy/plugins/benjsmith.okstratr/contrib"
[ -f "$REPO_ROOT/contrib/okstratr-menu.jsonc" ] && cp "$REPO_ROOT/contrib/okstratr-menu.jsonc" "$HOME/.config/omarchy/extensions/okstratr-menu.jsonc"
[ -f "$REPO_ROOT/contrib/menu.jsonc" ] && cp "$REPO_ROOT/contrib/menu.jsonc" "$HOME/.config/omarchy/plugins/benjsmith.okstratr/contrib/menu.jsonc"
[ -f "$REPO_ROOT/contrib/hypr-bindings.lua" ] && cp "$REPO_ROOT/contrib/hypr-bindings.lua" "$HOME/.config/omarchy/plugins/benjsmith.okstratr/contrib/hypr-bindings.lua"
"$BIN/okstratr" status >/dev/null || true
echo "Okstratr setup complete. Health: http://127.0.0.1:8767/health"
echo "Bar: left-click → panel; right-click → no-op (reserved)."
echo "Optional: merge contrib/hypr-bindings.lua (unbinds then binds Super+Shift+O; sets OMARCHY_PATH) into Hyprland binds."
echo "Note: layout e2e is not done until a VM screenshot shows Herdr RUNNING AGENTS."
