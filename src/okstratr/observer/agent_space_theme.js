/* Theme colors for agent-space canvas paint (labels + edges).
 * Readable under Switchbay light/dark remaps: host sets --fg/--border/--accent
 * on an ancestor; getComputedStyle(canvas) inherits them. Standalone observer
 * keeps Omarchy dark defaults from observer.css :root.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.OkstratrAgentSpaceTheme = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function colorWithAlpha(color, alpha) {
    var c = String(color || "").trim();
    if (c.charAt(0) === "#" && (c.length === 7 || c.length === 4)) {
      var r, g, b;
      if (c.length === 7) {
        r = parseInt(c.slice(1, 3), 16);
        g = parseInt(c.slice(3, 5), 16);
        b = parseInt(c.slice(5, 7), 16);
      } else {
        r = parseInt(c.charAt(1) + c.charAt(1), 16);
        g = parseInt(c.charAt(2) + c.charAt(2), 16);
        b = parseInt(c.charAt(3) + c.charAt(3), 16);
      }
      return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
    }
    if (c.indexOf("rgba(") === 0) return c;
    if (c.indexOf("rgb(") === 0) {
      return c.replace("rgb(", "rgba(").replace(")", ", " + alpha + ")");
    }
    return "rgba(41, 46, 66, " + alpha + ")";
  }

  function agentSpaceThemeColors(styleLike) {
    function prop(name, fallback) {
      var v = "";
      try {
        v = String(styleLike.getPropertyValue(name) || "").trim();
      } catch (e) {
        v = "";
      }
      return v || fallback;
    }
    var label = prop("--fg", prop("--text", "#c0caf5"));
    var border = prop("--border", "#292e42");
    var accent = prop("--accent", "#7aa2f7");
    return {
      label: label,
      idleEdge: colorWithAlpha(border, 0.95),
      flowingEdge: colorWithAlpha(accent, 0.8),
    };
  }

  return {
    colorWithAlpha: colorWithAlpha,
    agentSpaceThemeColors: agentSpaceThemeColors,
  };
});
