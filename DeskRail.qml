// Extracted standing-desk left rail (Omarchy/Quickshell sibling of Panel.qml).
// Panel owns HTTP / start/stop/focus; this file is presentation + local clicks.
import QtQuick
import QtQuick.Layouts

Item {
  id: root
  property var standingDesks: []
  property string focusDeskId: ""
  property string selectedKind: "auto"
  property var modelHelpers: null  // Model.js when available
  property color themeFg: "#a9b1d6"
  property color themeMuted: "#565f89"
  property color themeAccent: "#7aa2f7"
  property color themeBg: "#13141c"
  property color themePanel: "#1a1b26"
  property color themeBorder: "#292e42"
  property color themeDivider: "#292e42"

  signal focusRequested(string deskId)
  signal kindSelected(string kind)
  signal startRequested(string kind)
  signal stopRequested(string deskId)
  signal dismissRequested(string deskId)
  signal deleteRequested(string deskId)
  signal scheduleRequested(string deskId, string kind)

  function stateLabel(state) {
    if (root.modelHelpers && root.modelHelpers.deskStateLabel)
      return root.modelHelpers.deskStateLabel(state)
    var s = String(state || "")
    if (s === "working") return "Running"
    if (s === "quiet") return "Idle"
    if (s === "dismissed") return "dismissed"
    return ""
  }

  component MiniChip: Rectangle {
    id: chip
    property string label: ""
    property bool primary: false
    signal clicked()
    width: Math.max(48, chipLabel.implicitWidth + 16)
    height: 26
    radius: 7
    color: chip.primary ? "#3344aa55" : "transparent"
    border.width: 1
    border.color: chipMa.containsMouse || chip.primary ? root.themeAccent : root.themeBorder
    opacity: enabled ? 1 : 0.35
    Text {
      id: chipLabel
      anchors.centerIn: parent
      text: chip.label
      color: root.themeFg
      font.pixelSize: 11
    }
    MouseArea {
      id: chipMa
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: chip.clicked()
    }
  }

  Rectangle {
    anchors.fill: parent
    color: root.themeBg

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
          id: deskRow
          required property var modelData
          width: deskList.width
          height: 94
          radius: 8
          property bool isEmpty: !!modelData.placeholder || (!String(modelData.state || "") && String(modelData.id || "").indexOf("kind:") === 0)
          property bool isDismissed: String(modelData.state || "") === "dismissed"
          property bool isQuiet: String(modelData.state || "") === "quiet"
          property bool isBusy: String(modelData.state || "") === "working"
          property string stateLabel: root.stateLabel(modelData.state)
          color: (String(modelData.id) === String(root.focusDeskId)) ? "#3344aa88" : "#22000000"
          border.color: (String(modelData.id) === String(root.focusDeskId) || String(modelData.kind) === root.selectedKind) ? root.themeAccent : root.themeBorder
          border.width: 1

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              root.kindSelected(String(modelData.kind || "work"))
              if (!deskRow.isEmpty) root.focusRequested(String(modelData.id))
            }
          }

          Column {
            anchors.fill: parent
            anchors.margins: 8
            spacing: 7
            Row {
              width: parent.width
              spacing: 6
              Text {
                text: deskRow.stateLabel
                      ? ((modelData.kind || "desk") + " · " + deskRow.stateLabel)
                      : (modelData.kind || "desk")
                color: root.themeAccent
                font.pixelSize: 12
                font.bold: true
                width: Math.max(90, parent.width - deskObjective.width - 8)
                elide: Text.ElideRight
              }
              Text {
                id: deskObjective
                text: modelData.objective ? String(modelData.objective) : (deskRow.isEmpty ? "standing" : (deskRow.isDismissed ? "dismissed" : "standing"))
                color: root.themeMuted
                font.pixelSize: 10
                width: Math.min(150, implicitWidth)
                elide: Text.ElideRight
              }
            }
            Row {
              spacing: 5
              MiniChip {
                label: (deskRow.isEmpty || deskRow.isDismissed) ? "Start" : "Continue"
                primary: root.selectedKind === String(modelData.kind)
                onClicked: root.startRequested(String(modelData.kind || "auto"))
              }
              MiniChip {
                label: "Stop"
                opacity: deskRow.isBusy ? 1 : 0.35
                onClicked: root.stopRequested(String(modelData.id))
              }
              MiniChip {
                visible: !deskRow.isDismissed
                label: "Dismiss"
                opacity: deskRow.isEmpty ? 0.35 : 1
                onClicked: root.dismissRequested(String(modelData.id))
              }
              MiniChip {
                visible: deskRow.isDismissed
                label: "Delete"
                onClicked: root.deleteRequested(String(modelData.id))
              }
              MiniChip {
                label: "Schedule…"
                onClicked: root.scheduleRequested(String(modelData.id), String(modelData.kind || "auto"))
              }
            }
          }
        }
      }
    }
  }
}
