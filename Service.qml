// Headless Okstratr service. Does not run the orchestrator — python serve does.
// Exists so the plugin kind contract is complete and the shell keeps
// this plugin loaded.
// P4: prefer HTTP GET /api/status (DeskSession SSOT); FileView status.json is last-resort offline.

import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

Item {
  id: root
  visible: false
  readonly property string statusPath: (Quickshell.env("HOME") || "") + "/.local/state/okstratr/status.json"
  readonly property string apiUrl: "http://127.0.0.1:8767"
  property var status: null
  property bool ready: false
  property bool httpLive: false

  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onLoaded: root.applyFileStatus()
    onFileChanged: applyTimer.restart()
    onLoadFailed: {
      if (!root.httpLive) {
        root.status = null
        root.ready = false
      }
    }
  }
  Timer { id: applyTimer; interval: 150; onTriggered: statusFile.reload() }
  Timer {
    interval: 5000
    running: true
    repeat: true
    onTriggered: root.pollHttp()
  }

  function pollHttp() {
    Model.pollStatusHttp(root.apiUrl, function (parsed, ok) {
      if (ok && parsed) {
        root.status = parsed
        root.httpLive = true
        root.ready = !!(parsed.state && parsed.state !== "setup")
        return
      }
      root.httpLive = false
      statusFile.reload()
    })
  }

  function applyFileStatus() {
    if (root.httpLive)
      return
    try {
      root.status = JSON.parse(statusFile.text())
      root.ready = !!(root.status && root.status.state && root.status.state !== "setup")
    } catch (e) {
      root.status = null
      root.ready = false
    }
  }

  Component.onCompleted: root.pollHttp()
}
