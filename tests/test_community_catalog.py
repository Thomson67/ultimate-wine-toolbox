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
from community_profiles import Community
from community_packs import Packs


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
            es_options.publish({'mangohud'}, 'fr', features, home=home)
            with patch.object(Packs, 'listing', side_effect=AssertionError('network during feature generation')):
                es_options.enable_community('fr', features, home=home)
            tree = ET.parse(features)
            node = tree.find('.//feature[@value="uwt_community_reshade"]')
            self.assertEqual({choice.get('value') for choice in node}, {'preset', 'zip:'+pack['id']})
            node = tree.find('.//feature[@value="uwt_community_antimicrox"]')
            self.assertEqual({choice.get('value') for choice in node}, {'profile', 'other'})
            self.assertIn('[Launcher]', node.find('choice[@value="profile"]').get('name'))
            self.assertIn('mangohud', es_options.exposed(features))
            es_options.publish({'mangohud'}, 'fr', features, home=home)
            es_options.enable_community('fr', features, home=home)
            self.assertNotIn('community_reshade', es_options.exposed(features))

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
                 patch.object(community_es, 'es_environment', return_value={'DISPLAY': ':1'}), \
                 patch.object(community_es.subprocess, 'Popen') as launch:
                launch.return_value.poll.return_value = 0
                conf.write_text(f'windows.uwt_community_reshade=system-value\n{key}=matching\n')
                watcher.poll()
                launch.assert_not_called()
                watcher.poll()
                self.assertEqual(launch.call_args.args[0][-3:], ['antimicrox', str(rom), 'matching'])
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
                self.assertEqual(launch.call_args.args[0][-1], 'unavailable')

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
                subprocess.run([*helper, 'start'], check=True)
                self.assertEqual(lock.read_text(), first_pid)
                subprocess.run([*helper, 'status'], check=True)
            finally:
                subprocess.run([*helper, 'stop'], check=True)
            self.assertEqual(subprocess.run([*helper, 'status']).returncode, 1)


if __name__ == '__main__':
    unittest.main()
