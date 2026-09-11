// Shared status helpers for Okstratr QML surfaces.
// The daemon publishes ~/.local/state/okstratr/status.json.

.pragma library

function defaultStatus() {
    return {
        ts: 0,
        state: "setup",
        objective: "",
        seated: false,
        dag_nodes: 0,
        api_url: "http://127.0.0.1:8767",
        herdr: "herdr",
        message: "Run okstratr setup / seat an objective"
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

function isReady(status) {
    return !!(status && (status.state === "ready" || status.state === "seated" || status.state === "running"))
}

function needsSetup(status) {
    return !status || status.state === "setup" || status.state === "missing"
}

function label(status, stale) {
    if (!status || needsSetup(status))
        return "SETUP"
    if (stale)
        return "STALE"
    var obj = status.objective ? String(status.objective) : ""
    if (obj) {
        if (obj.length > 18)
            return obj.slice(0, 16) + "…"
        return obj
    }
    if (status.state === "seated" || status.state === "running")
        return "SEATED"
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
