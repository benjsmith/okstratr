// Okstratr panel: full-size FloatingWindow desk UI (native toplevel — not Overlay).
// Real xdg-shell window so it does NOT paint over lock/screensaver (unlike WlrLayer.Overlay).
// LEFT rail: standing desks from status.desk.standing / focus_desk_id (POST /api/desk/focus).
// Main: objective, kind·state, DAG summary, blackboard head, Open in Herdr.
// No free-text input (Herdr owns that). Keep open/close/toggle for shell summon.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
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
  readonly property color themePanel: (typeof Color !== "undefined" && Color.background) ? Color.background : "#181818"
  readonly property string apiUrl: (status && status.api_url) ? status.api_url : "http://127.0.0.1:8767"
  readonly property string deskKind: Model.deskKind(status)
  readonly property string deskState: Model.deskState(status)
  readonly property int dagCount: (status && status.dag_nodes) ? Number(status.dag_nodes) : 0
  readonly property var standingDesks: Model.standingDesks(status)
  readonly property string focusDeskId: Model.focusDeskId(status)
  readonly property string closeWarning: (status && status.ui && status.ui.close_warning) ? status.ui.close_warning : "Closing Okstratr will shut down the kernel. Standing desks will suspend (quiet) and the session returns to regular Herdr. Continue?"

  function open(payloadJson) {
    opened = true
    statusFile.reload()
    refreshLive()
  }
  function close() {
    // TODO QML dialog: root.closeWarning — then suspend kernel / quiet desks
    opened = false
  }
  function toggle(payloadJson) { opened ? close() : open(payloadJson) }

  function refreshLive() {
    Model.getJson(root.apiUrl + "/api/status", function (parsed) {
      if (parsed) root.status = parsed
    })
  }

  function openHerdr() {
    var obj = (root.status && root.status.objective) ? String(root.status.objective) : ""
    Quickshell.execDetached(["okstratr", "herdr", obj])
  }

  function focusDesk(deskId) {
    if (!deskId) return
    Model.postJson(root.apiUrl + "/api/desk/focus", {desk_id: String(deskId)}, function (parsed) {
      if (parsed && parsed.ok === false)
        return
      statusFile.reload()
      root.refreshLive()
    })
  }

  function setWeb(action) {
    Model.postJson(root.apiUrl + "/api/web", {action: action}, function (parsed) {
      if (parsed) {
        if (!root.status) root.status = {}
        root.status.web_egress = parsed
      }
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

  // Native toplevel (not layershell Overlay) — compositor treats like Herdr;
  // stays under lock/screensaver. Custom chrome for app-like desk UI.
  FloatingWindow {
    id: win
    visible: root.opened
    title: "Okstratr"
    color: root.themePanel
    // Screen-filling: request maximize when shown; Hyprland/Omarchy decorate natively.
    maximized: root.opened
    minimumSize: Qt.size(720, 480)

    onVisibleChanged: {
      if (!visible && root.opened)
        root.opened = false
    }

    Rectangle {
      anchors.fill: parent
      color: root.themePanel

      ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Title bar chrome
        Rectangle {
          Layout.fillWidth: true
          Layout.preferredHeight: 48
          color: root.themeBg
          border.color: root.themeBorder
          border.width: 1

          RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 10
            spacing: 12

            Text {
              text: "Okstratr"
              color: root.themeFg
              font.pixelSize: 16
              font.bold: true
            }

            Text {
              text: "desk brain · pairs with Herdr · no text input"
              color: root.themeMuted
              font.pixelSize: 11
              Layout.fillWidth: true
              elide: Text.ElideRight
            }

            Text {
              text: Model.webEgressChip(root.status)
              color: root.themeAccent
              font.pixelSize: 12
            }

            Button {
              text: "Once"
              onClicked: root.setWeb("once")
            }
            Button {
              text: "Session"
              onClicked: root.setWeb("session")
            }
            Button {
              text: "Off"
              onClicked: root.setWeb("off")
            }

            Button {
              text: "✕"
              flat: true
              onClicked: root.close()
              ToolTip.visible: hovered
              ToolTip.text: "Close panel"
            }
          }

          // Drag the custom chrome to move when not maximized
          MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            property real pressX: 0
            property real pressY: 0
            onPressed: function (mouse) {
              pressX = mouse.x
              pressY = mouse.y
            }
            onPositionChanged: function (mouse) {
              if (pressed && (Math.abs(mouse.x - pressX) > 4 || Math.abs(mouse.y - pressY) > 4))
                win.startSystemMove()
            }
            // Let buttons receive clicks — only drag on empty chrome
            z: -1
          }
        }

        // Body: left rail + main
        RowLayout {
          Layout.fillWidth: true
          Layout.fillHeight: true
          spacing: 0

          // Left rail — standing desks
          Rectangle {
            Layout.preferredWidth: 240
            Layout.fillHeight: true
            color: root.themeBg
            border.color: root.themeBorder
            border.width: 1

            ColumnLayout {
              anchors.fill: parent
              anchors.margins: 12
              spacing: 8

              Text {
                text: "Standing desks"
                color: root.themeMuted
                font.pixelSize: 11
                font.bold: true
              }

              ListView {
                id: deskList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 4
                model: root.standingDesks

                delegate: Rectangle {
                  required property var modelData
                  width: deskList.width
                  height: 56
                  radius: 8
                  color: (String(modelData.id) === String(root.focusDeskId)) ? "#3344aa88" : "#22000000"
                  border.color: (String(modelData.id) === String(root.focusDeskId)) ? root.themeAccent : root.themeBorder
                  border.width: 1

                  Column {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 2
                    Text {
                      text: (modelData.kind || "desk") + " · " + (modelData.state || "?")
                      color: root.themeAccent
                      font.pixelSize: 12
                      font.bold: true
                      width: parent.width
                      elide: Text.ElideRight
                    }
                    Text {
                      text: modelData.objective ? String(modelData.objective) : (modelData.id || "")
                      color: root.themeFg
                      font.pixelSize: 11
                      width: parent.width
                      elide: Text.ElideRight
                    }
                  }

                  MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.focusDesk(modelData.id)
                  }
                }

                Text {
                  anchors.centerIn: parent
                  visible: deskList.count === 0
                  text: "No standing desks"
                  color: root.themeMuted
                  font.pixelSize: 12
                }
              }
            }
          }

          // Main pane
          Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: root.themePanel

            Flickable {
              anchors.fill: parent
              anchors.margins: 20
              contentWidth: width
              contentHeight: mainCol.implicitHeight
              clip: true

              Column {
                id: mainCol
                width: parent.width
                spacing: 14

                Text {
                  text: {
                    var obj = root.status && root.status.objective ? String(root.status.objective) : ""
                    return obj || "No desk objective"
                  }
                  color: root.themeFg
                  font.pixelSize: 22
                  font.bold: true
                  wrapMode: Text.Wrap
                  width: parent.width
                }

                Text {
                  text: {
                    var kind = root.deskKind
                    var st = root.deskState
                    if (kind && st)
                      return kind + " · " + st
                    if (root.status && root.status.state)
                      return String(root.status.state)
                    return "no desk"
                  }
                  color: root.themeAccent
                  font.pixelSize: 14
                }

                Rectangle {
                  width: parent.width
                  height: 1
                  color: root.themeBorder
                }

                Text {
                  text: "DAG"
                  color: root.themeMuted
                  font.pixelSize: 11
                  font.bold: true
                }
                Text {
                  text: Model.dagSummaryText(root.status)
                  color: root.themeFg
                  font.pixelSize: 13
                  wrapMode: Text.Wrap
                  width: parent.width
                }

                Text {
                  text: "Blackboard"
                  color: root.themeMuted
                  font.pixelSize: 11
                  font.bold: true
                }
                Column {
                  width: parent.width
                  spacing: 6
                  Repeater {
                    model: Model.blackboardHead(root.status)
                    delegate: Text {
                      required property var modelData
                      width: parent.width
                      text: {
                        var kind = modelData.kind ? ("[" + modelData.kind + "] ") : ""
                        var author = modelData.author ? (modelData.author + ": ") : ""
                        var body = modelData.text ? String(modelData.text) : ""
                        if (body.length > 220)
                          body = body.slice(0, 218) + "…"
                        return kind + author + body
                      }
                      color: root.themeFg
                      font.pixelSize: 12
                      wrapMode: Text.Wrap
                    }
                  }
                  Text {
                    visible: Model.blackboardHead(root.status).length === 0
                    text: root.status ? "blackboard empty" : "daemon not publishing status"
                    color: root.themeMuted
                    font.pixelSize: 12
                  }
                }

                Row {
                  spacing: 10
                  Button {
                    text: "Open in Herdr"
                    onClicked: root.openHerdr()
                  }
                  Button {
                    text: "Refresh"
                    onClicked: root.refreshLive()
                  }
                }

                Text {
                  text: "Text input lives in Herdr. Workspace vision: Atlas | Nautilus | okstratr+Herdr"
                  color: root.themeMuted
                  font.pixelSize: 10
                  wrapMode: Text.Wrap
                  width: parent.width
                }
              }
            }
          }
        }
      }
    }
  }
}
