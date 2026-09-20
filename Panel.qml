// PRIMARY CONSOLE: the HTML observer panel (/observer/ on :8767) is the primary
// cross-platform visual (ADR-003) — desks / AGENT SPACE / blackboard; no chat bar.
// THIS FILE: Omarchy native twin / optional thin client of the same daemon. Kept for
// guest Omarchy; do not treat as the main console. Prefer opening the observer.
//
// Phase 4: pure client of okstratr daemon (ADR-001). DeskSession SSOT via GET /api/status;
// status.json FileView is offline/compat only (never overwrites HTTP while open).
// Harness editor: ConfigHarnessEditor.qml; standing rail: DeskRail.qml + /api/harness*.
// FloatingWindow desk UI (native toplevel — not Overlay / not over lock/screensaver).
// LEFT rail: standing desks from status.desk.standing / focus_desk_id (POST /api/desk/focus).
// Main: optional native query/workspace/config + DAG/blackboard (observer has no query bar).
// Text I/O: Herdr / CLI harnesses — not this panel as chat.

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
  readonly property var workspaceRows: Model.workspaceRows(status)
  readonly property bool workspaceReachable: Model.workspaceReachable(status)
  property string selectedWorkspaceId: Model.selectedWorkspaceId(status)
  property string selectedKind: "auto"
  property bool workspaceMenuOpen: false
  property bool configOpen: false
  property var harnessRows: []
  property string harnessConfigPath: "~/.config/okstratr/harnesses.toml"
  property string harnessActionMsg: ""
  // P4: true after a successful HTTP /api/status while panel is open — blocks FileView overwrite.
  property bool httpLive: false
  property string statusSource: "none"  // http | file | none
  property bool scheduleOpen: false
  property string scheduleDeskId: ""
  property string scheduleKind: ""
  property string actionMsg: ""
  property bool closeDialogVisible: false

  function persistPanelUi() {
    // Explicit close → panel_open false → stay closed after shell restart.
    uiFile.setText(JSON.stringify({ panel_open: !!root.opened }) + "\n")
  }

  function open(payloadJson) {
    opened = true
    persistPanelUi()
    root.refreshStatus()
    refreshLive()
  }
  function close() {
    // Confirm via close dialog (bind root.closeWarning); cancel keeps panel open.
    closeDialogVisible = true
  }

  function cancelClose() {
    closeDialogVisible = false
  }

  function confirmClose() {
    closeDialogVisible = false
    // Quiet working standing desks, then close panel.
    Model.postJson(root.apiUrl + "/api/desk/quiet_standing", {}, function (parsed) {
      if (parsed && parsed.ok === false)
        root.actionMsg = parsed.error || parsed.message || "Quiet standing failed"
      opened = false
      root.httpLive = false
      root.statusSource = "none"
      persistPanelUi()
      root.refreshStatus()
    })
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
      // Persist panel_open for explicit close state, but never auto-open on
      // Component.onCompleted / shell restart. User opens via Super+Shift+K
      // (okbay full-product) or Super+Shift+O (okstratr only).
      if (false && u && u.panel_open === true) {
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
      if (!parsed) {
        // HTTP miss — allow FileView mirror as last-resort offline while open.
        if (root.opened)
          root.httpLive = false
        return
      }
      root.status = parsed
      root.httpLive = true
      root.statusSource = "http"
      // Surface async Herdr job errors after Start returns (non-blocking).
      if (parsed.herdr_error) {
        var errMsg = parsed.message || ("Herdr: " + parsed.herdr_error)
        if (root.actionMsg !== errMsg)
          root.actionMsg = errMsg
      } else if (parsed.herdr_job && parsed.herdr_job.state === "running") {
        var jid = parsed.herdr_job.id || "?"
        var runMsg = "Herdr running (job " + jid + ")"
        // Keep Start message if it already mentions the job; else show Running.
        if (!root.actionMsg || root.actionMsg.indexOf("Herdr") < 0)
          root.actionMsg = runMsg
      }
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

  function standingObjectiveForKind(kind) {
    // Prefer standing desk of that kind, then focused desk, then status.objective.
    var rows = Model.standingDesks(root.status) || []
    var k = String(kind || "")
    var i
    for (i = 0; i < rows.length; i++) {
      var row = rows[i]
      if (!row || row.empty) continue
      if (k && String(row.kind) === k && row.objective)
        return String(row.objective)
    }
    var fid = String(root.focusDeskId || "")
    if (fid) {
      for (i = 0; i < rows.length; i++) {
        if (rows[i] && String(rows[i].id) === fid && rows[i].objective)
          return String(rows[i].objective)
      }
    }
    if (root.status && root.status.objective)
      return String(root.status.objective)
    return ""
  }

  function focusDesk(deskId) {
    if (!deskId) return
    // Refill query with this desk's objective so Continue/Start can edit & rerun.
    var rows = Model.standingDesks(root.status) || []
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i]
      if (row && String(row.id) === String(deskId)) {
        if (row.kind)
          root.selectedKind = String(row.kind)
        if (row.objective)
          queryInput.text = String(row.objective)
        break
      }
    }
    Model.postJson(root.apiUrl + "/api/desk/focus", {desk_id: String(deskId)}, function (parsed) {
      if (parsed && parsed.ok === false)
        return
      // Focus API path: ensure queryInput tracks status objective (quiet desks too).
      if (parsed && parsed.objective)
        queryInput.text = String(parsed.objective)
      root.refreshStatus()
      root.refreshLive()
    })
  }

  function afterDeskAction(parsed) {
    if (parsed && parsed.ok === false) {
      root.actionMsg = parsed.herdr_error || parsed.error || "Desk action failed"
      root.refreshStatus()
      root.refreshLive()
      return
    }
    if (parsed && parsed.herdr_error)
      root.actionMsg = parsed.message || ("Herdr: " + parsed.herdr_error)
    else if (parsed && parsed.herdr_job && parsed.herdr_job.state === "running")
      root.actionMsg = parsed.message || ("Herdr running (job " + parsed.herdr_job.id + ")")
    else
      root.actionMsg = (parsed && parsed.message) ? parsed.message : "Desk updated"
    // Do not clear queryInput on stop — keep objective for Continue/rerun.
    // If query empty and start returned a desk objective, refill it.
    var nested = parsed && parsed.desk
    var deskObj = ""
    if (nested) {
      if (nested.desk && nested.desk.objective)
        deskObj = String(nested.desk.objective)
      else if (nested.objective)
        deskObj = String(nested.objective)
    }
    if (deskObj && !String(queryInput.text || "").trim())
      queryInput.text = deskObj
    root.refreshStatus()
    root.refreshLive()
  }

  function parseDeskQuery(text) {
    // Query defaults to auto. Leading /work|/curate|/code|/deck|/auto overrides.
    var raw = String(text || "").trim()
    var m = raw.match(/^\/(work|curate|code|deck|auto)\b\s*([\s\S]*)$/i)
    if (m)
      return { kind: String(m[1]).toLowerCase(), objective: String(m[2] || "").trim(), slash: true }
    return { kind: null, objective: raw, slash: false }
  }

  function startDesk(kind) {
    var parsed = root.parseDeskQuery(queryInput.text)
    // Slash in the query always wins; otherwise use the rail kind / auto.
    var k = parsed.slash ? parsed.kind : String(kind || root.selectedKind || "auto")
    root.selectedKind = k
    var objective = parsed.objective
    // Empty query (Continue/Start after Stop) → reuse standing desk objective.
    if (!String(objective || "").trim())
      objective = root.standingObjectiveForKind(k)
    root.actionMsg = "Starting " + k + " desk…"
    // Non-empty effective objective → drive seats (run_ready). drive_herdr means
    // "drive seats" — Herdr *or* direct per harnesses.toml backend (not force herdr).
    var payload = {
      kind: k,
      objective: objective,
      workspace_id: root.selectedWorkspaceId
    }
    if (String(objective || "").trim())
      payload.drive_herdr = true
    Model.postJson(root.apiUrl + "/api/desk/start", payload, root.afterDeskAction)
  }

  function startFromQuery() {
    var parsed = root.parseDeskQuery(queryInput.text)
    root.startDesk(parsed.kind || "auto")
  }

  function stopDesk(deskId) {
    if (!deskId || String(deskId).indexOf("kind:") === 0) return
    Model.postJson(root.apiUrl + "/api/desk/stop", {desk_id: String(deskId)}, root.afterDeskAction)
  }

  function dismissDesk(deskId) {
    if (!deskId || String(deskId).indexOf("kind:") === 0) return
    Model.postJson(root.apiUrl + "/api/desk/dismiss", {desk_id: String(deskId)}, root.afterDeskAction)
  }

  function deleteDesk(deskId) {
    if (!deskId || String(deskId).indexOf("kind:") === 0) return
    Model.postJson(root.apiUrl + "/api/desk/delete", {desk_id: String(deskId)}, root.afterDeskAction)
  }

  function chooseWorkspace(item) {
    if (!item) return
    root.selectedWorkspaceId = String(item.id || item.name || "local")
    root.workspaceMenuOpen = false
    Model.postJson(root.apiUrl + "/api/workspace/select", {
      id: root.selectedWorkspaceId,
      path: item.path || ""
    }, function(parsed) {
      root.actionMsg = "Workspace: " + root.selectedWorkspaceId
      root.refreshStatus()
      root.refreshLive()
    })
  }

  function openSchedule(deskId, kind) {
    root.scheduleDeskId = String(deskId || "")
    root.scheduleKind = String(kind || "desk")
    scheduleInput.text = "daily"
    root.scheduleOpen = true
  }

  function saveSchedule() {
    var spec = String(scheduleInput.text || "").trim()
    if (!spec) return
    // Empty kind row: start the kind first, then attach schedule to returned desk id.
    if (!root.scheduleDeskId || root.scheduleDeskId.indexOf("kind:") === 0) {
      Model.postJson(root.apiUrl + "/api/desk/start", {
        kind: root.scheduleKind,
        objective: String(queryInput.text || "").trim(),
        workspace_id: root.selectedWorkspaceId
      }, function(started) {
        var did = started && started.desk && started.desk.desk ? started.desk.desk.id : ""
        if (!did && started && started.desk && started.desk.id) did = started.desk.id
        Model.postJson(root.apiUrl + "/api/desk/schedule", {desk_id: did, spec: spec}, root.afterDeskAction)
      })
    } else {
      Model.postJson(root.apiUrl + "/api/desk/schedule", {desk_id: root.scheduleDeskId, spec: spec}, root.afterDeskAction)
    }
    root.scheduleOpen = false
  }

  function saveRoleConfig() {
    var rows = Model.roleConfigRows(root.status)
    Model.postJson(root.apiUrl + "/api/config/roles", {roles: rows}, function(parsed) {
      root.actionMsg = (parsed && parsed.ok) ? "Role config saved" : "Role config save failed"
      root.configOpen = false
      root.refreshStatus()
      root.refreshLive()
    })
  }


  function applyHarnessPayload(parsed) {
    if (!parsed) return
    root.harnessRows = Model.harnessRows(parsed)
    root.harnessConfigPath = Model.harnessConfigPath(parsed)
    if (root.status) {
      root.status.harness = parsed
      if (parsed && parsed.ok !== false && root.status.desk_session === undefined)
        root.refreshLive()
    }
  }

  function loadHarnessConfig() {
    Model.getJson(root.apiUrl + "/api/harness", function (parsed) {
      if (parsed && parsed.ok !== false) {
        root.applyHarnessPayload(parsed)
        root.harnessActionMsg = ""
      } else {
        root.harnessActionMsg = (parsed && parsed.error) ? String(parsed.error) : "Harness API unavailable — use CLI"
        // Fall back to status.harness if daemon embedded it
        if (root.status && root.status.harness)
          root.applyHarnessPayload(root.status.harness)
      }
    })
  }

  function toggleHarness(hid, enable) {
    var path = enable ? "/api/harness/enable" : "/api/harness/disable"
    Model.postJson(root.apiUrl + path, {id: String(hid)}, function (parsed) {
      if (parsed && parsed.ok !== false) {
        root.applyHarnessPayload(parsed)
        root.harnessActionMsg = (enable ? "Enabled " : "Disabled ") + hid
        root.refreshLive()
      } else {
        root.harnessActionMsg = (parsed && parsed.error) ? String(parsed.error) : "Toggle failed"
      }
    })
  }

  function reloadHarnessConfig() {
    Model.postJson(root.apiUrl + "/api/harness/reload", {}, function (parsed) {
      if (parsed && parsed.ok !== false) {
        root.applyHarnessPayload(parsed)
        root.harnessActionMsg = "Reloaded harnesses.toml"
        root.refreshLive()
      } else {
        root.harnessActionMsg = (parsed && parsed.error) ? String(parsed.error) : "Reload failed"
      }
    })
  }


  function setHarnessModel(hid, model) {
    var key = "harness." + String(hid) + ".default_model"
    Model.postJson(root.apiUrl + "/api/harness/set", {key: key, value: String(model || "")}, function (parsed) {
      if (parsed && parsed.ok !== false) {
        root.applyHarnessPayload(parsed)
        root.harnessActionMsg = "Model " + hid + " → " + model
        root.refreshLive()
      } else {
        root.harnessActionMsg = (parsed && parsed.error) ? String(parsed.error) : "Set model failed"
      }
    })
  }


  function refreshStatus() {
    // P4: when HTTP is live, never poke FileView (avoids silent diverge).
    if (root.opened)
      root.refreshLive()
    else
      statusFile.reload()
  }

  function setWeb(action) {
    Model.postJson(root.apiUrl + "/api/web", {action: action}, function (parsed) {
      if (parsed) {
        if (!root.status) root.status = {}
        root.status.web_egress = parsed
      }
      root.refreshStatus()
    })
  }

    FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onLoaded: {
      // P4: status.json is compat mirror only. Never overwrite HTTP DeskSession while open+live.
      var parsed = Model.parseStatus(statusFile.text())
      if (root.opened && root.httpLive) {
        root.refreshLive()
        return
      }
      if (parsed) {
        root.status = parsed
        if (!root.httpLive)
          root.statusSource = "file"
      }
      if (root.opened)
        root.refreshLive()
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

  // Poll status while desk is working or a Herdr drive job is running (async Start).
  Timer {
    id: livePollTimer
    interval: (String(root.deskState || "") === "working"
      || (root.status && root.status.herdr_job && String(root.status.herdr_job.state || "") === "running"))
      ? 2000 : 5000
    repeat: true
    // P4: always HTTP-poll while open so FileView cannot silently diverge.
    running: root.opened
    onTriggered: root.refreshLive()
  }


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
              text: "desk console · query here · Herdr runs agents"
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
              label: "⚙ Config"
              onClicked: { root.configOpen = true; root.loadHarnessConfig(); root.refreshLive() }
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

          // Left rail — standing desks (extracted DeskRail.qml)
          DeskRail {
            Layout.preferredWidth: 370
            Layout.fillHeight: true
            standingDesks: root.standingDesks
            focusDeskId: String(root.focusDeskId || "")
            selectedKind: root.selectedKind
            modelHelpers: Model
            themeFg: root.themeFg
            themeMuted: root.themeMuted
            themeAccent: root.themeAccent
            themeBg: root.themeBg
            themePanel: root.themePanel
            themeBorder: root.themeBorder
            themeDivider: root.themeDivider
            onFocusRequested: (deskId) => root.focusDesk(deskId)
            onKindSelected: (kind) => { root.selectedKind = kind }
            onStartRequested: (kind) => root.startDesk(kind)
            onStopRequested: (deskId) => root.stopDesk(deskId)
            onDismissRequested: (deskId) => root.dismissDesk(deskId)
            onDeleteRequested: (deskId) => root.deleteDesk(deskId)
            onScheduleRequested: (deskId, kind) => root.openSchedule(deskId, kind)
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
                  text: "Desk objective"
                  color: root.themeMuted
                  font.pixelSize: 11
                  font.bold: true
                }

                Row {
                  width: parent.width
                  spacing: 8

                  Rectangle {
                    width: Math.max(220, parent.width - workspacePicker.width - startQuery.width - 18)
                    height: 42
                    radius: 9
                    color: root.themeBg
                    border.width: queryInput.activeFocus ? 2 : 1
                    border.color: queryInput.activeFocus ? root.themeAccent : root.themeBorder

                    TextInput {
                      id: queryInput
                      anchors.fill: parent
                      anchors.margins: 11
                      color: root.themeFg
                      selectionColor: root.themeAccent
                      selectedTextColor: root.themeBg
                      font.pixelSize: 14
                      clip: true
                      verticalAlignment: TextInput.AlignVCenter
                      onAccepted: root.startFromQuery()
                    }
                    Text {
                      anchors.fill: parent
                      anchors.margins: 11
                      visible: !queryInput.text && !queryInput.activeFocus
                      text: "Objective — defaults to auto; /curate /deck /work /code to override"
                      color: root.themeMuted
                      font.pixelSize: 14
                      verticalAlignment: Text.AlignVCenter
                    }
                    MouseArea {
                      anchors.fill: parent
                      cursorShape: Qt.IBeamCursor
                      onClicked: queryInput.forceActiveFocus()
                      z: -1
                    }
                  }

                  Rectangle {
                    id: workspacePicker
                    width: 150
                    height: 42
                    radius: 9
                    color: root.themeBg
                    border.width: 1
                    border.color: root.workspaceMenuOpen ? root.themeAccent : root.themeBorder
                    Text {
                      anchors.centerIn: parent
                      width: parent.width - 20
                      horizontalAlignment: Text.AlignHCenter
                      elide: Text.ElideRight
                      text: (root.workspaceReachable ? "⌂ " : "") + root.selectedWorkspaceId + " ▾"
                      color: root.themeFg
                      font.pixelSize: 12
                    }
                    MouseArea {
                      anchors.fill: parent
                      cursorShape: Qt.PointingHandCursor
                      onClicked: root.workspaceMenuOpen = !root.workspaceMenuOpen
                    }
                  }

                  Chip {
                    id: startQuery
                    label: {
                      var parsed = root.parseDeskQuery(queryInput.text)
                      return "Start " + (parsed.kind || "auto")
                    }
                    primary: true
                    implicitHeight: 42
                    implicitWidth: 110
                    onClicked: root.startFromQuery()
                  }
                }

                Rectangle {
                  visible: root.workspaceMenuOpen
                  width: 280
                  height: Math.min(240, workspaceListCol.implicitHeight + 16)
                  radius: 9
                  color: root.themeBg
                  border.width: 1
                  border.color: root.themeBorder
                  z: 20
                  Column {
                    id: workspaceListCol
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 3
                    Repeater {
                      model: root.workspaceRows
                      delegate: Rectangle {
                        required property var modelData
                        width: workspaceListCol.width
                        height: 30
                        radius: 6
                        color: workspaceMa.containsMouse ? "#33ffffff" : "transparent"
                        Text {
                          anchors.fill: parent
                          anchors.leftMargin: 8
                          text: (modelData.name || modelData.id || "local") + (modelData.path ? "  ·  " + modelData.path : "")
                          color: root.themeFg
                          font.pixelSize: 11
                          verticalAlignment: Text.AlignVCenter
                          elide: Text.ElideRight
                        }
                        MouseArea {
                          id: workspaceMa
                          anchors.fill: parent
                          hoverEnabled: true
                          cursorShape: Qt.PointingHandCursor
                          onClicked: root.chooseWorkspace(modelData)
                        }
                      }
                    }
                  }
                }

                Text {
                  visible: root.actionMsg.length > 0
                  text: root.actionMsg
                  color: root.themeAccent
                  font.pixelSize: 11
                  width: parent.width
                  elide: Text.ElideRight
                }

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
                    if (kind && st) {
                      var lab = Model.deskStateLabel(st)
                      return lab ? (kind + " · " + lab) : kind
                    }
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
                  spacing: 8
                  Repeater {
                    model: Model.blackboardGroups(root.status)
                    delegate: Column {
                      id: bbGroup
                      required property var modelData
                      readonly property var group: modelData
                      width: parent.width
                      spacing: 4

                      Row {
                        spacing: 6
                        Text {
                          text: String(bbGroup.group.label || bbGroup.group.deskTag || "general")
                          color: root.themeAccent
                          font.pixelSize: 10
                          font.bold: true
                        }
                        Text {
                          text: {
                            var ents = bbGroup.group.entries || []
                            var n = ents.length
                            return n + (n === 1 ? " thread" : " threads")
                          }
                          color: root.themeMuted
                          font.pixelSize: 10
                          anchors.verticalCenter: parent.verticalCenter
                        }
                      }

                      Repeater {
                        model: bbGroup.group.entries || []
                        delegate: Rectangle {
                          id: bbCard
                          required property var modelData
                          property bool expanded: false
                          width: parent.width
                          radius: 8
                          color: bbMa.containsMouse ? "#22ffffff" : "transparent"
                          border.width: 1
                          border.color: root.themeDivider
                          implicitHeight: bbCol.implicitHeight + 10

                          MouseArea {
                            id: bbMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: bbCard.expanded = !bbCard.expanded
                          }

                          Column {
                            id: bbCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 6
                            spacing: 2

                            Row {
                              spacing: 6
                              width: parent.width

                              Rectangle {
                                id: kindChip
                                radius: 6
                                implicitWidth: kindChipLabel.implicitWidth + 10
                                implicitHeight: 16
                                color: Qt.rgba(root.themeAccent.r, root.themeAccent.g, root.themeAccent.b, 0.18)
                                border.width: 1
                                border.color: root.themeAccent
                                Text {
                                  id: kindChipLabel
                                  anchors.centerIn: parent
                                  text: String(modelData.kind || "note")
                                  color: root.themeAccent
                                  font.pixelSize: 9
                                  font.bold: true
                                }
                              }

                              Text {
                                text: String(modelData.author || "")
                                color: root.themeMuted
                                font.pixelSize: 10
                                anchors.verticalCenter: parent.verticalCenter
                              }

                              Text {
                                text: String(modelData.title || "")
                                color: root.themeFg
                                font.pixelSize: 12
                                font.bold: true
                                elide: Text.ElideRight
                                width: Math.max(48, parent.width - kindChip.implicitWidth - 150)
                                anchors.verticalCenter: parent.verticalCenter
                              }

                              Text {
                                visible: Number(modelData.dupCount || 1) > 1
                                text: "×" + String(modelData.dupCount)
                                color: root.themeMuted
                                font.pixelSize: 10
                                anchors.verticalCenter: parent.verticalCenter
                              }

                              Text {
                                visible: String(modelData.metaLine || "").length > 0
                                text: String(modelData.metaLine || "")
                                color: root.themeMuted
                                font.pixelSize: 9
                                anchors.verticalCenter: parent.verticalCenter
                              }
                            }

                            Text {
                              visible: !bbCard.expanded && String(modelData.summary || "").length > 0
                              width: parent.width
                              text: String(modelData.summary || "")
                              color: root.themeMuted
                              font.pixelSize: 11
                              elide: Text.ElideRight
                            }

                            Text {
                              visible: bbCard.expanded
                              width: parent.width
                              text: String(modelData.text || "")
                              color: root.themeFg
                              font.pixelSize: 11
                              wrapMode: Text.Wrap
                            }
                          }
                        }
                      }
                    }
                  }
                  Text {
                    visible: Model.blackboardGroups(root.status).length === 0
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
                  text: "Query starts auto. Slash /curate /deck /work /code overrides. Herdr remains the agent runtime."
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

      // Lightweight modal host: real schedule + role-config persistence APIs.
      Rectangle {
        anchors.fill: parent
        visible: root.configOpen || root.scheduleOpen
        color: "#99000000"
        z: 100

        MouseArea {
          anchors.fill: parent
          onClicked: {
            root.configOpen = false
            root.scheduleOpen = false
          }
        }

        Rectangle {
          visible: root.scheduleOpen
          anchors.centerIn: parent
          width: 460
          height: 190
          radius: 12
          color: root.themePanel
          border.width: 1
          border.color: root.themeBorder

          MouseArea { anchors.fill: parent; onClicked: function(mouse) { mouse.accepted = true } }
          Column {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12
            Text {
              text: "Schedule " + root.scheduleKind + " desk"
              color: root.themeFg
              font.pixelSize: 16
              font.bold: true
            }
            Text {
              text: "Cadence: daily, hourly, weekly, 90m, 1h30m…"
              color: root.themeMuted
              font.pixelSize: 11
            }
            Rectangle {
              width: parent.width
              height: 40
              radius: 8
              color: root.themeBg
              border.width: 1
              border.color: scheduleInput.activeFocus ? root.themeAccent : root.themeBorder
              TextInput {
                id: scheduleInput
                anchors.fill: parent
                anchors.margins: 10
                color: root.themeFg
                font.pixelSize: 13
                verticalAlignment: TextInput.AlignVCenter
                onAccepted: root.saveSchedule()
              }
            }
            Row {
              spacing: 8
              Chip { label: "Save schedule"; primary: true; onClicked: root.saveSchedule() }
              Chip { label: "Cancel"; onClicked: root.scheduleOpen = false }
            }
          }
        }

        Rectangle {
          visible: root.configOpen
          anchors.centerIn: parent
          width: Math.min(parent.width - 60, 900)
          height: Math.min(parent.height - 40, 720)
          radius: 12
          color: root.themePanel
          border.width: 1
          border.color: root.themeBorder

          MouseArea { anchors.fill: parent; onClicked: function(mouse) { mouse.accepted = true } }
          Column {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 10
            Text {
              text: "⚙ Default roles"
              color: root.themeFg
              font.pixelSize: 18
              font.bold: true
            }
            Text {
              text: "Persisted in OKSTRATR_STATE_DIR/config/roles.json · CoS is always enabled"
              color: root.themeMuted
              font.pixelSize: 11
            }

            ConfigHarnessEditor {
              width: parent.width
              harnessRows: root.harnessRows
              harnessConfigPath: root.harnessConfigPath
              harnessActionMsg: root.harnessActionMsg
              themeFg: root.themeFg
              themeMuted: root.themeMuted
              themeAccent: root.themeAccent
              themeBg: root.themeBg
              themePanel: root.themePanel
              themeBorder: root.themeBorder
              themeDivider: root.themeDivider
              onReloadClicked: root.reloadHarnessConfig()
              onToggleClicked: function (hid, enable) { root.toggleHarness(hid, enable) }
              onModelCommit: function (hid, model) { root.setHarnessModel(hid, model) }
            }

            Row {
              width: parent.width
              spacing: 8
              Text { text: "Enabled"; width: 60; color: root.themeMuted; font.pixelSize: 10 }
              Text { text: "Role"; width: 110; color: root.themeMuted; font.pixelSize: 10 }
              Text { text: "Hire cap"; width: 70; color: root.themeMuted; font.pixelSize: 10 }
              Text { text: "Model hint"; width: 180; color: root.themeMuted; font.pixelSize: 10 }
              Text { text: "Notes"; color: root.themeMuted; font.pixelSize: 10 }
            }

            Column {
              id: rolesColumn
              width: parent.width
              spacing: 6
              Repeater {
                model: Model.roleConfigRows(root.status)
                delegate: Rectangle {
                  id: roleRow
                  required property var modelData
                  property bool rowEnabled: !!modelData.enabled
                  width: rolesColumn.width
                  height: 52
                  radius: 7
                  color: root.themeBg
                  border.width: 1
                  border.color: root.themeDivider
                  Row {
                    anchors.fill: parent
                    anchors.margins: 7
                    spacing: 8
                    Rectangle {
                      width: 60
                      height: 32
                      radius: 8
                      color: roleRow.rowEnabled ? "#3344aa88" : "transparent"
                      border.width: 1
                      border.color: roleRow.rowEnabled ? root.themeAccent : root.themeBorder
                      Text {
                        anchors.centerIn: parent
                        text: roleRow.rowEnabled ? "ON" : "OFF"
                        color: roleRow.rowEnabled ? root.themeAccent : root.themeMuted
                        font.pixelSize: 11
                        font.bold: true
                      }
                      MouseArea {
                        anchors.fill: parent
                        enabled: !modelData.always
                        cursorShape: modelData.always ? Qt.ArrowCursor : Qt.PointingHandCursor
                        onClicked: {
                          roleRow.rowEnabled = !roleRow.rowEnabled
                          modelData.enabled = roleRow.rowEnabled
                        }
                      }
                    }
                    Text {
                      text: modelData.title || modelData.id
                      width: 110
                      height: 32
                      verticalAlignment: Text.AlignVCenter
                      color: root.themeFg
                      font.pixelSize: 12
                      font.bold: !!modelData.always
                      elide: Text.ElideRight
                    }
                    Rectangle {
                      width: 70; height: 32; radius: 6; color: root.themePanel
                      TextInput {
                        anchors.fill: parent; anchors.margins: 7
                        text: (modelData.hire_cap === null || modelData.hire_cap === undefined) ? "" : String(modelData.hire_cap)
                        color: root.themeFg; font.pixelSize: 11; verticalAlignment: TextInput.AlignVCenter
                        validator: IntValidator { bottom: 0; top: 99 }
                        onEditingFinished: modelData.hire_cap = text ? Number(text) : null
                      }
                    }
                    Rectangle {
                      width: 180; height: 32; radius: 6; color: root.themePanel
                      TextInput {
                        anchors.fill: parent; anchors.margins: 7
                        text: modelData.model_hint || ""
                        color: root.themeFg; font.pixelSize: 11; verticalAlignment: TextInput.AlignVCenter
                        onEditingFinished: modelData.model_hint = text
                      }
                    }
                    Rectangle {
                      width: Math.max(100, roleRow.width - 60 - 110 - 70 - 180 - 64)
                      height: 32; radius: 6; color: root.themePanel
                      TextInput {
                        anchors.fill: parent; anchors.margins: 7
                        text: modelData.notes || ""
                        color: root.themeFg; font.pixelSize: 11; verticalAlignment: TextInput.AlignVCenter
                        onEditingFinished: modelData.notes = text
                      }
                    }
                  }
                }
              }
            }

            Row {
              spacing: 8
              Chip { label: "Save roles"; primary: true; onClicked: root.saveRoleConfig() }
              Chip { label: "Cancel"; onClicked: root.configOpen = false }
            }
          }
        }
      }
    }
  }

  // Close-warning dialog (status.ui.close_warning / root.closeWarning)
  Rectangle {
    id: closeDialogOverlay
    anchors.fill: parent
    visible: root.closeDialogVisible && root.opened
    z: 9999
    color: "#99000000"

    MouseArea {
      anchors.fill: parent
      onClicked: root.cancelClose()
    }

    Rectangle {
      anchors.centerIn: parent
      width: Math.min(520, parent.width - 48)
      height: closeDialogCol.height + 36
      radius: 12
      color: root.themePanel
      border.color: root.themeBorder
      border.width: 1

      MouseArea { anchors.fill: parent } // swallow clicks

      Column {
        id: closeDialogCol
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 18
        spacing: 14

        Text {
          text: "Close Okstratr?"
          color: root.themeFg
          font.pixelSize: 16
          font.bold: true
        }
        Text {
          width: parent.width
          text: root.closeWarning
          color: root.themeMuted
          font.pixelSize: 13
          wrapMode: Text.Wrap
        }
        Row {
          spacing: 10
          anchors.right: parent.right

          Rectangle {
            width: cancelCloseTxt.width + 24
            height: 34
            radius: 8
            color: "#22000000"
            border.color: root.themeBorder
            Text {
              id: cancelCloseTxt
              anchors.centerIn: parent
              text: "Cancel"
              color: root.themeFg
              font.pixelSize: 13
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: root.cancelClose()
            }
          }
          Rectangle {
            width: confirmCloseTxt.width + 24
            height: 34
            radius: 8
            color: root.themeAccent
            Text {
              id: confirmCloseTxt
              anchors.centerIn: parent
              text: "Close & quiet desks"
              color: "#ffffff"
              font.pixelSize: 13
              font.bold: true
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: root.confirmClose()
            }
          }
        }
      }
    }
  }

}
