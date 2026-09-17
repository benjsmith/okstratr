// Shared status helpers for Okstratr QML surfaces.
// The daemon publishes ~/.local/state/okstratr/status.json.
// Bind desk.kind + desk.state (working|quiet|dismissed), not "seated".
// Display labels: working→Running, quiet→Idle, dismissed→dismissed; empty has no Idle suffix.

.pragma library

function defaultStatus() {
    return {
        ts: 0,
        state: "setup",
        objective: "",
        seated: false,
        dag_nodes: 0,
        desk: { kind: "", state: null },
        herdr_labels: {},
        focus_desk_id: null,
        effort: null,
        web_egress: { mode: "off", label: "Off", chip: "Web: Off" },
        api_url: "http://127.0.0.1:8767",
        herdr: "herdr",
        message: "Run okstratr setup / start a desk"
    }
}

function parseStatus(text) {
    if (!text || !String(text).trim())
        return null
    try {
        var obj = JSON.parse(text)
        if (!obj || typeof obj !== "object")
            return null
        return obj
    } catch (e) {
        return null
    }
}

function deskKind(status) {
    if (status && status.desk && status.desk.kind)
        return String(status.desk.kind)
    if (status && status.desk_kind)
        return String(status.desk_kind)
    return ""
}

function deskState(status) {
    if (status && status.desk && status.desk.state)
        return String(status.desk.state)
    if (status && status.desk_state)
        return String(status.desk_state)
    return ""
}

/** UI label for internal desk state. Empty / placeholder / legacy idle → "". */
function deskStateLabel(state) {
    var s = String(state || "")
    if (s === "working")
        return "Running"
    if (s === "quiet")
        return "Idle"
    if (s === "dismissed")
        return "dismissed"
    // never-started placeholder, legacy "idle", or unknown — no Idle suffix
    return ""
}

function isReady(status) {
    if (!status)
        return false
    var st = status.state
    var ds = deskState(status)
    return !!(st === "ready" || st === "working" || st === "quiet" || st === "seated" || st === "running"
              || ds === "working" || ds === "quiet")
}

function needsSetup(status) {
    return !status || status.state === "setup" || status.state === "missing"
}

function label(status, stale) {
    if (!status || needsSetup(status))
        return "SETUP"
    if (stale)
        return "STALE"
    var kind = deskKind(status)
    var st = deskState(status)
    var n = status.dag_nodes || (status.dag && status.dag.nodes) || 0
    if (kind && (st === "working" || st === "quiet")) {
        var lab = deskStateLabel(st)
        var t = lab ? (kind + "·" + lab) : kind
        if (n)
            t = t + " " + n
        if (t.length > 18)
            return t.slice(0, 16) + "…"
        return t
    }
    var obj = status.objective ? String(status.objective) : ""
    if (obj) {
        if (obj.length > 18)
            return obj.slice(0, 16) + "…"
        return obj
    }
    return "READY"
}

function isStale(status, nowMs, staleAfterSec) {
    if (!status || !status.ts)
        return true
    var tsMs = Number(status.ts) > 1e12 ? Number(status.ts) : Number(status.ts) * 1000
    return (nowMs - tsMs) > (Number(staleAfterSec) * 1000)
}

function apiUrl(status) {
    if (status && status.api_url)
        return String(status.api_url).replace(/\/$/, "")
    return "http://127.0.0.1:8767"
}

function getJson(url, callback) {
    var xhr = new XMLHttpRequest()
    xhr.onreadystatechange = function () {
        if (xhr.readyState !== XMLHttpRequest.DONE)
            return
        var parsed = null
        try { parsed = JSON.parse(xhr.responseText) } catch (e) { parsed = null }
        callback(parsed, xhr.status)
    }
    xhr.open("GET", url)
    xhr.send()
}

function postJson(url, body, callback) {
    var xhr = new XMLHttpRequest()
    xhr.onreadystatechange = function () {
        if (xhr.readyState !== XMLHttpRequest.DONE)
            return
        var parsed = null
        try { parsed = JSON.parse(xhr.responseText) } catch (e) { parsed = null }
        callback(parsed, xhr.status)
    }
    xhr.open("POST", url)
    xhr.setRequestHeader("Content-Type", "application/json")
    xhr.send(JSON.stringify(body || {}))
}

function webEgress(status) {
    if (status && status.web_egress && status.web_egress.label)
        return String(status.web_egress.label)
    if (status && status.web_egress && status.web_egress.mode) {
        var m = String(status.web_egress.mode)
        if (m === "once") return "Once"
        if (m === "session") return "Session"
        return "Off"
    }
    return "Off"
}

function webEgressChip(status) {
    if (status && status.web_egress && status.web_egress.chip)
        return String(status.web_egress.chip)
    return "Web: " + webEgress(status)
}

function standingDesks(status) {
    if (!status)
        return []
    // P3: DeskSession is the preferred standing-desks shape
    if (status.desk_session && Array.isArray(status.desk_session.desks))
        return status.desk_session.desks
    if (status.desk_session && Array.isArray(status.desk_session.standing))
        return status.desk_session.standing
    if (Array.isArray(status.desks))
        return status.desks
    var desk = status.desk || {}
    var list = desk.standing
    if (Array.isArray(list))
        return list
    // Older status published standing as a count only
    if (status.standing && Array.isArray(status.standing))
        return status.standing
    return []
}

function focusDeskId(status) {
    if (!status)
        return ""
    if (status.focus_desk_id)
        return String(status.focus_desk_id)
    if (status.desk && status.desk.focus_desk_id)
        return String(status.desk.focus_desk_id)
    if (status.desk && status.desk.active_id)
        return String(status.desk.active_id)
    return ""
}

function dagSummaryText(status) {
    if (!status)
        return "daemon not publishing status"
    var d = status.dag || {}
    var n = status.dag_nodes || d.nodes || 0
    var by = d.by_state || {}
    var parts = []
    var keys = Object.keys(by)
    for (var i = 0; i < keys.length; i++)
        parts.push(keys[i] + "=" + by[keys[i]])
    var ready = d.ready || []
    var readyN = Array.isArray(ready) ? ready.length : 0
    var readyIds = Array.isArray(ready) ? ready.slice(0, 6).join(", ") : ""
    var line = "nodes=" + n
    if (parts.length)
        line += " · " + parts.join(" ")
    line += " · ready=" + readyN
    if (readyIds)
        line += " (" + readyIds + (readyN > 6 ? ", …" : "") + ")"
    if (d.cycle)
        line += " · CYCLE: " + d.cycle
    return line
}

function _bbFirstLine(text) {
    var raw = String(text || "")
    var nl = raw.indexOf("\n")
    return (nl >= 0 ? raw.slice(0, nl) : raw).trim()
}

function _bbNormalizeKey(s) {
    return String(s || "").replace(/\s+/g, " ").trim().toLowerCase()
}

function _bbParseCosPlan(firstLine) {
    var m = String(firstLine || "").match(/^CoS plan for:\s*(.+?)\s*\(kind=([^)]*)\)\s*$/i)
    if (m)
        return { objective: m[1].trim(), deskTag: String(m[2] || "").trim() }
    if (/^CoS plan for:/i.test(firstLine))
        return { objective: String(firstLine).replace(/^CoS plan for:\s*/i, "").trim(), deskTag: "" }
    return null
}

function _bbParseSteps(text) {
    var lines = String(text || "").split("\n")
    var steps = []
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i].replace(/^\s+/, "")
        var m = line.match(/^-\s+([\w.-]+)\s*:/)
        if (m)
            steps.push(String(m[1]).trim())
    }
    return steps
}

function _bbParseCreatedUpdated(text) {
    var m = String(text || "").match(/\(created=(\d+),\s*updated=(\d+)\)/)
    if (!m)
        return { created: null, updated: null }
    return { created: Number(m[1]), updated: Number(m[2]) }
}

function _bbFormatAge(ts) {
    var n = Number(ts || 0)
    if (!n)
        return ""
    var ms = n > 1e12 ? n : n * 1000
    var sec = Math.max(0, Math.floor((Date.now() - ms) / 1000))
    if (sec < 60)
        return sec + "s"
    if (sec < 3600)
        return Math.floor(sec / 60) + "m"
    if (sec < 86400)
        return Math.floor(sec / 3600) + "h"
    return Math.floor(sec / 86400) + "d"
}

function _bbEnrichEntry(raw) {
    var e = raw || {}
    var text = String(e.text || "")
    var first = _bbFirstLine(text)
    var cos = _bbParseCosPlan(first)
    var steps = _bbParseSteps(text)
    var cu = _bbParseCreatedUpdated(text)
    var deskTag = cos ? cos.deskTag : ""
    if (!deskTag && Array.isArray(e.tags)) {
        for (var t = 0; t < e.tags.length; t++) {
            var tag = String(e.tags[t] || "")
            if (tag && tag !== "cos" && tag !== "breakdown" && tag !== "default"
                && tag !== "retire" && tag !== "worker" && tag !== "herdr" && tag !== "seat" && tag !== "start") {
                deskTag = tag
                break
            }
        }
    }
    var isPlan = !!(cos || String(e.provenance || "") === "okstratr.cos.break_down"
        || (Array.isArray(e.tags) && e.tags.indexOf("breakdown") >= 0))
    var title = cos ? cos.objective : (first || "(empty)")
    if (title.length > 72)
        title = title.slice(0, 70) + "…"
    var summary = ""
    if (isPlan && steps.length)
        summary = steps.length + " step" + (steps.length === 1 ? "" : "s") + " · " + steps.join(", ")
    else if (isPlan)
        summary = "plan"
    else if (text.indexOf("\n") >= 0) {
        var rest = text.slice(first.length).replace(/^\s+/, "").replace(/\s+/g, " ").trim()
        if (rest.length > 96)
            rest = rest.slice(0, 94) + "…"
        summary = rest
    }
    var metaBits = []
    if (cu.created !== null)
        metaBits.push("+" + cu.created + "/~" + cu.updated)
    var age = _bbFormatAge(e.ts)
    if (age)
        metaBits.push(age)
    return {
        id: e.id || "",
        ts: e.ts || 0,
        author: e.author || "",
        kind: e.kind || "note",
        text: text,
        tags: e.tags || [],
        provenance: e.provenance || "",
        node_id: e.node_id || "",
        title: title,
        summary: summary,
        steps: steps,
        deskTag: deskTag,
        isPlan: isPlan,
        metaLine: metaBits.join(" · "),
        age: age,
        dupCount: 1,
        updatedTs: e.ts || 0
    }
}

function _bbDedupeKey(e) {
    // Decision/plan threads: desk + objective title. Others: kind/author/title.
    if (e.isPlan)
        return ["plan", _bbNormalizeKey(e.deskTag), _bbNormalizeKey(e.title)].join("|")
    return [
        _bbNormalizeKey(e.kind),
        _bbNormalizeKey(e.author),
        _bbNormalizeKey(e.provenance),
        _bbNormalizeKey(e.node_id),
        _bbNormalizeKey(e.title || _bbFirstLine(e.text))
    ].join("|")
}

function _bbDeskSortKey(tag) {
    var t = String(tag || "").toLowerCase()
    if (!t)
        return "zzz"
    return t
}

function blackboardHead(status) {
    // Flat newest-first list with global near-duplicate collapse.
    var groups = blackboardGroups(status)
    var out = []
    for (var i = 0; i < groups.length; i++) {
        var ents = groups[i].entries || []
        for (var j = 0; j < ents.length; j++)
            out.push(ents[j])
    }
    return out
}

function blackboardGroups(status) {
    // Group by desk/decision thread; collapse duplicate/near-duplicate posts.
    if (!status)
        return []
    var bb = status.blackboard
    if (!bb)
        return []
    var raw = []
    if (Array.isArray(bb.head))
        raw = bb.head
    else if (Array.isArray(bb))
        raw = bb
    else
        return []

    // Newest-first enrich
    var items = []
    for (var i = raw.length - 1; i >= 0; i--)
        items.push(_bbEnrichEntry(raw[i]))

    // Global collapse by thread key (keep newest)
    var collapsed = []
    var idxByKey = {}
    for (var j = 0; j < items.length; j++) {
        var cur = items[j]
        var key = _bbDedupeKey(cur)
        if (idxByKey[key] !== undefined) {
            var keep = collapsed[idxByKey[key]]
            keep.dupCount = (keep.dupCount || 1) + 1
            if (Number(cur.ts || 0) > Number(keep.updatedTs || 0))
                keep.updatedTs = cur.ts
            // Prefer richer summary from any copy
            if ((!keep.summary || keep.summary.length < (cur.summary || "").length) && cur.summary)
                keep.summary = cur.summary
            continue
        }
        idxByKey[key] = collapsed.length
        collapsed.push(cur)
    }

    // Bucket by desk tag (empty → "general")
    var buckets = {}
    var order = []
    for (var k = 0; k < collapsed.length; k++) {
        var e = collapsed[k]
        var desk = e.deskTag ? String(e.deskTag) : "general"
        if (!buckets[desk]) {
            buckets[desk] = []
            order.push(desk)
        }
        buckets[desk].push(e)
    }
    // Newest desk activity first (not alphabetical).
    order.sort(function (a, b) {
        function newestTs(desk) {
            var ents = buckets[desk] || []
            var best = 0
            for (var i = 0; i < ents.length; i++) {
                var t = Number(ents[i].updatedTs || ents[i].ts || 0)
                if (t > best) best = t
            }
            return best
        }
        var tb = newestTs(b)
        var ta = newestTs(a)
        if (tb !== ta)
            return tb - ta
        return _bbDeskSortKey(a).localeCompare(_bbDeskSortKey(b))
    })

    var groups = []
    for (var o = 0; o < order.length; o++) {
        var d = order[o]
        groups.push({
            deskTag: d,
            label: d === "general" ? "general" : d,
            entries: buckets[d]
        })
    }
    return groups
}

function dagGraph(status) {
    // Bindable Agent Space graph; idle defaults when empty.
    var idleNodes = [
        { id: "cos", label: "chief of staff", title: "Chief of Staff", role: "cos", kind: "cos", state: "ready", tier: 0, virtual: true },
        { id: "blackboard", label: "blackboard", title: "Blackboard", role: "blackboard", kind: "blackboard", state: "ready", tier: 2, virtual: true }
    ]
    var idleEdges = [{ from: "cos", to: "blackboard" }]
    if (!status)
        return { nodes: idleNodes, edges: idleEdges, idle: true, label: "AGENT SPACE" }
    var d = status.dag || {}
    var g = d.graph || status.graph || null
    if (g && Array.isArray(g.nodes) && g.nodes.length >= 2)
        return g
    // Fallback: synthesize from items
    var items = d.items || []
    var nodes = idleNodes.slice()
    var edges = []
    var seen = { cos: true, blackboard: true }
    var workers = []
    var terminals = []
    for (var i = 0; i < items.length; i++) {
        var it = items[i]
        if (!it || !it.id || it.id === "root" || it.kind === "root")
            continue
        var role = String(it.role || it.kind || "worker").toLowerCase()
        if (role === "cos")
            continue
        var tier = 1
        if (role === "verifier" || role === "synthesizer")
            tier = 3
        var nd = {
            id: String(it.id),
            label: String(it.id).length > 18 ? String(it.id).slice(0, 16) + "…" : String(it.id),
            title: it.title || it.id,
            role: role,
            kind: it.kind || role,
            state: it.state || "pending",
            tier: tier,
            virtual: false
        }
        nodes.push(nd)
        seen[nd.id] = true
        if (tier === 1) workers.push(nd.id)
        else if (tier === 3) terminals.push(nd.id)
        var deps = it.depends_on || []
        if (!deps.length)
            edges.push({ from: "cos", to: nd.id })
        for (var j = 0; j < deps.length; j++) {
            var dep = deps[j] === "root" ? "cos" : deps[j]
            if (dep === "cos" || seen[dep] || dep)
                edges.push({ from: (dep === "root" ? "cos" : String(dep)), to: nd.id })
        }
    }
    for (var w = 0; w < workers.length; w++)
        edges.push({ from: workers[w], to: "blackboard" })
    if (terminals.length) {
        edges.push({ from: "cos", to: "blackboard" })
        for (var t = 0; t < terminals.length; t++)
            edges.push({ from: "blackboard", to: terminals[t] })
    } else if (!workers.length) {
        edges.push({ from: "cos", to: "blackboard" })
    }
    return {
        nodes: nodes,
        edges: edges,
        idle: workers.length + terminals.length === 0,
        label: "AGENT SPACE"
    }
}

function nodeColorForRole(role) {
    var r = String(role || "").toLowerCase()
    if (r === "cos" || r === "root") return "#2dd4bf"      // cyan/teal
    if (r === "blackboard") return "#a78bfa"              // purple
    if (r === "investigator" || r === "researcher") return "#60a5fa"  // blue
    if (r === "verifier") return "#fbbf24"                // amber
    if (r === "synthesizer") return "#4ade80"             // green
    if (r === "planner" || r.indexOf("curator") === 0) return "#94a3b8"
    return "#7dd3fc"
}

function workspaceRows(status) {
    if (status && status.okbay_workspaces && Array.isArray(status.okbay_workspaces.workspaces))
        return status.okbay_workspaces.workspaces
    return [{ id: "local", name: "local", label: "local", path: "" }]
}

function workspaceReachable(status) {
    return !!(status && status.okbay_workspaces && status.okbay_workspaces.reachable)
}

function selectedWorkspaceId(status) {
    if (status && status.okbay_workspaces && status.okbay_workspaces.selected)
        return String(status.okbay_workspaces.selected)
    if (status && status.okbay && status.okbay.id)
        return String(status.okbay.id)
    return "local"
}

function roleConfigRows(status) {
    if (status && status.roles_config && Array.isArray(status.roles_config.roles))
        return status.roles_config.roles
    return [
        {id: "cos", title: "CoS", enabled: true, always: true, hire_cap: null, model_hint: "strongest_available", notes: "Always present"},
        {id: "investigator", title: "Investigator", enabled: true, hire_cap: null, model_hint: "diverse", notes: ""},
        {id: "synthesizer", title: "Synthesizer", enabled: true, hire_cap: null, model_hint: "strongest_available", notes: ""},
        {id: "verifier", title: "Verifier", enabled: true, hire_cap: null, model_hint: "diverse", notes: ""},
        {id: "curator", title: "Curator", enabled: true, hire_cap: null, model_hint: "strongest_available", notes: ""},
        {id: "researcher", title: "Researcher", enabled: true, hire_cap: null, model_hint: "diverse", notes: ""}
    ]
}


/** Phase 3: harness allowlist rows from /api/harness or status.harness */
function harnessRows(statusOrHarness) {
    var src = statusOrHarness
    if (src && src.harness && Array.isArray(src.harness.harnesses))
        src = src.harness
    if (src && Array.isArray(src.harnesses))
        return src.harnesses
    return []
}

function harnessConfigPath(statusOrHarness) {
    var src = statusOrHarness
    if (src && src.harness && src.harness.path)
        return String(src.harness.path)
    if (src && src.path)
        return String(src.path)
    return "~/.config/okstratr/harnesses.toml"
}

/** Prefer DeskSession standing rows when present. */
function standingDesksFromSession(status) {
    if (!status)
        return []
    if (status.desk_session && Array.isArray(status.desk_session.desks))
        return status.desk_session.desks
    if (status.desk_session && Array.isArray(status.desk_session.standing))
        return status.desk_session.standing
    return standingDesks(status)
}
