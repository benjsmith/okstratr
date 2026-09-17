// P4: extracted harness allowlist editor (Omarchy plugin sibling of Panel.qml).
// Emits signals; Panel owns HTTP calls so Start/focus/dismiss stay untouched.
import QtQuick

Item {
  id: root
  property var harnessRows: []
  property string harnessConfigPath: "~/.config/okstratr/harnesses.toml"
  property string harnessActionMsg: ""
  property color themeFg: "#a9b1d6"
  property color themeMuted: "#565f89"
  property color themeAccent: "#7aa2f7"
  property color themeBg: "#13141c"
  property color themePanel: "#1a1b26"
  property color themeBorder: "#292e42"
  property color themeDivider: "#292e42"

  signal reloadClicked()
  signal toggleClicked(string harnessId, bool enable)
  signal modelCommit(string harnessId, string model)

  implicitHeight: col.height

  component MiniChip: Rectangle {
    id: chip
    property string label: ""
    signal clicked()
    width: chipLabel.implicitWidth + 16
    height: 26
    radius: 7
    color: "transparent"
    border.width: 1
    border.color: chipMa.containsMouse ? root.themeAccent : root.themeBorder
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

  Column {
    id: col
    width: parent.width
    spacing: 6

    Row {
      width: parent.width
      spacing: 8
      Text {
        text: "Harness allowlist (daemon API)"
        color: root.themeFg
        font.pixelSize: 13
        font.bold: true
      }
      Item { width: 8; height: 1 }
      MiniChip {
        label: "Reload"
        onClicked: root.reloadClicked()
      }
    }
    Text {
      width: parent.width
      wrapMode: Text.Wrap
      text: root.harnessConfigPath + "  ·  GET/POST /api/harness*  ·  model → POST /api/harness/set"
      color: root.themeAccent
      font.pixelSize: 11
    }
    Text {
      visible: !!root.harnessActionMsg
      width: parent.width
      wrapMode: Text.Wrap
      text: root.harnessActionMsg
      color: root.themeMuted
      font.pixelSize: 10
    }
    Row {
      width: parent.width
      spacing: 8
      Text { text: "On"; width: 52; color: root.themeMuted; font.pixelSize: 10 }
      Text { text: "Harness"; width: 100; color: root.themeMuted; font.pixelSize: 10 }
      Text { text: "Default model"; width: 180; color: root.themeMuted; font.pixelSize: 10 }
      Text { text: "Effort rungs"; color: root.themeMuted; font.pixelSize: 10 }
    }
    Repeater {
      model: root.harnessRows
      delegate: Rectangle {
        id: harnessRow
        required property var modelData
        width: col.width
        height: 44
        radius: 6
        color: root.themePanel
        border.width: 1
        border.color: root.themeDivider
        Row {
          anchors.fill: parent
          anchors.margins: 6
          spacing: 8
          Rectangle {
            width: 52
            height: 28
            radius: 8
            color: modelData.enabled ? "#3344aa88" : "transparent"
            border.width: 1
            border.color: modelData.enabled ? root.themeAccent : root.themeBorder
            Text {
              anchors.centerIn: parent
              text: modelData.enabled ? "ON" : "OFF"
              color: modelData.enabled ? root.themeAccent : root.themeMuted
              font.pixelSize: 11
              font.bold: true
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: root.toggleClicked(String(modelData.id), !modelData.enabled)
            }
          }
          Text {
            text: (modelData.label || modelData.id) + (modelData.installed ? "" : " · missing")
            width: 100
            height: 28
            verticalAlignment: Text.AlignVCenter
            color: root.themeFg
            font.pixelSize: 12
            elide: Text.ElideRight
          }
          // P4: editable model field → POST /api/harness/set harness.<id>.default_model
          Rectangle {
            width: 180
            height: 28
            radius: 6
            color: root.themeBg
            border.width: 1
            border.color: modelField.activeFocus ? root.themeAccent : root.themeBorder
            TextInput {
              id: modelField
              anchors.fill: parent
              anchors.margins: 6
              text: modelData.default_model || ""
              color: root.themeFg
              font.pixelSize: 11
              selectByMouse: true
              clip: true
              verticalAlignment: TextInput.AlignVCenter
              onEditingFinished: {
                var next = String(text || "").trim()
                var cur = String(modelData.default_model || "").trim()
                if (next && next !== cur)
                  root.modelCommit(String(modelData.id), next)
              }
            }
          }
          // Quick pick from models[] when present
          Row {
            spacing: 4
            visible: modelData.models && modelData.models.length > 0
            Repeater {
              model: (modelData.models || []).slice(0, 3)
              delegate: Rectangle {
                required property var modelData
                // modelData here is the string model id from models[]
                property string mid: String(modelData || "")
                width: Math.min(64, pickLabel.implicitWidth + 10)
                height: 22
                radius: 5
                color: "transparent"
                border.width: 1
                border.color: root.themeDivider
                Text {
                  id: pickLabel
                  anchors.centerIn: parent
                  text: parent.mid.length > 10 ? parent.mid.slice(0, 9) + "…" : parent.mid
                  color: root.themeMuted
                  font.pixelSize: 9
                }
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.modelCommit(String(harnessRow.modelData.id), parent.mid)
                }
              }
            }
          }
          Text {
            visible: !(modelData.models && modelData.models.length)
            text: {
              var e = modelData.effort || {}
              var parts = []
              if (e.trivial) parts.push("tri=" + e.trivial)
              if (e.normal) parts.push("nrm=" + e.normal)
              if (e.hard) parts.push("hrd=" + e.hard)
              return parts.length ? parts.join(" · ") : "—"
            }
            width: Math.max(80, harnessRow.width - 52 - 100 - 180 - 40)
            height: 28
            verticalAlignment: Text.AlignVCenter
            color: root.themeMuted
            font.pixelSize: 10
            elide: Text.ElideRight
          }
        }
      }
    }
    Text {
      visible: !root.harnessRows || root.harnessRows.length === 0
      text: "No harness rows yet — open Reload or use CLI: okstratr harness list"
      color: root.themeMuted
      font.pixelSize: 10
    }
  }
}
