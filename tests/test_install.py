import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from install import deploy_ui


class InstallTests(unittest.TestCase):
    def test_new_import_changes_url_and_preserves_old_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            destination = Path(temporary) / 'installed'
            source.mkdir()
            (source / 'manifest.json').write_text(json.dumps({'entryPoints': {'barWidget': 'Panel.qml'}}))
            (source / 'Panel.qml').write_text('Content {}')
            (source / 'Content.qml').write_text('Item {}')
            first = deploy_ui(source, destination)
            self.assertEqual(first, deploy_ui(source, destination))
            (source / 'Content.qml').write_text('Item { property string title: "new" }')
            second = deploy_ui(source, destination)
            self.assertNotEqual(first, second)
            manifest = json.loads((destination / 'manifest.json').read_text())
            self.assertEqual(manifest['entryPoints']['barWidget'], f'.runtime/{second}/Panel.qml')
            self.assertEqual((destination / '.runtime' / first / 'Content.qml').read_text(), 'Item {}')
            self.assertEqual((destination / '.runtime' / second / 'Content.qml').read_bytes(), (source / 'Content.qml').read_bytes())
            self.assertEqual(json.loads((source / 'manifest.json').read_text())['entryPoints']['barWidget'], 'Panel.qml')

    def test_imported_javascript_changes_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            destination = Path(temporary) / 'installed'
            source.mkdir()
            (source / 'manifest.json').write_text('{"entryPoints": {"barWidget": "Panel.qml"}}')
            (source / 'Panel.qml').write_text('Item {}')
            (source / 'Model.js').write_text('function value() { return 1 }')
            first = deploy_ui(source, destination)
            (source / 'Model.js').write_text('function value() { return 2 }')
            self.assertNotEqual(first, deploy_ui(source, destination))

    def test_icons_ship_with_each_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            destination = Path(temporary) / 'installed'
            (source / 'icons').mkdir(parents=True)
            (source / 'manifest.json').write_text('{"entryPoints": {"barWidget": "Panel.qml"}}')
            (source / 'Panel.qml').write_text('Item {}')
            (source / 'icons' / 'claude.png').write_bytes(b'one')
            first = deploy_ui(source, destination)
            self.assertEqual((destination / '.runtime' / first / 'icons' / 'claude.png').read_bytes(), b'one')
            (source / 'icons' / 'claude.png').write_bytes(b'two')
            self.assertNotEqual(first, deploy_ui(source, destination))

