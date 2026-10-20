// Pure view model for the machines panel. Loaded by QML and by the Node tests.

var GB = 1024 * 1024 * 1024;
var STALE_MS = 5 * 60000;

// Usage thresholds, per metric: [yellow from, red from].
// A filling disk is something to plan for, not an emergency: it never turns red.
var LIMITS = {cpu: [70, 90], memory: [75, 90], disk: [75, Infinity], swap: [50, 80]};
var DISK_ALERT = 85;
// Memory pressure (PSI some avg60, % of the last minute with a task waiting for RAM): [yellow, red].
// A full swap with no pressure is just idle pages parked there and stays green.
var PRESSURE = [2, 10];

// Swap tone from what actually hurts: memory pressure (swapping that costs shows up there),
// or a full swap with no RAM left. The in/out rate over a 1 s window is too jumpy to alert on.
// Probes without PSI fall back to the used percentage.
function swapTone(d) {
  var mem = d.memory || {};
  var pct = percentOf(mem.swapUsed, mem.swapTotal);
  if (typeof mem.pressure !== "number") return tone("swap", pct);
  if (mem.pressure >= PRESSURE[1]) return "red";
  var cornered = pct >= 95 && mem.available < .1 * mem.total;
  return mem.pressure >= PRESSURE[0] || cornered ? "yellow" : "green";
}

function tone(kind, percent) {
  if (typeof percent !== "number" || !isFinite(percent)) return "none";
  var limit = LIMITS[kind] || LIMITS.cpu;
  return percent >= limit[1] ? "red" : percent >= limit[0] ? "yellow" : "green";
}

function worst(tones) {
  return tones.indexOf("red") >= 0 ? "red" : tones.indexOf("yellow") >= 0 ? "yellow" : tones.indexOf("green") >= 0 ? "green" : "none";
}

function gb(bytes) {
  var n = (bytes || 0) / GB;
  return n >= 100 ? Math.round(n) + "" : n.toFixed(1);
}

function bytes(n) {
  n = n || 0;
  if (n >= GB) return (n / GB).toFixed(1) + " GB";
  if (n >= 1048576) return (n / 1048576).toFixed(n >= 104857600 ? 0 : 1) + " MB";
  if (n >= 1024) return Math.round(n / 1024) + " kB";
  return Math.round(n) + " B";
}

function rate(n) { return bytes(n) + "/s"; }

function duration(seconds) {
  seconds = Math.max(0, Math.round(seconds || 0));
  if (seconds < 60) return seconds + "s";
  var m = Math.floor(seconds / 60);
  if (m < 60) return m + "min";
  var h = Math.floor(m / 60);
  if (h < 48) return h + "h " + (m % 60) + "min";
  return Math.floor(h / 24) + "d " + (h % 24) + "h";
}

// systemd escapes "-" inside unit names as \x2d; show the readable form.
function unitName(unit) { return String(unit).replace(/\\x([0-9a-f]{2})/gi, (m, hex) => String.fromCharCode(parseInt(hex, 16))); }

function percentOf(used, total) { return total > 0 ? Math.round(1000 * used / total) / 10 : null; }

// A disk holding loop images (one per user on a shared VPS) counts them as
// reserved, not used: the percentage is over the space left for the system.
function diskUse(disk) {
  var reserved = disk.reserved || 0;
  var used = Math.max(0, disk.used - reserved);
  return {used: used, reserved: reserved, size: used + disk.free,
          percent: reserved ? Math.round(1000 * used / Math.max(1, used + disk.free)) / 10 : disk.percent};
}

function diskDetail(disk) {
  var u = diskUse(disk);
  var holds = (disk.holds || []).map(m => m.split("/").pop()).join(" e ");
  return gb(u.used) + " / " + gb(u.size) + " GB" + (u.reserved ? " + " + gb(u.reserved) + " GB reservados pra " + holds : "")
    + (disk.image ? " · imagem " + disk.image : "");
}

function metrics(d) {
  var out = [];
  var cpu = d.cpu || {};
  var load = cpu.load || [];
  out.push({key: "cpu", label: "CPU", percent: cpu.percent, tone: tone("cpu", cpu.percent),
            detail: "carga " + (load[0] !== undefined ? load[0].toFixed(2) : "—") + " · " + (cpu.cores || "?") + " núcleos",
            value: Math.round(cpu.percent || 0) + "%"});
  var mem = d.memory || {};
  var memPct = percentOf(mem.used, mem.total);
  out.push({key: "memory", label: "RAM", percent: memPct, tone: tone("memory", memPct),
            detail: gb(mem.used) + " / " + gb(mem.total) + " GB", value: Math.round(memPct || 0) + "%"});
  var disks = (d.disks || []).slice().sort((a, b) => diskUse(b).percent - diskUse(a).percent);
  if (disks.length) {
    var disk = disks[0];
    var use = diskUse(disk);
    out.push({key: "disk", label: "Disco", percent: use.percent, tone: tone("disk", use.percent),
              detail: disk.mount + " · " + diskDetail(disk), value: Math.round(use.percent) + "%"});
  }
  if (mem.swapTotal > 0) {
    var swapPct = percentOf(mem.swapUsed, mem.swapTotal);
    var io = d.swap || {};
    out.push({key: "swap", label: "Swap", percent: swapPct, tone: swapTone(d),
              detail: gb(mem.swapUsed) + " / " + gb(mem.swapTotal) + " GB"
                + (typeof mem.pressure === "number" ? " · pressão " + mem.pressure.toFixed(1) + "%" : "")
                + ((io.in || 0) + (io.out || 0) > 0 ? " · entra " + rate(io.in) + ", sai " + rate(io.out) : ""),
              value: Math.round(swapPct || 0) + "%"});
  }
  return out;
}

function alerts(machine, d, stale) {
  var out = [];
  if (!machine.online) {
    var vps = machine.kind !== "local";
    out.push({text: (vps ? "Sem resposta" : "Desligado ou fora da rede") + (machine.error ? ": " + machine.error : ""), tone: vps ? "red" : "none"});
  }
  if (!d) return out;
  var cpu = d.cpu || {};
  (d.disks || []).forEach(function(disk) {
    var percent = diskUse(disk).percent;
    if (percent >= DISK_ALERT) out.push({text: "Disco " + disk.mount + " em " + Math.round(percent) + "%, " + gb(disk.free) + " GB livres", tone: "yellow"});
  });
  var mem = d.memory || {};
  var memPct = percentOf(mem.used, mem.total);
  if (memPct >= LIMITS.memory[1]) out.push({text: "Memória em " + Math.round(memPct) + "%", tone: "red"});
  var swapPct = percentOf(mem.swapUsed, mem.swapTotal);
  if (typeof mem.pressure === "number") {
    if (mem.pressure >= PRESSURE[0]) out.push({text: "Memória sob pressão: " + Math.round(mem.pressure) + "% do último minuto esperando RAM", tone: mem.pressure >= PRESSURE[1] ? "red" : "yellow"});
    else if (swapPct >= 95 && mem.available < .1 * mem.total) out.push({text: "Swap cheia e só " + gb(mem.available) + " GB de RAM livre: um pico vira OOM", tone: "yellow"});
  } else if (swapPct >= LIMITS.swap[1]) out.push({text: "Swap em " + Math.round(swapPct) + "%", tone: "yellow"});
  // Android counts uninterruptible kernel threads in the load average: it says nothing there.
  if (d.platform !== "android" && cpu.load && cpu.cores && cpu.load[1] > 1.5 * cpu.cores) out.push({text: "Carga " + cpu.load[1].toFixed(1) + " para " + cpu.cores + " núcleos", tone: "yellow"});
  if (cpu.steal >= 10) out.push({text: "Steal de " + Math.round(cpu.steal) + "%: o host da VPS está disputado", tone: "yellow"});
  if (d.temperature >= 85) out.push({text: "CPU a " + Math.round(d.temperature) + "°C", tone: "red"});
  var bat = d.battery;
  if (bat && bat.level !== null && !bat.plugged && bat.level <= 15) out.push({text: "Bateria em " + bat.level + "%, fora da tomada", tone: "yellow"});
  if (bat && bat.temp >= 45) out.push({text: "Bateria a " + Math.round(bat.temp) + "°C", tone: "yellow"});
  var failed = (d.failed || []).map(unitName);
  if (failed.length) out.push({text: (failed.length === 1 ? "Serviço falhando: " : failed.length + " serviços falhando: ") + failed.slice(0, 3).join(", ") + (failed.length > 3 ? "…" : ""), tone: "yellow"});
  (d.containers || []).forEach(function(c) {
    if (/unhealthy/.test(c.status || "")) out.push({text: "Container sem saúde: " + c.name, tone: "red"});
    else if (c.state === "restarting") out.push({text: "Container reiniciando: " + c.name, tone: "red"});
  });
  if (stale && machine.online) out.push({text: "Leitura antiga", tone: "none"});
  return out;
}

function machineView(machine, now) {
  var d = machine.data;
  var stale = !machine.probedAt || now - machine.probedAt * 1000 > STALE_MS;
  var list = d ? metrics(d) : [];
  var warnings = alerts(machine, d, stale);
  var sys = d ? d.system || {} : {};
  var containers = d && d.containers ? d.containers : [];
  var running = containers.filter(c => c.state === "running").length;
  var agentCount = d ? Object.keys(d.agents || {}).reduce((sum, k) => sum + d.agents[k], 0) : 0;
  var facts = [];
  if (d) {
    facts.push("↓ " + rate(d.net.rx) + "  ↑ " + rate(d.net.tx));
    if (d.containers) facts.push(running + "/" + containers.length + " containers");
    if (agentCount) facts.push(agentCount + (agentCount === 1 ? " agente" : " agentes"));
    if (d.temperature) facts.push(Math.round(d.temperature) + "°C");
    if (d.battery && d.battery.level !== null) facts.push("bateria " + d.battery.level + "%" + (d.battery.plugged ? " ⚡" : ""));
  }
  var online = machine.online;
  var state = !online ? (machine.kind === "local" ? "off" : "down") : warnings.some(w => w.tone === "red") ? "red" : warnings.some(w => w.tone === "yellow") ? "yellow" : "ok";
  return {
    id: machine.id, name: machine.name, role: machine.role || "", provider: machine.provider || sys.vendor || "",
    target: machine.target || machine.ssh || "", ssh: machine.ssh || "", adb: machine.adb || "", local: !!machine.local, kind: machine.kind,
    phone: !!machine.adb || (d && d.platform === "android") || false, readonly: !!machine.readonly,
    online: online, state: state, stale: stale, latencyMs: machine.latencyMs,
    ageText: machine.probedAt ? duration((now - machine.probedAt * 1000) / 1000) : "",
    host: sys.hostname || "", ip: (machine.tailnet && machine.tailnet.ip) || sys.tailscaleIp || "",
    tailnet: machine.tailnet,
    summary: d ? [sys.os, sys.cores ? sys.cores + " núcleos" : "", sys.uptime ? "ligado há " + duration(sys.uptime) : ""].filter(Boolean).join(" · ") : "Ainda sem leitura",
    metrics: list, alerts: warnings, facts: facts.join(" · "),
    cpuHistory: (machine.history || []).map(p => p[1]),
    memHistory: (machine.history || []).map(p => p[2]),
    data: d,
    terminals: d ? terminalRows(d) : [],
    tmux: d ? (d.tmux || []).map(t => ({name: t.name, socket: t.socket || "default", windows: t.windows, attached: t.attached, command: t.command, idleText: duration(t.idle)})) : [],
    procs: d ? procRows(d) : []
  };
}

// Open pseudo-terminals, busiest (least idle) first.
function terminalRows(d) {
  return (d.terminals || []).map(t => ({
    tty: t.tty, pid: t.pid, user: t.user, shell: t.shell, fg: t.fg, fgPid: t.fgPid, agent: !!t.agent,
    running: t.fg && t.fg !== t.shell ? t.fg : "",
    idleText: t.idle === null || t.idle === undefined ? "" : t.idle < 60 ? "ativo" : "parado há " + duration(t.idle),
    ageText: t.age ? "aberto há " + duration(t.age) : ""
  }));
}

// Single processes for the kill list: CPU-heavy first, then memory.
function procRows(d) {
  return (d.procs || []).slice().sort((a, b) => (b.cpu - a.cpu) || (b.mem - a.mem)).map(p => ({
    pid: p.pid, name: p.name, user: p.user, cpu: p.cpu, mem: p.mem, tty: p.tty || "",
    detail: p.cpu.toFixed(1) + "% · " + bytes(p.mem) + (p.age ? " · há " + duration(p.age) : "")
  }));
}

// Command line for act.py; the panel never builds shell strings itself.
function actCommand(script, verb, id, args) {
  return ["/usr/bin/python3", script, verb, id].concat((args || []).map(String));
}

var STATE_ORDER = {down: 0, red: 1, yellow: 2, ok: 3, off: 4};

function buildMachines(snapshot, now) {
  var list = ((snapshot && snapshot.machines) || []).map(m => machineView(m, now));
  return {
    machines: list,
    online: list.filter(m => m.online).length,
    attention: list.filter(m => m.state === "down" || m.state === "red" || m.state === "yellow").length
  };
}

function peerView(peer, now) {
  var seen = peer.lastSeen ? Date.parse(peer.lastSeen) : 0;
  return {
    name: peer.name, machine: peer.machine || "", os: peer.os, ip: peer.ip, online: peer.online, self: peer.self,
    link: peer.self ? "este PC" : !peer.online ? (seen ? "visto há " + duration((now - seen) / 1000) : "offline") : peer.direct ? "direto" : peer.relay ? "relay " + peer.relay : "online"
  };
}

if (typeof module !== "undefined") module.exports = {terminalRows: terminalRows, procRows: procRows, actCommand: actCommand, tone: tone, worst: worst, bytes: bytes, duration: duration, metrics: metrics, alerts: alerts, machineView: machineView, buildMachines: buildMachines, peerView: peerView, unitName: unitName, diskUse: diskUse, diskDetail: diskDetail, STATE_ORDER: STATE_ORDER};
