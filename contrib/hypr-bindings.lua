-- Okstratr fullscreen desk UI — optional Omarchy Hyprland bind (Super+Shift+O).
-- Summons the plugin FloatingWindow panel (native toplevel, not Overlay layershell).
-- Install: merge into ~/.config/hypr/bindings.lua (loaded after Omarchy defaults).
--
-- Super+Shift+K is owned by okbay full-product (okstratr summon + Herdr + Atlas).
-- This snippet is O-only: Okstratr panel without the Atlas/Herdr bundle.

hl.unbind("SUPER + SHIFT + O")
o.bind("SUPER + SHIFT + O", "Okstratr panel", {
  launch = "env OMARCHY_PATH=/usr/share/omarchy omarchy-shell shell summon benjsmith.okstratr '{\"surface\":\"panel\"}'",
})
