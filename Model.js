// Shared status helpers for Okstratr QML surfaces.
// The daemon publishes ~/.local/state/okstratr/status.json.
// Bind desk.kind + desk.state (working|quiet), not "seated".

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
        var t = kind + "·" + st
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
