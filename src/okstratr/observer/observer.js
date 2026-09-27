/* okstratr observer panel — DeskRail + AGENT SPACE canvas; not a chat UI.
 * No chat/query bar (ADR-003). Standing desk prompt lives below Blackboard.
 * New work: Rail (Switchbay) / Herdr (okbay) / CLI — not the observer chat surface.
 * Desk rail Start/Stop/Dismiss/Delete/Schedule/Edit (+ Quiet all) → /api/desk/* (see desk_rail.py).
 * Start POSTs kind (+ optional desk_id + standing objective), like Omarchy Start
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
  // Initial detection; prefer currentHosted() for every DOM write so soft remounts
  // / late bootstrap / zombie poll ticks cannot reintroduce Herdr on Switchbay.
  const HOSTED = detectHosted();

  /**
   * Live hosted-shell id. Re-reads window + body attr every call so a Switchbay
   * soft remount that refreshes OKSTRATR_HOSTED is honored by existing poll
   * intervals (teardown cannot clear prior IIFE timers from the shell).
   */
  function currentHosted() {
    try {
      if (typeof window.OKSTRATR_HOSTED === "string" && window.OKSTRATR_HOSTED) {
        const h = String(window.OKSTRATR_HOSTED).trim().toLowerCase();
        if (HOSTED_SHELLS[h]) return h;
      }
    } catch (e) { /* ignore */ }
    try {
      const attr =
        (document.body && document.body.getAttribute("data-okstratr-host")) || "";
      const h = String(attr).trim().toLowerCase();
      if (HOSTED_SHELLS[h]) return h;
    } catch (e2) { /* ignore */ }
    if (HOSTED && HOSTED_SHELLS[HOSTED]) return HOSTED;
    return detectHosted();
  }

  function isSwitchbayHost() {
    return currentHosted() === "switchbay";
  }

  function isOkbayHost() {
    const h = currentHosted();
    return h === "okbay" || h === "omarchy";
  }

  const GUIDANCE = {
    switchbay:
      "Start, stop, create, dismiss, and update desks from the Rail. New work requests go through the Rail chat.",
    okbay:
      "Start, stop, create, dismiss, and update desks from the Desk rail / Herdr. New work requests go through Herdr or okbay affordances.",
    bare:
      "Desk lifecycle: okstratr desk start|stop|dismiss|delete (or /okstratr in a harness). New work via CLI / Herdr — not a chat bar here.",
  };

  function guidanceText() {
    if (isSwitchbayHost()) return GUIDANCE.switchbay;
    if (isOkbayHost()) return GUIDANCE.okbay;
    return GUIDANCE.bare;
  }

  function deskPromptHintText() {
    if (isSwitchbayHost()) {
      return "Updates the desk standing instruction. New work still goes through the Rail chat — not this box.";
    }
    if (isOkbayHost()) {
      return "Updates the desk standing instruction. New work still goes through Herdr / okbay — not this box.";
    }
    return "Updates the desk standing instruction. New work still goes through CLI / Herdr — not this box.";
  }

  function updateHostGuidance() {
    const g = el("agents-guidance");
    if (g) g.textContent = guidanceText();
    const hint = el("desk-prompt-hint");
    if (hint) hint.textContent = deskPromptHintText();
  }


  /** CoS empty/status copy — Switchbay must not mention Herdr (okbay/bare may). */
  function cosCopyNoDesk() {
    if (isSwitchbayHost()) {
      return "Select a desk to view the ongoing CoS conversation.";
    }
    return "Select a desk to view ongoing CoS conversation in Herdr.";
  }

  function cosCopyNoTurns() {
    if (isSwitchbayHost()) {
      return "No CoS conversation yet for this desk. Start the desk.";
    }
    return "No CoS conversation yet for this desk. Start the desk or open Herdr.";
  }

  /** Single host-aware empty markup used by every conversation render path. */
  function cosEmptyHtml(kind) {
    const copy = kind === "no-turns" ? cosCopyNoTurns() : cosCopyNoDesk();
    return '<div class="bb-empty">' + copy + "</div>";
  }

  function cosStubHint(hint) {
    const h = String(hint || "");
    if (!isSwitchbayHost()) return h;
    if (!h) return h;
    // Neutralize any Herdr-bearing stub hint from API or cache.
    return (
      "Transcript not found; showing desk objective + CoS blackboard turns."
    );
  }

  function scrubHerdrStatus(msg) {
    if (!isSwitchbayHost() || !msg) return msg;
    return String(msg)
      .replace(/Herdr drive/gi, "Drive")
      .replace(/Herdr job/gi, "Drive job")
      .replace(/Herdr error/gi, "Drive error")
      .replace(/\bHerdr\b/g, "drive");
  }

  /** After any conversation innerHTML write: never leave Herdr in Switchbay DOM. */
  function ensureConversationHostCopy() {
    if (!isSwitchbayHost()) return;
    const root = el("conversation");
    if (!root) return;
    const raw = root.textContent || "";
    if (!/Herdr/i.test(raw)) return;
    // Preserve stub hint paragraph if present; replace only bb-empty / Herdr text.
    const hintEl = root.querySelector(".conv-stub-hint");
    const hintHtml = hintEl
      ? '<p class="conv-stub-hint">' + esc(cosStubHint(hintEl.textContent || "")) + "</p>"
      : "";
    const kind = state.focusDeskId ? "no-turns" : "no-desk";
    // Only rewrite empty / stub surfaces — do not clobber real turns.
    if (root.querySelector(".conv-row")) {
      if (hintEl && /Herdr/i.test(hintEl.textContent || "")) {
        hintEl.textContent = cosStubHint(hintEl.textContent || "");
      }
      return;
    }
    root.innerHTML = hintHtml + cosEmptyHtml(kind);
  }

  // Soft remount (Switchbay ProxiedSkillPanel) re-injects this IIFE. Teardown
  // clears the prior interval, but in-flight Promise callbacks and a buggy
  // "re-query #conversation" zombie check could still write the new DOM with
  // a stale focusDeskId — flipping selection between idle desks every poll.
  let mountAlive = true;
  const FOCUS_STORE_KEY = "okstratr.observer.focusDeskId";

  const state = {
    focusDeskId: "",
    /** Once set (user click, preferred embed desk, or first adopted focus),
     *  poll ticks must not replace focus with another idle/server desk. */
    focusSticky: false,
    /** Preferred desk from embed honored at most once per mount. */
    preferredDeskApplied: false,
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
    /** Phase 1b: desk list filter — all | working | quiet */
    groupFilter: "all",
    /** Optional kind chip filter (empty = all kinds) */
    kindFilter: "",
    workspaces: [],
    hostWorkspaces: [],
    selectedWorkspaceId: "",
    conversation: null,
  };

  function readStoredFocus() {
    try {
      const v = sessionStorage.getItem(FOCUS_STORE_KEY);
      return v && String(v).indexOf("kind:") !== 0 ? String(v) : "";
    } catch (e) {
      return "";
    }
  }

  function writeStoredFocus(id) {
    try {
      if (id) sessionStorage.setItem(FOCUS_STORE_KEY, String(id));
      else sessionStorage.removeItem(FOCUS_STORE_KEY);
    } catch (e) { /* ignore */ }
  }

  /** Switchbay (or other host) may pass a preferred desk once via bootstrap /
   *  query / body attr. Honor once, then stick — never re-promote on poll. */
  function detectPreferredDesk() {
    try {
      if (typeof window.OKSTRATR_FOCUS_DESK === "string" && window.OKSTRATR_FOCUS_DESK) {
        const id = String(window.OKSTRATR_FOCUS_DESK).trim();
        if (id && id.indexOf("kind:") !== 0) return id;
      }
    } catch (e) { /* ignore */ }
    try {
      if (typeof window.OKSTRATR_DESK_ID === "string" && window.OKSTRATR_DESK_ID) {
        const id = String(window.OKSTRATR_DESK_ID).trim();
        if (id && id.indexOf("kind:") !== 0) return id;
      }
    } catch (e2) { /* ignore */ }
    try {
      const q = new URLSearchParams(location.search || "");
      const id = String(q.get("desk") || q.get("focus") || q.get("desk_id") || "").trim();
      if (id && id.indexOf("kind:") !== 0) return id;
    } catch (e3) { /* ignore */ }
    try {
      const attr =
        (document.body && document.body.getAttribute("data-okstratr-desk")) || "";
      const id = String(attr).trim();
      if (id && id.indexOf("kind:") !== 0) return id;
    } catch (e4) { /* ignore */ }
    return "";
  }

  /** True while this IIFE owns the mount; false after teardown / remount.
   *  When called with a captured root arg (even null), never re-query by id —
   *  a soft remount would otherwise hand a zombie the new DOM. */
  function mountIsLive(capturedRoot) {
    if (!mountAlive) return false;
    if (arguments.length >= 1) {
      return !!(capturedRoot && capturedRoot.isConnected);
    }
    const desks = el("desks");
    const conv = el("conversation");
    if (!desks || !conv) return false;
    return desks.isConnected && conv.isConnected;
  }

  function setFocusDesk(deskId, opts) {
    const o = opts || {};
    const id = String(deskId || "");
    if (!id || id.indexOf("kind:") === 0) return false;
    state.focusDeskId = id;
    if (o.sticky !== false) {
      state.focusSticky = true;
      writeStoredFocus(id);
    }
    const row = state.desks.find(function (d) {
      return String(d.id) === id;
    });
    if (row && row.kind) state.selectedKind = String(row.kind);
    return true;
  }

  function clearFocusDesk() {
    state.focusDeskId = "";
    state.focusSticky = false;
    writeStoredFocus("");
  }

  /** Hide/disable HTML settings chrome when hosted by Switchbay/okbay. */
  function applyHostedMode() {
    updateHostGuidance();
    const hostedNow = currentHosted();
    if (!hostedNow) return;
    document.body.classList.add("hosted");
    document.body.setAttribute("data-okstratr-host", hostedNow);
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
      brand.textContent = brand.textContent + " · hosted:" + hostedNow;
    }
    // Herdr seating is okbay/Omarchy-only (docs/HERDR-AND-REGISTRY.md).
    // Switchbay seats via direct harness CLIs — strip the button from embed.
    if (hostedNow === "switchbay") {
      const herdrBtn = el("open-herdr-workspace");
      if (herdrBtn) {
        herdrBtn.hidden = true;
        herdrBtn.setAttribute("aria-hidden", "true");
        herdrBtn.disabled = true;
      }
      const herdrMsg = el("open-herdr-msg");
      if (herdrMsg) {
        herdrMsg.hidden = true;
      }
      // Scrub CoS empty/status copy (HTML default still mentions Herdr for okbay/bare).
      ensureConversationHostCopy();
    }
    updateHostGuidance();
  }

  function api(path, opts) {
    const o = opts || {};
    const headers = {
      Accept: "application/json",
      ...(o.body ? { "Content-Type": "application/json" } : {}),
    };
    // So conversation stub hint (and other host-aware copy) match the embed.
    const hostedNow = currentHosted();
    if (hostedNow) headers["X-Okstratr-Host"] = hostedNow;
    return fetch(API + path, {
      method: o.method || "GET",
      headers: headers,
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

  /** True when the focused (or overall) desk is not actively working. */
  function deskAtRest() {
    const id = String(state.focusDeskId || "");
    if (id && id.indexOf("kind:") !== 0) {
      for (let i = 0; i < state.desks.length; i++) {
        const d = state.desks[i];
        if (String(d.id) === id) {
          return String(d.state || "") !== "working";
        }
      }
    }
    return !anyRunning(state.desks);
  }

  function graphAtRest(graph) {
    if (graph && graph.idle) return true;
    if (graph && graph.at_rest) return true;
    return deskAtRest();
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
      setMsg(
        scrubHerdrStatus(parsed.herdr_error || parsed.error || "Desk action failed")
      );
      refresh();
      return;
    }
    if (parsed && parsed.herdr_error) {
      const err = parsed.herdr_error;
      const fallback =
        isSwitchbayHost() ? String(err) : "Herdr: " + err;
      setMsg(scrubHerdrStatus(parsed.message || fallback));
    } else if (parsed && parsed.herdr_job && parsed.herdr_job.state === "running") {
      const jid = parsed.herdr_job.id;
      const fallback =
        isSwitchbayHost()
          ? "Drive running (job " + jid + ")"
          : "Herdr running (job " + jid + ")";
      setMsg(scrubHerdrStatus(parsed.message || fallback));
    } else {
      setMsg(scrubHerdrStatus((parsed && parsed.message) || "Desk updated"));
    }
    refresh();
  }

  function focusDesk(deskId) {
    if (!setFocusDesk(deskId, { sticky: true })) return;
    renderDesks();
    api("/api/desk/focus", { method: "POST", body: { desk_id: String(deskId) } })
      .then(function (parsed) {
        if (!mountIsLive()) return;
        if (parsed && parsed.ok === false) return;
        refresh();
      })
      .catch(function (e) {
        if (!mountIsLive()) return;
        setMsg(String(e.message || e));
      });
  }

  function startDesk(kind, deskId) {
    const k = String(kind || state.selectedKind || "auto");
    state.selectedKind = k;
    const objective = standingObjectiveForKind(k);
    const id = deskId && String(deskId).indexOf("kind:") !== 0 ? String(deskId) : "";
    setMsg("Starting " + k + " desk…");
    const payload = { kind: k, objective: objective };
    if (id) payload.desk_id = id;
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

  function quietAll() {
    setMsg("Quieting all working desks…");
    api("/api/desk/quiet_standing", { method: "POST", body: {} })
      .then(afterDeskAction)
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  /** Human schedule chip from desk.schedule payload (Switchbay DesksPanel parity). */
  function scheduleLabel(sched) {
    if (!sched || typeof sched !== "object") return "";
    if (sched.describe) return String(sched.describe);
    if (sched.label) return String(sched.label);
    if (sched.description) return String(sched.description);
    if (sched.name) return String(sched.name);
    if (sched.kind === "named" && sched.name) return String(sched.name);
    if (sched.every_seconds) {
      const s = Number(sched.every_seconds);
      if (s >= 86400) return "every " + Math.round(s / 86400) + "d";
      if (s >= 3600) return "every " + Math.round(s / 3600) + "h";
      if (s >= 60) return "every " + Math.round(s / 60) + "m";
      return "every " + Math.round(s) + "s";
    }
    if (sched.raw) return String(sched.raw);
    return "scheduled";
  }

  function scheduleSpecPrefill(sched) {
    if (!sched || typeof sched !== "object") return "";
    if (sched.raw) return String(sched.raw);
    if (sched.name) return String(sched.name);
    if (sched.describe) return String(sched.describe);
    return "";
  }

  function closeModal(which) {
    const m = el(which === "edit" ? "edit-modal" : "schedule-modal");
    if (m) m.hidden = true;
  }

  function openScheduleDialog(deskId, kind, existingSpec) {
    const modal = el("schedule-modal");
    if (!modal) return;
    const title = el("schedule-modal-title");
    if (title) title.textContent = "Schedule " + (kind || "desk") + " desk";
    const realId = deskId && String(deskId).indexOf("kind:") !== 0 ? String(deskId) : "";
    el("schedule-desk-id").value = realId;
    el("schedule-kind").value = String(kind || "auto");
    el("schedule-spec").value = existingSpec || "daily";
    const clearBtn = el("schedule-clear");
    if (clearBtn) clearBtn.disabled = !realId || !existingSpec;
    modal.hidden = false;
    setTimeout(function () {
      const inp = el("schedule-spec");
      if (inp) { inp.focus(); inp.select(); }
    }, 0);
  }

  function saveSchedule() {
    const deskId = (el("schedule-desk-id").value || "").trim();
    const kind = (el("schedule-kind").value || "auto").trim() || "auto";
    const spec = (el("schedule-spec").value || "").trim();
    if (!spec) {
      setMsg("Enter a schedule cadence (daily, 1h30m, …)");
      return;
    }
    function postSchedule(id) {
      setMsg("Saving schedule…");
      api("/api/desk/schedule", {
        method: "POST",
        body: { desk_id: id, spec: spec },
      })
        .then(function (parsed) {
          closeModal("schedule");
          afterDeskAction(parsed);
        })
        .catch(function (e) {
          setMsg(String(e.message || e));
        });
    }
    if (!deskId) {
      setMsg("Starting " + kind + " desk for schedule…");
      const objective = standingObjectiveForKind(kind);
      const payload = { kind: kind, objective: objective };
      if (String(objective || "").trim()) payload.drive_herdr = true;
      api("/api/desk/start", { method: "POST", body: payload })
        .then(function (parsed) {
          if (parsed && parsed.ok === false) {
            afterDeskAction(parsed);
            return;
          }
          let desk = (parsed && parsed.desk) || {};
          if (desk.desk && typeof desk.desk === "object") desk = desk.desk;
          const id = desk.id || desk.desk_id;
          if (!id) {
            setMsg("Desk started but no id for schedule");
            refresh();
            return;
          }
          postSchedule(String(id));
        })
        .catch(function (e) {
          setMsg(String(e.message || e));
        });
      return;
    }
    postSchedule(deskId);
  }

  function clearSchedule() {
    const deskId = (el("schedule-desk-id").value || "").trim();
    if (!deskId) return;
    setMsg("Clearing schedule…");
    api("/api/desk/schedule", {
      method: "POST",
      body: { desk_id: deskId, clear: true },
    })
      .then(function (parsed) {
        closeModal("schedule");
        afterDeskAction(parsed);
      })
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function openEditDialog(deskId, kind, objective) {
    if (!deskId || String(deskId).indexOf("kind:") === 0) return;
    const modal = el("edit-modal");
    if (!modal) return;
    el("edit-desk-id").value = String(deskId);
    el("edit-kind").value = String(kind || "auto");
    el("edit-objective").value = objective || "";
    if (isSwitchbayHost()) {
      try {
        window.dispatchEvent(
          new CustomEvent("sy:rail-set-input", {
            detail: { text: objective || "", focus: true },
          })
        );
      } catch (e) { /* ignore */ }
    }
    modal.hidden = false;
    setTimeout(function () {
      const ta = el("edit-objective");
      if (ta) ta.focus();
    }, 0);
  }

  function saveEdit() {
    const deskId = (el("edit-desk-id").value || "").trim();
    const kind = (el("edit-kind").value || "auto").trim() || "auto";
    const objective = (el("edit-objective").value || "").trim();
    if (!deskId) return;
    if (!objective) {
      setMsg("Objective cannot be empty");
      return;
    }
    setMsg("Updating objective…");
    api("/api/desk/start", {
      method: "POST",
      body: {
        desk_id: deskId,
        kind: kind,
        objective: objective,
        drive_herdr: false,
      },
    })
      .then(function (parsed) {
        closeModal("edit");
        afterDeskAction(parsed);
      })
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function countDesksByKind(list) {
    const map = {};
    (list || []).forEach(function (d) {
      if (d.placeholder) return;
      const k = String(d.kind || "?");
      if (!map[k]) map[k] = { kind: k, n: 0, working: 0 };
      map[k].n += 1;
      if (String(d.state) === "working") map[k].working += 1;
    });
    return Object.keys(map)
      .sort()
      .map(function (k) { return map[k]; });
  }

  function renderKindSummary() {
    const root = el("desk-kind-summary");
    if (!root) return;
    const rows = countDesksByKind(state.desks);
    if (!rows.length) {
      root.innerHTML = "";
      return;
    }
    root.innerHTML = rows
      .map(function (r) {
        const active = state.kindFilter === r.kind ? " active" : "";
        const live = r.working > 0 ? " has-working" : "";
        return (
          '<button type="button" class="kind-chip' +
          active +
          live +
          '" data-kind-filter="' +
          esc(r.kind) +
          '" title="' +
          esc(r.kind) +
          ": " +
          r.n +
          " desk(s), " +
          r.working +
          ' working">' +
          esc(r.kind) +
          '<span class="n">' +
          r.n +
          "</span></button>"
        );
      })
      .join("");
  }

  function renderDeskDashboard(life) {
    const desksInfo = (life && life.desks) || {};
    const working = desksInfo.working != null
      ? desksInfo.working
      : state.desks.filter(function (d) { return String(d.state) === "working"; }).length;
    const quiet = desksInfo.quiet != null
      ? desksInfo.quiet
      : state.desks.filter(function (d) {
          return String(d.state) === "quiet" || String(d.state) === "idle";
        }).length;
    const total = desksInfo.total != null
      ? desksInfo.total
      : state.desks.filter(function (d) { return !d.placeholder; }).length;
    const tok = (life && life.tokens) || {};
    const files = (life && life.files) || {};
    const tokStr = tok.n_a ? "n/a" : String(tok.tokens || 0);
    const fileN = files.files || 0;
    const lineN = files.lines || 0;

    setText("dash-working", String(working));
    setText("dash-quiet", String(quiet));
    setText("dash-total", String(total));
    setText("dash-tokens", tokStr);
    setText("dash-files", String(fileN));
    setText("dash-lines", String(lineN));

    setText("chip-desks", "desks: " + working + " run / " + quiet + " idle");
    setText("chip-tokens", "tok: " + tokStr);
    setText("chip-files", "files written: " + fileN + " / " + lineN + " lines");
    const chipFiles = el("chip-files");
    if (chipFiles) {
      chipFiles.title =
        "Files written: " +
        fileN +
        " · Lines written: " +
        lineN +
        " (harness logs / audit file ops — not wiki links)";
    }

    const byKind = desksInfo.by_kind || {};
    const byState = desksInfo.by_state || {};
    function stateChipLabel(k) {
      const s = String(k || "");
      if (s === "working") return "Running";
      if (s === "quiet" || s === "idle") return "Idle";
      if (s === "dismissed") return "dismissed";
      return s;
    }
    function chipsFromMap(map, fallback, labelFn) {
      const keys = Object.keys(map || {}).filter(function (k) {
        const s = String(k || "").trim();
        return s && s !== "?";
      });
      if (!keys.length && fallback) return fallback;
      if (!keys.length) return '<span class="muted">—</span>';
      return keys
        .sort()
        .map(function (k) {
          const label = labelFn ? labelFn(k) : k;
          return (
            '<span class="dash-chip">' +
            esc(label) +
            "<strong>" +
            esc(String(map[k])) +
            "</strong></span>"
          );
        })
        .join("");
    }
    const kindFallback = countDesksByKind(state.desks)
      .map(function (r) {
        return (
          '<span class="dash-chip">' +
          esc(r.kind) +
          "<strong>" +
          r.n +
          "</strong></span>"
        );
      })
      .join("") || null;
    const kindRoot = el("dash-by-kind");
    const stateRoot = el("dash-by-state");
    if (kindRoot) kindRoot.innerHTML = chipsFromMap(byKind, kindFallback);
    if (stateRoot) {
      let html = chipsFromMap(byState, null, stateChipLabel);
      if (html.indexOf("—") >= 0 || html === '<span class="muted">—</span>') {
        const local = {};
        state.desks.forEach(function (d) {
          if (d.placeholder) return;
          const s = String(d.state || "").trim();
          if (!s || s === "?") return;
          local[s] = (local[s] || 0) + 1;
        });
        html = chipsFromMap(local, null, stateChipLabel);
      }
      stateRoot.innerHTML = html;
    }
    const meta = el("desk-dash-meta");
    if (meta) {
      const up = life && life.time && life.time.process_uptime
        ? " · up " + life.time.process_uptime
        : "";
      meta.textContent = "lifecycle stats" + up + " · no chat bar";
    }
  }

  /* —— Render desks —— */
  function renderDesks() {
    const root = el("desks");
    renderKindSummary();
    let list = ensureKindPlaceholders(state.desks);
    if (state.kindFilter) {
      list = list.filter(function (d) {
        return String(d.kind) === state.kindFilter;
      });
    }
    if (state.groupFilter === "working") {
      list = list.filter(function (d) {
        return String(d.state) === "working";
      });
    } else if (state.groupFilter === "quiet") {
      list = list.filter(function (d) {
        const st = String(d.state || "");
        return st === "quiet" || st === "idle";
      });
    }
    if (!list.length) {
      root.textContent =
        state.groupFilter !== "all" || state.kindFilter
          ? "No desks in this group."
          : "No desks yet.";
      return;
    }

    function rowHtml(d) {
      const id = String(d.id || "");
      const kind = String(d.kind || "desk");
      const st = String(d.state || "");
      const isEmpty = !!d.placeholder || (!st && id.indexOf("kind:") === 0);
      const isDismissed = st === "dismissed";
      const isBusy = st === "working";
      const lab = deskStateLabel(st);
      const stateCls = st
        ? '<span class="desk-state desk-state--' +
          esc(st === "idle" ? "quiet" : st) +
          '">' +
          esc(lab || st) +
          "</span>"
        : "";
      const sched = scheduleLabel(d.schedule);
      const schedHtml = sched
        ? '<span class="desk-sched" title="Schedule">⏱ ' + esc(sched) + "</span>"
        : "";
      const head = kind;
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
      const scheduleBtn = isDismissed
        ? ""
        : '<button type="button" class="btn mini" data-act="schedule" data-id="' +
          esc(id) +
          '" data-kind="' +
          esc(kind) +
          '" title="Create or edit schedule">Schedule</button>';
      const editBtn =
        isEmpty || isDismissed
          ? ""
          : '<button type="button" class="btn mini" data-act="edit" data-id="' +
            esc(id) +
            '" data-kind="' +
            esc(kind) +
            '" title="Edit standing objective">Edit</button>';
      return (
        '<div class="desk-row' +
        (focused ? " focused" : "") +
        (kindSel ? " kind-selected" : "") +
        '" data-id="' +
        esc(id) +
        '" data-kind="' +
        esc(kind) +
        '" data-state="' +
        esc(st) +
        '" data-objective="' +
        esc(obj) +
        '" data-sched-spec="' +
        esc(scheduleSpecPrefill(d.schedule)) +
        '">' +
        '<div class="desk-head"><span class="desk-kind">' +
        esc(head) +
        stateCls +
        schedHtml +
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
        '" data-id="' +
        esc(id) +
        '">' +
        startLbl +
        "</button>" +
        '<button type="button" class="btn mini" data-act="stop" data-id="' +
        esc(id) +
        '"' +
        (isBusy ? "" : " disabled") +
        ">Stop</button>" +
        dismissOrDelete +
        scheduleBtn +
        editBtn +
        "</div></div>"
      );
    }

    // Group sections: Working → Idle → Standing/other (Switchbay Running/Desks feel)
    const working = [];
    const idle = [];
    const other = [];
    list.forEach(function (d) {
      const st = String(d.state || "");
      if (st === "working") working.push(d);
      else if (st === "quiet" || st === "idle") idle.push(d);
      else other.push(d);
    });
    const parts = [];
    function section(title, rows) {
      if (!rows.length) return;
      if (state.groupFilter === "all" && (working.length || idle.length) && title) {
        parts.push('<div class="desk-section-label">' + esc(title) + "</div>");
      }
      rows.forEach(function (d) {
        parts.push(rowHtml(d));
      });
    }
    if (state.groupFilter === "all") {
      section("Working", working);
      section("Idle", idle);
      section(working.length || idle.length ? "Standing" : "", other);
    } else {
      list.forEach(function (d) {
        parts.push(rowHtml(d));
      });
    }
    root.innerHTML = parts.join("");
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
        const rest = !!g.idle || !!g.at_rest || deskAtRest();
        let nodes = g.nodes;
        if (rest) {
          nodes = g.nodes.map(function (n) {
            const nn = Object.assign({}, n);
            const st = String(nn.state || "").toLowerCase();
            if (st !== "done" && st !== "failed" && st !== "error") {
              nn.state = "idle";
            }
            return nn;
          });
        }
        return {
          nodes: nodes,
          edges: (g.edges || []).map(normalizeEdge).filter(Boolean),
          idle: rest,
          at_rest: rest,
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

    const empty = workers.length + terminals.length === 0;
    const rest = empty || deskAtRest();
    let outNodes = nodes;
    if (rest && !empty) {
      outNodes = nodes.map(function (n) {
        const nn = Object.assign({}, n);
        const st = String(nn.state || "").toLowerCase();
        if (st !== "done" && st !== "failed" && st !== "error") {
          nn.state = "idle";
        }
        return nn;
      });
    }
    return {
      nodes: outNodes,
      edges: edges,
      idle: rest,
      at_rest: rest,
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
    if (graphAtRest(state.graph)) return false;
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

      if (active && !graphAtRest(state.graph)) {
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
        !graphAtRest(g) &&
        ((state.layoutNodes || []).some(function (n) {
          return isActiveState(n.state);
        }) ||
        (g.edges || []).some(function (e) {
          return edgeFlowing(e, pos);
        }));
      paintAgentSpace();
      if (needs) state.animRaf = requestAnimationFrame(tick);
      else state.animRaf = 0;
    }
    state.animRaf = requestAnimationFrame(tick);
  }

  function renderAgentSpace(status, dagPayload) {
    const graph = synthesizeDagGraph(status, dagPayload);
    // Bind animation to desk quiet/working — last DAG stays visible but at rest.
    if ((dagPayload && dagPayload.at_rest) || deskAtRest()) {
      graph.idle = true;
      graph.at_rest = true;
    }
    state.graph = graph;
    setText("agent-space-title", graph.label || "AGENT SPACE");
    setText("dag-meta", dagSummaryText(status, graph));
    rebuildLayout();
    ensureAnimLoop();
  }

  function deskLabel(d) {
    if (!d) return "";
    const kind = String(d.kind || "desk");
    const st = deskStateLabel(d.state) || String(d.state || "");
    const obj = d.objective ? String(d.objective).slice(0, 40) : "";
    const id = String(d.id || "");
    let label = kind;
    if (st) label += " · " + st;
    if (obj) label += " — " + obj;
    else if (id && id.indexOf("kind:") !== 0) label += " · " + id.slice(0, 8);
    return label;
  }

  function renderDeskSwitcher() {
    const sel = el("desk-switcher");
    if (!sel) return;
    const prev = state.focusDeskId;
    const list = (state.desks || []).filter(function (d) {
      return d && d.id && String(d.id).indexOf("kind:") !== 0;
    });
    const opts = ['<option value="">Select a desk…</option>'].concat(
      list.map(function (d) {
        const id = String(d.id);
        const selected = id === String(prev) ? " selected" : "";
        return (
          '<option value="' +
          esc(id) +
          '"' +
          selected +
          ">" +
          esc(deskLabel(d)) +
          "</option>"
        );
      })
    );
    sel.innerHTML = opts.join("");
    const meta = el("switcher-meta");
    if (meta) {
      meta.textContent =
        (prev ? "desk " + prev.slice(0, 8) : "no desk") +
        " · ws " +
        (state.selectedWorkspaceId || "local");
    }
  }

  function workspaceOptionLabel(w) {
    if (!w) return "local (serve cwd)";
    const id = String(w.id || w.name || "");
    const name = String(w.name || w.id || "");
    const path = String(w.path || "");
    const label = String(w.label || "").trim();
    if (label) return label;
    if (id === "local" || name === "local") {
      return path ? "local (serve cwd) — " + path : "local (serve cwd)";
    }
    if (name && path) return name + " — " + path;
    return name || path || id || "workspace";
  }

  function normalizeWorkspaceRows(raw) {
    const rows = [];
    const list = Array.isArray(raw) ? raw : [];
    list.forEach(function (w) {
      if (!w) return;
      if (typeof w === "string") {
        const path = String(w);
        const name = path.split("/").filter(Boolean).pop() || path;
        rows.push({ id: name, name: name, path: path, label: name + " — " + path });
        return;
      }
      const id = String(w.id || w.name || w.path || "");
      if (!id) return;
      const name = String(w.name || w.id || id);
      const path = String(w.path || "");
      rows.push({
        id: id,
        name: name,
        path: path,
        label: workspaceOptionLabel({ id: id, name: name, path: path, label: w.label }),
        source: w.source || "",
      });
    });
    return rows;
  }

  function mergeWorkspaceRows(primary, extra) {
    const out = [];
    const seenId = {};
    const seenPath = {};
    function add(w) {
      if (!w) return;
      const id = String(w.id || "");
      const path = String(w.path || "");
      if (id && seenId[id]) return;
      if (path && seenPath[path]) return;
      if (id) seenId[id] = true;
      if (path) seenPath[path] = true;
      out.push(w);
    }
    (primary || []).forEach(add);
    (extra || []).forEach(add);
    return out;
  }

  function rowsFromSwitchbayPayload(payload) {
    if (!payload) return [];
    if (Array.isArray(payload.workspaces)) return normalizeWorkspaceRows(payload.workspaces);
    if (Array.isArray(payload.paths)) {
      return normalizeWorkspaceRows(
        payload.paths.map(function (p) {
          const path = String(p);
          const name = path.split("/").filter(Boolean).pop() || path;
          return { id: name, name: name, path: path, source: "switchbay" };
        })
      );
    }
    return [];
  }

  /** When embedded in Switchbay, /api/workspaces is host-reserved and lists vaults. */
  function fetchHostWorkspaces() {
    if (!isSwitchbayHost()) return Promise.resolve([]);
    // Absolute /api/workspaces — Switchbay fetch shim keeps this on the host.
    return fetch("/api/workspaces", { headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("workspaces " + r.status);
        return r.json();
      })
      .then(function (payload) {
        return rowsFromSwitchbayPayload(payload);
      })
      .catch(function () {
        return [];
      });
  }

  function renderWorkspaceSwitcher(status, hostRows) {
    const sel = el("workspace-switcher");
    if (!sel) return;
    let rows = [];
    let selected = state.selectedWorkspaceId || "";
    const pack =
      (status && status.okbay_workspaces) ||
      (state.status && state.status.okbay_workspaces) ||
      null;
    if (pack) {
      if (Array.isArray(pack.workspaces)) rows = normalizeWorkspaceRows(pack.workspaces);
      if (!selected && pack.selected) selected = String(pack.selected);
      if (!selected && pack.active) selected = String(pack.active.id || pack.active || "");
    }
    rows = mergeWorkspaceRows(rows, normalizeWorkspaceRows(hostRows || state.hostWorkspaces || []));
    // Always keep local (serve cwd) as an explicit fallback option.
    const cwd =
      (status && (status.cwd || status.operating_cwd)) ||
      state.cwd ||
      "";
    rows = mergeWorkspaceRows(rows, [
      {
        id: "local",
        name: "local",
        path: cwd ? String(cwd) : "",
        label: cwd ? "local (serve cwd) — " + cwd : "local (serve cwd)",
        source: "local",
      },
    ]);
    state.workspaces = rows;
    if (!selected) selected = rows[0] ? String(rows[0].id) : "local";
    state.selectedWorkspaceId = selected;
    const seen = {};
    const opts = [];
    function addOpt(id, label) {
      const v = String(id || "");
      if (!v || seen[v]) return;
      seen[v] = true;
      const selAttr = v === String(selected) ? " selected" : "";
      opts.push(
        '<option value="' + esc(v) + '"' + selAttr + ">" + esc(label || v) + "</option>"
      );
    }
    rows.forEach(function (w) {
      addOpt(String(w.id || w.name || ""), workspaceOptionLabel(w));
    });
    if (!opts.length) addOpt("local", "local (serve cwd)");
    sel.innerHTML = opts.join("");
  }

  function openHerdrWorkspace() {
    const wid = String(state.selectedWorkspaceId || (el("workspace-switcher") || {}).value || "");
    let path = "";
    (state.workspaces || []).forEach(function (w) {
      const id = String(w.id || w.name || "");
      if (id && id === wid && w.path) path = String(w.path);
    });
    const msg = el("open-herdr-msg");
    if (msg) {
      msg.hidden = false;
      msg.textContent = "Opening Herdr agent on " + (path || wid || "workspace") + "…";
    }
    setMsg("Open in Herdr…");
    api("/api/herdr/open-workspace", {
      method: "POST",
      body: {
        workspace_id: wid,
        path: path,
        prefer_harness: "grok",
        focus_ui: true,
      },
    })
      .then(function (parsed) {
        const cwd = (parsed && parsed.cwd) || path || wid;
        const kind = (parsed && parsed.kind) || "agent";
        const ok = !parsed || parsed.ok !== false;
        const line = ok
          ? "Agent at " + cwd + " · " + kind
          : String((parsed && (parsed.error || parsed.message)) || "Open in Herdr failed");
        setMsg(line);
        if (msg) {
          msg.hidden = false;
          msg.textContent = line;
        }
      })
      .catch(function (e) {
        const line = String(e.message || e);
        setMsg(line);
        if (msg) {
          msg.hidden = false;
          msg.textContent = line;
        }
      });
  }


  function focusedDeskRow() {
    const id = String(state.focusDeskId || "");
    if (!id) return null;
    const list = state.desks || [];
    for (let i = 0; i < list.length; i++) {
      if (String(list[i].id) === id) return list[i];
    }
    return null;
  }

  function renderDeskPrompt() {
    const ta = el("desk-prompt");
    const meta = el("desk-prompt-meta");
    const saveBtn = el("btn-desk-prompt-save");
    if (!ta) return;
    const desk = focusedDeskRow();
    const id = desk ? String(desk.id) : "";
    const obj = desk && desk.objective != null ? String(desk.objective) : "";
    // Avoid clobbering in-progress edits for the same desk.
    if (
      document.activeElement === ta &&
      String(ta.dataset.deskId || "") === id
    ) {
      if (meta) {
        meta.textContent = id ? "editing · " + id.slice(0, 8) : "select a desk";
      }
      return;
    }
    ta.dataset.deskId = id;
    ta.value = obj;
    ta.disabled = !id || id.indexOf("kind:") === 0;
    if (saveBtn) saveBtn.disabled = ta.disabled;
    if (meta) {
      meta.textContent = id
        ? "desk " + id.slice(0, 8) + (desk.kind ? " · " + desk.kind : "")
        : "select a desk";
    }
  }

  function saveDeskPrompt() {
    const ta = el("desk-prompt");
    if (!ta || ta.disabled) return;
    const deskId = String(ta.dataset.deskId || state.focusDeskId || "").trim();
    if (!deskId || deskId.indexOf("kind:") === 0) {
      setMsg("Select a desk first");
      return;
    }
    const desk = focusedDeskRow();
    const kind = (desk && desk.kind) || "auto";
    const objective = String(ta.value || "");
    setMsg("Saving desk prompt…");
    api("/api/desk/start", {
      method: "POST",
      body: {
        desk_id: deskId,
        kind: kind,
        objective: objective,
        drive_herdr: false,
      },
    })
      .then(function (parsed) {
        setMsg("Desk prompt saved");
        // Keep textarea in sync after save.
        ta.dataset.deskId = deskId;
        afterDeskAction(parsed);
      })
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function chooseWorkspace(id) {
    const wid = String(id || "local");
    state.selectedWorkspaceId = wid;
    let path = "";
    (state.workspaces || []).forEach(function (w) {
      const rowId = String(w.id || w.name || "");
      if (rowId && rowId === wid && w.path) path = String(w.path);
    });
    setMsg("Workspace: " + wid + (path ? " · " + path : ""));
    api("/api/workspace/select", {
      method: "POST",
      body: { id: wid, workspace_id: wid, path: path || undefined },
    })
      .then(function (parsed) {
        const cwd =
          (parsed && (parsed.operating_cwd || (parsed.cwd && parsed.cwd.cwd))) ||
          path ||
          wid;
        if (cwd) {
          state.cwd = cwd;
          setText("s-cwd", cwd);
          setText("cwd-chip", "cwd: " + cwd);
        }
        setMsg("Workspace: " + wid + " · cwd " + cwd);
        refresh();
      })
      .catch(function (e) {
        setMsg(String(e.message || e));
      });
  }

  function renderConversation(payload) {
    const root = el("conversation");
    const meta = el("conversation-meta");
    if (!root) return;
    state.conversation = payload || null;
    if (!state.focusDeskId) {
      if (meta) meta.textContent = "select a desk";
      root.innerHTML = cosEmptyHtml("no-desk");
      ensureConversationHostCopy();
      return;
    }
    const msgs = (payload && payload.messages) || [];
    const src = (payload && payload.source) || "stub";
    if (meta) {
      meta.textContent =
        (payload && payload.stub ? "stub · " : "") +
        src +
        " · " +
        msgs.length +
        " turn" +
        (msgs.length === 1 ? "" : "s");
    }
    if (!msgs.length) {
      let empty = cosEmptyHtml("no-turns");
      if (payload && payload.hint) {
        empty =
          '<p class="conv-stub-hint">' +
          esc(cosStubHint(payload.hint)) +
          "</p>" +
          empty;
      }
      root.innerHTML = empty;
      ensureConversationHostCopy();
      return;
    }
    let html = "";
    if (payload && payload.stub && payload.hint) {
      html +=
        '<p class="conv-stub-hint">' + esc(cosStubHint(payload.hint)) + "</p>";
    }
    html += msgs
      .map(function (m) {
        const role = String(m.role || "system").toLowerCase();
        const author = String(m.author || role);
        const body = String(m.text || m.content || "");
        return (
          '<div class="conv-row role-' +
          esc(role) +
          '"><div class="conv-meta"><span class="conv-author">' +
          esc(author) +
          "</span><span>" +
          esc(role) +
          '</span></div><div class="conv-body">' +
          esc(body.slice(0, 1200)) +
          "</div></div>"
        );
      })
      .join("");
    root.innerHTML = html;
    ensureConversationHostCopy();
  }

  function renderBlackboard(payload) {
    const root = el("blackboard");
    const label = el("bb-desk-label");
    if (label) {
      label.textContent = state.focusDeskId
        ? "desk " + String(state.focusDeskId).slice(0, 10)
        : "select a desk";
    }
    if (!state.focusDeskId) {
      root.innerHTML =
        '<div class="bb-empty">Select a desk to show its live blackboard.</div>';
      return;
    }
    const items = (payload && (payload.items || payload.entries || payload.head)) || [];
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      root.innerHTML = '<div class="bb-empty">blackboard empty for this desk</div>';
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
    setText("s-files", (files.files || 0) + " files written / " + (files.lines || 0) + " lines written");
    const hp = el("harness-path");
    if (hp && life.cwd) hp.textContent = "harnesses.toml · " + life.cwd;
    renderDeskDashboard(life);
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
    // Capture roots from THIS mount. Re-querying by id after soft remount would
    // find the new DOM and let a zombie interval fight the new IIFE's focus.
    const convRoot = el("conversation");
    const desksRoot = el("desks");
    if (!mountIsLive(convRoot) || !mountIsLive(desksRoot)) return;
    setText("poll-status", "refreshing…");
    const focusedAtStart = state.focusDeskId;
    const dagPath = focusedAtStart
      ? "/api/dag?desk_id=" + encodeURIComponent(focusedAtStart)
      : "/api/dag";
    const bbPath = focusedAtStart
      ? "/api/blackboard?n=12&desk_id=" + encodeURIComponent(focusedAtStart)
      : "/api/blackboard?n=12";
    const convPath = focusedAtStart
      ? "/api/desk/conversation?desk_id=" + encodeURIComponent(focusedAtStart)
      : null;
    Promise.all([
      api("/api/status").catch(function () { return {}; }),
      api(dagPath).catch(function () { return {}; }),
      api("/api/desk/status").catch(function () { return {}; }),
      api("/api/desk_session").catch(function () { return {}; }),
      api("/api/lifecycle").catch(function () { return null; }),
      api(bbPath).catch(function () { return {}; }),
      convPath
        ? api(convPath).catch(function () { return { messages: [], stub: true }; })
        : Promise.resolve(null),
      fetchHostWorkspaces(),
    ])
      .then(function (parts) {
        // Stale mount: interval cleared or soft remount replaced the nodes.
        if (!mountIsLive(convRoot) || !mountIsLive(desksRoot)) return;
        const status = parts[0];
        const dag = parts[1];
        const deskStatus = parts[2];
        const deskSession = parts[3];
        const life = parts[4];
        const bb = parts[5];
        const conv = parts[6];
        const hostWs = parts[7] || [];
        state.status = status;
        state.hostWorkspaces = hostWs;

        let desks = normalizeDesks(deskSession);
        if (!desks.length) desks = normalizeDesks(deskStatus);
        if (!desks.length) desks = normalizeDesks(status);
        state.desks = desks;

        // Adopt a desk only when we have none yet. Never auto-promote another
        // idle/server desk over the user's sticky selection on later ticks.
        if (!state.focusDeskId && !state.focusSticky) {
          const fid =
            (deskSession && deskSession.focus_desk_id) ||
            (status && status.focus_desk_id) ||
            (status && status.desk && status.desk.focus_desk_id) ||
            "";
          if (fid) setFocusDesk(fid, { sticky: true });
        }

        renderDesks();
        renderDeskSwitcher();
        renderWorkspaceSwitcher(status, hostWs);
        renderDeskPrompt();
        renderAgentSpace(status, dag);
        renderConversation(conv);
        renderBlackboard(bb);
        if (life) renderLifecycle(life);
        else renderDeskDashboard(null);
        renderRunChip();
        setText("poll-status", "updated " + new Date().toLocaleTimeString());
      })
      .catch(function (e) {
        if (!mountIsLive(convRoot)) return;
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
        startDesk(kind, id);
      } else if (act === "stop") stopDesk(id);
      else if (act === "dismiss") dismissDesk(id);
      else if (act === "delete") deleteDesk(id);
      else if (act === "schedule") {
        const row = btn.closest(".desk-row");
        const existing = row ? row.getAttribute("data-sched-spec") || "" : "";
        openScheduleDialog(id, kind, existing);
      } else if (act === "edit") {
        const row = btn.closest(".desk-row");
        const objective = row ? row.getAttribute("data-objective") || "" : "";
        openEditDialog(id, kind, objective);
      }
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
  const quietBtn = el("btn-quiet-all");
  if (quietBtn) quietBtn.addEventListener("click", quietAll);
  el("btn-bb-clear").addEventListener("click", clearBlackboard);

  const groupFilter = el("desk-group-filter");
  if (groupFilter) {
    groupFilter.addEventListener("click", function (ev) {
      const t = ev.target;
      if (!(t instanceof Element)) return;
      const btn = t.closest("button[data-group]");
      if (!btn) return;
      state.groupFilter = btn.getAttribute("data-group") || "all";
      groupFilter.querySelectorAll("button[data-group]").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-group") === state.groupFilter);
      });
      renderDesks();
    });
  }
  const kindSummary = el("desk-kind-summary");
  if (kindSummary) {
    kindSummary.addEventListener("click", function (ev) {
      const t = ev.target;
      if (!(t instanceof Element)) return;
      const btn = t.closest("button[data-kind-filter]");
      if (!btn) return;
      const k = btn.getAttribute("data-kind-filter") || "";
      state.kindFilter = state.kindFilter === k ? "" : k;
      renderDesks();
    });
  }

  document.querySelectorAll("[data-web]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (currentHosted()) return; // shell owns settings in hosted mode
      setWeb(b.getAttribute("data-web"));
    });
  });
  window.addEventListener("resize", function () {
    rebuildLayout();
  });

  const deskSwitcher = el("desk-switcher");
  if (deskSwitcher) {
    deskSwitcher.addEventListener("change", function () {
      const id = deskSwitcher.value;
      if (id) focusDesk(id);
      else {
        clearFocusDesk();
        renderConversation(null);
        renderBlackboard({});
        renderDeskSwitcher();
      }
    });
  }
  const wsSwitcher = el("workspace-switcher");
  if (wsSwitcher) {
    wsSwitcher.addEventListener("change", function () {
      chooseWorkspace(wsSwitcher.value);
    });
  }
  const openHerdrBtn = el("open-herdr-workspace");
  if (openHerdrBtn) {
    openHerdrBtn.addEventListener("click", function () {
      openHerdrWorkspace();
    });
  }
  const deskPromptSave = el("btn-desk-prompt-save");
  if (deskPromptSave) {
    deskPromptSave.addEventListener("click", saveDeskPrompt);
  }
  const deskPromptTa = el("desk-prompt");
  if (deskPromptTa) {
    deskPromptTa.addEventListener("keydown", function (ev) {
      if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") {
        ev.preventDefault();
        saveDeskPrompt();
      }
    });
  }

  // Drop any prior observer IIFE left by Switchbay soft remount / re-inject.
  try {
    if (typeof window.__okstratrObserverTeardown === "function") {
      window.__okstratrObserverTeardown();
    }
  } catch (e) { /* ignore */ }

  applyHostedMode();

  // Preferred embed desk once, else restore sticky selection across remounts.
  // Poll must not later flip to another idle desk.
  (function adoptInitialFocus() {
    const preferred = detectPreferredDesk();
    if (preferred && !state.preferredDeskApplied) {
      state.preferredDeskApplied = true;
      setFocusDesk(preferred, { sticky: true });
      return;
    }
    const stored = readStoredFocus();
    if (stored) setFocusDesk(stored, { sticky: true });
  })();

  const health = el("health-link");
  if (health) health.setAttribute("href", API + "/health");

  const schedSave = el("schedule-save");
  if (schedSave) schedSave.addEventListener("click", saveSchedule);
  const schedClear = el("schedule-clear");
  if (schedClear) schedClear.addEventListener("click", clearSchedule);
  const schedCancel = el("schedule-cancel");
  if (schedCancel) {
    schedCancel.addEventListener("click", function () { closeModal("schedule"); });
  }
  const schedSpec = el("schedule-spec");
  if (schedSpec) {
    schedSpec.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        ev.preventDefault();
        saveSchedule();
      } else if (ev.key === "Escape") {
        closeModal("schedule");
      }
    });
  }
  const editSave = el("edit-save");
  if (editSave) editSave.addEventListener("click", saveEdit);
  const editCancel = el("edit-cancel");
  if (editCancel) {
    editCancel.addEventListener("click", function () { closeModal("edit"); });
  }
  document.querySelectorAll(".modal-backdrop[data-close]").forEach(function (b) {
    b.addEventListener("click", function () {
      closeModal(b.getAttribute("data-close"));
    });
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape") return;
    const sm = el("schedule-modal");
    const em = el("edit-modal");
    if (sm && !sm.hidden) closeModal("schedule");
    if (em && !em.hidden) closeModal("edit");
  });

  let pollTimer = 0;
  function stopObserver() {
    // Mark dead first so in-flight refresh().then cannot stomp a new mount.
    mountAlive = false;
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = 0;
    }
    if (state.animRaf) {
      try { cancelAnimationFrame(state.animRaf); } catch (e) { /* ignore */ }
      state.animRaf = 0;
    }
  }
  window.__okstratrObserverTeardown = stopObserver;

  refresh();
  pollTimer = setInterval(function () {
    if (!mountAlive) {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = 0;
      }
      return;
    }
    refresh();
  }, POLL_MS);
})();
