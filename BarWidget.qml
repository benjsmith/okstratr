// Okstratr / Herdr bar widget.
// Left-click: open/focus okstratr panel (same as Super+Shift+O summon).
// Right-click: no-op for now (reserved; explicitly documented).
// Shows desk kind + state (working|quiet) and DAG count.
// Uses the Quattro BarWidget host type (same contract as okbay / khephri.sia).

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

  readonly property string statusPath: (Quickshell.env("HOME") || "") + "/.local/state/okstratr/status.json"
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
    onLoaded: root.applyStatus()
    onFileChanged: applyTimer.restart()
    onLoadFailed: {
      root.status = null
      root.statusResolved = true
      root.stale = true
    }
  }

  Timer {
    id: applyTimer
    interval: 150
    onTriggered: statusFile.reload()
  }

  Timer {
    interval: 4000
    running: true
    repeat: true
    onTriggered: {
      root.nowMs = Date.now()
      root.stale = Model.isStale(root.status, root.nowMs, root.staleAfterSec)
      statusFile.reload()
    }
  }

  function applyStatus() {
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
    text: "\u25b6 " + root.chipText + " · " + root.webChip
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
