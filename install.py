#!/usr/bin/python3
"""Deploy the machines radar with fresh QML URLs, without restarting the shell."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

def deploy_ui(source, destination):
    """Give each QML generation a fresh URL in the running shell's cache."""
    files = sorted([*source.glob('*.qml'), *source.glob('*.js'), *source.glob('icons/*.png'), *source.glob('act.py')])
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(source).as_posix().encode() + b'\0' + path.read_bytes())
    generation = digest.hexdigest()[:20]
    runtime = destination / '.runtime' / generation
    runtime.parent.mkdir(parents=True, exist_ok=True)
    if not runtime.exists():
        temporary = Path(tempfile.mkdtemp(prefix='.staging-', dir=runtime.parent))
        try:
            for path in files:
                target = temporary / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            temporary.rename(runtime)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    manifest = json.loads((source / 'manifest.json').read_text())
    manifest['entryPoints']['barWidget'] = '.runtime/' + generation + '/Panel.qml'
    with tempfile.NamedTemporaryFile('w', prefix='.manifest-', dir=destination, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    try:
        temporary.chmod(0o644)
        temporary.replace(destination / 'manifest.json')
    finally:
        temporary.unlink(missing_ok=True)
    return generation


def install():
    source = Path(__file__).resolve().parent
    destination = Path.home() / '.config/omarchy/plugins/lol.machines'
    subprocess.run(['omarchy-plugin-validate', str(source)], check=True)
    generation = deploy_ui(source, destination)
    for name in ('collect.py', 'probe.py', 'android.py', 'cloud.py', 'act.py', 'machines.example.json'):
        shutil.copy2(source / name, destination / name)
    units = Path.home() / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    (units / 'omarchy-machines.service').write_text(
        '[Unit]\nDescription=Machines radar: usage of servers and PCs\n\n'
        '[Service]\nType=oneshot\nExecStart=/usr/bin/python3 ' + json.dumps(str(destination / 'collect.py')) + '\n'
        'TimeoutStartSec=120\nUMask=0077\nNice=10\n')
    (units / 'omarchy-machines.timer').write_text(
        '[Unit]\nDescription=Refresh machines radar\n\n'
        '[Timer]\nOnStartupSec=20\nOnUnitInactiveSec=60\nAccuracySec=5\n\n'
        '[Install]\nWantedBy=timers.target\n')
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'omarchy-machines.timer'], check=True)
    subprocess.run(['omarchy-shell', 'shell', 'rescanPlugins'], check=True)
    for _ in range(50):
        plugins = json.loads(subprocess.run(['omarchy-plugin-list', '--json'], check=True, capture_output=True, text=True).stdout)
        if any(p.get('id') == 'lol.machines' for p in plugins):
            break
        time.sleep(.1)
    if not any(p.get('id') == 'lol.machines' and p.get('enabled') for p in plugins):
        subprocess.run(['omarchy-plugin-enable', 'lol.machines', '--after', 'lol.routers'], check=True)
    subprocess.run(['systemctl', '--user', 'start', '--no-block', 'omarchy-machines.service'], check=True)
    print('Máquinas instalado: ' + generation)


if __name__ == '__main__':
    install()
