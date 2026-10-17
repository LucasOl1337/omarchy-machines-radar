#!/usr/bin/python3
"""Collect a snapshot of every configured machine for the Omarchy bar.

Each machine runs probe.py: locally with Python, or remotely through
`ssh ALIAS python3 -` with the script on stdin, so nothing is installed on the
servers. Android phones are read over adb by android.py. SSH uses the aliases and keys already in ~/.ssh/config, in batch mode.
The state file keeps the last good snapshot of each machine plus about an hour
of CPU and memory history, and the tailnet list from `tailscale status`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
CONFIG = Path(os.environ.get("OMARCHY_MACHINES_CONFIG", Path.home() / ".config/omarchy-machines/machines.json"))
STATE_DIR = Path(os.environ.get("OMARCHY_MACHINES_STATE", Path.home() / ".local/state/omarchy-trackers/machines"))
STATUS = STATE_DIR / "status.json"
HISTORY_POINTS = 90
TIMEOUT = 45


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_status(data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)
    with tempfile.NamedTemporaryFile("w", dir=STATE_DIR, prefix=".status-", delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False)
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    temporary.replace(STATUS)


def ssh_target(alias):
    """User and hostname that `ssh -G` resolves for the alias, for display only."""
    try:
        out = subprocess.run(["ssh", "-G", alias], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return alias
    fields = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)
    host = fields.get("hostname", alias)
    return fields["user"] + "@" + host if fields.get("user") else host


def probe(machine):
    if machine.get("adb"):
        import android
        return android.probe(machine["adb"])
    script = (HERE / "probe.py").read_text()
    if machine.get("local"):
        command = [sys.executable, "-"]
    else:
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", machine["ssh"], "python3", "-"]
    started = time.monotonic()
    try:
        result = subprocess.run(command, input=script, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "Sem resposta em %d s" % TIMEOUT, None
    except OSError as error:
        return None, str(error), None
    elapsed = int((time.monotonic() - started) * 1000)
    if result.returncode != 0:
        lines = [l for l in result.stderr.strip().splitlines() if l.strip()]
        return None, (lines[-1] if lines else "saída %d" % result.returncode)[:160], elapsed
    try:
        return json.loads(result.stdout), "", elapsed
    except ValueError:
        return None, "Resposta inválida do probe", elapsed


def tailnet():
    try:
        raw = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10).stdout
        data = json.loads(raw)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    me = data.get("Self") or {}
    peers = []
    for peer in [me] + list((data.get("Peer") or {}).values()):
        seen = peer.get("LastSeen") or ""
        peers.append({
            "name": peer.get("HostName") or "", "dns": (peer.get("DNSName") or "").rstrip("."),
            "os": peer.get("OS") or "", "ip": (peer.get("TailscaleIPs") or [""])[0],
            "online": bool(peer.get("Online")) or peer is me, "self": peer is me,
            "lastSeen": None if seen.startswith("0001") else seen,
            "direct": bool(peer.get("CurAddr")), "relay": peer.get("Relay") or "",
        })
    peers.sort(key=lambda p: (not p["self"], not p["online"], p["name"].lower()))
    return {"self": me.get("HostName"), "peers": peers}


def collect():
    config = load_json(CONFIG, None)
    if not config:
        config = load_json(HERE / "machines.example.json", {"machines": []})
    previous = {m["id"]: m for m in load_json(STATUS, {}).get("machines", [])}
    machines = config.get("machines", [])

    old = load_json(STATUS, {})
    if old:
        old["refreshing"] = True
        write_status(old)

    with ThreadPoolExecutor(max_workers=max(1, len(machines))) as pool:
        results = list(pool.map(probe, machines))
    net = tailnet()
    peers = {p["ip"]: p for p in (net or {}).get("peers", [])}
    peers_by_name = {p["name"].lower(): p for p in (net or {}).get("peers", [])}

    now = int(time.time())
    out = []
    for machine, (data, error, latency) in zip(machines, results):
        before = previous.get(machine["id"], {})
        history = before.get("history", [])
        if data:
            history = (history + [[now, data["cpu"]["percent"],
                                   round(100 * data["memory"]["used"] / max(1, data["memory"]["total"]), 1)]])[-HISTORY_POINTS:]
        snapshot = data or before.get("data")
        ip = (snapshot or {}).get("system", {}).get("tailscaleIp")
        peer = peers.get(ip) or peers_by_name.get(str(machine.get("tailnet") or (snapshot or {}).get("system", {}).get("hostname") or "").lower())
        if peer:
            peer["machine"] = machine.get("name", machine["id"])
        out.append({
            "id": machine["id"], "name": machine.get("name", machine["id"]),
            "role": machine.get("role", ""), "provider": machine.get("provider", ""),
            "kind": machine.get("kind", "local" if machine.get("local") or machine.get("adb") else "vps"),
            "ssh": machine.get("ssh", ""), "adb": machine.get("adb", ""), "local": bool(machine.get("local")),
            "readonly": bool(machine.get("readonly")),
            "target": "este PC" if machine.get("local") else "adb " + machine["adb"] if machine.get("adb") else ssh_target(machine["ssh"]),
            "online": data is not None, "error": error, "latencyMs": latency,
            "probedAt": now if data else before.get("probedAt"),
            "data": snapshot, "history": history,
            "tailnet": {"name": peer["name"], "ip": peer["ip"], "online": peer["online"], "direct": peer["direct"],
                        "relay": peer["relay"], "lastSeen": peer["lastSeen"]} if peer else None,
        })
    write_status({"updatedAt": now, "refreshing": False, "machines": out, "tailnet": net})


if __name__ == "__main__":
    collect()
