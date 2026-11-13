"""Focused regression tests; no real host or operational data is required."""
import base64
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collector', ROOT / 'collect.py')
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)


class WindowsTests(unittest.TestCase):
    def test_probe_uses_short_encoded_wrapper_and_stdin(self):
        answer = {'platform': 'windows', 'cpu': {'percent': 12}}
        with patch.object(collect.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(answer), '')) as run:
            data, error, latency = collect.probe({'ssh': 'store', 'platform': 'windows'})
        self.assertEqual(data, answer)
        self.assertEqual(error, '')
        args, kwargs = run.call_args
        command = args[0]
        self.assertIn('-NonInteractive', command)
        wrapper = base64.b64decode(command[-1]).decode('utf-16le')
        self.assertIn('ReadToEnd', wrapper)
        self.assertLess(len(' '.join(command)), 2000)
        self.assertIn('Win32_OperatingSystem', kwargs['input'])
        self.assertEqual(kwargs['encoding'], 'utf-8')
        self.assertEqual(kwargs['errors'], 'replace')

    def test_legacy_windows_stderr_cannot_crash_other_machines(self):
        # The real failure was CP850 stderr from cmd.exe; exercise the decoder,
        # not a mock returning already-decoded text.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'ssh'
            fake.write_text('#!/usr/bin/python3\nimport os\nos.write(2, b"inv\\xa2lido\\n")\nraise SystemExit(1)\n')
            fake.chmod(0o700)
            with patch.dict('os.environ', {'PATH': tmp}):
                data, error, _ = collect.probe({'ssh': 'store', 'platform': 'windows'})
            self.assertIsNone(data)
            self.assertIn('inv', error)

    def test_windows_health_is_readonly_and_bounded(self):
        source = (ROOT / 'windows-probe.ps1').read_text()
        for field in ('bootAt', 'bootBrasilia', 'smartAvailable', 'eventsAvailable', 'smart199'):
            self.assertIn(field, source)
        self.assertIn('-MaxEvents 10', source)
        self.assertIn('-OperationTimeoutSec 4', source)
        for mutation in ('Restart-', 'Stop-Process', 'Set-', 'Out-File', 'Start-Service'):
            self.assertNotIn(mutation, source)

    def test_nonadmin_fallback_reads_os_apis_without_elevation(self):
        source = (ROOT / 'windows-probe.ps1').read_text()
        for api in ('GlobalMemoryStatusEx', 'GetSystemTimes', 'GetTickCount64', '[IO.DriveInfo]::GetDrives()'):
            self.assertIn(api, source)
        self.assertIn("metricSource = 'win32-readonly'", source)
        self.assertIn('elapsed <= 0', source)
        self.assertIn('Memory metrics unavailable', source)
        for escalation in ('SetSecurityDescriptor', 'Register-ScheduledTask', 'RunAs', 'icacls', 'Add-LocalGroupMember'):
            self.assertNotIn(escalation, source)

    def test_store_readonly_blocks_all_destructive_verbs(self):
        import os
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'machines.json'
            config.write_text(json.dumps({'machines': [{'id': 'store', 'ssh': 'invalid', 'platform': 'windows', 'readonly': True}]}))
            for args in [('kill', 'store', '123', 'Byte'), ('tmux-kill', 'store', 'radar'), ('tty-hup', 'store', '1'), ('unit', 'store', 'restart', 'sshd', 'system')]:
                result = subprocess.run([sys.executable, str(ROOT / 'act.py'), *args], env=dict(os.environ, OMARCHY_MACHINES_CONFIG=str(config)), capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(json.loads(result.stdout)['ok'])


if __name__ == '__main__':
    unittest.main()
