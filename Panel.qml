// Okstratr panel: seated objective, blackboard head, launch Herdr.
// Thinner sibling of okbay Panel — no Atlas, no reviews inbox.

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

  function open(payloadJson) {
    opened = true
    statusFile.reload()
    Model.getJson(root.apiUrl + "/api/status", function (parsed) {
      if (parsed) root.status = parsed
    })
  }
  function close() { opened = false }
  function toggle(payloadJson) { opened ? close() : open(payloadJson) }

  function openHerdr() {
    var obj = (root.status && root.status.objective) ? String(root.status.objective) : ""
    Quickshell.execDetached(["okstratr", "herdr", obj])
  }

  function seatFromField() {
    var text = objectiveField.text || ""
    Model.postJson(root.apiUrl + "/api/seat", {"objective": text}, function (parsed) {
      if (parsed) root.status = parsed
      statusFile.reload()
    })
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
          text: "desk brain · pairs with Herdr"
          color: root.themeMuted
          font.pixelSize: 11
        }
        Text {
          text: root.status && root.status.objective
                ? ("Seated: " + root.status.objective)
                : "No objective seated"
          color: root.themeAccent
          font.pixelSize: 13
          wrapMode: Text.Wrap
          width: parent.width
        }
        TextField {
          id: objectiveField
          width: parent.width
          placeholderText: "Seat an objective…"
          color: root.themeFg
        }
        Row {
          spacing: 6
          Button { text: "Seat"; onClicked: root.seatFromField() }
          Button { text: "Open in Herdr"; onClicked: root.openHerdr() }
        }
        Text {
          text: root.status
                ? ("state=" + (root.status.state || "?") + " · dag=" + (root.status.dag_nodes || 0))
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
