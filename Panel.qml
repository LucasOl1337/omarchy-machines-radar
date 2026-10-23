import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "MachinesModel.js" as MachinesModel

Panel {
  id: root
  moduleName: "lol.machines"
  ipcTarget: "lol.machines"
  manageIpc: false
  IpcHandler {
    enabled: root.ipcTarget !== ""
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function select(id: string): void { content.tab = id }
    function diagnostics(): string {
      return JSON.stringify({version: "1.3.0", sourceUrl: Qt.resolvedUrl("Panel.qml").toString(), tab: content.tab, columns: content.columns,
                             machines: summary.machines.map(m => ({id: m.id, state: m.state, online: m.online})), updatedAt: root.snapshot.updatedAt})
    }
  }
  property var snapshot: ({machines: []})
  property double now: Date.now()
  readonly property var summary: MachinesModel.buildMachines(snapshot, now)
  readonly property bool alarm: summary.machines.some(m => m.state === "down" || m.state === "red")
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  function refresh() { if (!refreshProcess.running) refreshProcess.running = true }
  onOpenedChanged: if (opened && (!snapshot.updatedAt || Date.now() - snapshot.updatedAt * 1000 > 30000)) refresh()
  Timer { interval: 30000; running: true; repeat: true; onTriggered: root.now = Date.now() }
  // The state file may not exist yet on first install; keep retrying until it does.
  Timer { interval: 5000; running: !root.snapshot.updatedAt; repeat: true; onTriggered: statusFile.reload() }
  FileView {
    id: statusFile
    printErrors: false
    path: Quickshell.env("HOME") + "/.local/state/omarchy-trackers/machines/status.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try { root.snapshot = JSON.parse(text()); root.now = Date.now() } catch (e) { console.warn("Máquinas: JSON inválido") }
    }
  }
  Process { id: refreshProcess; command: ["systemctl", "--user", "start", "--no-block", "omarchy-machines.service"] }
  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    active: root.alarm
    tooltipText: "Máquinas · " + root.summary.online + " de " + root.summary.machines.length + " online"
      + (root.summary.attention ? " · " + root.summary.attention + " pedem atenção" : "")
    onPressed: function(b) { if (b === Qt.MiddleButton) root.refresh(); else root.toggle() }
  }
  KeyboardPanel {
    id: popup
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keys
    contentWidth: popup.fittedContentWidth(Style.space(1480))
    contentHeight: popup.fittedContentHeight(Style.space(940))
    PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) {
        if (dy) content.scrollBy(dy * Style.space(120))
        if (dx) content.cycleTab(dx)
      }
      onTextKey: function(t) {
        var key = t.toLowerCase()
        if (key === "r") root.refresh()
        else if (key === "t") content.tab = "tailnet"
        else if (/^[0-9]$/.test(key)) content.selectTab(Number(key))
      }
      Content {
        id: content
        anchors.fill: parent
        snapshot: root.snapshot
        summary: root.summary
        now: root.now
        foreground: root.bar ? root.bar.foreground : Color.foreground
        fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
        onRefreshRequested: root.refresh()
        onCloseRequested: root.close()
      }
    }
  }
}
