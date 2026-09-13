// Okstratr panel: full-size FloatingWindow desk UI (native toplevel — not Overlay).
// Real xdg-shell window so it does NOT paint over lock/screensaver (unlike WlrLayer.Overlay).
// LEFT rail: standing desks from status.desk.standing / focus_desk_id (POST /api/desk/focus).
// Main: objective, kind·state, DAG summary, blackboard head, Open in Herdr.
// No free-text input (Herdr owns that). Keep open/close/toggle for shell summon.

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import "Model.js" as Model

Item {
  id: root
  property bool opened: false
  property var status: null
  property bool restoringPanel: false
  readonly property string statusPath: (Quickshell.env("HOME") || "") + "/.local/state/okstratr/status.json"
  readonly property string uiPath: (Quickshell.env("HOME") || "") + "/.local/state/okstratr/ui.json"
  // Omarchy Color (qs.Commons) loads ~/.local/state/omarchy/current/theme/colors.toml.
  // Fallbacks: Tokyo Night / Switchbay — never flat #181818.
  readonly property color themePanel: (typeof Color !== "undefined" && Color.background) ? Color.background : "#1a1b26"
  readonly property color themeBg: (typeof Color !== "undefined" && Color.popups && Color.popups.background) ? Color.popups.background : "#13141c"
  readonly property color themeFg: (typeof Color !== "undefined" && Color.foreground) ? Color.foreground : "#a9b1d6"
  readonly property color themeMuted: (typeof Color !== "undefined" && Color.muted) ? Color.muted : "#565f89"
  readonly property color themeAccent: (typeof Color !== "undefined" && Color.accent) ? Color.accent : "#7aa2f7"
  readonly property color themeBorder: (typeof Color !== "undefined" && Color.popups && Color.popups.border) ? Color.popups.border : "#292e42"
  // Quiet chrome hairlines (match Herdr grey dividers) — not accent-heavy popups.border.
  readonly property color themeDivider: (typeof Color !== "undefined" && Color.muted)
    ? Qt.rgba(Color.muted.r, Color.muted.g, Color.muted.b, 0.35)
    : "#292e42"
  // Color singleton has no darker_background; recess AGENT SPACE like Switchbay.
  readonly property color themeRecessed: (typeof Color !== "undefined" && Color.background)
    ? Qt.darker(Color.background, 1.45)
    : "#0e0e14"
  readonly property string apiUrl: (status && status.api_url) ? status.api_url : "http://127.0.0.1:8767"
  readonly property string deskKind: Model.deskKind(status)
  readonly property string deskState: Model.deskState(status)
  readonly property int dagCount: (status && status.dag_nodes) ? Number(status.dag_nodes) : 0
  readonly property var standingDesks: Model.standingDesks(status)
  readonly property string focusDeskId: Model.focusDeskId(status)
  readonly property string closeWarning: (status && status.ui && status.ui.close_warning) ? status.ui.close_warning : "Closing Okstratr will shut down the kernel. Standing desks will suspend (quiet) and the session returns to regular Herdr. Continue?"
  property string herdrLaunchMsg: ""
  readonly property var dagGraph: Model.dagGraph(status)

  function persistPanelUi() {
    // Explicit close → panel_open false → stay closed after shell restart.
    uiFile.setText(JSON.stringify({ panel_open: !!root.opened }) + "\n")
  }

  function open(payloadJson) {
    opened = true
    persistPanelUi()
    statusFile.reload()
    refreshLive()
  }
  function close() {
    // TODO QML dialog: root.closeWarning — then suspend kernel / quiet desks
    opened = false
    persistPanelUi()
  }
  function toggle(payloadJson) { opened ? close() : open(payloadJson) }

  function maybeRestorePanel() {
    if (root.opened || root.restoringPanel)
      return
    try {
      var raw = uiFile.text()
      if (!raw || !String(raw).trim())
        return
      var u = JSON.parse(raw)
      if (u && u.panel_open === true) {
        root.restoringPanel = true
        root.open()
        root.restoringPanel = false
      }
    } catch (e) {
      // Missing/invalid ui.json → stay closed (default).
    }
  }

  function refreshLive() {
    Model.getJson(root.apiUrl + "/api/status", function (parsed) {
      if (parsed) root.status = parsed
    })
  }

  function openHerdr() {
    var obj = (root.status && root.status.objective) ? String(root.status.objective) : ""
    root.herdrLaunchMsg = "Launching Herdr…"
    // Prefer HTTP so PATH + systemd user env match herdr.launch.
    // Local execDetached only if serve is down / launch fails — never both on success.
    Model.postJson(root.apiUrl + "/api/herdr/launch", {objective: obj}, function (parsed) {
      if (parsed && parsed.ok !== false) {
        var via = parsed.launcher || (parsed.exec && parsed.exec[0]) || "herdr"
        root.herdrLaunchMsg = "Opened via " + via
        return
      }
      if (parsed && parsed.ok === false)
        root.herdrLaunchMsg = (parsed.message || parsed.error || "Herdr launch failed") + " — trying local…"
      else
        root.herdrLaunchMsg = "Serve unavailable — launching locally…"
      // Fallback: import user env + uwsm-app + terminal + herdr
      // (explicit --dir $HOME — never omarchy-cmd-terminal-cwd / pgrep).
      var esc = String(obj).replace(/'/g, "'\\''")
      Quickshell.execDetached([
        "sh", "-lc",
        "export PATH=\"$HOME/.local/bin:/usr/local/bin:$PATH\"; "
        + "eval \"$(systemctl --user show-environment 2>/dev/null | "
        + "awk -F= '/^(WAYLAND_DISPLAY|DISPLAY|XDG_RUNTIME_DIR|HYPRLAND_INSTANCE_SIGNATURE|"
        + "HYPRLAND_CMD|DBUS_SESSION_BUS_ADDRESS|QT_QPA_PLATFORM)=/ {print \"export \" $0}')\"; "
        + (obj ? ("export OKSTRATR_OBJECTIVE='" + esc + "'; export HERDR_OBJECTIVE='" + esc + "'; ") : "")
        + "if command -v uwsm-app >/dev/null && command -v xdg-terminal-exec >/dev/null; then "
        + "exec uwsm-app -- xdg-terminal-exec --dir \"$HOME\" herdr; "
        + "elif command -v uwsm-app >/dev/null && command -v foot >/dev/null; then "
        + "exec uwsm-app -- foot herdr; "
        + "elif command -v herdr >/dev/null; then exec herdr; "
        + "elif command -v omarchy-launch-terminal-herdr >/dev/null; then exec omarchy-launch-terminal-herdr; "
        + "else exit 1; fi"
      ])
    })
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

  // Persist desk UI visibility across omarchy-shell restart (KeepLoaded alone is not enough).
  FileView {
    id: uiFile
    path: root.uiPath
    watchChanges: false
    printErrors: false
    onLoaded: root.maybeRestorePanel()
    onLoadFailed: { /* no ui.json yet — stay closed */ }
  }

  Component.onCompleted: uiFile.reload()


  // Omarchy-native chip control (mint accent) — replaces Qt Quick Controls Button
  component Chip: Rectangle {
    id: chip
    property string label: ""
    property bool primary: false
    signal clicked()

    implicitWidth: Math.max(chipLabel.implicitWidth + 20, primary ? 108 : 52)
    implicitHeight: 28
    radius: 9
    color: {
      if (primary) {
        var a = chipMa.containsMouse ? 0.38 : 0.22
        return Qt.rgba(root.themeAccent.r, root.themeAccent.g, root.themeAccent.b, a)
      }
      return chipMa.containsMouse ? "#33ffffff" : root.themeBg
    }
    border.width: 1
    border.color: (primary || chipMa.containsMouse) ? root.themeAccent : root.themeBorder

    Text {
      id: chipLabel
      anchors.centerIn: parent
      text: chip.label
      color: root.themeFg
      font.pixelSize: 12
      font.bold: chip.primary
    }

    MouseArea {
      id: chipMa
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: chip.clicked()
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
      // Window hide / compositor close — same as explicit close (do not re-open after restart).
      if (!visible && root.opened)
        root.close()
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

          // Quiet bottom divider (Herdr-like hairline)
          Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: root.themeDivider
          }

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

            Chip {
              label: "Once"
              onClicked: root.setWeb("once")
            }
            Chip {
              label: "Session"
              onClicked: root.setWeb("session")
            }
            Chip {
              label: "Off"
              onClicked: root.setWeb("off")
            }

            Chip {
              label: "✕"
              implicitWidth: 32
              onClicked: root.close()
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

            // Quiet right divider vs main column
            Rectangle {
              anchors.top: parent.top
              anchors.bottom: parent.bottom
              anchors.right: parent.right
              width: 1
              color: root.themeDivider
              z: 2
            }

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
                  color: root.themeDivider
                }

                // AGENT SPACE — Switchbay-like visual DAG frame (pure QML)
                Rectangle {
                  id: agentSpace
                  width: parent.width
                  height: 248
                  radius: 10
                  color: root.themeRecessed
                  border.color: root.themeDivider
                  border.width: 1

                  property var graph: root.dagGraph
                  property var layoutNodes: []

                  function rebuildLayout() {
                    var g = agentSpace.graph || { nodes: [], edges: [] }
                    var nodes = g.nodes || []
                    var w = Math.max(dagArea.width, 200)
                    var h = Math.max(dagArea.height, 160)
                    // Group by tier
                    var tiers = {}
                    for (var i = 0; i < nodes.length; i++) {
                      var t = (nodes[i].tier !== undefined) ? Number(nodes[i].tier) : 1
                      if (!tiers[t]) tiers[t] = []
                      tiers[t].push(nodes[i])
                    }
                    var tierKeys = Object.keys(tiers).map(function (k) { return Number(k) })
                    tierKeys.sort(function (a, b) { return a - b })
                    var tierCount = Math.max(tierKeys.length, 1)
                    var out = []
                    for (var ti = 0; ti < tierKeys.length; ti++) {
                      var key = tierKeys[ti]
                      var row = tiers[key]
                      var y = (ti + 0.5) * (h / tierCount)
                      for (var j = 0; j < row.length; j++) {
                        var x = (row.length === 1)
                          ? w / 2
                          : (j + 0.5) * (w / row.length)
                        var node = row[j]
                        out.push({
                          id: node.id,
                          label: node.label || node.id,
                          role: node.role || node.kind || "",
                          state: node.state || "",
                          virtual: !!node.virtual,
                          x: x,
                          y: y,
                          color: Model.nodeColorForRole(node.role || node.kind)
                        })
                      }
                    }
                    agentSpace.layoutNodes = out
                    dagCanvas.requestPaint()
                  }

                  Component.onCompleted: rebuildLayout()
                  onWidthChanged: rebuildLayout()
                  onGraphChanged: rebuildLayout()

                  Text {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.margins: 10
                    text: (agentSpace.graph && agentSpace.graph.label) ? agentSpace.graph.label : "AGENT SPACE"
                    color: root.themeMuted
                    font.pixelSize: 10
                    font.bold: true
                    font.letterSpacing: 1.2
                  }

                  Text {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 10
                    text: Model.dagSummaryText(root.status)
                    color: root.themeMuted
                    font.pixelSize: 10
                    elide: Text.ElideRight
                    width: Math.min(implicitWidth, parent.width * 0.55)
                    horizontalAlignment: Text.AlignRight
                  }

                  Item {
                    id: dagArea
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    anchors.topMargin: 32
                    anchors.bottomMargin: 12
                    onWidthChanged: agentSpace.rebuildLayout()
                    onHeightChanged: agentSpace.rebuildLayout()

                    Canvas {
                      id: dagCanvas
                      anchors.fill: parent
                      onPaint: {
                        var ctx = getContext("2d")
                        ctx.reset()
                        ctx.clearRect(0, 0, width, height)
                        var g = agentSpace.graph || { edges: [] }
                        var edges = g.edges || []
                        var pos = {}
                        var layout = agentSpace.layoutNodes || []
                        for (var i = 0; i < layout.length; i++)
                          pos[layout[i].id] = layout[i]
                        ctx.strokeStyle = Qt.rgba(root.themeBorder.r, root.themeBorder.g, root.themeBorder.b, 0.55)
                        ctx.lineWidth = 1
                        for (var e = 0; e < edges.length; e++) {
                          var a = pos[edges[e].from]
                          var b = pos[edges[e].to]
                          if (!a || !b) continue
                          ctx.beginPath()
                          ctx.moveTo(a.x, a.y)
                          ctx.lineTo(b.x, b.y)
                          ctx.stroke()
                        }
                      }
                    }

                    Repeater {
                      model: agentSpace.layoutNodes
                      delegate: Item {
                        required property var modelData
                        x: modelData.x - 18
                        y: modelData.y - 18
                        width: 36
                        height: 36

                        // Glow ring for Chief of Staff
                        Rectangle {
                          visible: String(modelData.role) === "cos"
                          anchors.centerIn: parent
                          width: 44
                          height: 44
                          radius: 22
                          color: "transparent"
                          border.width: 2
                          border.color: "#662dd4bf"
                        }
                        Rectangle {
                          visible: String(modelData.role) === "cos"
                          anchors.centerIn: parent
                          width: 52
                          height: 52
                          radius: 26
                          color: "#222dd4bf"
                        }

                        Rectangle {
                          id: nodeDot
                          anchors.centerIn: parent
                          width: 22
                          height: 22
                          radius: 11
                          color: modelData.color
                          border.width: String(modelData.role) === "cos" ? 2 : 1
                          border.color: String(modelData.role) === "cos" ? "#99f6e4" : "#1f2937"
                          opacity: (modelData.state === "done") ? 0.55 : 1.0
                        }

                        Text {
                          anchors.horizontalCenter: parent.horizontalCenter
                          anchors.bottom: parent.top
                          anchors.bottomMargin: 2
                          text: modelData.label
                          color: root.themeFg
                          font.pixelSize: 9
                          font.bold: String(modelData.role) === "cos" || String(modelData.role) === "blackboard"
                        }
                      }
                    }
                  }
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
                  Chip {
                    label: "Open in Herdr"
                    primary: true
                    onClicked: root.openHerdr()
                  }
                  Chip {
                    label: "Refresh"
                    onClicked: root.refreshLive()
                  }
                }

                Text {
                  visible: root.herdrLaunchMsg.length > 0
                  text: root.herdrLaunchMsg
                  color: root.themeMuted
                  font.pixelSize: 11
                  wrapMode: Text.Wrap
                  width: parent.width
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
