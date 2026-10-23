"""Machines read through a provider API instead of SSH, in the shape probe.py gives.

Two sources, both read-only:

- `portainer`: one Docker Swarm node behind Portainer. A short `sh` command runs
  inside a container already on that node (containers share the host's /proc
  and root filesystem), so CPU, memory, load and disk are the VM's own. The
  node's tasks become the container list; a task meant to run that isn't is a
  failing service. With a Hetzner Cloud token, network rates come from the
  Cloud metrics API.
- `railway`: one Railway project (or all of the account), with CPU, memory,
  network and volumes summed over its services from the metrics API.

Tokens live in ~/.config/omarchy-machines/secrets.env (KEY=VALUE, mode 0600),
never in machines.json. Processes are names only, as everywhere else.
"""
from __future__ import annotations

import datetime
import json
import os
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS = Path(os.environ.get("OMARCHY_MACHINES_SECRETS", Path.home() / ".config/omarchy-machines/secrets.env"))
USER_AGENT = "omarchy-machines-radar/1.2"
RAILWAY_API = "https://backboard.railway.com/graphql/v2"
HCLOUD_API = "https://api.hetzner.cloud/v1"
SEP = "@@radar@@"
# One command, host values: /proc/stat twice a second apart, memory, load, uptime, root disk.
NODE_SCRIPT = "; ".join([
    "head -1 /proc/stat", "sleep 1", "head -1 /proc/stat", "echo " + SEP,
    "cat /proc/meminfo", "echo " + SEP,
    "cat /proc/loadavg /proc/uptime", "echo " + SEP,
    "df -P -k /", "echo " + SEP,
    "cat /proc/pressure/memory 2>/dev/null", "echo " + SEP,
    "nproc; cat /proc/sys/kernel/osrelease",
])
# Containers worth exec'ing into first: small, with a shell, not the ones holding sessions.
EXEC_AVOID = ("portainer_agent", "waha", "evolution", "chatwoot")


def secrets():
    out = {}
    try:
        text = SECRETS.read_text()
    except OSError:
        return out
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def http(url, headers=None, data=None, method=None, raw=False, timeout=20):
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    body = None
    if data is not None:
        h["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    request = urllib.request.Request(url, data=body, headers=h, method=method or ("POST" if body else "GET"))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    if raw:
        return payload
    return json.loads(payload) if payload else None


def short_error(error):
    if isinstance(error, urllib.error.HTTPError):
        return "HTTP %d" % error.code
    if isinstance(error, urllib.error.URLError):
        return str(error.reason)[:120]
    return str(error)[:160]


_cache, _lock = {}, threading.Lock()


def cached(key, load):
    """One read per collect run for what every node of a cluster shares."""
    with _lock:
        slot = _cache.setdefault(key, {"lock": threading.Lock()})
    with slot["lock"]:
        if "value" not in slot:
            try:
                slot["value"] = (load(), None)
            except Exception as error:  # noqa: BLE001 - every node reports the same failure
                slot["value"] = (None, error)
    value, error = slot["value"]
    if error:
        raise error
    return value


# ---------- Portainer / Swarm ----------

def demux(raw):
    """Docker's multiplexed stdout/stderr stream to text."""
    out, i = b"", 0
    while i + 8 <= len(raw):
        size = struct.unpack(">I", raw[i + 4:i + 8])[0]
        out += raw[i + 8:i + 8 + size]
        i += 8 + size
    return (out or raw).decode("utf-8", "replace")


def _cpu(line):
    return [int(x) for x in line.split()[1:9]]


def parse_node(raw, elapsed=1.0):
    """Output of NODE_SCRIPT to the cpu, memory, disks and system fields of probe.py."""
    parts = [p.strip("\n") for p in raw.split(SEP)]
    if len(parts) < 6:
        raise ValueError("resposta incompleta do nó")
    stat, meminfo, times, df, pressure, info = parts[:6]
    lines = [l for l in stat.splitlines() if l.startswith("cpu ")]
    c0, c1 = _cpu(lines[0]), _cpu(lines[-1])
    delta = [b - a for a, b in zip(c0, c1)]
    total = sum(delta) or 1
    idle = delta[3] + delta[4]
    mem = {}
    for line in meminfo.splitlines():
        key, _, value = line.partition(":")
        if value.split():
            mem[key] = int(value.split()[0]) * 1024
    psi = None
    for line in pressure.splitlines():
        if line.startswith("some"):
            psi = float(dict(f.split("=") for f in line.split()[1:])["avg60"])
    t = times.split()
    disks = []
    for line in df.splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 6 and cols[1].isdigit():
            size, used, free = int(cols[1]) * 1024, int(cols[2]) * 1024, int(cols[3]) * 1024
            disks.append({"mount": "/", "fs": "host", "total": size, "used": used, "free": free,
                          "percent": round(100 * used / max(1, used + free), 1)})
            break
    info = info.split()
    cores = int(info[0]) if info and info[0].isdigit() else 1
    return {
        "cpu": {"percent": round(100 * (total - idle) / total, 1), "iowait": round(100 * delta[4] / total, 1),
                "steal": round(100 * delta[7] / total, 1), "load": [float(x) for x in t[:3]], "cores": cores},
        "memory": {"total": mem.get("MemTotal", 0), "used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
                   "available": mem.get("MemAvailable", 0), "cache": mem.get("Cached", 0) + mem.get("Buffers", 0),
                   "swapTotal": mem.get("SwapTotal", 0), "swapUsed": mem.get("SwapTotal", 0) - mem.get("SwapFree", 0),
                   "pressure": psi},
        "disks": disks,
        "uptime": int(float(t[5])) if len(t) > 5 else 0,
        "kernel": info[1] if len(info) > 1 else "",
    }


def swarm_view(nodes, tasks, services, hostname):
    """The node, its running tasks and the ones that should run but don't."""
    node = next((n for n in nodes if (n.get("Description") or {}).get("Hostname") == hostname), None)
    if node is None:
        return None, [], []
    names = {s["ID"]: (s.get("Spec") or {}).get("Name", "?") for s in services}
    running, failing = [], []
    for task in tasks:
        if task.get("NodeID") != node["ID"] or task.get("DesiredState") != "running":
            continue
        status = task.get("Status") or {}
        entry = {"service": names.get(task.get("ServiceID"), "?"), "state": status.get("State", "?"),
                 "container": (status.get("ContainerStatus") or {}).get("ContainerID", ""),
                 "message": status.get("Err") or status.get("Message") or ""}
        (running if entry["state"] == "running" else failing).append(entry)
    running.sort(key=lambda e: e["service"])
    return node, running, failing


def exec_order(running):
    """Containers to try the read in, the ones holding sessions last and the agent never."""
    usable = [e for e in running if e["container"] and not e["service"].startswith("portainer_agent")]
    return sorted(usable, key=lambda e: any(word in e["service"] for word in EXEC_AVOID))


def portainer_probe(machine, env):
    cfg = machine["portainer"]
    prefix = cfg.get("env", "")
    url = (cfg.get("url") or env.get(prefix + "_PORTAINER_URL", "")).rstrip("/")
    token = env.get(prefix + "_PORTAINER_TOKEN", "")
    if not url or not token:
        return None, "Falta %s_PORTAINER_URL/TOKEN em %s" % (prefix, SECRETS), None
    endpoint = str(cfg.get("endpoint", 1))
    base = url + "/api/endpoints/" + endpoint + "/docker"
    auth = {"X-API-Key": token}
    target = dict(auth, **{"X-PortainerAgent-Target": cfg["node"]})
    started = time.monotonic()
    try:
        nodes, tasks, services = cached(("swarm", url, endpoint), lambda: (
            http(base + "/nodes", auth), http(base + "/tasks", auth), http(base + "/services", auth)))
    except Exception as error:  # noqa: BLE001
        return None, "Portainer: " + short_error(error), None
    node, running, failing = swarm_view(nodes, tasks, services, cfg["node"])
    if node is None:
        return None, "Nó %s não está no Swarm" % cfg["node"], None
    state = (node.get("Status") or {}).get("State")
    if state != "ready":
        return None, "Nó %s %s no Swarm" % (cfg["node"], state), int((time.monotonic() - started) * 1000)
    raw, last_error = None, "nenhum container com shell no nó"
    for entry in exec_order(running):
        try:
            created = http(base + "/containers/" + entry["container"] + "/exec", target,
                           {"AttachStdout": True, "AttachStderr": True, "Tty": False, "Cmd": ["sh", "-c", NODE_SCRIPT]})
            t0 = time.monotonic()
            raw = demux(http(base + "/exec/" + created["Id"] + "/start", target, {"Detach": False, "Tty": False}, raw=True))
            elapsed = time.monotonic() - t0
            if SEP in raw:
                break
            raw, last_error = None, "exec sem resposta em " + entry["service"]
        except Exception as error:  # noqa: BLE001 - try the next container
            raw, last_error = None, short_error(error)
    if raw is None:
        return None, "Portainer: " + last_error, int((time.monotonic() - started) * 1000)
    try:
        host = parse_node(raw, max(1.0, elapsed - 0.2))
    except (ValueError, IndexError) as error:
        return None, "Resposta inválida do nó: " + str(error)[:120], int((time.monotonic() - started) * 1000)

    containers = []
    for entry in running:
        mem = None
        try:
            stats = http(base + "/containers/" + entry["container"] + "/stats?stream=false&one-shot=true", target, timeout=10)
            usage = stats.get("memory_stats") or {}
            mem = max(0, usage.get("usage", 0) - ((usage.get("stats") or {}).get("inactive_file") or 0)) or None
        except Exception:  # noqa: BLE001 - memory is a nice-to-have
            pass
        containers.append({"name": entry["service"], "image": "", "state": "running", "status": "running", "cpu": None, "mem": mem})
    for entry in failing:
        containers.append({"name": entry["service"], "image": "", "state": entry["state"], "status": entry["message"][:80] or entry["state"], "cpu": None, "mem": None})

    rx = tx = 0.0
    hcloud = env.get(prefix + "_HCLOUD_TOKEN")
    addr = (node.get("Status") or {}).get("Addr")
    if hcloud and addr:
        try:
            rx, tx = hcloud_network(hcloud, addr)
        except Exception:  # noqa: BLE001 - network rates are optional
            pass

    desc = node.get("Description") or {}
    items = [{"name": c["name"], "cpu": 0.0, "mem": c["mem"] or 0, "count": 1} for c in containers if c["state"] == "running"]
    data = {
        "platform": "swarm", "takenAt": int(time.time()),
        "cpu": host["cpu"], "memory": host["memory"], "disks": host["disks"],
        "net": {"rx": rx, "tx": tx}, "io": {"read": 0, "write": 0},
        "processes": {"total": len(running), "running": len(running), "topCpu": [],
                      "topMem": sorted(items, key=lambda g: -g["mem"])[:10]},
        "agents": {},
        "system": {"hostname": desc.get("Hostname", cfg["node"]),
                   "os": "Swarm " + ((node.get("Spec") or {}).get("Role") or "nó") + " · Docker " + ((desc.get("Engine") or {}).get("EngineVersion") or "?"),
                   "kernel": host["kernel"], "cpuModel": None, "cores": host["cpu"]["cores"], "uptime": host["uptime"],
                   "vendor": None, "tailscaleIp": None, "users": 0, "address": addr},
        "temperature": None, "gpus": [], "containers": containers,
        "failed": sorted({"%s (%s)" % (e["service"], e["state"]) for e in failing})[:20], "failedUser": [],
        "tmux": [], "terminals": [], "procs": [],
    }
    return data, "", int((time.monotonic() - started) * 1000)


def hcloud_network(token, address):
    """Inbound and outbound bytes/s of the Hetzner Cloud server with this public IPv4."""
    auth = {"Authorization": "Bearer " + token}
    servers = cached(("hcloud", token), lambda: http(HCLOUD_API + "/servers?per_page=50", auth)["servers"])
    server = next((s for s in servers if ((s.get("public_net") or {}).get("ipv4") or {}).get("ip") == address), None)
    if not server:
        return 0.0, 0.0
    end = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    query = urllib.parse.urlencode({"type": "network", "start": (end - datetime.timedelta(minutes=5)).isoformat(),
                                    "end": end.isoformat(), "step": 60})
    series = http(HCLOUD_API + "/servers/%d/metrics?%s" % (server["id"], query), auth)["metrics"]["time_series"]

    def last(name):
        values = (series.get(name) or {}).get("values") or []
        return float(values[-1][1]) if values else 0.0
    return last("network.0.bandwidth.in"), last("network.0.bandwidth.out")


# ---------- Railway ----------

RAILWAY_PROJECTS = """{ projects { edges { node { id name
  environments { edges { node { id name } } }
  services { edges { node { id name serviceInstances { edges { node { environmentId numReplicas latestDeployment { status createdAt } } } } } } }
  volumes { edges { node { name volumeInstances { edges { node { environmentId currentSizeMB sizeMB mountPath } } } } } } } } } }"""
RAILWAY_METRICS = """query($p: String!, $e: String!, $s: DateTime!) { metrics(projectId: $p, environmentId: $e, startDate: $s,
  sampleRateSeconds: 60, groupBy: [SERVICE_ID], measurements: [CPU_USAGE, CPU_LIMIT, MEMORY_USAGE_GB, MEMORY_LIMIT_GB,
  NETWORK_RX_GB, NETWORK_TX_GB]) { measurement tags { serviceId } values { ts value } } }"""
# Deployment states that mean the service is up, and the ones worth a warning while recent.
RAILWAY_UP = {"SUCCESS", "SLEEPING"}
RAILWAY_BROKEN = {"FAILED", "CRASHED"}
RAILWAY_RECENT = 24 * 3600


def railway_gql(token, query, variables=None):
    answer = http(RAILWAY_API, {"Authorization": "Bearer " + token}, {"query": query, "variables": variables or {}})
    if answer.get("errors"):
        raise RuntimeError(answer["errors"][0].get("message", "erro no GraphQL"))
    return answer["data"]


def edges(node, key):
    return [e["node"] for e in ((node or {}).get(key) or {}).get("edges", [])]


def _ago(stamp, now):
    try:
        return now - datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def railway_view(projects, samples, cfg, now=None):
    """Projects and their last metric samples to the probe.py shape. samples: {(env id, service id): {measurement: value}}."""
    now = now or time.time()
    wanted_env = cfg.get("environment", "production")
    services, disks, failed = [], [], []
    for project in projects:
        envs = {e["id"]: e["name"] for e in edges(project, "environments")}
        for service in edges(project, "services"):
            for inst in edges(service, "serviceInstances"):
                if envs.get(inst["environmentId"]) != wanted_env:
                    continue
                dep = inst.get("latestDeployment") or {}
                status = dep.get("status") or "sem deploy"
                m = samples.get((inst["environmentId"], service["id"]), {})
                age = _ago(dep.get("createdAt"), now)
                name = service["name"] if len(projects) == 1 else project["name"] + "/" + service["name"]
                services.append({"name": name, "status": status, "age": age, "cpu": m.get("CPU_USAGE", 0.0),
                                 "cpuLimit": m.get("CPU_LIMIT", 0.0), "mem": m.get("MEMORY_USAGE_GB", 0.0) * 1e9,
                                 "memLimit": m.get("MEMORY_LIMIT_GB", 0.0) * 1e9,
                                 "rx": m.get("NETWORK_RX_GB", 0.0) * 1e9 / 60, "tx": m.get("NETWORK_TX_GB", 0.0) * 1e9 / 60})
                if status in RAILWAY_BROKEN and age is not None and age < RAILWAY_RECENT:
                    failed.append("%s (deploy %s)" % (name, status.lower()))
        for volume in edges(project, "volumes"):
            for inst in edges(volume, "volumeInstances"):
                if envs.get(inst["environmentId"]) != wanted_env or not inst.get("sizeMB"):
                    continue
                total, used = inst["sizeMB"] * 1e6, (inst.get("currentSizeMB") or 0) * 1e6
                disks.append({"mount": volume["name"].removesuffix("-volume"), "fs": inst.get("mountPath") or "volume", "total": total,
                              "used": used, "free": max(0, total - used), "percent": round(100 * used / total, 1)})
    up = [s for s in services if s["status"] in RAILWAY_UP]
    cpu_used = sum(s["cpu"] for s in up)
    cpu_limit = sum(s["cpuLimit"] for s in up) or 1
    mem_used = sum(s["mem"] for s in up)
    mem_limit = sum(s["memLimit"] for s in up)
    containers = [{"name": s["name"], "image": "", "state": "running" if s["status"] in RAILWAY_UP else "exited",
                   "status": s["status"].lower() + (" há %dd" % (s["age"] // 86400) if s["age"] and s["age"] >= 86400 else ""),
                   "cpu": round(100 * s["cpu"], 1) if s["status"] in RAILWAY_UP else None,
                   "mem": int(s["mem"]) or None} for s in services]
    containers.sort(key=lambda c: (c["state"] != "running", c["name"]))
    items = [{"name": s["name"], "cpu": round(100 * s["cpu"], 1), "mem": int(s["mem"]), "count": 1} for s in up]
    names = sorted({p["name"] for p in projects})
    return {
        "platform": "railway", "takenAt": int(now),
        "cpu": {"percent": round(100 * cpu_used / cpu_limit, 1), "iowait": 0.0, "steal": 0.0, "load": [0.0, 0.0, 0.0],
                "cores": round(cpu_limit), "used": round(cpu_used, 3)},
        "memory": {"total": mem_limit, "used": mem_used, "available": max(0, mem_limit - mem_used), "cache": 0,
                   "swapTotal": 0, "swapUsed": 0},
        "disks": disks,
        "net": {"rx": sum(s["rx"] for s in up), "tx": sum(s["tx"] for s in up)}, "io": {"read": 0, "write": 0},
        "processes": {"total": len(services), "running": len(up),
                      "topCpu": sorted((i for i in items if i["cpu"] >= 0.5), key=lambda i: -i["cpu"])[:10],
                      "topMem": sorted(items, key=lambda i: -i["mem"])[:10]},
        "agents": {},
        "system": {"hostname": ", ".join(names), "os": "Railway · %d de %d serviços no ar" % (len(up), len(services)),
                   "kernel": "", "cpuModel": None, "cores": round(cpu_limit), "uptime": 0, "vendor": "Railway",
                   "tailscaleIp": None, "users": 0},
        "temperature": None, "gpus": [], "containers": containers,
        "failed": failed[:20], "failedUser": [], "tmux": [], "terminals": [], "procs": [],
    }


def railway_probe(machine, env):
    cfg = machine["railway"]
    token = env.get(cfg.get("token", "RAILWAY_TOKEN"), "")
    if not token:
        return None, "Falta %s em %s" % (cfg.get("token", "RAILWAY_TOKEN"), SECRETS), None
    started = time.monotonic()
    try:
        projects = edges(railway_gql(token, RAILWAY_PROJECTS), "projects")
        if cfg.get("project"):
            projects = [p for p in projects if cfg["project"] in (p["id"], p["name"])]
        if not projects:
            return None, "Nenhum projeto Railway visível com esse token", int((time.monotonic() - started) * 1000)
        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)).isoformat()
        samples = {}
        for project in projects:
            for env_node in edges(project, "environments"):
                if env_node["name"] != cfg.get("environment", "production"):
                    continue
                for series in railway_gql(token, RAILWAY_METRICS, {"p": project["id"], "e": env_node["id"], "s": since})["metrics"]:
                    values = series.get("values") or []
                    if values:
                        key = (env_node["id"], (series.get("tags") or {}).get("serviceId"))
                        samples.setdefault(key, {})[series["measurement"]] = values[-1]["value"]
    except Exception as error:  # noqa: BLE001
        return None, "Railway: " + short_error(error), int((time.monotonic() - started) * 1000)
    return railway_view(projects, samples, cfg), "", int((time.monotonic() - started) * 1000)


def probe(machine):
    """(data, error, elapsed ms), like collect.probe."""
    env = secrets()
    if machine.get("portainer"):
        return portainer_probe(machine, env)
    return railway_probe(machine, env)
