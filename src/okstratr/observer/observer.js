/* okstratr observer panel — DeskRail/Panel-style desks + DAG; not a chat UI */
(function () {
  const API = (window.OKSTRATR_API || "").replace(/\/$/, "") || "";
  const POLL_MS = 3000;
  const KIND_ORDER = ["work", "curate", "code", "deck", "auto"];

  const state = {
    focusDeskId: "",
    selectedKind: "auto",
    desks: [],
    life: null,
    status: null,
    cwd: "",
  };

  function api(path, opts) {
    const o = opts || {};
    return fetch(API + path, {
      method: o.method || "GET",
      headers: {
        Accept: "application/json",
        ...(o.body ? { "Content-Type": "application/json" } : {}),
      },
      body: o.body ? JSON.stringify(o.body) : undefined,
    }).then(function (r) {
      return r.json().catch(function () {
        return { ok: false, error: path + " " + r.status };
      }).then(function (j) {
        if (!r.ok && (!j || j.ok !== false)) {
          throw new Error(path + " " + r.status);
        }
        return j;
      });
    });
  }

  function el(id) {
    return document.getElementById(id);
  }

  function setText(id, text) {
    const n = el(id);
    if (n) n.textContent = text;
  }

  function setMsg(text) {
    const n = el("action-msg");
    if (!n) return;
    if (!text) {
      n.hidden = true;
      n.textContent = "";
      return;
    }
    n.hidden = false;
    n.textContent = text;
  }

  function deskStateLabel(st) {
    const s = String(st || "");
    if (s === "working") return "Running";
    if (s === "quiet") return "Idle";
    if (s === "dismissed") return "dismissed";
    return "";
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function parseDeskQuery(text) {
    const raw = String(text || "").trim();
    const m = raw.match(/^\/(work|curate|code|deck|auto)\b\s*([\s\S]*)$/i);
    if (m) {
      return { kind: m[1].toLowerCase(), objective: String(m[2] || "").trim(), slash: true };
    }
    return { kind: null, objective: raw, slash: false };
  }

  function standingObjectiveForKind(kind) {
    const k = String(kind || "");
    for (let i = 0; i < state.desks.length; i++) {
      const d = state.desks[i];
      if (String(d.kind) === k && d.objective) return String(d.objective);
    }
    return "";
  }

  function normalizeDesks(payload) {
    if (!payload) return [];
    if (Array.isArray(payload.desks)) return payload.desks;
    if (Array.isArray(payload.standing)) return payload.standing;
    if (Array.isArray(payload.items)) return payload.items;
    if (payload.desk_session) {
      const ds = payload.desk_session;
      if (Array.isArray(ds.desks)) return ds.desks;
      if (Array.isArray(ds.standing)) return ds.standing;
    }
    if (payload.desk && Array.isArray(payload.desk.standing)) return payload.desk.standing;
    return [];
  }

  function ensureKindPlaceholders(list) {
    const byKind = {};
    list.forEach(function (d) {
      const k = String(d.kind || "");
      if (k) byKind[k] = d;
    });
    const out = [];
    KIND_ORDER.forEach(function (k) {
      if (byKind[k]) {
        out.push(byKind[k]);
        delete byKind[k];
      } else {
        out.push({ id: "kind:" + k, kind: k, state: "", objective: "", placeholder: true });
      }
    });
    Object.keys(byKind).forEach(function (k) {
      out.push(byKind[k]);
    });
    return out;
  }

  function anyRunning(desks) {
    return desks.some(function (d) {
      return String(d.state) === "working";
    });
  }

  /* —— Desk actions (POST mirrors Panel.qml) —— */
  function afterDeskAction(parsed) {
    if (parsed && parsed.ok === false) {
      setMsg(parsed.herdr_error || parsed.error || "Desk action failed");
      refresh();
      return;
    }
    if (parsed && parsed.herdr_error) {
      setMsg(parsed.message || ("Herdr: " + parsed.herdr_error));
    } else if (parsed && parsed.herdr_job && parsed.herdr_job.state === "running") {
      setMsg(parsed.message || ("Herdr running (job " + parsed.herdr_job.id + ")"));
    } else {
      setMsg((parsed && parsed.message) || "Desk updated");
    }
    refresh();
  }

  function focusDesk(deskId) {
    if (!deskId || String(deskId).indexOf("kind:") === 0) return;
    state.focusDeskId = String(deskId);
    const row = state.desks.find(function (d) {
      return String(d.id) === String(deskId);
    });
    if (row) {
      if (row.kind) state.selectedKind = String(row.kind);
      if (row.objective) el("query-input").value = String(row.objective);
    }
    updateStartLabel();
    renderDesks();
    api("/api/desk/focus", { method: "POST", body: { desk_id: String(deskId) } })
      .then(function (parsed) {
        if (parsed && parsed.ok === false) return;
        if (parsed && parsed.objective) el("query-input").value = String(parsed.objective);
        refresh();
      })
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function startDesk(kind) {
    const parsed = parseDeskQuery(el("query-input").value);
    const k = parsed.slash ? parsed.kind : String(kind || state.selectedKind || "auto");
    state.selectedKind = k;
    let objective = parsed.objective;
    if (!String(objective || "").trim()) objective = standingObjectiveForKind(k);
    setMsg("Starting " + k + " desk…");
    const payload = { kind: k, objective: objective };
    if (String(objective || "").trim()) payload.drive_herdr = true;
    api("/api/desk/start", { method: "POST", body: payload })
      .then(afterDeskAction)
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function stopDesk(deskId) {
    if (!deskId || String(deskId).indexOf("kind:") === 0) return;
    api("/api/desk/stop", { method: "POST", body: { desk_id: String(deskId) } })
      .then(afterDeskAction)
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function dismissDesk(deskId) {
    if (!deskId || String(deskId).indexOf("kind:") === 0) return;
    api("/api/desk/dismiss", { method: "POST", body: { desk_id: String(deskId) } })
      .then(afterDeskAction)
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function deleteDesk(deskId) {
    if (!deskId || String(deskId).indexOf("kind:") === 0) return;
    api("/api/desk/delete", { method: "POST", body: { desk_id: String(deskId) } })
      .then(afterDeskAction)
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function clearBlackboard() {
    setMsg("Clearing blackboard…");
    api("/api/blackboard/clear", { method: "POST", body: {} })
      .then(function (parsed) {
        setMsg((parsed && parsed.message) || "Blackboard cleared");
        refresh();
      })
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function setWeb(mode) {
    api("/api/web", { method: "POST", body: { action: mode } })
      .then(function (parsed) {
        setMsg((parsed && (parsed.message || parsed.label)) || ("Web: " + mode));
        refresh();
      })
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function updateStartLabel() {
    const parsed = parseDeskQuery(el("query-input").value);
    const k = parsed.kind || state.selectedKind || "auto";
    el("btn-start").textContent = "Start " + k;
  }

  /* —— Render desks —— */
  function renderDesks() {
    const root = el("desks");
    const list = ensureKindPlaceholders(state.desks);
    if (!list.length) {
      root.textContent = "No desks yet.";
      return;
    }
    root.innerHTML = list
      .map(function (d) {
        const id = String(d.id || "");
        const kind = String(d.kind || "desk");
        const st = String(d.state || "");
        const isEmpty = !!d.placeholder || (!st && id.indexOf("kind:") === 0);
        const isDismissed = st === "dismissed";
        const isBusy = st === "working";
        const lab = deskStateLabel(st);
        const head = lab ? kind + " · " + lab : kind;
        const obj = d.objective
          ? String(d.objective)
          : isEmpty
            ? "standing"
            : isDismissed
              ? "dismissed"
              : "standing";
        const focused = id && id === String(state.focusDeskId) && id.indexOf("kind:") !== 0;
        const kindSel = kind === state.selectedKind;
        const startLbl = isEmpty || isDismissed ? "Start" : "Continue";
        const dismissOrDelete = isDismissed
          ? '<button type="button" class="btn mini" data-act="delete" data-id="' +
            esc(id) +
            '">Delete</button>'
          : '<button type="button" class="btn mini" data-act="dismiss" data-id="' +
            esc(id) +
            '"' +
            (isEmpty ? " disabled" : "") +
            ">Dismiss</button>";
        return (
          '<div class="desk-row' +
          (focused ? " focused" : "") +
          (kindSel ? " kind-selected" : "") +
          '" data-id="' +
          esc(id) +
          '" data-kind="' +
          esc(kind) +
          '">' +
          '<div class="desk-head"><span class="desk-kind">' +
          esc(head) +
          '</span><span class="desk-obj" title="' +
          esc(obj) +
          '">' +
          esc(obj.slice(0, 48)) +
          "</span></div>" +
          '<div class="desk-actions">' +
          '<button type="button" class="btn mini' +
          (kindSel ? " active" : "") +
          '" data-act="start" data-kind="' +
          esc(kind) +
          '">' +
          startLbl +
          "</button>" +
          '<button type="button" class="btn mini" data-act="stop" data-id="' +
          esc(id) +
          '"' +
          (isBusy ? "" : " disabled") +
          ">Stop</button>" +
          dismissOrDelete +
          "</div></div>"
        );
      })
      .join("");
  }

  /* —— DAG topo by depth from depends_on —— */
  function nodesFromDag(payload) {
    if (!payload) return [];
    if (payload.graph && Array.isArray(payload.graph.nodes)) return payload.graph.nodes;
    if (Array.isArray(payload.nodes) && payload.nodes.length && typeof payload.nodes[0] === "object") {
      return payload.nodes;
    }
    if (Array.isArray(payload.items)) return payload.items;
    return [];
  }

  function edgesFromDag(payload, nodes) {
    if (payload && payload.graph && Array.isArray(payload.graph.edges)) return payload.graph.edges;
    if (payload && Array.isArray(payload.edges)) return payload.edges;
    const edges = [];
    nodes.forEach(function (n) {
      const deps = n.depends_on || n.deps || [];
      deps.forEach(function (d) {
        edges.push({ from: String(d), to: String(n.id) });
      });
    });
    return edges;
  }

  function depthColumns(nodes) {
    const byId = {};
    nodes.forEach(function (n) {
      byId[String(n.id)] = n;
    });
    const depth = {};
    function depList(n) {
      return (n.depends_on || n.deps || []).map(String).filter(function (d) {
        return byId[d];
      });
    }
    function depthOf(id, stack) {
      if (depth[id] != null) return depth[id];
      if (stack[id]) return 0;
      stack[id] = true;
      const n = byId[id];
      const deps = n ? depList(n) : [];
      let d = 0;
      deps.forEach(function (dep) {
        d = Math.max(d, depthOf(dep, stack) + 1);
      });
      // Prefer explicit tier from graph_view when present
      if (n && n.tier != null && deps.length === 0) d = Number(n.tier) || 0;
      else if (n && n.tier != null) d = Math.max(d, Number(n.tier) || 0);
      depth[id] = d;
      delete stack[id];
      return d;
    }
    nodes.forEach(function (n) {
      depthOf(String(n.id), {});
    });
    // If all have tier, prefer tier columns
    const allTier = nodes.every(function (n) {
      return n.tier != null;
    });
    const cols = {};
    nodes.forEach(function (n) {
      const id = String(n.id);
      const col = allTier ? Number(n.tier) || 0 : depth[id] || 0;
      if (!cols[col]) cols[col] = [];
      cols[col].push(n);
    });
    const keys = Object.keys(cols)
      .map(Number)
      .sort(function (a, b) {
        return a - b;
      });
    return keys.map(function (k) {
      return { depth: k, nodes: cols[k] };
    });
  }

  function renderDag(payload) {
    const root = el("dag-graph");
    const nodes = nodesFromDag(payload);
    const edges = edgesFromDag(payload, nodes);
    const focus = state.focusDeskId || "—";
    setText("dag-meta", "focus: " + focus + (nodes.length ? " · " + nodes.length + " nodes" : ""));

    if (!nodes.length) {
      root.innerHTML = '<div class="dag-empty">DAG empty — start a desk to populate Agent Space.</div>';
      return;
    }

    const columns = depthColumns(nodes);
    const colsHtml = columns
      .map(function (col) {
        const cards = col.nodes
          .map(function (n) {
            const id = String(n.id || "?");
            const title = String(n.title || n.objective || n.label || "").slice(0, 64);
            const st = String(n.state || "?");
            const role = String(n.role || n.kind || "");
            const virt = n.virtual ? " virtual" : "";
            return (
              '<div class="dag-node state-' +
              esc(st) +
              " role-" +
              esc(role) +
              virt +
              '" data-node="' +
              esc(id) +
              '">' +
              '<div class="nid">' +
              esc(n.label || id) +
              "</div>" +
              (title && title !== id
                ? '<div class="ntitle">' + esc(title) + "</div>"
                : "") +
              '<span class="nstate">' +
              esc(st) +
              "</span></div>"
            );
          })
          .join("");
        return (
          '<div class="dag-col"><div class="dag-col-label">depth ' +
          col.depth +
          "</div>" +
          cards +
          "</div>"
        );
      })
      .join("");

    let edgeHtml = "";
    if (edges.length) {
      edgeHtml =
        '<div class="dag-edges">edges: ' +
        edges
          .slice(0, 40)
          .map(function (e) {
            return "<code>" + esc(e.from) + "→" + esc(e.to) + "</code>";
          })
          .join(" · ") +
        (edges.length > 40 ? " …" : "") +
        "</div>";
    }

    root.innerHTML = '<div class="dag-cols">' + colsHtml + "</div>" + edgeHtml;
  }

  function renderBlackboard(payload) {
    const root = el("blackboard");
    const items = (payload && (payload.items || payload.entries || payload.head)) || [];
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      root.innerHTML = '<div class="bb-empty">blackboard empty</div>';
      return;
    }
    root.innerHTML = list
      .slice(0, 12)
      .map(function (it) {
        const kind = it.kind || it.role || it.tag || "note";
        const body =
          it.summary || it.text || it.body || it.content || it.message || JSON.stringify(it).slice(0, 120);
        return (
          '<div class="bb-row"><span class="bb-kind">' +
          esc(String(kind)) +
          '</span><span class="bb-body">' +
          esc(String(body).slice(0, 200)) +
          "</span></div>"
        );
      })
      .join("");
  }

  function renderLifecycle(life) {
    if (!life) return;
    state.life = life;
    const svc = life.services || {};
    const serve = svc.serve || {};
    setText("chip-board", "bb: " + (life.board_duration_chip || "n/a"));
    setText("chip-web", "web: " + (life.web_egress || "n/a"));
    const harn = (life.harnesses || []).join(",") || "n/a";
    setText("chip-harness", "harness: " + harn);
    setText("s-board", life.board_duration_chip || "n/a");
    setText("s-web", life.web_egress || "n/a");
    setText("s-harness", harn);
    setText("s-serve", (serve.up ? "UP" : "DOWN") + " " + (serve.url || ""));
    state.cwd = life.cwd || "";
    setText("s-cwd", life.cwd || "n/a");
    setText("s-backend", life.backend || "n/a");
    setText("cwd-chip", "cwd: " + (life.cwd || "n/a"));
    const tok = life.tokens || {};
    setText("s-tokens", tok.n_a ? "n/a" : String(tok.tokens || 0));
    const files = life.files || {};
    setText("s-files", (files.files || 0) + " / " + (files.lines || 0) + " lines");
    const hp = el("harness-path");
    if (hp && life.cwd) {
      hp.textContent = "harnesses.toml · " + life.cwd;
    }
  }

  function renderRunChip() {
    const chip = el("chip-run");
    if (!chip) return;
    if (anyRunning(state.desks)) {
      chip.textContent = "Running";
      chip.className = "chip running";
    } else {
      chip.textContent = "Idle";
      chip.className = "chip idle";
    }
  }

  function refresh() {
    setText("poll-status", "refreshing…");
    const dagPath = state.focusDeskId
      ? "/api/dag?desk_id=" + encodeURIComponent(state.focusDeskId)
      : "/api/dag";
    Promise.all([
      api("/api/status").catch(function () {
        return {};
      }),
      api(dagPath).catch(function () {
        return {};
      }),
      api("/api/desk/status").catch(function () {
        return {};
      }),
      api("/api/desk_session").catch(function () {
        return {};
      }),
      api("/api/lifecycle").catch(function () {
        return null;
      }),
      api("/api/blackboard?n=12").catch(function () {
        return {};
      }),
    ])
      .then(function (parts) {
        const status = parts[0];
        const dag = parts[1];
        const deskStatus = parts[2];
        const deskSession = parts[3];
        const life = parts[4];
        const bb = parts[5];
        state.status = status;

        let desks = normalizeDesks(deskSession);
        if (!desks.length) desks = normalizeDesks(deskStatus);
        if (!desks.length) desks = normalizeDesks(status);
        state.desks = desks;

        if (!state.focusDeskId) {
          const fid =
            (deskSession && deskSession.focus_desk_id) ||
            (status && status.focus_desk_id) ||
            (status && status.desk && status.desk.focus_desk_id) ||
            "";
          if (fid) state.focusDeskId = String(fid);
        }

        renderDesks();
        renderDag(dag);
        renderBlackboard(bb);
        if (life) renderLifecycle(life);
        renderRunChip();
        updateStartLabel();
        setText("poll-status", "updated " + new Date().toLocaleTimeString());
      })
      .catch(function (e) {
        setText("poll-status", "error: " + e.message);
      });
  }

  /* —— Events —— */
  el("desks").addEventListener("click", function (ev) {
    const t = ev.target;
    if (!(t instanceof Element)) return;
    const btn = t.closest("button[data-act]");
    if (btn) {
      ev.stopPropagation();
      const act = btn.getAttribute("data-act");
      const id = btn.getAttribute("data-id") || "";
      const kind = btn.getAttribute("data-kind") || state.selectedKind;
      if (act === "start") {
        state.selectedKind = kind;
        startDesk(kind);
      } else if (act === "stop") stopDesk(id);
      else if (act === "dismiss") dismissDesk(id);
      else if (act === "delete") deleteDesk(id);
      return;
    }
    const row = t.closest(".desk-row");
    if (!row) return;
    const kind = row.getAttribute("data-kind") || "auto";
    const id = row.getAttribute("data-id") || "";
    state.selectedKind = kind;
    updateStartLabel();
    if (id && id.indexOf("kind:") !== 0) focusDesk(id);
    else renderDesks();
  });

  el("btn-refresh").addEventListener("click", refresh);
  el("btn-start").addEventListener("click", function () {
    const parsed = parseDeskQuery(el("query-input").value);
    startDesk(parsed.kind || state.selectedKind || "auto");
  });
  el("query-input").addEventListener("input", updateStartLabel);
  el("query-input").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") {
      const parsed = parseDeskQuery(el("query-input").value);
      startDesk(parsed.kind || state.selectedKind || "auto");
    }
  });
  el("btn-bb-clear").addEventListener("click", clearBlackboard);
  document.querySelectorAll("[data-web]").forEach(function (b) {
    b.addEventListener("click", function () {
      setWeb(b.getAttribute("data-web"));
    });
  });

  refresh();
  setInterval(refresh, POLL_MS);
})();
