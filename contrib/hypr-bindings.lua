-- Okstratr fullscreen desk UI — optional Omarchy Hyprland bind (Super+Shift+O).
-- Summons the plugin FloatingWindow panel (native toplevel, not Overlay layershell).
-- Install: merge into ~/.config/hypr/bindings.lua (loaded after Omarchy defaults).

hl.unbind("SUPER + SHIFT + O")
o.bind("SUPER + SHIFT + O", "Okstratr panel", {
  launch = "env OMARCHY_PATH=/usr/share/omarchy omarchy-shell shell summon benjsmith.okstratr '{\"surface\":\"panel\"}'",
})
