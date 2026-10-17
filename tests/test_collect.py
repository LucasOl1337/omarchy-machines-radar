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
