"""Snapshot of an Android phone over adb, in the same shape probe.py gives.

One `adb shell` call reads /proc, df, dumpsys battery and top with a
one-second window. Only the shell user's view is available: no root, no
per-app network, no containers or systemd. Processes are names only.
"""
from __future__ import annotations

import re
import subprocess
import time

SEP = "@@radar@@"
SCRIPT = "; ".join([
    "head -1 /proc/stat", "cat /proc/net/dev", "echo " + SEP,
    "top -b -n 2 -d 1 -m 30 -s 3 -o PID,USER,%CPU,RES,NAME 2>/dev/null", "echo " + SEP,
    "head -1 /proc/stat", "cat /proc/net/dev", "echo " + SEP,
    "cat /proc/meminfo", "echo " + SEP,
    "df -k /data", "echo " + SEP,
    "dumpsys battery", "echo " + SEP,
    "cat /proc/uptime /proc/loadavg", "echo " + SEP,
    "getprop ro.product.marketname; getprop ro.product.model; getprop ro.build.version.release; "
    "getprop ro.mi.os.version.name; getprop ro.soc.model; getprop ro.product.manufacturer; nproc; uname -r", "echo " + SEP,
    "ps -A -o PID,USER,RSS,NAME -k -rss 2>/dev/null | head -31", "echo " + SEP,
    "ps -A -o PID 2>/dev/null | wc -l",
])
NET_IFACES = ("wlan", "rmnet", "ccmni", "eth", "tun")


def adb(serial, *args, timeout=30):
    return subprocess.run(["adb", "-s", serial, *args], capture_output=True, text=True, timeout=timeout)


def _cpu(line):
    cols = [int(x) for x in line.split()[1:9]]
    return cols


def _net(text):
    rx = tx = 0
    for line in text.splitlines():
        name, sep, data = line.partition(":")
        if not sep or not name.strip().startswith(NET_IFACES):
            continue
        cols = data.split()
        if len(cols) >= 9:
            rx += int(cols[0])
            tx += int(cols[8])
    return rx, tx


def _size(text):
    m = re.match(r"^([\d.]+)([KMGT]?)$", text.strip())
    if not m:
        return 0
    return int(float(m.group(1)) * 1024 ** "BKMGT".index(m.group(2) or "B"))


def _top(text):
    """Last iteration of `top -b -n 2`: pid, user, cpu %, rss, name."""
    blocks = re.split(r"\n(?=Tasks:)", text)
    rows = []
    for line in blocks[-1].splitlines():
        cols = line.split(None, 4)
        if len(cols) == 5 and cols[0].isdigit():
            try:
                rows.append({"pid": int(cols[0]), "user": cols[1], "cpu": float(cols[2]), "mem": _size(cols[3]), "name": cols[4].strip().strip("[]")})
            except ValueError:
                continue
    return rows


def parse(raw, elapsed=1.0):
    parts = raw.split(SEP)
    if len(parts) < 10:
        raise ValueError("resposta incompleta do adb")
    first, top_text, second, meminfo, df, battery, times, props, ps, count = [p.strip("\n") for p in parts[:10]]
    c0, c1 = _cpu(first.splitlines()[0]), _cpu(second.splitlines()[0])
    n0, n1 = _net(first), _net(second)
    delta = [b - a for a, b in zip(c0, c1)]
    total = sum(delta) or 1
    idle = delta[3] + delta[4]

    mem = {}
    for line in meminfo.splitlines():
        key, _, value = line.partition(":")
        if value.split():
            mem[key] = int(value.split()[0]) * 1024
    memory = {"total": mem.get("MemTotal", 0), "used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
              "available": mem.get("MemAvailable", 0), "cache": mem.get("Cached", 0) + mem.get("Buffers", 0),
              "swapTotal": mem.get("SwapTotal", 0), "swapUsed": mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)}

    disks = []
    for line in df.splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 6 and cols[1].isdigit():
            total_b, used_b, free_b = int(cols[1]) * 1024, int(cols[2]) * 1024, int(cols[3]) * 1024
            disks.append({"mount": "/data", "fs": "f2fs", "total": total_b, "used": used_b, "free": free_b,
                          "percent": round(100 * used_b / max(1, used_b + free_b), 1)})
            break

    bat = {}
    for line in battery.splitlines():
        key, _, value = line.strip().partition(":")
        bat[key.strip()] = value.strip()
    level = int(bat["level"]) if bat.get("level", "").isdigit() else None
    temp = int(bat["temperature"]) / 10 if bat.get("temperature", "").lstrip("-").isdigit() else None
    plugged = any(bat.get(k) == "true" for k in ("AC powered", "USB powered", "Wireless powered", "Dock powered"))
    status = {"2": "carregando", "3": "descarregando", "4": "sem carregar", "5": "cheia"}.get(bat.get("status", ""), "")

    t = times.split()
    uptime = int(float(t[0])) if t else 0
    load = [float(x) for x in t[2:5]] if len(t) >= 5 else [0.0, 0.0, 0.0]
    p = (props.splitlines() + [""] * 8)[:8]
    cores = int(p[6]) if p[6].strip().isdigit() else 8

    rows = _top(top_text)
    by_pid = {r["pid"]: r for r in rows}
    for line in ps.splitlines()[1:]:
        cols = line.split(None, 3)
        if len(cols) == 4 and cols[0].isdigit() and cols[2].isdigit():
            pid = int(cols[0])
            by_pid.setdefault(pid, {"pid": pid, "user": cols[1], "cpu": 0.0, "mem": int(cols[2]) * 1024, "name": cols[3].strip()})
            by_pid[pid]["mem"] = int(cols[2]) * 1024
    procs = [dict(r, tty="", age=None) for r in by_pid.values() if r["name"] not in ("top", "ps", "sh")]
    groups = {}
    for r in procs:
        g = groups.setdefault(r["name"], {"name": r["name"], "cpu": 0.0, "mem": 0, "count": 0})
        g["cpu"] += r["cpu"]
        g["mem"] += r["mem"]
        g["count"] += 1
    items = list(groups.values())
    return {
        "platform": "android", "takenAt": int(time.time()),
        "cpu": {"percent": round(100 * (total - idle) / total, 1), "iowait": round(100 * delta[4] / total, 1), "steal": 0.0,
                "load": load, "cores": cores},
        "net": {"rx": max(0, (n1[0] - n0[0]) / elapsed), "tx": max(0, (n1[1] - n0[1]) / elapsed)},
        "io": {"read": 0, "write": 0},
        "processes": {"total": int(count.strip() or 1) - 1, "running": 0,
                      "topCpu": sorted((g for g in items if g["cpu"] >= 0.5), key=lambda g: -g["cpu"])[:10],
                      "topMem": sorted(items, key=lambda g: -g["mem"])[:10]},
        "agents": {},
        "system": {"hostname": p[0] or p[1], "os": "Android " + p[2] + (" · HyperOS " + p[3] if p[3] else ""),
                   "kernel": p[7], "cpuModel": p[4], "cores": cores, "uptime": uptime, "vendor": p[5],
                   "tailscaleIp": None, "users": 0},
        "memory": memory, "disks": disks, "temperature": None, "gpus": [], "containers": None,
        "failed": [], "failedUser": [], "tmux": [], "terminals": [],
        "procs": sorted(procs, key=lambda r: (-r["cpu"], -r["mem"]))[:40],
        "battery": {"level": level, "temp": temp, "plugged": plugged, "status": status},
    }


def probe(serial):
    """(data, error, elapsed ms), like collect.probe."""
    started = time.monotonic()
    try:
        state = adb(serial, "get-state", timeout=8)
        if state.stdout.strip() != "device":
            return None, (state.stderr.strip().splitlines() or ["adb: " + (state.stdout.strip() or "fora do ar")])[-1][:160], None
        t0 = time.monotonic()
        result = adb(serial, "shell", SCRIPT, timeout=40)
        elapsed = time.monotonic() - t0
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, "adb: " + str(error)[:150], None
    ms = int((time.monotonic() - started) * 1000)
    if result.returncode != 0:
        return None, (result.stderr.strip().splitlines() or ["adb saiu %d" % result.returncode])[-1][:160], ms
    try:
        # top runs for ~1 s between the two /proc/stat reads.
        return parse(result.stdout, max(1.0, elapsed - 0.3)), "", ms
    except (ValueError, IndexError) as error:
        return None, "Resposta inválida do celular: " + str(error)[:120], ms
