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
