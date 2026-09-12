// Okstratr panel: desk kind + state (working|quiet), DAG + blackboard.
// LEFT PANE (stub): desk switch binds status.desk.standing / status.focus_desk_id
// Main pane: DAG + blackboard. No free-text input (Herdr owns text).
// Close: warn via status.ui.close_warning; kernel suspends (desks go quiet).

import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "Model.js" as Model

Item {
  id: root
  property bool opened: false
  property var status: null
  readonly property string statusPath: (Quickshell.env("HOME") || "") + "/.local/state/okstratr/status.json"
  readonly property color themeBg: (typeof Color !== "undefined" && Color.popups && Color.popups.background) ? Color.popups.background : "#f2111111"
  readonly property color themeBorder: (typeof Color !== "undefined" && Color.popups && Color.popups.border) ? Color.popups.border : "#44ffffff"
  readonly property color themeFg: (typeof Color !== "undefined" && Color.foreground) ? Color.foreground : "#f2f2f2"
  readonly property color themeMuted: (typeof Color !== "undefined" && Color.dark_foreground) ? Color.dark_foreground : "#888888"
  readonly property color themeAccent: (typeof Color !== "undefined" && Color.accent) ? Color.accent : "#6be8b3"
  readonly property string apiUrl: (status && status.api_url) ? status.api_url : "http://127.0.0.1:8767"
  readonly property string deskKind: Model.deskKind(status)
  readonly property string deskState: Model.deskState(status)
  readonly property int dagCount: (status && status.dag_nodes) ? Number(status.dag_nodes) : 0
  readonly property string closeWarning: (status && status.ui && status.ui.close_warning) ? status.ui.close_warning : "Closing Okstratr will shut down the kernel. Standing desks will suspend (quiet) and the session returns to regular Herdr. Continue?"

  function open(payloadJson) {
    opened = true
    statusFile.reload()
    Model.getJson(root.apiUrl + "/api/status", function (parsed) {
      if (parsed) root.status = parsed
    })
  }
  function close() {
    // TODO QML dialog: root.closeWarning — then suspend kernel / quiet desks
    opened = false
  }
  function toggle(payloadJson) { opened ? close() : open(payloadJson) }

  function openHerdr() {
    var obj = (root.status && root.status.objective) ? String(root.status.objective) : ""
    Quickshell.execDetached(["okstratr", "herdr", obj])
  }

  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onLoaded: {
      var parsed = Model.parseStatus(statusFile.text())
      if (parsed) root.status = parsed
    }
  }

  PanelWindow {
    visible: root.opened
    color: "transparent"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
    WlrLayershell.namespace: "okstratr-panel"
    anchors.top: true
    anchors.right: true
    margins.top: 42
    margins.right: 12
    implicitWidth: 380
    implicitHeight: 360
    Rectangle {
      anchors.fill: parent
      radius: 12
      color: root.themeBg
      border.color: root.themeBorder
      border.width: 1
      Column {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10
        Text { text: "Okstratr"; color: root.themeFg; font.pixelSize: 16; font.bold: true }
        Text {
          text: "desk brain · pairs with Herdr · no text input"
          color: root.themeMuted
          font.pixelSize: 11
        }
        Text {
          text: {
            var kind = root.deskKind
            var st = root.deskState
            var obj = root.status && root.status.objective ? String(root.status.objective) : ""
            if (kind && st)
              return kind + " · " + st + (obj ? (" — " + obj) : "")
            if (obj)
              return obj
            return "No desk"
          }
          color: root.themeAccent
          font.pixelSize: 13
          wrapMode: Text.Wrap
          width: parent.width
        }
        // Text input lives in Herdr. Left-pane desk switch (stub) binds
        // status.focus_desk_id / status.desk.standing / status.herdr_labels.
        Row {
          spacing: 6
          Button { text: "Open in Herdr"; onClicked: root.openHerdr() }
        }
        Text {
          text: root.status && root.status.web_egress
                ? (root.status.web_egress.chip || ("Web: " + (root.status.web_egress.label || "Off")))
                : "Web: Off"
          color: root.themeAccent
          font.pixelSize: 12
        }
        Row {
          spacing: 6
          Button {
            text: "Web Once"
            onClicked: Model.postJson(root.apiUrl + "/api/web", {action: "once"}, function (parsed) {
              if (parsed) {
                if (!root.status) root.status = {}
                root.status.web_egress = parsed
              }
              statusFile.reload()
            })
          }
          Button {
            text: "Web Session"
            onClicked: Model.postJson(root.apiUrl + "/api/web", {action: "session"}, function (parsed) {
              if (parsed) {
                if (!root.status) root.status = {}
                root.status.web_egress = parsed
              }
              statusFile.reload()
            })
          }
          Button {
            text: "Web Off"
            onClicked: Model.postJson(root.apiUrl + "/api/web", {action: "off"}, function (parsed) {
              if (parsed) {
                if (!root.status) root.status = {}
                root.status.web_egress = parsed
              }
              statusFile.reload()
            })
          }
        }
        Text {
          text: root.status
                ? ((root.deskState || root.status.state || "?") + " · dag=" + root.dagCount)
                : "daemon not publishing status"
          color: root.themeMuted
          font.pixelSize: 11
        }
        Text {
          text: "Workspace vision: Atlas | Nautilus | okstratr+Herdr"
          color: root.themeMuted
          font.pixelSize: 10
          wrapMode: Text.Wrap
          width: parent.width
        }
        Button { text: "Close"; onClicked: root.close() }
      }
    }
  }
}
