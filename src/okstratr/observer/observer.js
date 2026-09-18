/* okstratr observer panel — polls serve API; not a chat UI */
(function () {
  const API = (window.OKSTRATR_API || "").replace(/\/$/, "") || "";

  function api(path) {
    return fetch(API + path, { headers: { Accept: "application/json" } }).then((r) => {
      if (!r.ok) throw new Error(path + " " + r.status);
      return r.json();
    });
  }

  function el(id) {
    return document.getElementById(id);
  }

  function setText(id, text) {
    const n = el(id);
    if (n) n.textContent = text;
  }

  function renderDesks(payload) {
    const root = el("desks");
    const desks =
      (payload && payload.desks) ||
      (payload && payload.standing) ||
      (payload && payload.items) ||
      [];
    const list = Array.isArray(desks) ? desks : [];
    if (!list.length) {
      root.textContent = "No desks yet.";
      return;
    }
    root.innerHTML = list
      .map((d) => {
        const kind = d.kind || "?";
        const state = d.state || "?";
        const id = d.id || "";
        const obj = (d.objective || d.title || "").slice(0, 80);
        return (
          '<div class="row"><div><strong>' +
          kind +
          "</strong> <span class=\"tag\">" +
          id +
          '</span><div class="tag">' +
          obj +
          '</div></div><span class="tag ' +
          state +
          '">' +
          state +
          "</span></div>"
        );
      })
      .join("");
  }

  function renderDag(payload) {
    const root = el("dag");
    const nodes = Array.isArray(payload && payload.nodes)
      ? payload.nodes
      : Array.isArray(payload && payload.items)
        ? payload.items
        : [];
    if (!nodes.length) {
      root.textContent = "DAG empty.";
      return;
    }
    root.innerHTML = nodes
      .slice(0, 40)
      .map((n) => {
        const id = n.id || "?";
        const title = (n.title || n.objective || "").slice(0, 72);
        const state = n.state || "?";
        return (
          '<div class="row"><div><strong>' +
          id +
          '</strong><div class="tag">' +
          title +
          '</div></div><span class="tag ' +
          state +
          '">' +
          state +
          "</span></div>"
        );
      })
      .join("");
  }

  function renderLifecycle(life) {
    const svc = (life && life.services) || {};
    const serve = svc.serve || {};
    const observer = svc.observer || {};
    setText("chip-board", "board: " + (life.board_duration_chip || "n/a"));
    setText("chip-web", "web: " + (life.web_egress || "n/a"));
    const harn = (life.harnesses || []).join(",") || "n/a";
    setText("chip-harness", "harness: " + harn);
    const up = (life.time && life.time.process_uptime) || "n/a";
    setText("chip-dur", "up: " + up);
    setText(
      "s-serve",
      (serve.up ? "UP" : "DOWN") + " " + (serve.url || "")
    );
    setText(
      "s-observer",
      (observer.up || observer.reachable ? "UP" : "DOWN") + " " + (observer.url || "")
    );
    setText("s-cwd", (life.cwd || "n/a") + " / " + (life.backend || "n/a"));
    const tok = life.tokens || {};
    setText("s-tokens", tok.n_a ? "n/a" : String(tok.tokens || 0));
    const files = life.files || {};
    setText(
      "s-files",
      (files.files || 0) + " files / " + (files.lines || 0) + " lines"
    );
  }

  function refresh() {
    setText("poll-status", "refreshing…");
    Promise.all([
      api("/api/status").catch(() => ({})),
      api("/api/dag").catch(() => ({})),
      api("/api/desk/status").catch(() => ({})),
      api("/api/lifecycle").catch(() => null),
    ])
      .then(([status, dag, deskStatus, life]) => {
        renderDesks(deskStatus.standing ? deskStatus : status.desks ? status : deskStatus);
        if (deskStatus && (deskStatus.standing || deskStatus.desks)) {
          renderDesks(deskStatus);
        } else if (status && status.desk_session) {
          renderDesks(status.desk_session);
        } else {
          renderDesks(deskStatus || status || {});
        }
        renderDag(dag);
        if (life) renderLifecycle(life);
        else {
          setText("s-serve", status && status.ok !== false ? "UP (api/status)" : "…");
          setText("chip-board", "board: " + ((status && status.bb_chip) || "…"));
        }
        setText("poll-status", "updated " + new Date().toLocaleTimeString());
      })
      .catch((e) => {
        setText("poll-status", "error: " + e.message);
      });
  }

  el("btn-refresh").addEventListener("click", refresh);
  el("btn-docs").addEventListener("click", () => {
    window.open("https://github.com/benjsmith/okstratr", "_blank", "noopener");
  });
  refresh();
  setInterval(refresh, 4000);
})();
