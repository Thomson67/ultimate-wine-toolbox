"""Check ES choices, selection dispatch, cache preservation and service lifecycle."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / 'toolbox/helpers'
sys.path.insert(0, str(HELPERS))

import community_catalog as catalogue
import community_es
import es_options
import xml.etree.ElementTree as ET
from community_profiles import Community, apply_launcher_import, launcher_export
from community_packs import Packs
from antimicrox_launcher import Store
from antimicrox_pad2key_state import Pad2KeyStore, atomic as pad_atomic
from antimicrox_profiles import Profiles


def profile(kind, game):
    suffix = '.ini' if kind == 'reshade' else '.amgp'
    return dict(id='profile', kind=kind, game=game, title='Profile', author='Author',
                file=f'{kind}/profile{suffix}', sha256=hashlib.sha256(b'fixture').hexdigest())


class CatalogueTests(unittest.TestCase):
    def test_cached_profiles_and_packs_are_published_as_native_choices(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            digest = hashlib.sha256(b'zip').hexdigest()
            pack = dict(id='pack-'+digest, sha256=digest, game='Psychonauts',
                        title='Graphics pack', author='Author')
            community = Community(home)
            community.cache.parent.mkdir(parents=True)
            community.cache.write_text(json.dumps({
                'source': community.base,
                'catalog': {'schema': 1, 'entries': [
                    dict(profile('antimicrox', 'Psychonauts'), requirements=['UWT launcher-package-v1']),
                    dict(profile('antimicrox', 'Psychonauts 2'), id='other',
                         file='antimicrox/other.amgp'),
                    dict(profile('reshade', 'Psychonauts'), id='preset', file='reshade/preset.ini'),
                ]},
            }))
            packs = Packs(home)
            with patch.object(Packs, 'listing', return_value=[pack]):
                catalogue.refresh_packs(packs)
            features = home / 'es_features.cfg'
            es_options.publish({'mangohud', 'antimicrox', 'reshade'}, 'fr', features, home=home)
            with patch.object(Packs, 'listing', side_effect=AssertionError('network during feature generation')):
                es_options.enable_community('fr', features, home=home)
            tree = ET.parse(features)
            node = tree.find('.//feature[@value="uwt_community_reshade"]')
            self.assertEqual({choice.get('value') for choice in node}, {'preset', 'zip:'+pack['id']})
            node = tree.find('.//feature[@value="uwt_community_antimicrox"]')
            self.assertEqual({choice.get('value') for choice in node}, {'profile', 'other'})
            self.assertEqual(node.find('choice[@value="profile"]').get('name'), 'profile.amgp [Launcher]')
            self.assertEqual(node.find('choice[@value="other"]').get('name'), 'other.amgp')
            system = tree.find('./emulator/system')
            keys = [feature.get('value') for feature in system]
            for kind in ('reshade', 'antimicrox'):
                self.assertEqual(keys[keys.index(f'uwt_{kind}')+1], f'uwt_community_{kind}')
            system.insert(0, system[-1])
            del system[-1]
            es_options.write_features(features, tree.getroot())
            es_options.refresh(features, home=home)
            self.assertEqual([feature.get('value') for feature in ET.parse(features).find('./emulator/system')], keys)
            self.assertIn('mangohud', es_options.exposed(features))
            es_options.publish({'mangohud'}, 'fr', features, home=home)
            es_options.enable_community('fr', features, home=home)
            self.assertNotIn('community_reshade', es_options.exposed(features))

    def test_reshade_es_labels_only_show_the_preset_or_bundle_filename(self):
        game = 'The Legend of Zelda - Ocarina of Time 3D'
        entries = {
            'named': dict(game=game, title=f'{game} — Sans CRT', file='reshade/sans-crt.ini', author='Auteur'),
            'zip:pack-bundle': dict(game=game, title='Pack Ultra', author='Auteur'),
            'zip:pack-second': dict(game=game, title='Original.zip', author='Auteur'),
        }
        with patch.object(catalogue, 'cached_entries', return_value=entries):
            choices = dict(catalogue.es_choices(Path('/unused'), 'reshade'))
        self.assertEqual(choices, {'named': 'sans-crt.ini',
                                   'zip:pack-bundle': 'Pack Ultra.zip', 'zip:pack-second': 'Original.zip'})

    def test_es_selection_targets_the_game_once_and_auto_rearms_it(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            rom = home / 'Psychonauts[GE-Proton11-11-UMU].wsquashfs'
            rom.touch()
            features = home / 'es_features.cfg'
            es_options.publish({'community'}, 'fr', features, home=home)
            conf = home / 'batocera.conf'
            key = es_options.game_key(rom, 'community_antimicrox')
            entries = {'matching': {'game': 'Psychonauts'}, 'other': {'game': 'Psychonauts 2'}}
            watcher = community_es.Selections(home, lambda *_: entries, features, conf)
            with patch.object(community_es, 'es_games', return_value=[(str(rom), 'Psychonauts')]), \
                 patch.object(community_es, 'EsApi') as es, \
                 patch.object(community_es, 'open_selection', return_value=True) as launch:
                es.return_value.running.return_value = (200, '/another/game')

                conf.write_text(f'windows.uwt_community_reshade=system-value\n{key}=matching\n')
                watcher.poll()
                launch.assert_not_called()
                watcher.poll()
                launch.assert_not_called()
                es.return_value.running.return_value = (201, '')
                watcher.retry_at = 0
                watcher.poll()
                self.assertEqual(launch.call_args.args[2], ['antimicrox', str(rom), 'matching'])
                watcher = community_es.Selections(home, lambda *_: entries, features, conf)
                watcher.poll()
                watcher.poll()
                self.assertEqual(launch.call_count, 1)
                conf.write_text(f'{key}=auto\n')
                watcher.poll()
                watcher.poll()
                conf.write_text(f'{key}=matching\n')
                watcher.poll()
                watcher.poll()
                self.assertEqual(launch.call_count, 2)
                conf.write_text(f'{key}=other\n')
                watcher.poll()
                watcher.poll()
                self.assertEqual(launch.call_args.args[2], ['antimicrox', str(rom), 'other'])

    def test_selection_requires_a_unique_registered_game(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            rom = home/'Renamed.wine'
            rom.mkdir()
            duplicate = home/'other'/rom.name
            duplicate.mkdir(parents=True)
            share = {'game': 'Original title'}
            amx = 'community_antimicrox'
            reshade = 'community_reshade'
            games = [(str(rom), 'Custom ES title')]
            with patch.object(community_es, 'es_games', return_value=games):
                self.assertEqual(community_es.resolve_game(amx, es_options.game_key(rom, amx), share), str(rom))
                self.assertIsNone(community_es.resolve_game(reshade, es_options.game_key(rom, reshade), share))
                games.append((str(duplicate), 'Original title'))
                self.assertIsNone(community_es.resolve_game(amx, es_options.game_key(rom, amx), share))

    def test_reselecting_assigned_antimicrox_profile_keeps_toolbox_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            rom = home/'Renamed.wine'
            rom.mkdir()
            features, conf = home/'es_features.cfg', home/'batocera.conf'
            es_options.publish({'community'}, 'fr', features, home=home)
            share = profile('antimicrox', 'Original title')
            path = Community(home).install_profile(share, b'<gamecontroller><sets/></gamecontroller>')
            associations = home/'config/antimicrox-games.tsv'
            associations.write_text(f'{rom}\t{path}\n')
            edited = b'<gamecontroller><uniqueID>local-pad</uniqueID><sets/></gamecontroller>'
            path.write_bytes(edited)
            key = es_options.game_key(rom, 'community_antimicrox')
            conf.write_text(f'{key}=profile\n')
            watcher = community_es.Selections(home, lambda *_: {'profile': share}, features, conf)
            with patch.object(community_es, 'es_games', return_value=[(str(rom), 'Custom ES title')]), \
                 patch.object(community_es, 'EsApi') as api, \
                 patch.object(community_es, 'open_selection') as launch:
                api.return_value.running.return_value = (201, '')
                watcher.poll()
                watcher.poll()
                launch.assert_not_called()
                self.assertEqual(watcher.dispatched, {key: 'profile'})
            self.assertEqual(path.read_bytes(), edited)
            self.assertEqual(associations.read_text(), f'{rom}\t{path}\n')
            self.assertFalse(community_es.antimicrox_already_assigned(home, str(rom), dict(share, sha256='f'*64)))
            self.assertFalse(community_es.antimicrox_already_assigned(home, str(home/'Other.wine'), share))

    def test_reselecting_launcher_requires_the_complete_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            rom = str(home/'Target.wine')
            source = home/'original.amgp'
            source.write_bytes(b'<gamecontroller><sets/></gamecontroller>')
            store = Store(home)
            rule = {'field': 'title', 'match': 'exact', 'value': 'Launcher'}
            store.save(rom, 'profiles', str(source), rule, str(source))
            bundle = launcher_export(home, source, rom)
            share = profile('antimicrox', 'Original title')
            share['sha256'] = hashlib.sha256(bundle).hexdigest()
            launcher = Community(home).install_profile(share, bundle)
            (home/'config/antimicrox-games.tsv').write_text(f'{rom}\t{launcher}\n')
            self.assertFalse(community_es.antimicrox_already_assigned(home, rom, share))
            config = apply_launcher_import(home, launcher, rom)
            self.assertTrue(community_es.antimicrox_already_assigned(home, rom, share))
            store.save(rom, 'profiles', str(launcher), dict(rule, value='Customized'),
                       config['game_profile'])
            self.assertTrue(community_es.antimicrox_already_assigned(home, rom, share))
            game = Path(config['game_profile'])
            game.write_text('<gamecontroller>')
            self.assertFalse(community_es.antimicrox_already_assigned(home, rom, share))
            game.unlink()
            self.assertFalse(community_es.antimicrox_already_assigned(home, rom, share))

    def test_es_applies_downloaded_profile_and_backs_up_pad2key_without_opening_toolbox(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            rom = home/'Renamed.wine'
            rom.mkdir()
            keys = rom/'padto.keys'
            original = b'{"actions_player1": [{"trigger": "a", "type": "key", "target": ["KEY_A"]}]}'
            keys.write_bytes(original)
            features, conf = home/'es_features.cfg', home/'batocera.conf'
            es_options.publish({'community'}, 'fr', features, home=home)
            share = profile('antimicrox', 'Original title')
            path = Community(home).install_profile(share, b'<gamecontroller><sets/></gamecontroller>')
            binary = home/'tools/antimicrox/antimicrox'
            binary.parent.mkdir(parents=True)
            binary.touch(mode=0o755)
            pad = Pad2KeyStore(home, home)
            key = es_options.game_key(rom, 'community_antimicrox')
            conf.write_text(f'{key}=profile\n')
            watcher = community_es.Selections(home, lambda *_: {'profile': share}, features, conf)
            with patch.object(community_es, 'es_games', return_value=[(str(rom), 'Renamed')]), \
                 patch.object(community_es, 'EsApi') as api, \
                 patch.object(community_es, 'open_selection') as launch, \
                 patch('antimicrox_pad2key_state.Pad2KeyStore', return_value=pad), \
                 patch.object(Profiles, 'running', return_value=False):
                api.return_value.running.return_value = (201, '')
                watcher.poll()
                watcher.poll()
                launch.assert_not_called()
                self.assertEqual(watcher.dispatched, {key: 'profile'})
            self.assertEqual(pad.cfg.read_text(), f'{rom}\t{path}\n')
            self.assertEqual(json.loads(keys.read_bytes())['actions_player1'][0]['target'], [])
            pad.assign(str(rom), '')
            self.assertEqual(keys.read_bytes(), original)

    def test_cached_launcher_and_pad2key_assignment_roll_back_together(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            rom = home/'Target.wine'
            rom.mkdir()
            keys = rom/'padto.keys'
            original = b'{"actions_player1": []}'
            keys.write_bytes(original)
            source = home/'original.amgp'
            source.write_bytes(b'<gamecontroller><sets/></gamecontroller>')
            store = Store(home)
            rule = {'field': 'title', 'match': 'exact', 'value': 'Launcher'}
            store.save(str(rom), 'profiles', str(source), rule, str(source))
            bundle = launcher_export(home, source, str(rom))
            share = dict(profile('antimicrox', 'Original title'), sha256=hashlib.sha256(bundle).hexdigest())
            launcher = Community(home).install_profile(share, bundle)
            binary = home/'tools/antimicrox/antimicrox'
            binary.parent.mkdir(parents=True)
            binary.touch(mode=0o755)
            pad = Pad2KeyStore(home, home)
            launcher_path = store.path(str(rom))
            before = launcher_path.read_bytes()

            def fail_launcher_write(path, data, *args):
                if path == launcher_path:
                    raise OSError('Could not write launcher')
                return pad_atomic(path, data, *args)

            with patch('antimicrox_pad2key_state.Pad2KeyStore', return_value=pad), \
                 patch.object(Profiles, 'running', return_value=False):
                with patch('antimicrox_pad2key_state.atomic', side_effect=fail_launcher_write):
                    self.assertFalse(community_es.apply_downloaded_antimicrox(home, str(rom), share))
                self.assertEqual(keys.read_bytes(), original)
                self.assertEqual(launcher_path.read_bytes(), before)
                self.assertFalse(pad.cfg.exists())
                self.assertFalse(pad.state.exists())
                self.assertTrue(community_es.apply_downloaded_antimicrox(home, str(rom), share))
            self.assertEqual(pad.cfg.read_text(), f'{rom}\t{launcher}\n')
            self.assertEqual(store.load(str(rom), str(launcher))['launcher_rule'], rule)

    def test_local_preset_selection_does_not_relaunch_a_pending_community_request(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            rom = home/'Game.wine'
            rom.mkdir()
            features, conf = home/'es_features.cfg', home/'batocera.conf'
            es_options.publish({'community'}, 'fr', features, home=home)
            community_key = es_options.game_key(rom, 'community_reshade')
            local_key = es_options.game_key(rom, es_options.RESHADE_PRESET_KEY)
            local_value = 'a'*24+':'+'b'*24
            watcher = community_es.Selections(home, lambda *_: {}, features, conf)
            with patch.object(community_es, 'EsApi') as api, patch.object(community_es, 'open_selection') as launch:
                api.return_value.running.return_value = (200, '/gamelist')
                conf.write_text(f'{community_key}=old-share\n')
                watcher.poll()
                watcher.poll()
                watcher.retry_at = 0
                api.return_value.running.return_value = (201, '')
                conf.write_text(f'{community_key}=old-share\n{local_key}={local_value}\n')
                watcher.poll()
                watcher.poll()
                launch.assert_not_called()
                conf.write_text(f'{community_key}=new-share\n{local_key}={local_value}\n')
                watcher.poll()
                watcher.poll()
                launch.assert_called_once()

    def test_community_pack_reactivation_keeps_the_toolbox_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            rom = home/'Game.wine'
            rom.mkdir()
            features, conf = home/'es_features.cfg', home/'batocera.conf'
            es_options.publish({'community'}, 'fr', features, home=home)
            key = es_options.game_key(rom, 'community_reshade')
            value = 'zip:pack-'+'a'*64
            conf.write_text(f'{key}={value}\n')
            watcher = community_es.Selections(home, lambda *_: {value: {'game': 'Game'}}, features, conf)
            with patch.object(community_es, 'EsApi') as api, \
                 patch.object(community_es, 'es_games', return_value=[(str(rom), 'Game')]), \
                 patch.object(community_es, 'apply_installed_reshade', return_value=True) as apply, \
                 patch.object(community_es, 'open_selection') as launch:
                api.return_value.running.return_value = (201, '')
                watcher.poll()
                watcher.poll()
                apply.assert_called_once()
                launch.assert_not_called()

    def test_auto_clears_delivered_state_even_when_another_selection_cannot_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            features = home/'es_features.cfg'
            es_options.publish({'community'}, 'fr', features, home=home)
            conf = home/'batocera.conf'
            first = es_options.game_key('First.wine', 'community_reshade')
            second = es_options.game_key('Second.wine', 'community_antimicrox')
            watcher = community_es.Selections(home, lambda *_: {}, features, conf)
            watcher.save_delivered({first: 'already-opened'})
            conf.write_text(f'{second}=pending\n')
            with patch.object(community_es, 'EsApi') as api:
                api.return_value.running.return_value = (200, '/toolbox')
                watcher.poll()
                watcher.poll()
            self.assertEqual(json.loads(watcher.state.read_text()), {})

    def test_unconfirmed_launch_is_not_retried_until_auto_is_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            features = home/'es_features.cfg'
            es_options.publish({'community'}, 'fr', features, home=home)
            conf = home/'batocera.conf'
            key = es_options.game_key('Game.wine', 'community_reshade')
            watcher = community_es.Selections(home, lambda *_: {}, features, conf)
            with patch.object(community_es, 'EsApi') as es, \
                 patch.object(community_es, 'open_selection', return_value=False) as launch:
                es.return_value.running.return_value = (201, '')
                conf.write_text(f'{key}=preset\n')
                watcher.poll()
                watcher.poll()
                watcher.poll()
                launch.assert_called_once()
                conf.write_text(f'{key}=auto\n')
                watcher.poll()
                watcher.poll()
                conf.write_text(f'{key}=preset\n')
                watcher.poll()
                watcher.poll()
                self.assertEqual(launch.call_count, 2)

    def test_selection_stages_literal_arguments_for_es_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            request = home / 'state' / community_es.REQUEST
            arguments = ['reshade', '/userdata/roms/windows/Game with spaces & accents é.wine', 'preset']
            def consume(folder, parent_pid, **kwargs):
                self.assertEqual(kwargs['request_name'], request.name)
                self.assertIsNone(parent_pid)
                self.assertEqual(kwargs['max_attempts'], 1)
                self.assertGreaterEqual(kwargs['confirm_timeout'], 30)
                self.assertEqual(request.read_text().splitlines(), arguments)
                request.unlink()
                return True
            with patch.object(community_es, 'resume', side_effect=consume):
                self.assertTrue(community_es.open_selection(home, object(), arguments))
            with patch.object(community_es, 'resume', return_value=False):
                self.assertFalse(community_es.open_selection(home, object(), arguments))
            self.assertFalse(request.exists())

    def test_failed_refresh_preserves_existing_catalogues(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            community = Community(home)
            packs = Packs(home)
            paths = (community.cache, catalogue.pack_cache(packs))
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'previous cache')
            with patch.object(community, 'refresh', side_effect=OSError('offline')), \
                 patch.object(packs, 'listing', side_effect=OSError('offline')):
                self.assertFalse(catalogue.refresh(community, lambda: packs))
            self.assertEqual([path.read_bytes() for path in paths], [b'previous cache'] * 2)

    def test_service_start_is_idempotent_and_stop_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / 'config').mkdir()
            (home / 'config/community-source.json').write_text('invalid JSON')
            helper = [sys.executable, str(HELPERS / 'community_catalog.py'),
                      '--home', folder, '--log', str(home / 'test.log')]
            lock = home / 'state/community/catalog-sync.lock'
            subprocess.run([*helper, 'start'], check=True)
            try:
                for _ in range(50):
                    if (home / 'test.log').stat().st_size:
                        break
                    time.sleep(0.02)
                self.assertTrue((home / 'test.log').stat().st_size)
                first_pid = lock.read_text()
                self.assertEqual(Path(f'/proc/{first_pid}/cwd').resolve(), home.resolve())
                subprocess.run([*helper, 'start'], check=True)
                self.assertEqual(lock.read_text(), first_pid)
                subprocess.run([*helper, 'status'], check=True)
            finally:
                subprocess.run([*helper, 'stop'], check=True)
            self.assertEqual(subprocess.run([*helper, 'status']).returncode, 1)


if __name__ == '__main__':
    unittest.main()
