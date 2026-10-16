import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import community_profiles as community
from antimicrox_pad2key_state import Pad2KeyStore

AMX = b'<gamecontroller><uniqueID>private-id</uniqueID><sdlname>Private Pad</sdlname><sets><set index="1"><button index="6"><setselect>2</setselect><setselectcondition>while-held</setselectcondition></button><button index="1"><slots><slot><code>65</code><mode>keyboard</mode></slot></slots></button></set></sets></gamecontroller>'
PRESET = b'Techniques=CAS@CAS.fx\nTechniqueSorting=CAS@CAS.fx\n[CAS.fx]\nSharpness=0.500\n'


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.home = self.base/'userdata/system/toolbox'
        self.community = community.Community(self.home)

    def pack(self, kind='antimicrox'):
        source = self.base/('original.amgp' if kind == 'antimicrox' else 'preset.ini')
        source.write_bytes(AMX if kind == 'antimicrox' else PRESET)
        package, url = self.community.share(kind, source, 'My Game', 'Test profile', 'Tester',
                                             tested_on='Batocera 43.1', requirements=['Standard effects'] if kind == 'reshade' else [])
        return source, package, url

    def catalogue(self, kind='antimicrox'):
        source, package, url = self.pack(kind)
        root = self.base/'catalogue'
        path = community.approve(package, root)
        value = json.loads((root/'catalog.json').read_text())
        self.community.download = lambda url: (root/url.removeprefix(self.community.base)).read_bytes()
        self.community.refresh()
        return value['entries'][0], path

    def test_export_strips_controller_identity_and_never_modifies_original(self):
        source, package, url = self.pack()
        self.assertEqual(source.read_bytes(), AMX)
        with zipfile.ZipFile(package) as archive:
            data = archive.read('profile.amgp')
            self.assertNotIn(b'private-id', data); self.assertNotIn(b'Private Pad', data)
            meta = json.loads(archive.read('metadata.json'))
            self.assertEqual(meta['sha256'], hashlib.sha256(data).hexdigest())
            self.assertIn('Guide', meta['hotkey'])
            self.assertNotIn(str(self.home).encode(), archive.read('metadata.json'))
        self.assertTrue(url.startswith('https://github.com/Thomson67/ultimate-wine-toolbox/issues/new?'))
        self.assertIn('Tester', url)
        self.assertTrue(package.with_suffix('.txt').is_file())

    def test_review_export_catalogue_download_roundtrip(self):
        for kind in ('antimicrox', 'reshade'):
            with self.subTest(kind=kind):
                if (self.base/'catalogue').exists():
                    import shutil; shutil.rmtree(self.base/'catalogue')
                item, published = self.catalogue(kind)
                fetched = self.community.fetch(kind, item['id'])
                self.assertEqual(fetched.read_bytes(), published.read_bytes())
                self.assertEqual(self.community.fetch(kind, item['id']), fetched)
                self.assertIn(item['game'], community.details(item))
                if kind == 'antimicrox': self.assertTrue(Pad2KeyStore(self.home, self.base/'userdata').is_community(str(fetched)))

    def test_failed_refresh_preserves_offline_cache(self):
        item, _ = self.catalogue()
        before = self.community.cache.read_bytes()
        self.community.download = Mock(side_effect=OSError('offline'))
        with self.assertRaises(OSError): self.community.refresh()
        self.assertEqual(self.community.cache.read_bytes(), before)
        self.assertEqual(self.community.find('antimicrox', item['id'])['author'], 'Tester')
        self.community.download.assert_called_once()

    def test_bad_refresh_does_not_replace_previous_catalogue(self):
        self.catalogue(); before = self.community.cache.read_bytes()
        for value in ({'schema': 2, 'entries': []}, {'schema': 1, 'entries': [{}]}):
            self.community.download = lambda _: json.dumps(value).encode()
            with self.assertRaises(ValueError): self.community.refresh()
            self.assertEqual(self.community.cache.read_bytes(), before)

    def test_hash_mismatch_never_installs_profile(self):
        item, _ = self.catalogue()
        self.community.download = lambda _: b'changed'
        with self.assertRaisesRegex(ValueError, 'checksum'): self.community.fetch('antimicrox', item['id'])
        self.assertFalse((self.home/'config/antimicrox-profiles').exists())

    def test_personal_edit_to_download_is_preserved_on_redownload(self):
        item, _ = self.catalogue()
        first = self.community.fetch('antimicrox', item['id']); first.write_bytes(b'personal edit')
        second = self.community.fetch('antimicrox', item['id'])
        self.assertNotEqual(first, second); self.assertEqual(first.read_bytes(), b'personal edit')
        self.assertTrue(second.is_file())

    def test_catalogue_rejects_traversal_urls_duplicates_and_terminal_controls(self):
        item, _ = self.catalogue()
        for change in ({'file': '../bad.amgp'}, {'file': 'https://example.com/evil.amgp'},
                       {'file': 'antimicrox/../../evil.amgp'}, {'file': 'reshade/wrong.ini'},
                       {'title': 'bad\x1b[2J'}, {'sha256': 123}, {'id': '../escape'}):
            with self.subTest(change=change), self.assertRaises(ValueError): community.entry(dict(item, **change))
        with self.assertRaises(ValueError): community.catalogue({'schema': 1, 'entries': [item, item]})

    def test_external_command_or_profile_load_is_rejected_even_nested(self):
        for mode in ('execute', 'loadprofile'):
            data = AMX.replace(b'<mode>keyboard</mode>', f'<mode>{mode}</mode>'.encode())
            with self.assertRaises(ValueError): community.profile_bytes('antimicrox', data, export=True)
        with self.assertRaises(ValueError): community.profile_bytes('antimicrox', AMX)

    def test_only_portable_reshade_presets_are_accepted(self):
        self.assertEqual(community.profile_bytes('reshade', PRESET, export=True), PRESET)
        for bad in (b'[GENERAL]\nPresetPath=Z:\\userdata\\test.ini', PRESET+b'EffectSearchPaths=/userdata/shaders\n',
                    PRESET+b'UserPath=C:\\Users\\Alice\\test\n', b'not a preset', b'\x00'):
            with self.subTest(bad=bad), self.assertRaises(ValueError): community.profile_bytes('reshade', bad, export=True)

    def test_invalid_archive_is_never_extracted(self):
        _, package, _ = self.pack()
        with zipfile.ZipFile(package, 'a') as archive: archive.writestr('../escape', 'bad')
        with self.assertRaises(ValueError): community.approve(package, self.base/'target')
        self.assertFalse((self.base/'escape').exists())

    def test_imported_profile_assignment_suspends_and_restores_pad2key(self):
        item, _ = self.catalogue(); profile = self.community.fetch('antimicrox', item['id'])
        rom = self.base/'userdata/roms/windows/Game.wsquashfs'; rom.parent.mkdir(parents=True); rom.touch()
        keys = Path(str(rom)+'.keys'); original = b'{"actions_player1":[{"trigger":"b","type":"key","target":"KEY_ENTER"}]}'
        keys.write_bytes(original)
        store = Pad2KeyStore(self.home, self.base/'userdata')
        store.assign(str(rom), str(profile))
        self.assertEqual(json.loads(keys.read_text())['actions_player1'][0]['target'], [])
        store.assign(str(rom), '')
        self.assertEqual(keys.read_bytes(), original)

    def test_different_source_does_not_reuse_wrong_catalogue_cache(self):
        self.catalogue()
        (self.home/'config').mkdir(exist_ok=True)
        (self.home/'config/community-source.json').write_text(json.dumps({'repository': 'Other/Catalogue', 'ref': 'main'}))
        fetch = Mock(return_value=b'{"schema":1,"entries":[]}')
        other = community.Community(self.home, fetch)
        self.assertEqual(other.load()['entries'], [])
        fetch.assert_called_once_with('https://raw.githubusercontent.com/Other/Catalogue/main/catalog.json')

    def test_menu_routes_are_separate_for_each_tool(self):
        for function, kind in [('antimicrox_menu', 'antimicrox'), ('resh_menu', 'reshade')]:
            script = r'''
set -u
source "$ROOT/toolbox/lib/common.sh"
WT_HOME="$TEST_HOME"; WT_LANGUAGE=fr
source "$ROOT/toolbox/lang/fr.sh"
source "$ROOT/toolbox/modules/community.sh"
source "$ROOT/toolbox/modules/antimicrox.sh"
source "$ROOT/toolbox/modules/reshade.sh"
msgbox() { :; }
menu_select() { if [ -f "$TEST_HOME/once" ]; then echo 0; else mkdir -p "$TEST_HOME"; touch "$TEST_HOME/once"; echo community; fi; }
community_menu() { echo "selected:$1"; }
"$FUNCTION"
'''
            home = self.base/kind
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                                    env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(home), FUNCTION=function), timeout=5)
            # AntiMicroX's exit item is 0; menu stub returns an empty choice on the second call.
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('selected:'+kind, result.stdout)

    def test_reshade_apply_exports_backup_first_and_never_applies_after_export_failure(self):
        for fail in ('none', 'export', 'preset'):
            with self.subTest(fail=fail):
                home = self.base/fail; home.mkdir()
                preset = home/'download.ini'; preset.write_bytes(PRESET)
                script = r'''
set -u
source "$ROOT/toolbox/lib/common.sh"
WT_HOME="$TEST_HOME"; WT_LANGUAGE=fr
source "$ROOT/toolbox/lang/fr.sh"
source "$ROOT/toolbox/modules/community.sh"
menu_select() { if [ -f "$WT_HOME/once" ]; then echo back; else touch "$WT_HOME/once"; echo apply; fi; }
yesno() { return 0; }
msgbox() { printf '%s\n' "$2" >> "$WT_HOME/messages"; }
resh_cmd() {
  case "$1" in
    status) echo enabled;;
    export) [ "$FAIL" != export ] || { echo 'export failed'; return 1; }; echo old-preset > "$3";;
    preset) echo attempted >> "$WT_HOME/applied"; [ "$FAIL" != preset ] || return 1; cat "$3" > "$WT_HOME/new-preset";;
  esac
}
community_import_actions reshade "$WT_HOME/download.ini" ReShade /userdata/roms/windows/Game.wine
'''
                result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                    env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(home), FAIL=fail), timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                backups = list((home/'exports/community-backups').glob('*.ini'))
                if fail == 'export':
                    self.assertEqual(backups, []); self.assertFalse((home/'applied').exists())
                else:
                    self.assertEqual(len(backups), 1); self.assertEqual(backups[0].read_text(), 'old-preset\n')
                    self.assertTrue((home/'applied').exists())
                if fail == 'none': self.assertEqual((home/'new-preset').read_bytes(), PRESET)
                self.assertEqual(preset.read_bytes(), PRESET)

    def test_community_live_launch_exits_ports_not_a_subshell(self):
        script = r'''
set -u
source "$ROOT/toolbox/lib/common.sh"
WT_HOME="$TEST_HOME"; WT_LANGUAGE=fr
source "$ROOT/toolbox/lang/fr.sh"
source "$ROOT/toolbox/modules/community.sh"
menu_select() { echo live; }
yesno() { return 0; }
msgbox() { :; }
amx_running() { return 1; }
amx_set_profile() { printf '%s' "$2" > "$WT_HOME/assigned"; }
amx_live_start_for() { touch "$WT_HOME/live"; exit 0; }
community_import_actions antimicrox /userdata/profile.amgp AntiMicroX /userdata/roms/windows/Game.wine
echo must-not-continue
'''
        self.home.mkdir(parents=True)
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                    env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(self.home)), timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home/'live').exists())
        self.assertNotIn('must-not-continue', result.stdout)

    def test_runtime_is_required_before_suspending_pad2key_for_community_profile(self):
        import antimicrox_pad2key as converter
        item, _ = self.catalogue(); profile = self.community.fetch('antimicrox', item['id'])
        with patch.object(sys, 'argv', ['converter', '--home', str(self.home), 'assign', '/userdata/roms/windows/Game.wine', str(profile)]), \
             patch.object(converter.os, 'access', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Install AntiMicroX'): converter.main()
        self.assertFalse(Pad2KeyStore(self.home).state.exists())


if __name__ == '__main__': unittest.main()
