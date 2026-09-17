// Okstratr / Herdr bar widget.
// Left-click: open/focus okstratr panel (same as Super+Shift+O summon).
// Right-click: no-op for now (reserved; explicitly documented).
// Shows desk kind + display label (Running|Idle) and DAG count.
// Uses the Quattro BarWidget host type (same contract as okbay / khephri.sia).
// P4: prefer HTTP GET /api/status (DeskSession SSOT); FileView status.json is last-resort offline.

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "benjsmith.okstratr"

  property var status: null
  property bool statusResolved: false
  property bool stale: true
  property real nowMs: Date.now()
  property bool httpLive: false

  readonly property string statusPath: (Quickshell.env("HOME") || "") + "/.local/state/okstratr/status.json"
  readonly property string apiUrl: Model.resolveApiUrl(root.status)
  readonly property real staleAfterSec: {
    var v = root.setting ? root.setting("staleAfterSec", 240) : 240
    return Number(v)
  }
  readonly property string chipText: Model.label(status, stale)
  readonly property string webChip: Model.webEgressChip(status)
  readonly property bool setupMode: Model.needsSetup(status)

  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onLoaded: root.applyFileStatus()
    onFileChanged: applyTimer.restart()
    onLoadFailed: {
      // Only clear if HTTP is also down — keep last HTTP snapshot when live.
      if (!root.httpLive) {
        root.status = null
        root.statusResolved = true
        root.stale = true
      }
    }
  }

  Timer {
    id: applyTimer
    interval: 150
    onTriggered: statusFile.reload()
  }

  // P4: HTTP poll is primary; FileView only when HTTP fails.
  Timer {
    interval: 4000
    running: true
    repeat: true
    onTriggered: {
      root.nowMs = Date.now()
      root.stale = Model.isStale(root.status, root.nowMs, root.staleAfterSec)
      root.pollHttp()
    }
  }

  function pollHttp() {
    Model.pollStatusHttp(root.apiUrl, function (parsed, ok) {
      if (ok && parsed) {
        root.status = parsed
        root.statusResolved = true
        root.httpLive = true
        root.stale = Model.isStale(parsed, Date.now(), root.staleAfterSec)
        return
      }
      // Last-resort offline: FileView mirror.
      root.httpLive = false
      statusFile.reload()
    })
  }

  function applyFileStatus() {
    // P4: never let FileView overwrite a live HTTP DeskSession.
    if (root.httpLive)
      return
    var parsed = Model.parseStatus(statusFile.text())
    root.status = parsed
    root.statusResolved = true
    root.stale = Model.isStale(parsed, Date.now(), root.staleAfterSec)
  }

  function summonOkstratr(payload) {
    var body = payload || "{\"surface\":\"panel\"}"
    if (root.bar && root.bar.shell && root.bar.shell.summon)
      root.bar.shell.summon("benjsmith.okstratr", body)
    else
      Quickshell.execDetached(["omarchy-shell", "shell", "summon", "benjsmith.okstratr", body])
  }

  function runSetup() {
    Quickshell.execDetached(["sh", "-lc", "command -v okstratr >/dev/null && okstratr status || (command -v foot && foot -e bash -lc 'echo Okstratr is not on PATH yet. Clone github.com/benjsmith/okstratr and run contrib/setup.sh; read')"])
  }

  Component.onCompleted: root.pollHttp()

  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: function (mouse) {
      if (root.setupMode) {
        root.runSetup()
        return
      }
      // Right-click: no-op for now (reserved for a future Herdr/action menu).
      if (mouse.button === Qt.RightButton)
        return
      root.summonOkstratr("{\"surface\":\"panel\"}")
    }
  }

  Text {
    anchors.centerIn: parent
    text: "\\u25b6 " + root.chipText + " · " + root.webChip
    color: {
      if (root.setupMode || root.stale)
        return (typeof Color !== "undefined" && Color.urgent) ? Color.urgent : "#f7768e"
      if (root.status && root.status.objective)
        return (typeof Color !== "undefined" && Color.accent) ? Color.accent : "#7aa2f7"
      if (typeof Color !== "undefined" && Color.foreground)
        return Color.foreground
      return parent.bar && parent.bar.foreground ? parent.bar.foreground : "#a9b1d6"
    }
    font.pixelSize: 12
  }
}
