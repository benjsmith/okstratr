-- Okstratr panel — optional Omarchy Hyprland bind (Super+Shift+O).
-- Install: merge into ~/.config/hypr/bindings.lua (loaded after Omarchy defaults).

o.bind("SUPER + SHIFT + O", "Okstratr panel", {
  launch = "omarchy-shell shell summon benjsmith.okstratr '{\"surface\":\"panel\"}'",
})
