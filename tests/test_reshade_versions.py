import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import test_reshade as fixtures
from test_reshade import pe, r, ROOT

sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
import reshade_versions as v


class VersionCatalogTests(unittest.TestCase):
    def setup_bytes(self, marker=b''):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for arch in (32, 64):
                archive.writestr(f'ReShade{arch}.dll', pe(arch) + marker)
        return stream.getvalue()

    def test_catalog_has_only_real_variants_and_rejects_duplicates_and_wrong_source(self):
        entries = v.catalog()
        self.assertEqual(sum(e['variant'] == 'standard' for e in entries), 62)
        self.assertIn('4.1.0', {e['id'] for e in entries})
        self.assertEqual({e['version'] for e in entries if e['variant'] != 'standard'}, {'6.4.1', '6.2.0'})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.json'
            for bad in (entries + [entries[0]], [dict(entries[0], url='https://example.org/setup.exe')],
                        [dict(entries[0], id='../bad')]):
                path.write_text(json.dumps({'schema': 1, 'entries': bad}))
                with self.assertRaises(ValueError):
                    v.catalog(path)

    def test_old_vulkan_versions_are_filtered_and_rejected_before_game_changes(self):
        self.assertFalse(v.supports_api(v.selection('4.3.0'), 'vulkan'))
        self.assertTrue(v.supports_api(v.selection('4.4.0'), 'vulkan'))
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            rom = home/'Game.wine'
            rom.mkdir()
            with self.assertRaisesRegex(ValueError, 'does not support Vulkan'):
                r.prepare(home, rom, 'Game.exe', 'vulkan', '4.1.0', 'none', '4.1.0')
            self.assertEqual(list(home.iterdir()), [rom])
            self.assertEqual(list(rom.iterdir()), [])
            args = [sys.executable, str(v.CATALOG.parents[1]/'helpers/reshade_versions.py'), 'versions']
            directx = subprocess.run(args, text=True, capture_output=True, check=True)
            vulkan = subprocess.run(args+['--api', 'vulkan'], text=True, capture_output=True, check=True)
            self.assertIn('4.1.0\t0', directx.stdout)
            self.assertNotIn('4.1.0\t0', vulkan.stdout)
            self.assertIn('4.4.0\t0', vulkan.stdout)

    def test_separate_variants_cache_reuse_and_corruption_repair(self):
        entries = copy.deepcopy([e for e in v.catalog() if e['version'] in ('6.4.1', '6.2.0', '4.1.0')])
        with tempfile.TemporaryDirectory() as folder:
            for entry in entries:
                data = self.setup_bytes(entry['id'].encode())
                entry['sha256'] = hashlib.sha256(data).hexdigest()
                file = v.payload(folder, entry['id'], 64, lambda url: data, entries)
                self.assertEqual(file.read_bytes(), pe(64) + entry['id'].encode())
                with patch.object(v, 'download', side_effect=AssertionError('cache must be reused')):
                    self.assertEqual(v.payload(folder, entry['id'], 64, entries=entries), file)
                file.write_bytes(b'corrupt')
                self.assertEqual(v.payload(folder, entry['id'], 64, lambda url: data, entries).read_bytes(),
                                 pe(64) + entry['id'].encode())
            standard = Path(folder) / 'reshade/runtime/builds/6.4.1/ReShade64.dll'
            self.assertEqual(standard.read_bytes(), pe(64) + b'6.4.1')

    def test_wrong_hash_architecture_and_redirected_cache_write_nothing(self):
        entry = dict(v.catalog()[0])
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / 'home'
            with self.assertRaisesRegex(ValueError, 'checksum'):
                v.payload(home, entry['id'], 64, lambda url: b'bad', [entry])
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as archive:
                archive.writestr('ReShade32.dll', pe(64))
                archive.writestr('ReShade64.dll', pe(64))
            data = data.getvalue()
            entry['sha256'] = hashlib.sha256(data).hexdigest()
            with self.assertRaisesRegex(ValueError, 'architecture'):
                v.payload(home, entry['id'], 64, lambda url: data, [entry])
            self.assertFalse(home.exists())
            (home / 'reshade').mkdir(parents=True)
            (home / 'reshade/runtime').symlink_to(Path(folder), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'redirected'):
                v.payload(home, entry['id'], 64, lambda url: data, [entry])

    def test_picker_official_variant_back_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            counter = Path(folder) / 'count'
            script = '''source "$WT_ROOT/modules/reshade.sh"
i18n() { printf '%s' "$1"; }
menu_select() {
 local count=0; [ ! -f "$COUNT" ] || read -r count < "$COUNT"
 count=$((count+1)); echo "$count" > "$COUNT"
 case "$MODE:$count" in
 official:1) echo 1;; variant:1|back:1) echo "$VERSION_INDEX";;
 variant:2) echo 2;; back:2) echo back;; back:3) echo 1;;
 *) return 1;; esac
}
resh_version_select /unused/game.wine
'''
            for mode, expected in [('official', '6.8.0'), ('variant', '6.4.1-no-startup-banner'),
                                   ('back', '6.8.0'), ('cancel', '')]:
                counter.unlink(missing_ok=True)
                result = subprocess.run(['bash', '-c', script], text=True, capture_output=True,
                    env=dict(os.environ, WT_ROOT=str(ROOT / 'toolbox'), WT_HOME=folder,
                             COUNT=str(counter), MODE=mode,
                             VERSION_INDEX=str(sorted({e['version'] for e in v.catalog()}, key=lambda x: tuple(map(int, x.split('.'))), reverse=True).index('6.4.1')+1)))
                self.assertEqual(result.stdout, expected, result.stderr)
                self.assertEqual(result.returncode, int(mode == 'cancel'), result.stderr)

    def test_finish_switches_exact_variant_without_changing_presets(self):
        # Reuse the real manager's game/backend fixture, rather than mocking finish.
        fixture = fixtures.ReShadeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        entries = copy.deepcopy([e for e in v.catalog() if e['version'] in ('6.4.1', '6.2.0', '4.1.0')])
        initial = (fixture.profile / 'ReShadePreset.ini').read_bytes()
        for entry in entries:
            data = self.setup_bytes(entry['id'].encode())
            entry['sha256'] = hashlib.sha256(data).hexdigest()
            selected = v.payload(fixture.home, entry['id'], 64, lambda url: data, entries)
            with patch.object(v, 'catalog', return_value=entries):
                ws = r.prepare(fixture.home, fixture.rom, fixture.exe, 'dxgi', entry['version'], 'sweetfx-shaders', entry['id'])
                for name, source in [('dxgi.dll', fixture.runtime), ('d3dcompiler_47.dll', fixture.compiler),
                                     ('ReShade_shaders', fixture.shaders)]:
                    target = ws / name
                    target.unlink(missing_ok=True)
                    target.symlink_to(source)
                pending = r.read_json(ws / 'pending.json')
                state = fixture.home / 'reshade/runtime/game-state' / (pending['state_key'] + '.state')
                state.write_text(state.read_text().replace('selected_repos=\n', 'selected_repos=sweetfx-shaders\n'))
                with patch.dict(r.COMPILER_HASH, {64: r.fingerprint(fixture.compiler)['sha256']}):
                    config = r.finish(fixture.home, fixture.rom)
                self.assertEqual(config['runtime'], str(selected))
                self.assertEqual(config['release_id'], entry['id'])
                self.assertEqual(v.current(fixture.home, fixture.rom), entry['id'])
            self.assertEqual((fixture.profile / 'ReShadePreset.ini').read_bytes(), initial)


if __name__ == '__main__':
    unittest.main()
