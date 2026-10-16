import base64
import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock
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

    def test_downloaded_copies_are_detected_for_both_kinds_and_missing_files_ignored(self):
        for kind in ('antimicrox', 'reshade'):
            with self.subTest(kind=kind):
                self.catalogue(kind)
                item = next(item for item in self.community.load()['entries'] if item['kind'] == kind)
                path = self.community.fetch(kind, item['id'])
                self.assertEqual(self.community.local_profile(item), (path, False))
                output = io.StringIO()
                with patch.object(sys, 'argv', ['community', '--home', str(self.home), 'list', kind]), contextlib.redirect_stdout(output):
                    community.main()
                self.assertIn('[Téléchargé]', output.getvalue())
                with patch.object(community, 'es_games', return_value=[]):
                    self.assertEqual(community.suggest_game(self.home, kind, path), 'My Game')
                data = path.read_bytes()
                path.write_bytes(data + b'\n')
                self.assertEqual(self.community.local_profile(item), (path, True))
                path.unlink()
                self.assertIsNone(self.community.local_profile(item))

    def test_related_games_are_ranked_first_without_hiding_other_games(self):
        games = [('other', 'Unrelated'), ('mp3', 'Max Payne 3'), ('mp1', 'Max Payne'),
                 ('mp2', 'MAX PAYNE 2'), ('partial', 'Payne')]
        ranked = community.prioritize_games(games, 'Max Payne')
        self.assertEqual({path for path, _ in ranked[:3]}, {'mp1', 'mp2', 'mp3'})
        self.assertEqual(ranked[0][0], 'mp1')
        self.assertEqual(set(ranked), set(games))
        self.assertEqual(community.prioritize_games(games, ''), games)

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
        self.assertTrue(url.startswith('https://github.com/Thomson67/ultimate-wine-toolbox-community/issues/new?'))
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

    def test_explicit_refresh_bypasses_stale_github_cache_and_lists_new_reshade(self):
        _, package, _ = self.pack('reshade')
        root = self.base/'published'; community.approve(package, root)
        published = (root/'catalog.json').read_bytes()
        requested = []

        def serve(request, **kwargs):
            requested.append(request)
            response = MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = request.full_url
            # Model an edge cache still serving the empty catalogue at the branch URL.
            response.read.return_value = published if '?uwt_refresh=' in request.full_url else b'{"schema":1,"entries":[]}'
            return response

        with patch.object(community.urllib.request, 'urlopen', side_effect=serve):
            self.community.refresh()
            item = self.community.load()['entries'][0]
            self.assertEqual(item['kind'], 'reshade')
            self.community.refresh()
            self.assertNotEqual(requested[0].full_url, requested[1].full_url)
            self.assertTrue(all(r.get_header('Cache-control') == 'no-cache' for r in requested))
            self.assertEqual(json.loads(self.community.cache.read_text())['source'], self.community.base)
            self.community.network(self.community.base+item['file'])
            self.assertNotIn('uwt_refresh', requested[-1].full_url)

    def test_list_labels_omit_repeated_game_name_but_keep_distinct_profile_titles(self):
        item={'game':'Max Payne','title':'Max Payne','author':'Thomson'}
        self.assertEqual(community.entry_label(item),'Max Payne — Thomson')
        self.assertEqual(community.entry_label(dict(item,title=' max  PAYNE ')),'Max Payne — Thomson')
        self.assertEqual(community.entry_label(dict(item,title='Clavier AZERTY')),'Max Payne — Clavier AZERTY — Thomson')

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

    def test_game_name_is_derived_from_profile_title_or_generated_filename(self):
        source = self.base/'Gobliins 6[L]-pad2key-abcdef12-2.amgp'
        source.write_bytes(AMX)
        with patch.object(community, 'es_games', side_effect=OSError('offline')):
            self.assertEqual(community.suggest_game(self.home, 'antimicrox', source), 'Gobliins 6')
            source.write_text('<gamecontroller><profilename>Max Payne.wsquashfs (Pad2Key)</profilename></gamecontroller>')
            self.assertEqual(community.suggest_game(self.home, 'antimicrox', source), 'Max Payne')
        self.assertEqual(community.game_title('Oddworld Strangers Wrath HD[L]-a373c62f.amgp'), 'Oddworld Strangers Wrath HD')
        self.assertEqual(community.game_title('Game [GE-Proton11-7-UMU].wsquashfs.keys'), 'Game')
        self.assertEqual(community.game_title('[PROTOTYPE].amgp'), '[PROTOTYPE]')

    def test_association_uses_scraped_es_name_and_shared_profile_requires_selection(self):
        source = self.base/'profile.amgp'; source.write_bytes(AMX)
        config = self.home/'config'; config.mkdir(parents=True)
        rom = '/userdata/roms/windows/Game[L].wsquashfs'
        associations = config/'antimicrox-games.tsv'; associations.write_text(f'{rom}\t{source}\n')
        with patch.object(community, 'es_games', return_value=[(rom, 'The scraped game title')]):
            self.assertEqual(community.suggest_game(self.home, 'antimicrox', source), 'The scraped game title')
        associations.write_text(associations.read_text()+f'/userdata/roms/windows/Other.wine\t{source}\n')
        with patch.object(community, 'es_games') as games:
            self.assertEqual(community.suggest_game(self.home, 'antimicrox', source), '')
            games.assert_not_called()

    def test_reshade_suggestion_uses_selected_game_not_temporary_export_filename(self):
        rom = '/userdata/roms/windows/Game [L].wine'
        source = self.base/'uwt-community-preset.ABC123.ini'; source.write_bytes(PRESET)
        with patch.object(community, 'es_games', return_value=[(rom, 'Game title from ES')]):
            self.assertEqual(community.suggest_game(self.home, 'reshade', source, rom), 'Game title from ES')
        with patch.object(community, 'es_games', side_effect=OSError):
            self.assertEqual(community.suggest_game(self.home, 'reshade', source, rom), 'Game')

    def test_suggestion_uses_download_metadata_and_conversion_source(self):
        item, _ = self.catalogue(); source = self.community.fetch('antimicrox', item['id'])
        with patch.object(community, 'es_games', return_value=[]):
            self.assertEqual(community.suggest_game(self.home, 'antimicrox', source), 'My Game')
        imported = self.home/'state/community/imports.json'; imported.unlink()
        registry = self.home/'state/antimicrox-pad2key-conversions.json'
        registry.write_text(json.dumps({str(source.resolve()): {'source': '/userdata/roms/windows/Converted Game.wine/padto.keys'}}))
        with patch.object(community, 'es_games', return_value=[]):
            self.assertEqual(community.suggest_game(self.home, 'antimicrox', source), 'Converted Game')

    def test_manual_game_list_reads_es_and_ignores_non_windows_game_items(self):
        values = [{'path': '/userdata/roms/windows/A[L].wsquashfs', 'name': 'A [L]'},
                  {'path': '/userdata/roms/windows/B.pc', 'name': 'B'},
                  {'path': '/userdata/roms/windows/folder', 'name': 'Folder'},
                  {'path': '/userdata/roms/ports/Toolbox.sh', 'name': 'Toolbox'}]
        response = MagicMock(); response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = json.dumps(values).encode()
        with patch.object(community.urllib.request, 'urlopen', return_value=response) as request:
            self.assertEqual(community.es_games(), [('/userdata/roms/windows/A[L].wsquashfs', 'A'),
                                                   ('/userdata/roms/windows/B.pc', 'B')])
            self.assertEqual(request.call_args.args[0], 'http://127.0.0.1:1234/systems/windows/games')

    def test_share_game_choice_accepts_suggestion_or_selects_gamelist_without_typing_name(self):
        for choice, expected in [('use', 'Detected Game'), ('select', 'Game from ES')]:
            script = r'''
set -u
WT_HOME="$TEST_HOME"; WT_LANGUAGE=fr
source "$ROOT/toolbox/modules/community.sh"
i18n() { echo Back; }
msgbox() { :; }
input_text() { echo unexpected-free-text; return 1; }
community_cmd() { case "$1" in suggest-game) echo 'Detected Game';; games) printf '/userdata/roms/windows/Game.wsquashfs\tGame from ES\n';; esac; }
menu_select() { if [ "$3" = use ]; then echo "$CHOICE"; else echo 1; fi; }
community_share_game antimicrox /userdata/profile.amgp Community
'''
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(self.home), CHOICE=choice), timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, expected)

    def test_game_name_selected_for_share_is_passed_to_package_metadata(self):
        script = r'''
set -u
WT_HOME="$TEST_HOME"; WT_LANGUAGE=fr
source "$ROOT/toolbox/modules/community.sh"
amx_profile_file() { echo /userdata/profiles/Game.amgp; }
community_cmd() {
  case "$1" in
    suggest-game) echo 'Detected Game';;
    share) printf '%s\n' "$@" > "$TEST_HOME/shared-args"; printf '/userdata/package.zip\nhttps://github.com/example/issues/new\n';;
  esac
}
menu_select() { echo use; }
input_text() { if [ "$2" = 'Votre pseudo public' ]; then echo Tester; else printf '%s' "$3"; fi; }
yesno() { return 0; }
community_report() { :; }
community_send_package() { :; }
msgbox() { :; }
i18n() { echo Back; }
community_share antimicrox Community
'''
        self.home.mkdir(parents=True)
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
            env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(self.home)), timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.home/'shared-args').read_text().splitlines()
        self.assertEqual(args[args.index('--game')+1], 'Detected Game')
        self.assertEqual(args[args.index('--title')+1], 'Detected Game')


if __name__ == '__main__': unittest.main()
