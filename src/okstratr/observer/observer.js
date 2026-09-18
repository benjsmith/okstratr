/* okstratr observer panel — DeskRail + AGENT SPACE canvas; not a chat UI.
 * No objective/query text input — Herdr / CLI harness is the only text surface.
 * Desk Start POSTs kind (+ standing objective when present), like Omarchy Start
 * when the query box is empty.
 */
(function () {
  const POLL_MS = 2500;
  const KIND_ORDER = ["work", "curate", "code", "deck", "auto"];
  const HOSTED_SHELLS = { switchbay: true, okbay: true };

  function detectApiBase() {
    if (typeof window.OKSTRATR_API === "string" && window.OKSTRATR_API.length) {
      return String(window.OKSTRATR_API).replace(/\/$/, "");
    }
    if (typeof window.OKSTRATR_PUBLIC_BASE === "string" && window.OKSTRATR_PUBLIC_BASE.length) {
      return String(window.OKSTRATR_PUBLIC_BASE).replace(/\/$/, "");
    }
    // Infer proxy prefix from pathname (e.g. /embed/okstratr/observer/)
    const path = String(location.pathname || "");
    const m = path.match(/^(.*?\/embed\/okstratr)(?:\/|$)/);
    if (m) return m[1];
    return "";
  }

  function detectHosted() {
    if (typeof window.OKSTRATR_HOSTED === "string" && window.OKSTRATR_HOSTED) {
      const h = String(window.OKSTRATR_HOSTED).trim().toLowerCase();
      if (HOSTED_SHELLS[h]) return h;
    }
    try {
      const q = new URLSearchParams(location.search || "");
      const h = String(q.get("host") || "").trim().toLowerCase();
      if (HOSTED_SHELLS[h]) return h;
    } catch (e) { /* ignore */ }
    return "";
  }

  const API = detectApiBase();
  const HOSTED = detectHosted();

  const state = {
    focusDeskId: "",
    selectedKind: "auto",
    desks: [],
    life: null,
    status: null,
    cwd: "",
    graph: null,
    layoutNodes: [],
    animT: 0,
    animRaf: 0,
    hosted: HOSTED,
  };

  /** Hide/disable HTML settings chrome when hosted by Switchbay/okbay. */
  function applyHostedMode() {
    if (!HOSTED) return;
    document.body.classList.add("hosted");
    document.body.setAttribute("data-okstratr-host", HOSTED);
    const config = document.querySelector("aside.config");
    if (config) {
      config.hidden = true;
      config.setAttribute("aria-hidden", "true");
      config.querySelectorAll("button, input, select, textarea").forEach(function (n) {
        n.disabled = true;
      });
    }
    document.querySelectorAll("[data-web]").forEach(function (b) {
      b.disabled = true;
    });
    const brand = document.querySelector(".brand");
    if (brand && !brand.dataset.hostedTagged) {
      brand.dataset.hostedTagged = "1";
      brand.textContent = brand.textContent + " · hosted:" + HOSTED;
    }
  }

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
      return r
        .json()
        .catch(function () {
          return { ok: false, error: path + " " + r.status };
        })
        .then(function (j) {
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

  function isActiveState(st) {
    const s = String(st || "").toLowerCase();
    return s === "working" || s === "running" || s === "active" || s === "busy";
  }

  function isReadyState(st) {
    const s = String(st || "").toLowerCase();
    return s === "ready" || s === "pending" || s === "queued";
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
    if (row && row.kind) state.selectedKind = String(row.kind);
    renderDesks();
    api("/api/desk/focus", { method: "POST", body: { desk_id: String(deskId) } })
      .then(function (parsed) {
        if (parsed && parsed.ok === false) return;
        refresh();
      })
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function startDesk(kind) {
    const k = String(kind || state.selectedKind || "auto");
    state.selectedKind = k;
    const objective = standingObjectiveForKind(k);
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

  /* —— AGENT SPACE (Model.dagGraph + Panel.qml canvas) —— */
  function nodeColorForRole(role) {
    const r = String(role || "").toLowerCase();
    if (r === "cos" || r === "root") return "#2dd4bf";
    if (r === "blackboard") return "#a78bfa";
    if (r === "investigator" || r === "researcher") return "#60a5fa";
    if (r === "verifier") return "#fbbf24";
    if (r === "synthesizer") return "#4ade80";
    if (r === "planner" || r.indexOf("curator") === 0) return "#94a3b8";
    return "#7dd3fc";
  }

  function dagSummaryText(status, graph) {
    const d = (status && status.dag) || {};
    const nodes = (graph && graph.nodes) || [];
    let n = nodes.length;
    if (status && status.dag_nodes != null) n = status.dag_nodes;
    else if (d.nodes != null && typeof d.nodes === "number") n = d.nodes;
    const by = d.by_state || {};
    const parts = [];
    Object.keys(by).forEach(function (k) {
      parts.push(k + "=" + by[k]);
    });
    if (!parts.length && nodes.length) {
      const counts = {};
      nodes.forEach(function (nd) {
        const s = String(nd.state || "?");
        counts[s] = (counts[s] || 0) + 1;
      });
      Object.keys(counts).forEach(function (k) {
        parts.push(k + "=" + counts[k]);
      });
    }
    const ready = d.ready || [];
    const readyN = Array.isArray(ready) ? ready.length : 0;
    let line = "nodes=" + n;
    if (parts.length) line += " · " + parts.join(" ");
    line += " · ready=" + readyN;
    if (state.focusDeskId) line += " · focus=" + state.focusDeskId;
    if (d.cycle) line += " · CYCLE: " + d.cycle;
    return line;
  }

  function normalizeEdge(e) {
    if (!e) return null;
    const from = e.from != null ? e.from : e.source;
    const to = e.to != null ? e.to : e.target;
    if (from == null || to == null) return null;
    return { from: String(from), to: String(to) };
  }

  /** Prefer status.dagGraph; else synthesize like Model.dagGraph from /api/dag nodes. */
  function synthesizeDagGraph(status, dagPayload) {
    const idleNodes = [
      {
        id: "cos",
        label: "chief of staff",
        title: "Chief of Staff",
        role: "cos",
        kind: "cos",
        state: "ready",
        tier: 0,
        virtual: true,
      },
      {
        id: "blackboard",
        label: "blackboard",
        title: "Blackboard",
        role: "blackboard",
        kind: "blackboard",
        state: "ready",
        tier: 2,
        virtual: true,
      },
    ];
    const idleEdges = [{ from: "cos", to: "blackboard" }];

    const candidates = [
      status && status.dagGraph,
      status && status.dag && status.dag.graph,
      status && status.graph,
      dagPayload && dagPayload.graph,
      dagPayload && dagPayload.dagGraph,
    ];
    for (let i = 0; i < candidates.length; i++) {
      const g = candidates[i];
      if (g && Array.isArray(g.nodes) && g.nodes.length >= 2) {
        return {
          nodes: g.nodes,
          edges: (g.edges || []).map(normalizeEdge).filter(Boolean),
          idle: !!g.idle,
          label: g.label || "AGENT SPACE",
        };
      }
    }

    const items =
      (dagPayload && (dagPayload.items || (Array.isArray(dagPayload.nodes) ? dagPayload.nodes : null))) ||
      (status && status.dag && status.dag.items) ||
      [];
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      return { nodes: idleNodes, edges: idleEdges, idle: true, label: "AGENT SPACE" };
    }

    const nodes = idleNodes.slice();
    const edges = [];
    const workers = [];
    const terminals = [];

    list.forEach(function (it) {
      if (!it || !it.id || it.id === "root" || it.kind === "root") return;
      const role = String(it.role || it.kind || "worker").toLowerCase();
      if (role === "cos" || role === "blackboard") return;
      let tier = it.tier != null ? Number(it.tier) : 1;
      if (role === "verifier" || role === "synthesizer") tier = 3;
      const id = String(it.id);
      nodes.push({
        id: id,
        label: id.length > 18 ? id.slice(0, 16) + "…" : id,
        title: it.title || it.id,
        role: role,
        kind: it.kind || role,
        state: it.state || "pending",
        tier: tier,
        virtual: false,
      });
      if (tier === 1) workers.push(id);
      else if (tier === 3) terminals.push(id);
      const deps = it.depends_on || it.deps || [];
      if (!deps.length) edges.push({ from: "cos", to: id });
      deps.forEach(function (dep) {
        edges.push({ from: dep === "root" ? "cos" : String(dep), to: id });
      });
    });

    workers.forEach(function (w) {
      edges.push({ from: w, to: "blackboard" });
    });
    if (terminals.length) {
      edges.push({ from: "cos", to: "blackboard" });
      terminals.forEach(function (t) {
        edges.push({ from: "blackboard", to: t });
      });
    } else if (!workers.length) {
      edges.push({ from: "cos", to: "blackboard" });
    }

    return {
      nodes: nodes,
      edges: edges,
      idle: workers.length + terminals.length === 0,
      label: "AGENT SPACE",
    };
  }

  function rebuildLayout() {
    const g = state.graph || { nodes: [], edges: [] };
    const nodes = g.nodes || [];
    const canvas = el("agent-space-canvas");
    const wrap = el("dag-graph");
    if (!canvas || !wrap) return;

    const dpr = window.devicePixelRatio || 1;
    const cssW = Math.max(wrap.clientWidth || 200, 200);
    const cssH = Math.max(wrap.clientHeight || 220, 200);
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
    canvas.style.width = cssW + "px";
    canvas.style.height = cssH + "px";
    const ctx = canvas.getContext("2d");
    if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const padX = 36;
    const padY = 36;
    const w = cssW - padX * 2;
    const h = cssH - padY * 2;
    const tiers = {};
    nodes.forEach(function (n) {
      const t = n.tier !== undefined ? Number(n.tier) : 1;
      if (!tiers[t]) tiers[t] = [];
      tiers[t].push(n);
    });
    const tierKeys = Object.keys(tiers)
      .map(Number)
      .sort(function (a, b) {
        return a - b;
      });
    const tierCount = Math.max(tierKeys.length, 1);
    const out = [];
    tierKeys.forEach(function (key, ti) {
      const row = tiers[key];
      const y = padY + (ti + 0.5) * (h / tierCount);
      row.forEach(function (node, j) {
        const x = row.length === 1 ? padX + w / 2 : padX + (j + 0.5) * (w / row.length);
        out.push({
          id: String(node.id),
          label: node.label || node.id,
          role: node.role || node.kind || "",
          state: node.state || "",
          virtual: !!node.virtual,
          x: x,
          y: y,
          color: nodeColorForRole(node.role || node.kind),
        });
      });
    });
    state.layoutNodes = out;
    paintAgentSpace();
  }

  function edgeFlowing(edge, pos) {
    const a = pos[edge.from];
    const b = pos[edge.to];
    if (!a || !b) return false;
    if (isActiveState(a.state) || isActiveState(b.state)) return true;
    if (isActiveState(a.state) && isReadyState(b.state)) return true;
    return false;
  }

  function paintAgentSpace() {
    const canvas = el("agent-space-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    ctx.clearRect(0, 0, w, h);

    const g = state.graph || { edges: [] };
    const edges = g.edges || [];
    const layout = state.layoutNodes || [];
    const pos = {};
    layout.forEach(function (n) {
      pos[n.id] = n;
    });
    const t = state.animT;

    edges.forEach(function (e) {
      const a = pos[e.from];
      const b = pos[e.to];
      if (!a || !b) return;
      const flowing = edgeFlowing(e, pos);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      if (flowing) {
        ctx.strokeStyle = "rgba(122, 162, 247, 0.8)";
        ctx.lineWidth = 1.6;
        ctx.setLineDash([5, 7]);
        ctx.lineDashOffset = -((t * 48) % 12);
      } else {
        ctx.strokeStyle = "rgba(41, 46, 66, 0.95)";
        ctx.lineWidth = 1;
        ctx.setLineDash([]);
        ctx.lineDashOffset = 0;
      }
      ctx.stroke();
      ctx.setLineDash([]);

      if (flowing) {
        // token-flow particles along active edges
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        for (let p = 0; p < 3; p++) {
          const u = (t * 0.6 + p / 3) % 1;
          ctx.beginPath();
          ctx.arc(a.x + dx * u, a.y + dy * u, 2.5, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(158, 206, 106, 0.95)";
          ctx.fill();
        }
      }
    });

    layout.forEach(function (n) {
      const done = String(n.state).toLowerCase() === "done";
      const active = isActiveState(n.state);
      const isCos = String(n.role) === "cos";

      if (isCos) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, 26, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(45, 212, 191, 0.12)";
        ctx.fill();
        ctx.beginPath();
        ctx.arc(n.x, n.y, 22, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(45, 212, 191, 0.4)";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      ctx.globalAlpha = done ? 0.55 : 1;
      ctx.beginPath();
      ctx.arc(n.x, n.y, 11, 0, Math.PI * 2);
      ctx.fillStyle = n.color;
      ctx.fill();
      ctx.lineWidth = isCos ? 2 : 1;
      ctx.strokeStyle = isCos ? "#99f6e4" : "#1f2937";
      ctx.stroke();

      if (active) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, 14 + Math.sin(t * 6) * 1.5, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(158, 206, 106, 0.7)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      ctx.fillStyle = "#c0caf5";
      ctx.font =
        (isCos || String(n.role) === "blackboard" ? "bold " : "") +
        "10px IBM Plex Sans, system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(String(n.label || n.id), n.x, n.y + 14);
    });
  }

  function ensureAnimLoop() {
    if (state.animRaf) return;
    function tick(ts) {
      state.animT = (ts || 0) / 1000;
      const pos = {};
      (state.layoutNodes || []).forEach(function (n) {
        pos[n.id] = n;
      });
      const g = state.graph || { edges: [] };
      const needs =
        (state.layoutNodes || []).some(function (n) {
          return isActiveState(n.state);
        }) ||
        (g.edges || []).some(function (e) {
          return edgeFlowing(e, pos);
        });
      paintAgentSpace();
      if (needs) state.animRaf = requestAnimationFrame(tick);
      else state.animRaf = 0;
    }
    state.animRaf = requestAnimationFrame(tick);
  }

  function renderAgentSpace(status, dagPayload) {
    const graph = synthesizeDagGraph(status, dagPayload);
    state.graph = graph;
    setText("agent-space-title", graph.label || "AGENT SPACE");
    setText("dag-meta", dagSummaryText(status, graph));
    rebuildLayout();
    ensureAnimLoop();
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
    if (hp && life.cwd) hp.textContent = "harnesses.toml · " + life.cwd;
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
      api("/api/status").catch(function () { return {}; }),
      api(dagPath).catch(function () { return {}; }),
      api("/api/desk/status").catch(function () { return {}; }),
      api("/api/desk_session").catch(function () { return {}; }),
      api("/api/lifecycle").catch(function () { return null; }),
      api("/api/blackboard?n=12").catch(function () { return {}; }),
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
        renderAgentSpace(status, dag);
        renderBlackboard(bb);
        if (life) renderLifecycle(life);
        renderRunChip();
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
    if (id && id.indexOf("kind:") !== 0) focusDesk(id);
    else renderDesks();
  });

  el("btn-refresh").addEventListener("click", refresh);
  el("btn-bb-clear").addEventListener("click", clearBlackboard);
  document.querySelectorAll("[data-web]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (HOSTED) return; // shell owns settings in hosted mode
      setWeb(b.getAttribute("data-web"));
    });
  });
  window.addEventListener("resize", function () {
    rebuildLayout();
  });

  applyHostedMode();
  const health = el("health-link");
  if (health) health.setAttribute("href", API + "/health");

  refresh();
  setInterval(refresh, POLL_MS);
})();
