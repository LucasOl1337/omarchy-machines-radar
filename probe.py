#!/usr/bin/env python3
"""Snapshot of one Linux machine as JSON on stdout.

Runs on the machine itself: locally, or piped through `ssh HOST python3 -`.
Standard library only, so any VPS with Python 3.8+ works without installing
anything. CPU, network and disk I/O are measured over a one-second window.
Processes are reported by name (comm) only, never by command line, which can
carry secrets.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path

REAL_FS = {"ext4", "ext3", "xfs", "btrfs", "f2fs", "zfs", "bcachefs", "ntfs3", "exfat"}
SKIP_IFACES = ("lo", "veth", "docker", "br-", "virbr", "vnet", "tailscale", "wg", "tun", "cni", "flannel")
AGENTS = {"claude", "codex", "grok", "opencode", "gemini", "jcode", "omp", "pi", "aider", "cursor-agent", "hermes"}
HZ = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def run(cmd, timeout=15):
    if not shutil.which(cmd[0]):
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def cpu_ticks():
    # user nice system idle iowait irq softirq steal
    return [int(x) for x in read("/proc/stat").split("\n", 1)[0].split()[1:9]]


def processes():
    """pid -> (comm, cpu ticks, rss bytes, state)."""
    out = {}
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        stat = read("/proc/" + entry.name + "/stat")
        if not stat:
            continue
        i, j = stat.find("("), stat.rfind(")")
        rest = stat[j + 2:].split()
        try:
            out[int(entry.name)] = (stat[i + 1:j], int(rest[11]) + int(rest[12]), int(rest[21]) * PAGE, rest[0])
        except (IndexError, ValueError):
            continue
    return out


def net_bytes():
    rx = tx = 0
    for line in read("/proc/net/dev").splitlines()[2:]:
        name, _, data = line.partition(":")
        if name.strip().startswith(SKIP_IFACES):
            continue
        cols = data.split()
        rx += int(cols[0])
        tx += int(cols[8])
    return rx, tx


def disk_bytes():
    # whole disks only, 512-byte sectors
    rd = wr = 0
    blocks = set(os.listdir("/sys/block")) if os.path.isdir("/sys/block") else set()
    for line in read("/proc/diskstats").splitlines():
        c = line.split()
        if len(c) < 10 or c[2] not in blocks or c[2].startswith(("loop", "ram", "zram", "dm-", "sr")):
            continue
        rd += int(c[5]) * 512
        wr += int(c[9]) * 512
    return rd, wr


def memory():
    m = {}
    for line in read("/proc/meminfo").splitlines():
        key, _, value = line.partition(":")
        m[key] = int(value.split()[0]) * 1024
    total, available = m.get("MemTotal", 0), m.get("MemAvailable", 0)
    return {
        "total": total, "used": total - available, "available": available,
        "cache": m.get("Cached", 0) + m.get("Buffers", 0),
        "swapTotal": m.get("SwapTotal", 0), "swapUsed": m.get("SwapTotal", 0) - m.get("SwapFree", 0),
    }


def loop_images():
    """Loop devices backed by an image file: device -> (file, its fs id, allocated bytes).

    A preallocated image (one disk per user on a shared VPS, for example) fills
    the host filesystem without being "used" by anything there.
    """
    out = {}
    for loop in Path("/sys/block").glob("loop*"):
        backing = read(str(loop) + "/loop/backing_file").strip()
        if not backing:
            continue
        try:
            st = os.stat(backing)
        except OSError:
            continue
        out["/dev/" + loop.name] = (backing, st.st_dev, st.st_blocks * 512)
    return out


def disks():
    seen, out = set(), []
    images, by_mount = loop_images(), {}
    for line in read("/proc/mounts").splitlines():
        dev, mount, fstype = line.split()[:3]
        mount = mount.replace("\\040", " ")
        if fstype not in REAL_FS or dev in seen or mount.startswith(("/boot", "/snap", "/var/lib/docker", "/run")):
            continue
        try:
            sv = os.statvfs(mount)
        except OSError:
            continue
        total = sv.f_blocks * sv.f_frsize
        if total < 2 * 1024 ** 3:
            continue
        seen.add(dev)
        free = sv.f_bavail * sv.f_frsize
        used = total - sv.f_bfree * sv.f_frsize
        # Same percentage as df: root's reserved blocks don't count as free.
        disk = {"mount": mount, "fs": fstype, "total": total, "used": used, "free": free,
                "percent": round(100 * used / max(1, used + free), 1)}
        if dev in images:
            disk["image"] = images[dev][0]
            by_mount[mount] = dev
        out.append(disk)
    # Images living on a filesystem are reserved space there, not usage.
    for disk in out:
        try:
            host = os.stat(disk["mount"]).st_dev
        except OSError:
            continue
        held = [m for m, dev in by_mount.items() if images[dev][1] == host]
        if held:
            disk["reserved"] = sum(images[by_mount[m]][2] for m in held)
            disk["holds"] = held
    return out[:8]


def temperature():
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        if read(str(hw) + "/name").strip() in ("k10temp", "coretemp", "zenpower", "cpu_thermal"):
            values = [int(read(str(t)) or 0) for t in hw.glob("temp*_input")]
            if values:
                return round(max(values) / 1000, 1)
    best = None
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        if read(str(zone) + "/type").strip() in ("x86_pkg_temp", "cpu-thermal", "acpitz"):
            best = max(best or 0, int(read(str(zone) + "/temp") or 0) / 1000)
    return round(best, 1) if best else None


def gpus():
    out = []
    csv = run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
               "--format=csv,noheader,nounits"], 10)
    for line in csv.strip().splitlines():
        c = [x.strip() for x in line.split(",")]
        if len(c) < 5:
            continue
        num = lambda x: float(x) if x.replace(".", "", 1).isdigit() else None
        out.append({"name": c[0], "util": num(c[1]), "memUsed": (num(c[2]) or 0) * 1024 ** 2,
                    "memTotal": (num(c[3]) or 0) * 1024 ** 2, "temp": num(c[4])})
    return out


def size(text):
    units = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "TiB": 1024 ** 4, "kB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}
    for unit in sorted(units, key=len, reverse=True):
        if text.endswith(unit):
            try:
                return int(float(text[:-len(unit)]) * units[unit])
            except ValueError:
                return None
    return None


def containers():
    if not shutil.which("docker"):
        return None
    ps = run(["docker", "ps", "-a", "--format", "{{json .}}"], 15)
    stats = run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], 25) if ps else ""
    usage = {}
    for line in stats.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        usage[d.get("Name")] = d
    out = []
    for line in ps.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        u = usage.get(d.get("Names"), {})
        cpu = (u.get("CPUPerc") or "").rstrip("%")
        out.append({
            "name": d.get("Names"), "image": (d.get("Image") or "")[:80], "state": d.get("State"),
            "status": d.get("Status"), "cpu": float(cpu) if cpu.replace(".", "", 1).isdigit() else None,
            "mem": size((u.get("MemUsage") or "").split("/")[0].strip()),
        })
    out.sort(key=lambda c: (c["state"] != "running", -(c["cpu"] or 0), c["name"] or ""))
    return out[:40]


def failed_units():
    names = []
    for cmd in (["systemctl", "--failed", "--no-legend", "--plain"], ["systemctl", "--user", "--failed", "--no-legend", "--plain"]):
        for line in run(cmd, 10).splitlines():
            if line.split():
                names.append(line.split()[0])
    return sorted(set(names))[:20]


def system():
    os_name = next((l.split("=", 1)[1].strip('"') for l in read("/etc/os-release").splitlines() if l.startswith("PRETTY_NAME=")), None)
    model = next((l.split(":", 1)[1].strip() for l in read("/proc/cpuinfo").splitlines() if l.startswith("model name")), None)
    vendor = read("/sys/class/dmi/id/sys_vendor").strip() or None
    return {
        "hostname": socket.gethostname(), "os": os_name, "kernel": platform.release(), "cpuModel": model,
        "cores": os.cpu_count(), "uptime": int(float(read("/proc/uptime").split()[0] or 0)), "vendor": vendor,
        "tailscaleIp": (run(["tailscale", "ip", "-4"], 5).split() or [None])[0],
        "users": len({l.split()[0] for l in run(["who"], 5).splitlines() if l.split()}),
    }


def measure(window=1.0):
    t0 = time.monotonic()
    c0, p0, n0, d0 = cpu_ticks(), processes(), net_bytes(), disk_bytes()
    time.sleep(window)
    c1, p1, n1, d1 = cpu_ticks(), processes(), net_bytes(), disk_bytes()
    dt = time.monotonic() - t0
    delta = [b - a for a, b in zip(c0, c1)]
    total = sum(delta) or 1
    idle = delta[3] + delta[4]

    # Grouped by process name: CPU over the window (% of one core) and summed RSS.
    groups, running = {}, 0
    for pid, (name, ticks, rss, state) in p1.items():
        g = groups.setdefault(name, {"name": name, "cpu": 0.0, "mem": 0, "count": 0})
        g["count"] += 1
        g["mem"] += rss
        if pid in p0 and p0[pid][0] == name:
            g["cpu"] += (ticks - p0[pid][1]) / HZ / dt * 100
        if state == "R":
            running += 1
    items = list(groups.values())
    for g in items:
        g["cpu"] = round(g["cpu"], 1)
    return {
        "cpu": {
            "percent": round(100 * (total - idle) / total, 1), "iowait": round(100 * delta[4] / total, 1),
            "steal": round(100 * delta[7] / total, 1),
            "load": [float(x) for x in read("/proc/loadavg").split()[:3]], "cores": os.cpu_count() or 1,
        },
        "net": {"rx": max(0, (n1[0] - n0[0]) / dt), "tx": max(0, (n1[1] - n0[1]) / dt)},
        "io": {"read": max(0, (d1[0] - d0[0]) / dt), "write": max(0, (d1[1] - d0[1]) / dt)},
        "processes": {
            "total": len(p1), "running": running,
            "topCpu": sorted((g for g in items if g["cpu"] >= 0.5), key=lambda g: -g["cpu"])[:10],
            "topMem": sorted(items, key=lambda g: -g["mem"])[:10],
        },
        "agents": {g["name"]: g["count"] for g in items if g["name"] in AGENTS},
    }


def snapshot():
    out = measure()
    out.update({
        "takenAt": int(time.time()), "system": system(), "memory": memory(), "disks": disks(),
        "temperature": temperature(), "gpus": gpus(), "containers": containers(), "failed": failed_units(),
    })
    return out


if __name__ == "__main__":
    print(json.dumps(snapshot(), ensure_ascii=False))
