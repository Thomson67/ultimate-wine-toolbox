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
    def test_version_menu_marks_only_releases_with_a_no_banner_variant(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            result = subprocess.run(['bash', '-c', '''source "$WT_ROOT/lib/common.sh"
WT_LANGUAGE=fr; load_i18n
source "$WT_ROOT/modules/reshade.sh"
menu_select() { printf '%s\\n' "$@" > "$MENU_LOG"; return 1; }
resh_version_select /unused/Game.wine
'''], capture_output=True, text=True, env=dict(os.environ, WT_ROOT=str(ROOT/'toolbox'),
                   WT_HOME=folder, MENU_LOG=str(home/'menu')))
            self.assertEqual(result.returncode, 1, result.stderr)
            labels = (home/'menu').read_text().splitlines()
            marked = [label for label in labels if 'sans bannière disponible' in label]
            self.assertEqual(marked, [version + ' — sans bannière disponible' for version in
                                      ('6.8.0', '6.7.3', '6.7.1', '6.6.2', '6.5.1', '6.5.0', '6.4.1', '6.2.0')])
            self.assertIn('6.8.0 — sans bannière disponible', labels)

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
        self.assertEqual(sum(e['variant'] == 'standard-addons' for e in entries), 41)
        self.assertEqual(sum(e['variant'] == 'no-startup-banner' for e in entries), 11)
        self.assertEqual({e['version'] for e in entries if e['variant'] == 'no-startup-banner'},
                         {'6.2.0', '6.4.1', '6.5.0', '6.5.1', '6.6.2', '6.7.1', '6.7.3', '6.8.0'})
        fork = next(e for e in entries if e['variant'] == 'no-startup-banner')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.json'
            for bad in (entries + [entries[0]], [dict(entries[0], url='https://example.org/setup.exe')],
                        [dict(entries[0], id='../bad')],
                        [dict(fork, provider='unknown/OverlayDisabledReShade')],
                        [dict(fork, containers=['../unexpected.exe'])],
                        [dict(fork, url=fork['url'].replace('github.com/', 'github.com.evil/'))]):
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
                entry.pop('dll_sha256', None)
                entry.pop('binary_versions', None)
                entry.pop('containers', None)
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

    def test_nested_fork_zip_and_same_version_providers_have_distinct_caches(self):
        entries = copy.deepcopy([v.selection('6.5.1-knitby-no-startup-banner'),
                                 v.selection('6.5.1-andrewgdx-no-startup-banner')])
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for entry in entries:
                inner = self.setup_bytes(entry['provider'].encode())
                data = inner
                for name in reversed(entry.get('containers', [])):
                    outer = io.BytesIO()
                    with zipfile.ZipFile(outer, 'w') as archive:
                        archive.writestr(name, data)
                    data = outer.getvalue()
                entry.pop('dll_sha256', None)
                entry.pop('binary_versions', None)
                entry['sha256'] = hashlib.sha256(data).hexdigest()
                paths.append(v.payload(folder, entry['id'], 64, lambda url, data=data: data, [entry]))
            self.assertNotEqual(paths[0], paths[1])
            self.assertNotEqual(paths[0].read_bytes(), paths[1].read_bytes())

    def test_pinned_binary_version_is_verified_before_writing(self):
        import struct
        entry = copy.deepcopy(v.selection('6.8.0-addons'))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for bits in (32, 64):
                revision = 1 if bits == 32 else 2
                content = pe(bits) + struct.pack('<IIII', 0xFEEF04BD, 0x10000, (6 << 16) | 8, revision)
                archive.writestr(f'ReShade{bits}.dll', content)
                entry['dll_sha256'][str(bits)] = hashlib.sha256(content).hexdigest()
                entry['binary_versions'][str(bits)] = f'6.8.0.{revision}'
        data = stream.getvalue()
        entry['sha256'] = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'home'
            bad = copy.deepcopy(entry)
            bad['binary_versions']['64'] = '6.8.0.99'
            with self.assertRaisesRegex(ValueError, 'version or checksum'):
                v.payload(root, bad['id'], 64, lambda url: data, [bad])
            self.assertFalse(root.exists())
            self.assertTrue(v.payload(root, entry['id'], 64, lambda url: data, [entry]).is_file())

    def test_official_addons_and_fork_choices_are_separate_and_ordered(self):
        result = subprocess.run([sys.executable, str(ROOT / 'toolbox/helpers/reshade_versions.py'),
                                 'variants', '6.5.1'], text=True, capture_output=True, check=True)
        ids = [line.split('\t')[0] for line in result.stdout.splitlines()]
        self.assertEqual(ids, ['6.5.1', '6.5.1-addons', '6.5.1-knitby-no-startup-banner',
                               '6.5.1-andrewgdx-no-startup-banner'])
        self.assertEqual(v.selection('6.5.1-addons')['variant'], 'standard-addons')
        self.assertFalse(v.selection('6.2.0-mjd4219-no-startup-banner')['source_available'])

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
 official:1|official:2) echo 1;; variant:1|back:1) echo "$VERSION_INDEX";;
 variant:2) echo 3;; back:2) echo back;; back:3|back:4) echo 1;;
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
            entry.pop('dll_sha256', None)
            entry.pop('binary_versions', None)
            entry.pop('containers', None)
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
