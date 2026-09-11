// Headless Okstratr service. Does not run the orchestrator — python serve does.
// Exists so the plugin kind contract is complete and the shell keeps
// this plugin loaded. Status is published as
// ~/.local/state/okstratr/status.json; surfaces FileView that file.

import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root
  visible: false
  readonly property string statusPath: (Quickshell.env("HOME") || "") + "/.local/state/okstratr/status.json"
  readonly property string apiUrl: "http://127.0.0.1:8767"
  property var status: null
  property bool ready: false
  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onLoaded: root.applyStatus()
    onFileChanged: applyTimer.restart()
    onLoadFailed: { root.status = null; root.ready = false }
  }
  Timer { id: applyTimer; interval: 150; onTriggered: statusFile.reload() }
  Timer { interval: 5000; running: true; repeat: true; onTriggered: statusFile.reload() }
  function applyStatus() {
    try {
      root.status = JSON.parse(statusFile.text())
      root.ready = !!(root.status && root.status.state && root.status.state !== "setup")
    } catch (e) {
      root.status = null
      root.ready = false
    }
  }
}
