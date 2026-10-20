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
    """pid -> (comm, cpu ticks, rss bytes, state, extra) where extra has uid, tty, tpgid, session, start."""
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
            uid = entry.stat().st_uid
            extra = {"uid": uid, "session": int(rest[3]), "tty": int(rest[4]), "tpgid": int(rest[5]), "start": int(rest[19])}
            out[int(entry.name)] = (stat[i + 1:j], int(rest[11]) + int(rest[12]), int(rest[21]) * PAGE, rest[0], extra)
        except (IndexError, ValueError, OSError):
            continue
    return out


def users():
    names = {}
    for line in read("/etc/passwd").splitlines():
        parts = line.split(":")
        if len(parts) > 2 and parts[2].isdigit():
            names.setdefault(int(parts[2]), parts[0])
    return names


def pts_name(tty_nr):
    """Pseudo-terminal name for a tty_nr from /proc/PID/stat, or None for anything else."""
    major = (tty_nr >> 8) & 0xfff
    minor = (tty_nr & 0xff) | ((tty_nr >> 12) & 0xfff00)
    if 136 <= major <= 143:
        return "pts/%d" % ((major - 136) * 256 + minor)
    return None


def terminals(procs, names, boot_ticks_now):
    """Open pseudo-terminals: owner, shell, what runs in the foreground and last activity."""
    by_tty = {}
    for pid, (name, _ticks, _rss, _state, extra) in procs.items():
        tty = pts_name(extra["tty"])
        if tty:
            by_tty.setdefault(tty, []).append(pid)
    now = time.time()
    out = []
    for tty, pids in by_tty.items():
        first = procs[pids[0]][4]
        fg = procs.get(first["tpgid"]) if first["tpgid"] > 0 else None
        leader = procs.get(first["session"]) or procs[min(pids)]
        try:
            st = os.stat("/dev/" + tty)
            idle = max(0, int(now - max(st.st_atime, st.st_mtime)))
        except OSError:
            idle = None
        out.append({
            "tty": tty, "pid": first["session"], "user": names.get(leader[4]["uid"], str(leader[4]["uid"])),
            "shell": leader[0], "fg": fg[0] if fg else leader[0], "fgPid": first["tpgid"] if fg else first["session"],
            "procs": len(pids), "idle": idle, "age": max(0, int((boot_ticks_now - leader[4]["start"]) / HZ)),
            "agent": any(procs[p][0] in AGENTS for p in pids),
        })
    out.sort(key=lambda t: (t["idle"] is None, t["idle"] or 0))
    return out[:60]


def tmux_sessions():
    """Sessions of every tmux server of this user (default and named -L sockets)."""
    base = Path(os.environ.get("TMUX_TMPDIR", "/tmp")) / ("tmux-%d" % os.getuid())
    sockets = sorted(p.name for p in base.glob("*")) if base.is_dir() else []
    fmt = "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_activity}\t#{pane_current_command}"
    out = []
    for socket_name in sockets or ["default"]:
        raw = run(["tmux", "-L", socket_name, "list-sessions", "-F", fmt], 5)
        for line in raw.splitlines():
            c = line.split("\t")
            if len(c) < 5:
                continue
            try:
                out.append({"name": c[0], "socket": socket_name, "windows": int(c[1]), "attached": int(c[2]) > 0,
                            "idle": max(0, int(time.time()) - int(c[3])), "command": c[4]})
            except ValueError:
                continue
    out.sort(key=lambda s: s["idle"])
    return out[:40]


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


def swap_pages():
    v = dict(line.split() for line in read("/proc/vmstat").splitlines() if line.startswith("pswp"))
    return int(v.get("pswpin", 0)), int(v.get("pswpout", 0))


def memory_pressure():
    """Share of the last minute some task stalled waiting for memory (PSI), or None without PSI."""
    for line in read("/proc/pressure/memory").splitlines():
        if line.startswith("some"):
            return float(dict(f.split("=") for f in line.split()[1:])["avg60"])
    return None


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
        "pressure": memory_pressure(),
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


def failed_units(scope="system"):
    cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + ["--failed", "--no-legend", "--plain"]
    return sorted({line.split()[0] for line in run(cmd, 10).splitlines() if line.split()})[:20]


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
    c0, p0, n0, d0, s0 = cpu_ticks(), processes(), net_bytes(), disk_bytes(), swap_pages()
    time.sleep(window)
    c1, p1, n1, d1, s1 = cpu_ticks(), processes(), net_bytes(), disk_bytes(), swap_pages()
    dt = time.monotonic() - t0
    delta = [b - a for a, b in zip(c0, c1)]
    total = sum(delta) or 1
    idle = delta[3] + delta[4]

    # Grouped by process name: CPU over the window (% of one core) and summed RSS.
    groups, running, single = {}, 0, []
    names = users()
    uptime_ticks = float(read("/proc/uptime").split()[0] or 0) * HZ
    for pid, (name, ticks, rss, state, extra) in p1.items():
        cpu = (ticks - p0[pid][1]) / HZ / dt * 100 if pid in p0 and p0[pid][0] == name else 0.0
        single.append({"pid": pid, "name": name, "user": names.get(extra["uid"], str(extra["uid"])),
                       "cpu": round(cpu, 1), "mem": rss, "tty": pts_name(extra["tty"]) or "",
                       "age": max(0, int((uptime_ticks - extra["start"]) / HZ))})
        g = groups.setdefault(name, {"name": name, "cpu": 0.0, "mem": 0, "count": 0})
        g["count"] += 1
        g["mem"] += rss
        g["cpu"] += cpu
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
        # Pages moved in and out of swap, in bytes/s: a full but quiet swap costs nothing.
        "swap": {"in": max(0, (s1[0] - s0[0]) * PAGE / dt), "out": max(0, (s1[1] - s0[1]) * PAGE / dt)},
        "processes": {
            "total": len(p1), "running": running,
            "topCpu": sorted((g for g in items if g["cpu"] >= 0.5), key=lambda g: -g["cpu"])[:10],
            "topMem": sorted(items, key=lambda g: -g["mem"])[:10],
        },
        "agents": {g["name"]: g["count"] for g in items if g["name"] in AGENTS},
        # Individual processes (name only, never the command line) for the kill list.
        "procs": top_single(single),
        "terminals": terminals(p1, names, uptime_ticks),
    }


def top_single(single, size=25):
    by_cpu = sorted((p for p in single if p["cpu"] >= 0.5), key=lambda p: -p["cpu"])[:size]
    by_mem = sorted(single, key=lambda p: -p["mem"])[:size]
    seen, out = set(), []
    for p in by_cpu + by_mem:
        if p["pid"] not in seen:
            seen.add(p["pid"])
            out.append(p)
    return out


def snapshot():
    out = measure()
    out.update({
        "takenAt": int(time.time()), "system": system(), "memory": memory(), "disks": disks(),
        "temperature": temperature(), "gpus": gpus(), "containers": containers(),
        "failed": sorted(set(failed_units()) | set(failed_units("user")))[:20], "failedUser": failed_units("user"),
        "tmux": tmux_sessions(),
    })
    return out


if __name__ == "__main__":
    print(json.dumps(snapshot(), ensure_ascii=False))
