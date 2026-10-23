import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import "MachinesModel.js" as MachinesModel

Item {
  id: root
  property var snapshot: ({machines: []})
  property var summary: ({machines: [], groups: [], online: 0, attention: 0})
  property double now: Date.now()
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property string tab: "all"
  readonly property var tabs: [{id: "all", name: "Todas", count: summary.machines.length}]
    // A cluster's nodes share one chip, where its first node would be; the chip opens their cards.
    .concat(summary.machines.filter((m, i) => !m.group || summary.machines.findIndex(x => x.group === m.group) === i)
      .map(m => m.group ? (summary.groups || []).find(g => g.name === m.group) : {id: m.id, name: m.name, state: m.state}))
    .concat([{id: "tailnet", name: "Tailnet", count: peers.length}])
  readonly property var selected: summary.machines.find(m => m.id === tab) || null
  readonly property string groupTab: tab.indexOf("group:") === 0 ? tab.slice(6) : ""
  readonly property var cards: tab === "all" ? summary.machines : groupTab ? summary.machines.filter(m => m.group === groupTab) : []
  readonly property var peers: ((snapshot.tailnet || {}).peers || []).map(p => MachinesModel.peerView(p, now))
  readonly property real gap: Style.space(10)
  readonly property int columns: Math.max(1, Math.floor((width + gap) / (Style.space(400) + gap)))
  readonly property real cardWidth: (list.width - Style.space(10) - gap * (columns - 1)) / columns
  readonly property color cpuColor: "#60a5fa"
  readonly property color memColor: "#c084fc"
  signal refreshRequested()
  signal closeRequested()

  function toneColor(tone) { return ({green: "#22c55e", yellow: "#eab308", red: "#ef4444"})[tone] || faint(.35) }
  function stateColor(state) { return ({ok: "#22c55e", yellow: "#eab308", red: "#ef4444", down: "#ef4444"})[state] || faint(.3) }
  function stateText(m) {
    return ({ok: "ok", yellow: "atenção", red: "alerta", down: "sem resposta", off: "desligado"})[m.state] || m.state
  }
  function faint(alpha) { return Qt.rgba(foreground.r, foreground.g, foreground.b, alpha) }
  function cycle(list, current, step) {
    var index = list.findIndex(x => x.id === current)
    return list[(index + step + list.length) % list.length].id
  }
  function cycleTab(step) { tab = cycle(tabs, tab, step) }
  function selectTab(index) { if (index < tabs.length) tab = tabs[index].id }
  function scrollBy(amount) { list.contentY = Math.max(0, Math.min(Math.max(0, list.contentHeight - list.height), list.contentY + amount)) }
  // Every action goes through act.py with plain arguments; it resolves the machine and quotes.
  readonly property string actScript: decodeURIComponent(Qt.resolvedUrl("act.py").toString().replace(/^file:\/\//, ""))
  property string toast: ""
  property bool toastOk: true
  property var pending: null       // {label, verb, args} waiting for a second click
  function act(m, verb, args, closeAfter) {
    if (actProcess.running) return
    actProcess.command = MachinesModel.actCommand(actScript, verb, m.id, args)
    actProcess.running = true
    if (closeAfter) closeRequested()
  }
  // Destructive actions ask for a second click within 4 s.
  function confirmAct(m, key, label, verb, args) {
    if (pending && pending.key === key) { pending = null; act(m, verb, args, false); return }
    pending = {key: key, label: label}
    confirmTimer.restart()
  }
  function isPending(key) { return pending !== null && pending.key === key }
  function openShell(m) { act(m, "open", ["shell"], true) }
  function openTop(m) { act(m, "open", ["top"], true) }
  function copySsh(m) { launch(["wl-copy", m.local ? m.host : m.adb ? "adb -s " + m.adb + " shell" : "ssh " + m.ssh]); showToast(true, "comando copiado") }
  function launch(command) { actions.command = command; actions.running = true }
  function showToast(ok, text) { toastOk = ok; toast = text; toastTimer.restart() }
  Timer { id: toastTimer; interval: 6000; onTriggered: root.toast = "" }
  Timer { id: confirmTimer; interval: 4000; onTriggered: root.pending = null }
  Process {
    id: actProcess
    stdout: StdioCollector {
      onStreamFinished: {
        try { var r = JSON.parse(text); root.showToast(r.ok, r.text) } catch (e) { root.showToast(false, "ação sem resposta") }
        if (!root.toast) return
        root.refreshRequested()
      }
    }
  }
  property string killFilter: ""
  onTabChanged: { list.contentY = 0; savePrefs() }
  onTabsChanged: if (prefsLoaded && !tabs.some(t => t.id === tab) && !summary.machines.some(m => m.id === tab)) tab = "all"
  Process { id: actions }

  property bool prefsLoaded: false
  function savePrefs() { if (prefsLoaded) prefs.setText(JSON.stringify({tab: tab})) }
  FileView {
    id: prefs
    path: Quickshell.env("HOME") + "/.local/state/omarchy-trackers/machines/view.json"
    printErrors: false
    onLoaded: {
      try { var saved = JSON.parse(text()); if (typeof saved.tab === "string") root.tab = saved.tab } catch (e) {}
      root.prefsLoaded = true
    }
    onLoadFailed: root.prefsLoaded = true
  }

  component Label: Text {
    color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption
    textFormat: Text.PlainText; elide: Text.ElideRight
  }

  component Chip: Rectangle {
    id: chip
    property string label: ""
    property bool selected: false
    property color dot: "transparent"
    signal clicked()
    width: chipText.implicitWidth + Style.space(22) + (dot.a > 0 ? Style.space(12) : 0); height: Style.space(26); radius: Style.space(6)
    color: selected ? root.faint(.14) : chipMouse.containsMouse ? root.faint(.07) : "transparent"
    border.width: 1; border.color: root.faint(selected ? .22 : .1)
    Row {
      anchors.centerIn: parent; spacing: Style.space(6)
      Rectangle { visible: chip.dot.a > 0; anchors.verticalCenter: parent.verticalCenter; width: Style.space(6); height: width; radius: width / 2; color: chip.dot }
      Text { id: chipText; text: chip.label; color: root.foreground; opacity: chip.selected ? 1 : .65; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.bold: chip.selected }
    }
    MouseArea { id: chipMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chip.clicked() }
  }

  component Badge: Rectangle {
    property string label: ""
    property color tint: root.foreground
    visible: label !== ""
    width: badgeText.implicitWidth + Style.space(12); height: Style.space(18); radius: height / 2
    color: Qt.rgba(tint.r, tint.g, tint.b, .1); border.width: 1; border.color: Qt.rgba(tint.r, tint.g, tint.b, .3)
    Text { id: badgeText; anchors.centerIn: parent; text: parent.label; color: parent.tint; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
  }

  // One usage row: dot, label, bar with detail underneath, percentage.
  component Meter: Item {
    id: meter
    property var metric: ({})
    height: Style.space(30)
    Rectangle { id: meterDot; anchors.verticalCenter: parent.verticalCenter; width: Style.space(8); height: width; radius: width / 2; color: root.toneColor(meter.metric.tone) }
    Text {
      id: meterLabel
      anchors.left: meterDot.right; anchors.leftMargin: Style.space(7); anchors.verticalCenter: parent.verticalCenter
      width: Style.space(52); text: meter.metric.label || ""; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.bold: true
    }
    Text {
      id: meterValue
      anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
      width: Style.space(44); horizontalAlignment: Text.AlignRight
      text: meter.metric.value || "—"; color: root.toneColor(meter.metric.tone); font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.bold: true
    }
    Item {
      anchors.left: meterLabel.right; anchors.leftMargin: Style.space(4)
      anchors.right: meterValue.left; anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter; height: Style.space(24)
      Rectangle {
        width: parent.width; height: Style.space(4); radius: height / 2
        color: Qt.rgba(root.toneColor(meter.metric.tone).r, root.toneColor(meter.metric.tone).g, root.toneColor(meter.metric.tone).b, .15)
        Rectangle { width: parent.width * Math.min(100, meter.metric.percent || 0) / 100; height: parent.height; radius: height / 2; color: root.toneColor(meter.metric.tone) }
      }
      Label { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; text: meter.metric.detail || ""; opacity: .5 }
    }
  }

  // CPU and memory over the last hour, 0–100%.
  component Spark: Canvas {
    id: spark
    property var cpu: []
    property var mem: []
    onCpuChanged: requestPaint()
    onMemChanged: requestPaint()
    onWidthChanged: requestPaint()
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      ctx.strokeStyle = Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, .08)
      ctx.lineWidth = 1
      for (var g = 1; g < 4; g++) { var gy = Math.round(height * g / 4) + .5; ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(width, gy); ctx.stroke() }
      function line(points, color) {
        if (!points || points.length < 2) return
        var step = width / (Math.max(points.length, 30) - 1), x0 = width - step * (points.length - 1)
        ctx.beginPath()
        for (var i = 0; i < points.length; i++) {
          var x = x0 + i * step, y = height - 2 - (height - 4) * Math.max(0, Math.min(100, points[i])) / 100
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
        }
        ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke()
        ctx.lineTo(width, height); ctx.lineTo(x0, height); ctx.closePath()
        ctx.fillStyle = Qt.rgba(color.r, color.g, color.b, .1); ctx.fill()
      }
      line(spark.mem, root.memColor)
      line(spark.cpu, root.cpuColor)
    }
  }

  component Legend: Row {
    spacing: Style.space(12)
    Repeater {
      model: [{label: "CPU", color: root.cpuColor}, {label: "RAM", color: root.memColor}]
      delegate: Row {
        required property var modelData
        spacing: Style.space(5)
        Rectangle { anchors.verticalCenter: parent.verticalCenter; width: Style.space(10); height: 2; color: modelData.color }
        Label { text: modelData.label; opacity: .55 }
      }
    }
  }

  component Section: Label { font.bold: true; opacity: .45; topPadding: Style.space(6) }

  component Action: Rectangle {
    id: action
    property string label: ""
    property string tip: ""
    property bool danger: false
    property bool armed: false
    property bool small: false
    signal clicked()
    readonly property color tint: danger && (actionMouse.containsMouse || armed) ? "#ef4444" : root.foreground
    width: actionText.implicitWidth + Style.space(small ? 14 : 22); height: Style.space(small ? 20 : 26); radius: Style.space(6)
    color: armed ? Qt.rgba(0.94, 0.27, 0.27, .25) : actionMouse.containsMouse ? Qt.rgba(tint.r, tint.g, tint.b, .12) : Qt.rgba(tint.r, tint.g, tint.b, .04)
    border.width: 1; border.color: Qt.rgba(tint.r, tint.g, tint.b, armed ? .6 : .14)
    Text { id: actionText; anchors.centerIn: parent; text: action.armed ? "confirmar?" : action.label; color: action.tint; opacity: action.small && !actionMouse.containsMouse && !action.armed ? .6 : 1; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
    MouseArea { id: actionMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: action.clicked() }
    ToolTip.visible: tip !== "" && actionMouse.containsMouse
    ToolTip.delay: 500
    ToolTip.text: tip
  }

  // A row in a list: label on the left, detail and buttons on the right.
  component ListRow: Rectangle {
    id: row
    property string label: ""
    property string sub: ""
    property string info: ""
    property color dot: "transparent"
    property bool strong: false
    default property alias buttons: rowButtons.data
    height: Style.space(26); radius: Style.space(5)
    color: rowMouse.containsMouse ? root.faint(.05) : "transparent"
    MouseArea { id: rowMouse; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
    Rectangle { visible: row.dot.a > 0; x: Style.space(4); anchors.verticalCenter: parent.verticalCenter; width: Style.space(6); height: width; radius: width / 2; color: row.dot }
    Label { id: rowLabel; x: Style.space(16); anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, parent.width * .4); text: row.label; font.bold: row.strong }
    Label { anchors.left: rowLabel.right; anchors.leftMargin: Style.space(6); anchors.right: rowDetail.left; anchors.rightMargin: Style.space(8); anchors.verticalCenter: parent.verticalCenter; text: row.sub; opacity: .5 }
    Label { id: rowDetail; anchors.right: rowButtons.left; anchors.rightMargin: Style.space(8); anchors.verticalCenter: parent.verticalCenter; text: row.info; opacity: .7; elide: Text.ElideNone }
    Row { id: rowButtons; anchors.right: parent.right; anchors.rightMargin: Style.space(4); anchors.verticalCenter: parent.verticalCenter; spacing: Style.space(4) }
  }

  // ---------- header ----------
  Column {
    id: header
    width: parent.width; spacing: Style.space(10)
    Item {
      width: parent.width; height: Style.space(28)
      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: "Máquinas · uso"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.heading; font.bold: true
      }
      Row {
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: Style.space(10)
        Text {
          anchors.verticalCenter: parent.verticalCenter
          text: root.summary.online + " de " + root.summary.machines.length + " online · "
            + (root.snapshot.updatedAt ? "atualizado " + Qt.formatDateTime(new Date(root.snapshot.updatedAt * 1000), "HH:mm:ss") : "aguardando leitura")
          color: root.foreground; opacity: .5; font.family: root.fontFamily; font.pixelSize: Style.font.caption
        }
        Chip { label: root.snapshot.refreshing ? "Atualizando…" : "↻ Atualizar"; onClicked: root.refreshRequested() }
      }
    }
    Flow {
      width: parent.width; spacing: Style.space(6)
      Repeater {
        model: root.tabs
        delegate: Chip {
          required property var modelData
          label: modelData.name + (modelData.count !== undefined ? "  " + modelData.count : "")
          selected: root.tab === modelData.id || (!!root.selected && "group:" + root.selected.group === modelData.id)
          dot: modelData.state ? root.stateColor(modelData.state) : "transparent"
          onClicked: root.tab = modelData.id
        }
      }
    }
  }

  Flickable {
    id: list
    anchors.top: header.bottom; anchors.topMargin: Style.space(12)
    anchors.bottom: footer.top; anchors.bottomMargin: Style.space(8)
    anchors.left: parent.left; anchors.right: parent.right
    clip: true; contentWidth: width
    contentHeight: root.cards.length ? grid.implicitHeight : root.tab === "tailnet" ? tailnetList.implicitHeight : detail.implicitHeight
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    // ---------- overview: one card per machine ----------
    Grid {
      id: grid
      visible: root.cards.length > 0
      columns: root.columns; spacing: root.gap
      Repeater {
        model: root.cards
        delegate: Rectangle {
          id: card
          required property var modelData
          width: root.cardWidth; height: body.implicitHeight + Style.space(24)
          radius: Style.space(8)
          color: cardMouse.containsMouse ? root.faint(.06) : root.faint(.035)
          border.width: 1; border.color: modelData.state === "down" || modelData.state === "red" ? Qt.rgba(0.94, 0.27, 0.27, .45) : root.faint(.09)
          opacity: modelData.online ? 1 : .6
          MouseArea { id: cardMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.tab = card.modelData.id }
          Column {
            id: body
            x: Style.space(12); y: Style.space(12); width: parent.width - Style.space(24); spacing: Style.space(6)
            Item {
              width: parent.width; height: Style.space(34)
              Rectangle {
                id: stateBox
                width: Style.space(34); height: width; radius: Style.space(7); color: root.faint(.06)
                Text { anchors.centerIn: parent; text: card.modelData.phone ? "" : card.modelData.local ? "" : card.modelData.api === "railway" ? "" : ""; color: root.stateColor(card.modelData.state); font.family: root.fontFamily; font.pixelSize: Style.font.title }
              }
              Column {
                anchors.left: stateBox.right; anchors.leftMargin: Style.space(10); anchors.right: badges.left; anchors.rightMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter; spacing: Style.space(2)
                Text { width: parent.width; text: card.modelData.name; elide: Text.ElideRight; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body; font.bold: true }
                Label { width: parent.width; text: card.modelData.target + (card.modelData.ip && card.modelData.target.indexOf(card.modelData.ip) < 0 ? " · " + card.modelData.ip : ""); opacity: .6 }
              }
              Row {
                id: badges
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: Style.space(4)
                Badge { label: root.stateText(card.modelData); tint: root.stateColor(card.modelData.state) }
                Badge { label: card.modelData.provider }
              }
            }
            Label { width: parent.width; text: card.modelData.role; opacity: .75 }
            Label { width: parent.width; text: card.modelData.summary; opacity: .45 }
            Repeater {
              model: card.modelData.metrics
              delegate: Meter { required property var modelData; width: body.width; metric: modelData }
            }
            Item {
              visible: card.modelData.cpuHistory.length > 1
              width: parent.width; height: Style.space(46)
              Spark { anchors.fill: parent; anchors.bottomMargin: Style.space(14); cpu: card.modelData.cpuHistory; mem: card.modelData.memHistory }
              Legend { anchors.bottom: parent.bottom }
              Label { anchors.right: parent.right; anchors.bottom: parent.bottom; text: "última hora"; opacity: .35 }
            }
            Repeater {
              model: card.modelData.alerts.slice(0, 3)
              delegate: Label { required property var modelData; width: body.width; text: "• " + modelData.text; color: modelData.tone === "none" ? root.foreground : root.toneColor(modelData.tone); opacity: modelData.tone === "none" ? .5 : .95 }
            }
            Label { visible: card.modelData.alerts.length > 3; text: "+ " + (card.modelData.alerts.length - 3) + " avisos no detalhe"; opacity: .45 }
            Rectangle { width: parent.width; height: 1; color: root.faint(.08) }
            Label {
              width: parent.width; opacity: .5
              text: card.modelData.online ? card.modelData.facts + (card.modelData.latencyMs ? " · leitura em " + (card.modelData.latencyMs / 1000).toFixed(1) + " s" : "")
                : card.modelData.ageText ? "última leitura há " + card.modelData.ageText : "nunca respondeu"
            }
          }
        }
      }
    }

    // ---------- one machine in detail ----------
    Column {
      id: detail
      visible: root.selected !== null
      width: list.width - Style.space(10); spacing: Style.space(10)
      readonly property var m: root.selected || ({metrics: [], alerts: [], cpuHistory: [], memHistory: [], terminals: [], tmux: [], procs: [], phone: false, readonly: false, api: "", group: "", data: null})
      readonly property var d: m.data || ({})
      Item {
        width: parent.width; height: Style.space(40)
        Column {
          anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; spacing: Style.space(2)
          Row {
            spacing: Style.space(8)
            Text { text: detail.m.name || ""; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.heading; font.bold: true }
            Badge { anchors.verticalCenter: parent.verticalCenter; label: root.selected ? root.stateText(detail.m) : ""; tint: root.stateColor(detail.m.state) }
            Badge { anchors.verticalCenter: parent.verticalCenter; label: detail.m.provider || "" }
          }
          Label {
            opacity: .6
            text: [detail.m.target, detail.m.host ? "host " + detail.m.host : "", detail.m.ip ? "tailnet " + detail.m.ip : "",
                   detail.m.tailnet ? (detail.m.tailnet.direct ? "direto" : detail.m.tailnet.relay ? "relay " + detail.m.tailnet.relay : "") : ""].filter(Boolean).join(" · ")
          }
        }
        // Machines read through a provider API have no shell to open.
        Row {
          visible: !detail.m.api
          anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: Style.space(6)
          Action { label: "Terminal"; tip: detail.m.phone ? "adb shell no celular" : "shell novo na máquina"; onClicked: root.openShell(detail.m) }
          Action { visible: !detail.m.phone; label: "tmux"; tip: "entra (ou cria) a sessão tmux \"radar\": continua viva se a janela fechar"; onClicked: root.act(detail.m, "open", ["tmux", "radar"], true) }
          Action { label: detail.m.phone ? "top" : "btop"; onClicked: root.openTop(detail.m) }
          Action { visible: detail.m.phone; label: "Tela"; tip: "espelha e controla o celular (scrcpy)"; onClicked: root.act(detail.m, "open", ["screen"], true) }
          Action { label: detail.m.local ? "Copiar host" : detail.m.phone ? "Copiar adb" : "Copiar ssh"; onClicked: root.copySsh(detail.m) }
        }
      }
      Label { width: parent.width; text: detail.m.role || ""; opacity: .75 }
      Label {
        width: parent.width; opacity: .45
        text: [detail.m.summary, detail.d.system ? detail.d.system.kernel : "", detail.d.system ? detail.d.system.cpuModel : "",
               detail.m.online ? "lido há " + detail.m.ageText + (detail.m.latencyMs ? " em " + (detail.m.latencyMs / 1000).toFixed(1) + " s" : "") : ""].filter(Boolean).join(" · ")
      }
      Label { visible: !detail.m.data; width: parent.width; text: detail.m.alerts.length ? detail.m.alerts[0].text : "Sem leitura ainda."; opacity: .7 }

      Row {
        visible: !!detail.m.data
        width: parent.width; spacing: Style.space(16)
        // Left: usage, history, disks, warnings.
        Column {
          width: (parent.width - parent.spacing) * .5; spacing: Style.space(6)
          Repeater { model: detail.m.metrics; delegate: Meter { required property var modelData; width: parent.width; metric: modelData } }
          Label {
            // Railway has no host to speak of, and a Swarm node's processes are its containers, listed beside.
            visible: detail.m.api !== "railway"
            width: parent.width; opacity: .5
            text: detail.d.cpu ? "iowait " + detail.d.cpu.iowait + "% · steal " + detail.d.cpu.steal + "% · carga " + detail.d.cpu.load.map(x => x.toFixed(2)).join(" / ")
              + (detail.m.api ? "" : " · " + detail.d.processes.total + " processos, " + detail.d.processes.running + " rodando") : ""
          }
          Label {
            width: parent.width; opacity: .5
            text: detail.d.net ? "rede ↓ " + MachinesModel.bytes(detail.d.net.rx) + "/s ↑ " + MachinesModel.bytes(detail.d.net.tx) + "/s"
              + (detail.m.api ? "" : " · disco lê " + MachinesModel.bytes(detail.d.io.read) + "/s, grava " + MachinesModel.bytes(detail.d.io.write) + "/s")
              + (detail.d.temperature ? " · " + Math.round(detail.d.temperature) + "°C" : "") : ""
          }
          Repeater {
            model: detail.d.gpus || []
            delegate: Label { required property var modelData; width: parent.width; opacity: .5; text: "GPU " + modelData.name + " · " + modelData.util + "% · " + MachinesModel.bytes(modelData.memUsed) + " / " + MachinesModel.bytes(modelData.memTotal) + (modelData.temp ? " · " + modelData.temp + "°C" : "") }
          }
          Item {
            visible: detail.m.cpuHistory.length > 1
            width: parent.width; height: Style.space(130)
            Spark { anchors.fill: parent; anchors.bottomMargin: Style.space(16); cpu: detail.m.cpuHistory; mem: detail.m.memHistory }
            Legend { anchors.bottom: parent.bottom }
            Label { anchors.right: parent.right; anchors.bottom: parent.bottom; text: detail.m.cpuHistory.length + " leituras, cerca de 1 por minuto"; opacity: .35 }
          }
          Section { text: "DISCOS" }
          Repeater {
            model: detail.d.disks || []
            delegate: Meter {
              required property var modelData
              width: parent.width
              readonly property var use: MachinesModel.diskUse(modelData)
              metric: ({label: modelData.mount === "/" ? "raiz" : modelData.mount.split("/").pop().slice(0, 6), percent: use.percent, tone: MachinesModel.tone("disk", use.percent), value: Math.round(use.percent) + "%",
                        detail: modelData.mount + " · " + modelData.fs + " · " + MachinesModel.diskDetail(modelData) + " · " + MachinesModel.bytes(modelData.free) + " livres"})
            }
          }
          Section { text: detail.m.alerts.length ? "AVISOS" : "AVISOS · nenhum" }
          Repeater {
            model: detail.m.alerts
            delegate: Label { required property var modelData; width: parent.width; text: "• " + modelData.text; color: modelData.tone === "none" ? root.foreground : root.toneColor(modelData.tone) }
          }
          Section { visible: (detail.d.failed || []).length > 0; text: "SERVIÇOS FALHANDO · " + (detail.d.failed || []).length }
          Repeater {
            model: detail.d.failed || []
            delegate: ListRow {
              id: unitRow
              required property var modelData
              readonly property string scope: (detail.d.failedUser || []).indexOf(modelData) >= 0 ? "user" : "system"
              readonly property string key: "unit:" + detail.m.id + ":" + modelData
              width: parent.width; label: MachinesModel.unitName(modelData); sub: detail.m.api === "railway" ? "deploy" : detail.m.api ? "Swarm" : scope === "user" ? "usuário" : "sistema"; dot: "#eab308"
              Action { small: true; visible: !detail.m.api; label: "log"; tip: "journalctl -f numa janela"; onClicked: root.act(detail.m, "unit", ["log", unitRow.modelData, unitRow.scope], true) }
              Action { small: true; visible: !detail.m.readonly && !detail.m.api; label: "reiniciar"; danger: true; armed: root.isPending(unitRow.key)
                       onClicked: root.confirmAct(detail.m, unitRow.key, "", "unit", ["restart", unitRow.modelData, unitRow.scope]) }
            }
          }
        }
        // Right: processes, containers, agents.
        Column {
          width: (parent.width - parent.spacing) * .5; spacing: Style.space(4)
          // API machines list their containers or services below instead of processes.
          Section { visible: !detail.m.api; text: "PROCESSOS POR CPU (% DE UM NÚCLEO)" }
          Repeater {
            model: detail.d.processes && !detail.m.api ? detail.d.processes.topCpu.slice(0, 8) : []
            delegate: Item {
              required property var modelData
              width: parent.width; height: Style.space(18)
              Label { width: parent.width * .6; text: modelData.name + (modelData.count > 1 ? " ×" + modelData.count : "") }
              Label { anchors.right: parent.right; text: modelData.cpu.toFixed(1) + "%  ·  " + MachinesModel.bytes(modelData.mem); opacity: .7 }
            }
          }
          Label { visible: !detail.m.api && !!detail.d.processes && !detail.d.processes.topCpu.length; text: "nada acima de 0,5% agora"; opacity: .45 }
          Section { visible: !detail.m.api; text: "PROCESSOS POR MEMÓRIA" }
          Repeater {
            model: detail.d.processes && !detail.m.api ? detail.d.processes.topMem.slice(0, 8) : []
            delegate: Item {
              required property var modelData
              width: parent.width; height: Style.space(18)
              Label { width: parent.width * .6; text: modelData.name + (modelData.count > 1 ? " ×" + modelData.count : "") }
              Label { anchors.right: parent.right; text: MachinesModel.bytes(modelData.mem) + "  ·  " + modelData.cpu.toFixed(1) + "%"; opacity: .7 }
            }
          }
          Section {
            visible: !!detail.d.containers
            text: (detail.m.api === "railway" ? "SERVIÇOS · " : "CONTAINERS · ") + (detail.d.containers || []).filter(c => c.state === "running").length + " de " + (detail.d.containers || []).length + (detail.m.api === "railway" ? " no ar" : " rodando")
          }
          Repeater {
            model: (detail.d.containers || []).slice(0, 16)
            delegate: Item {
              required property var modelData
              width: parent.width; height: Style.space(18)
              Rectangle { anchors.verticalCenter: parent.verticalCenter; width: Style.space(6); height: width; radius: width / 2
                color: /unhealthy/.test(modelData.status || "") || modelData.state === "restarting" ? "#ef4444" : modelData.state === "running" ? "#22c55e" : root.faint(.3) }
              Label { x: Style.space(12); width: parent.width * .55; text: modelData.name; opacity: modelData.state === "running" ? 1 : .5 }
              Label {
                anchors.right: parent.right; opacity: .6
                text: modelData.state === "running" ? [modelData.cpu !== null && modelData.cpu !== undefined ? modelData.cpu.toFixed(1) + "%" : "", modelData.mem ? MachinesModel.bytes(modelData.mem) : ""].filter(Boolean).join("  ·  ") : (modelData.status || modelData.state)
              }
            }
          }
          Label { visible: (detail.d.containers || []).length > 16; text: "+ " + ((detail.d.containers || []).length - 16) + " containers"; opacity: .45 }
          Section { visible: Object.keys(detail.d.agents || {}).length > 0; text: "AGENTES ABERTOS" }
          Label {
            visible: Object.keys(detail.d.agents || {}).length > 0; width: parent.width; opacity: .75
            text: Object.keys(detail.d.agents || {}).map(k => k + " ×" + detail.d.agents[k]).join(" · ")
          }
        }
      }

      // ---------- terminals, tmux and processes: full width, with actions ----------
      Rectangle { visible: !!detail.m.data && !detail.m.phone && !detail.m.api; width: parent.width; height: 1; color: root.faint(.08) }
      Row {
        visible: !!detail.m.data && !detail.m.phone && !detail.m.api
        width: parent.width; spacing: Style.space(16)
        Column {
          width: (parent.width - parent.spacing) * .5; spacing: Style.space(2)
          Section { text: "TERMINAIS ABERTOS · " + detail.m.terminals.length + (detail.m.terminals.filter(t => t.agent).length ? " · " + detail.m.terminals.filter(t => t.agent).length + " com agente" : "") }
          Label { visible: !detail.m.terminals.length; text: "nenhum terminal (pts) aberto"; opacity: .45 }
          Repeater {
            model: detail.m.terminals.slice(0, 24)
            delegate: ListRow {
              id: ttyRow
              required property var modelData
              readonly property string key: "tty:" + detail.m.id + ":" + modelData.pid
              width: parent.width
              label: modelData.tty + "  " + (modelData.running || modelData.shell)
              strong: modelData.agent
              sub: modelData.user + (modelData.running ? " · em " + modelData.shell : "")
              info: [modelData.idleText, modelData.ageText].filter(Boolean).join(" · ")
              dot: modelData.idleText === "ativo" ? "#22c55e" : root.faint(.25)
              Action { small: true; visible: !detail.m.readonly && !!ttyRow.modelData.running; label: "parar " + ttyRow.modelData.running; danger: true
                       tip: "SIGTERM só no programa da frente (" + ttyRow.modelData.running + "), o terminal fica"
                       armed: root.isPending(ttyRow.key + ":fg")
                       onClicked: root.confirmAct(detail.m, ttyRow.key + ":fg", "", "kill", [ttyRow.modelData.fgPid, ttyRow.modelData.fg, "TERM"]) }
              Action { small: true; visible: !detail.m.readonly; label: "fechar"; danger: true; tip: "SIGHUP no terminal inteiro, como fechar a janela"
                       armed: root.isPending(ttyRow.key)
                       onClicked: root.confirmAct(detail.m, ttyRow.key, "", "tty-hup", [ttyRow.modelData.pid, ttyRow.modelData.shell]) }
            }
          }
          Label { visible: detail.m.terminals.length > 24; text: "+ " + (detail.m.terminals.length - 24) + " terminais"; opacity: .45 }

          Section { visible: detail.m.tmux.length > 0; text: "SESSÕES TMUX · " + detail.m.tmux.length }
          Repeater {
            model: detail.m.tmux
            delegate: ListRow {
              id: tmuxRow
              required property var modelData
              readonly property string key: "tmux:" + detail.m.id + ":" + modelData.name
              width: parent.width; label: modelData.name + (modelData.socket !== "default" ? "  (-L " + modelData.socket + ")" : ""); strong: modelData.attached
              sub: modelData.windows + (modelData.windows === 1 ? " janela" : " janelas") + " · " + modelData.command
              info: (modelData.attached ? "conectada · " : "") + "ativa há " + modelData.idleText
              dot: modelData.attached ? "#22c55e" : root.faint(.25)
              Action { small: true; label: "entrar"; onClicked: root.act(detail.m, "open", ["tmux", tmuxRow.modelData.name, tmuxRow.modelData.socket], true) }
              Action { small: true; visible: !detail.m.readonly; label: "encerrar"; danger: true; armed: root.isPending(tmuxRow.key)
                       onClicked: root.confirmAct(detail.m, tmuxRow.key, "", "tmux-kill", [tmuxRow.modelData.name, tmuxRow.modelData.socket]) }
            }
          }
        }
        Column {
          width: (parent.width - parent.spacing) * .5; spacing: Style.space(2)
          Item {
            width: parent.width; height: Style.space(26)
            Section { anchors.verticalCenter: parent.verticalCenter; topPadding: 0; text: detail.m.readonly ? "PROCESSOS · só leitura (máquina compartilhada)" : "PROCESSOS · encerrar" }
            Rectangle {
              anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
              width: Style.space(170); height: Style.space(22); radius: Style.space(5); color: root.faint(.05); border.width: 1; border.color: root.faint(.12)
              TextInput {
                id: filterInput
                anchors.fill: parent; anchors.leftMargin: Style.space(8); anchors.rightMargin: Style.space(8); verticalAlignment: TextInput.AlignVCenter
                color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; clip: true
                onTextChanged: root.killFilter = text.toLowerCase()
                Keys.onEscapePressed: { text = ""; focus = false }
              }
              Label { visible: !filterInput.text; anchors.verticalCenter: parent.verticalCenter; x: Style.space(8); text: "filtrar por nome…"; opacity: .35 }
            }
          }
          Repeater {
            model: detail.m.procs.filter(p => !root.killFilter || p.name.toLowerCase().indexOf(root.killFilter) >= 0 || String(p.pid) === root.killFilter).slice(0, 24)
            delegate: ListRow {
              id: procRow
              required property var modelData
              readonly property string key: "pid:" + detail.m.id + ":" + modelData.pid
              width: parent.width; label: modelData.name; sub: modelData.pid + " · " + modelData.user + (modelData.tty ? " · " + modelData.tty : "")
              info: modelData.cpu.toFixed(1) + "% · " + MachinesModel.bytes(modelData.mem)
              Action { small: true; visible: !detail.m.readonly; label: "encerrar"; danger: true; tip: "SIGTERM: pede pro processo sair"; armed: root.isPending(procRow.key)
                       onClicked: root.confirmAct(detail.m, procRow.key, "", "kill", [procRow.modelData.pid, procRow.modelData.name, "TERM"]) }
              Action { small: true; visible: !detail.m.readonly; label: "matar"; danger: true; tip: "SIGKILL: força, sem chance de salvar"; armed: root.isPending(procRow.key + ":k")
                       onClicked: root.confirmAct(detail.m, procRow.key + ":k", "", "kill", [procRow.modelData.pid, procRow.modelData.name, "KILL"]) }
            }
          }
        }
      }

      // ---------- phone: battery and apps ----------
      Rectangle { visible: detail.m.phone && !!detail.m.data; width: parent.width; height: 1; color: root.faint(.08) }
      Column {
        visible: detail.m.phone && !!detail.m.data
        width: parent.width; spacing: Style.space(2)
        Label {
          width: parent.width; opacity: .7
          text: detail.d.battery ? "Bateria " + detail.d.battery.level + "%" + (detail.d.battery.status ? " · " + detail.d.battery.status : "")
            + (detail.d.battery.temp ? " · " + detail.d.battery.temp.toFixed(1) + "°C" : "") : ""
        }
        Section { text: "APPS E PROCESSOS · fechar app usa force-stop; processo do sistema o adb não encerra" }
        Repeater {
          model: detail.m.procs.slice(0, 20)
          delegate: ListRow {
            id: appRow
            required property var modelData
            readonly property bool app: /^[a-zA-Z][\w]*(\.[\w]+)+(:[\w.]+)?$/.test(modelData.name)
            readonly property string key: "app:" + detail.m.id + ":" + modelData.pid
            width: parent.width; label: modelData.name; strong: app; sub: modelData.pid + " · " + modelData.user; info: modelData.detail
            Action { small: true; visible: appRow.app; label: "fechar app"; danger: true; armed: root.isPending(appRow.key)
                     onClicked: root.confirmAct(detail.m, appRow.key, "", "kill", [appRow.modelData.pid, appRow.modelData.name, "TERM"]) }
          }
        }
      }
    }

    // ---------- tailnet ----------
    Column {
      id: tailnetList
      visible: root.tab === "tailnet"
      width: list.width - Style.space(10); spacing: Style.space(2)
      Label { visible: !root.peers.length; text: "Tailscale não respondeu."; opacity: .6 }
      Repeater {
        model: root.tab === "tailnet" ? root.peers : []
        delegate: Rectangle {
          required property var modelData
          required property int index
          width: tailnetList.width; height: Style.space(30); radius: Style.space(6)
          color: index % 2 ? "transparent" : root.faint(.03)
          Rectangle { x: Style.space(10); anchors.verticalCenter: parent.verticalCenter; width: Style.space(8); height: width; radius: width / 2; color: modelData.online ? "#22c55e" : root.faint(.25) }
          Label { x: Style.space(28); anchors.verticalCenter: parent.verticalCenter; width: parent.width * .3; text: modelData.name + (modelData.machine && modelData.machine !== modelData.name ? "  ·  " + modelData.machine : ""); font.bold: modelData.self || !!modelData.machine; opacity: modelData.online ? 1 : .55 }
          Label { x: parent.width * .36; anchors.verticalCenter: parent.verticalCenter; width: parent.width * .14; text: modelData.os; opacity: .6 }
          Label { x: parent.width * .52; anchors.verticalCenter: parent.verticalCenter; width: parent.width * .2; text: modelData.ip; opacity: .6 }
          Label { anchors.right: parent.right; anchors.rightMargin: Style.space(10); anchors.verticalCenter: parent.verticalCenter; text: modelData.link; opacity: .6 }
        }
      }
    }
  }

  Text {
    id: footer
    anchors.bottom: parent.bottom; width: parent.width; elide: Text.ElideRight
    text: root.toast ? (root.toastOk ? "✓ " : "✗ ") + root.toast
      : root.pending ? "clique de novo pra confirmar (4 s)"
      : "← → aba · 0–9 escolhe · T tailnet · ↑ ↓ rola · R atualiza · clique no card abre o detalhe · leitura a cada 1 min"
    color: root.toast ? (root.toastOk ? "#22c55e" : "#ef4444") : root.pending ? "#eab308" : root.foreground
    opacity: root.toast || root.pending ? .95 : .4; font.family: root.fontFamily; font.pixelSize: Style.font.caption
  }
}
