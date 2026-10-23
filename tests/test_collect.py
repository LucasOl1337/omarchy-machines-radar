import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProbeTests(unittest.TestCase):
    def test_probe_reports_the_fields_the_panel_reads(self):
        out = subprocess.run([sys.executable, str(ROOT / 'probe.py')], capture_output=True, text=True, check=True, timeout=60)
        data = json.loads(out.stdout)
        for key in ('cpu', 'memory', 'disks', 'net', 'io', 'processes', 'system', 'agents', 'failed'):
            self.assertIn(key, data)
        self.assertGreater(data['memory']['total'], 0)
        self.assertNotIn('cmdline', out.stdout)


    def test_probe_lists_terminals_and_single_processes_without_command_lines(self):
        out = subprocess.run([sys.executable, str(ROOT / 'probe.py')], capture_output=True, text=True, check=True, timeout=60)
        data = json.loads(out.stdout)
        self.assertIsInstance(data['terminals'], list)
        self.assertIsInstance(data['tmux'], list)
        self.assertTrue(data['procs'])
        self.assertEqual(set(data['procs'][0]), {'pid', 'name', 'user', 'cpu', 'mem', 'tty', 'age'})


class AndroidTests(unittest.TestCase):
    # Trimmed real answer of the POCO X8 Pro Max (17/10/2026).
    RAW = """cpu  100 0 100 800 0 0 0 0 0 0
 wlan0: 1000 10 0 0 0 0 0 0 2000 20 0 0 0 0 0 0
@@radar@@
Tasks: 1089 total
  PID USER         %CPU  RES NAME
 1 root 0.0 1M init
Tasks: 1089 total
  PID USER         %CPU  RES NAME
20808 u0_a348       7.0 664M com.picpay
 1488 system        3.0 152M surfaceflinger
@@radar@@
cpu  150 0 150 900 0 0 0 0 0 0
 wlan0: 3000 10 0 0 0 0 0 0 6000 20 0 0 0 0 0 0
@@radar@@
MemTotal:       11539412 kB
MemAvailable:    4430568 kB
SwapTotal:      12582908 kB
SwapFree:        8738700 kB
@@radar@@
Filesystem 1K-blocks Used Available Use% Mounted on
/dev/block/dm-86 243357664 61274060 181546736  26% /data/user/0
@@radar@@
Current Battery Service state:
  AC powered: true
  status: 2
  level: 56
  temperature: 359
@@radar@@
1389523.38 6645620.08
16.90 17.13 17.50 4/8884 29869
@@radar@@
POCO X8 Pro Max
2602BPC18G
16
OS3.0
MT6991
Xiaomi
8
6.6.118
@@radar@@
  PID USER            RSS NAME
 2538 system       688384 system_server
@@radar@@
1090
"""

    def test_parse_gives_the_panel_shape(self):
        sys.path.insert(0, str(ROOT))
        import android
        d = android.parse(self.RAW, 1.0)
        self.assertEqual(d['cpu']['percent'], 50.0)
        self.assertEqual(d['net'], {'rx': 2000.0, 'tx': 4000.0})
        self.assertEqual(d['battery'], {'level': 56, 'temp': 35.9, 'plugged': True, 'status': 'carregando'})
        self.assertEqual(d['disks'][0]['mount'], '/data')
        self.assertEqual(d['system']['hostname'], 'POCO X8 Pro Max')
        self.assertEqual([p['name'] for p in d['procs']][:2], ['com.picpay', 'surfaceflinger'])
        self.assertIn('system_server', [p['name'] for p in d['procs']])
        self.assertEqual(d['processes']['total'], 1089)


class CloudTests(unittest.TestCase):
    """Parsing of the API sources, on fixed answers; nothing goes to the network."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        import cloud
        self.cloud = cloud

    def test_node_output_becomes_host_cpu_memory_and_disk(self):
        sep = self.cloud.SEP
        raw = "\n".join([
            "cpu  100 0 100 700 50 0 0 50 0 0", "cpu  200 0 200 1300 100 0 0 100 0 0", sep,
            "MemTotal: 4000000 kB", "MemFree: 500000 kB", "MemAvailable: 2500000 kB", "Buffers: 100000 kB", "Cached: 900000 kB",
            "SwapTotal: 0 kB", "SwapFree: 0 kB", sep,
            "0.04 0.18 0.17 1/300 99", "20232779.5 1000.0", sep,
            "Filesystem 1024-blocks Used Available Capacity Mounted on", "overlay 39052844 25891788 11524488 70% /", sep,
            "some avg10=0.00 avg60=1.50 avg300=0.00 total=1", "full avg10=0.00 avg60=0.00 avg300=0.00 total=1", sep,
            "3", "6.1.0-43-amd64"])
        node = self.cloud.parse_node(raw)
        self.assertEqual(node["cpu"]["percent"], 27.8)
        self.assertEqual(node["cpu"]["iowait"], 5.6)
        self.assertEqual(node["cpu"]["steal"], 5.6)
        self.assertEqual(node["cpu"]["cores"], 3)
        self.assertEqual(node["memory"]["used"], 1500000 * 1024)
        self.assertEqual(node["memory"]["pressure"], 1.5)
        self.assertEqual(node["disks"][0]["percent"], 69.2)
        self.assertEqual(node["kernel"], "6.1.0-43-amd64")
        self.assertEqual(node["uptime"], 20232779)
        with self.assertRaises(ValueError):
            self.cloud.parse_node("cpu  1 2 3")

    def test_swarm_view_splits_running_and_failing_tasks_of_one_node(self):
        nodes = [{"ID": "n1", "Description": {"Hostname": "evolution"}}, {"ID": "n2", "Description": {"Hostname": "db01"}}]
        services = [{"ID": "s1", "Spec": {"Name": "waha_waha"}}, {"ID": "s2", "Spec": {"Name": "portainer_agent"}},
                    {"ID": "s3", "Spec": {"Name": "redis_waha_redis"}}, {"ID": "s4", "Spec": {"Name": "postgres_postgres"}}]
        task = lambda node, service, state, desired="running", cid="c": {"NodeID": node, "ServiceID": service, "DesiredState": desired,
                                                                          "Status": {"State": state, "ContainerStatus": {"ContainerID": cid + service}}}
        tasks = [task("n1", "s1", "running"), task("n1", "s2", "running"), task("n1", "s3", "running"),
                 task("n1", "s3", "failed", "shutdown"), task("n1", "s1", "rejected"), task("n2", "s4", "running")]
        node, running, failing = self.cloud.swarm_view(nodes, tasks, services, "evolution")
        self.assertEqual(node["ID"], "n1")
        self.assertEqual([e["service"] for e in running], ["portainer_agent", "redis_waha_redis", "waha_waha"])
        self.assertEqual([e["service"] for e in failing], ["waha_waha"])
        self.assertEqual([e["service"] for e in self.cloud.exec_order(running)], ["redis_waha_redis", "waha_waha"])
        self.assertIsNone(self.cloud.swarm_view(nodes, tasks, services, "nada")[0])

    def test_railway_counts_only_services_in_the_air_and_recent_failures(self):
        now = 1_800_000_000
        iso = lambda ago: __import__("datetime").datetime.fromtimestamp(now - ago, __import__("datetime").timezone.utc).isoformat()
        inst = lambda status, ago: {"edges": [{"node": {"environmentId": "e1", "numReplicas": 1, "latestDeployment": {"status": status, "createdAt": iso(ago)}}}]}
        project = {"id": "p1", "name": "infra", "environments": {"edges": [{"node": {"id": "e1", "name": "production"}}]},
                   "services": {"edges": [{"node": {"id": "a", "name": "router", "serviceInstances": inst("SUCCESS", 90000)}},
                                          {"node": {"id": "b", "name": "velho", "serviceInstances": inst("FAILED", 60 * 86400)}},
                                          {"node": {"id": "c", "name": "novo", "serviceInstances": inst("CRASHED", 600)}}]},
                   "volumes": {"edges": [{"node": {"name": "router-volume", "volumeInstances": {"edges": [
                       {"node": {"environmentId": "e1", "currentSizeMB": 1500, "sizeMB": 50000, "mountPath": "/app/data"}}]}}}]}}
        samples = {("e1", "a"): {"CPU_USAGE": 0.5, "CPU_LIMIT": 8, "MEMORY_USAGE_GB": 0.4, "MEMORY_LIMIT_GB": 8, "NETWORK_RX_GB": 0.00006}}
        data = self.cloud.railway_view([project], samples, {}, now)
        self.assertEqual(data["cpu"]["percent"], 6.2)
        self.assertEqual(data["memory"]["used"], 0.4e9)
        self.assertEqual(data["net"]["rx"], 1000.0)
        self.assertEqual(data["failed"], ["novo (deploy crashed)"])
        self.assertEqual([(c["name"], c["state"]) for c in data["containers"]], [("router", "running"), ("novo", "exited"), ("velho", "exited")])
        self.assertEqual((data["disks"][0]["mount"], data["disks"][0]["percent"]), ("router", 3.0))
        self.assertEqual(data["system"]["os"], "Railway · 1 de 3 serviços no ar")

    def test_secrets_file_is_read_as_key_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets.env"
            path.write_text("# comentário\nA=1\nB='dois'\n\nlixo\n")
            old, self.cloud.SECRETS = self.cloud.SECRETS, path
            try:
                self.assertEqual(self.cloud.secrets(), {"A": "1", "B": "dois"})
            finally:
                self.cloud.SECRETS = old


class ActTests(unittest.TestCase):
    def act(self, config, *args):
        env = dict(os.environ, OMARCHY_MACHINES_CONFIG=str(config))
        out = subprocess.run([sys.executable, str(ROOT / 'act.py'), *args], capture_output=True, text=True, env=env, timeout=30)
        return json.loads(out.stdout)

    def test_kill_refuses_a_pid_whose_name_changed_and_readonly_machines(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'machines.json'
            config.write_text(json.dumps({'machines': [{'id': 'here', 'local': True}, {'id': 'shared', 'local': True, 'readonly': True}]}))
            child = subprocess.Popen(['sleep', '30'])
            try:
                wrong = self.act(config, 'kill', 'here', str(child.pid), 'not-sleep')
                self.assertFalse(wrong['ok'])
                self.assertIsNone(child.poll())
                blocked = self.act(config, 'kill', 'shared', str(child.pid), 'sleep')
                self.assertFalse(blocked['ok'])
                self.assertIsNone(child.poll())
                right = self.act(config, 'kill', 'here', str(child.pid), 'sleep')
                self.assertTrue(right['ok'], right)
                child.wait(5)
            finally:
                child.kill()

    def test_unknown_machine_and_bad_unit_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'machines.json'
            config.write_text(json.dumps({'machines': [{'id': 'here', 'local': True}]}))
            self.assertFalse(self.act(config, 'kill', 'nope', '1234', 'x')['ok'])
            self.assertFalse(self.act(config, 'unit', 'here', 'restart', 'x; reboot', 'system')['ok'])


class CollectTests(unittest.TestCase):
    def test_unreachable_machine_keeps_last_snapshot_and_reports_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'machines.json'
            config.write_text(json.dumps({'machines': [
                {'id': 'here', 'name': 'Here', 'local': True},
                {'id': 'gone', 'name': 'Gone', 'ssh': 'nonexistent.invalid'}]}))
            state = Path(temporary) / 'state'
            state.mkdir()
            (state / 'status.json').write_text(json.dumps({'machines': [{'id': 'gone', 'probedAt': 1, 'data': {'cpu': {}}, 'history': [[1, 5, 5]]}]}))
            env = dict(os.environ, OMARCHY_MACHINES_CONFIG=str(config), OMARCHY_MACHINES_STATE=str(state))
            subprocess.run([sys.executable, str(ROOT / 'collect.py')], env=env, check=True, timeout=120)
            status = json.loads((state / 'status.json').read_text())
            here, gone = status['machines']
            self.assertTrue(here['online'])
            self.assertEqual(len(here['history']), 1)
            self.assertFalse(gone['online'])
            self.assertTrue(gone['error'])
            self.assertEqual(gone['data'], {'cpu': {}})
            self.assertEqual(gone['probedAt'], 1)
            self.assertEqual((state / 'status.json').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
