#!/usr/bin/env bash
# Visible installer. omarchy plugin add never runs this.
#
# Puts `okstratr` on ~/.local/bin so hosts with a stripped PATH (e.g. Switchbay
# LaunchAgent: /usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin) can spawn
# `okstratr serve`. Prefer `uv tool install -e` so the shim uses a Python that
# satisfies requires-python (>=3.11); macOS /usr/bin/python3 is often 3.9 and
# will fail import (Switchbay then logs "No module named okstratr" / exit 1
# when it falls back to its own venv `python -m okstratr`).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${OKSTRATR_PREFIX:-$HOME/.local}"
BIN="$PREFIX/bin"
mkdir -p "$BIN" "$HOME/.local/state/okstratr" "$HOME/.config/okstratr"

install_cli() {
  if command -v uv >/dev/null 2>&1; then
    # Editable tool env → ~/.local/bin/okstratr (uv manages the interpreter).
    (cd "$REPO_ROOT" && uv tool install -e . --force)
    return 0
  fi
  # Prefer an in-repo venv if present (Dev/Work dual-checkout).
  if [ -x "$REPO_ROOT/.venv/bin/okstratr" ]; then
    ln -sfn "$REPO_ROOT/.venv/bin/okstratr" "$BIN/okstratr"
    return 0
  fi
  # Last resort: PYTHONPATH wrapper. Prefer python3.12/3.11 over system 3.9.
  local py=""
  for c in python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      ver="$("$c" -c 'import sys; print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)"
      case "$ver" in
        3.1[1-9]|3.[2-9]*) py="$c"; break ;;
      esac
    fi
  done
  if [ -z "$py" ]; then
    echo "error: need Python >=3.11 or uv to install okstratr CLI" >&2
    return 1
  fi
  cat > "$BIN/okstratr" <<WRAP
#!/usr/bin/env bash
export PYTHONPATH="$REPO_ROOT/src:\${PYTHONPATH:-}"
exec $(command -v "$py") -m okstratr "\$@"
WRAP
  chmod +x "$BIN/okstratr"
}

install_cli

# In-harness skill (/okstratr) — same dirs as okbay-ask / okbay-desk
if [ -f "$REPO_ROOT/skills/okstratr/SKILL.md" ]; then
  for dest in "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.pi/agent/skills" "$HOME/.gemini/config/skills"; do
    mkdir -p "$dest"
    ln -sfn "$REPO_ROOT/skills/okstratr" "$dest/okstratr"
  done
fi
mkdir -p "$HOME/.config/omarchy/plugins/benjsmith.okstratr"
for f in manifest.json BarWidget.qml Panel.qml Service.qml Model.js DeskRail.qml ConfigHarnessEditor.qml LICENSE README.md; do
  [ -f "$REPO_ROOT/$f" ] && cp "$REPO_ROOT/$f" "$HOME/.config/omarchy/plugins/benjsmith.okstratr/$f"
done
mkdir -p "$HOME/.config/omarchy/extensions" "$HOME/.config/omarchy/plugins/benjsmith.okstratr/contrib"
[ -f "$REPO_ROOT/contrib/okstratr-menu.jsonc" ] && cp "$REPO_ROOT/contrib/okstratr-menu.jsonc" "$HOME/.config/omarchy/extensions/okstratr-menu.jsonc"
[ -f "$REPO_ROOT/contrib/menu.jsonc" ] && cp "$REPO_ROOT/contrib/menu.jsonc" "$HOME/.config/omarchy/plugins/benjsmith.okstratr/contrib/menu.jsonc"
[ -f "$REPO_ROOT/contrib/hypr-bindings.lua" ] && cp "$REPO_ROOT/contrib/hypr-bindings.lua" "$HOME/.config/omarchy/plugins/benjsmith.okstratr/contrib/hypr-bindings.lua"
"$BIN/okstratr" status >/dev/null || true
echo "Okstratr setup complete. CLI: $BIN/okstratr → $($BIN/okstratr -h >/dev/null 2>&1 && echo ok || echo check)"
echo "Health: http://127.0.0.1:8767/health (Switchbay Agents needs this on PATH via ~/.local/bin)"
echo "Skill: ~/.agents/skills/okstratr → $REPO_ROOT/skills/okstratr (slash /okstratr in Grok/Herdr)"
echo "Bar: left-click → panel; right-click → no-op (reserved)."
echo "Optional: merge contrib/hypr-bindings.lua (unbinds then binds Super+Shift+O; sets OMARCHY_PATH) into Hyprland binds."
echo "Note: layout e2e is not done until a VM screenshot shows Herdr RUNNING AGENTS."
