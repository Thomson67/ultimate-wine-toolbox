"""Check ES catalogue filtering, cache preservation and service lifecycle."""
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
from community_profiles import Community
from community_packs import Packs


def profile(kind, game):
    suffix = '.ini' if kind == 'reshade' else '.amgp'
    return dict(id='profile', kind=kind, game=game, title='Profile', author='Author',
                file=f'{kind}/profile{suffix}', sha256=hashlib.sha256(b'fixture').hexdigest())


class CatalogueTests(unittest.TestCase):
    def test_cached_profiles_and_packs_are_filtered_by_rom_and_es_name(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            digest = hashlib.sha256(b'zip').hexdigest()
            pack = dict(id='pack-'+digest, sha256=digest, game='Psychonauts',
                        title='Graphics pack', author='Author')
            other = dict(pack, game='Psychonauts 2')
            community = Community(home)
            community.cache.parent.mkdir(parents=True)
            community.cache.write_text(json.dumps({
                'source': community.base,
                'catalog': {'schema': 1, 'entries': [
                    profile('antimicrox', 'Psychonauts'),
                    dict(profile('antimicrox', 'Psychonauts 2'), id='other',
                         file='antimicrox/other.amgp'),
                    dict(profile('reshade', 'Psychonauts'), id='preset', file='reshade/preset.ini'),
                ]},
            }))
            packs = Packs(home)
            for entry in (pack, other):
                with patch.object(Packs, 'listing', return_value=[entry]):
                    catalogue.refresh_packs(packs)
                with patch.object(Packs, 'listing', side_effect=AssertionError('network on cached list')):
                    rom = '/userdata/roms/windows/Psychonauts[GE-Proton11-11-UMU].wsquashfs'
                    rows, errors = catalogue.list_for_game(home, 'antimicrox', rom, 'Release')
                    self.assertEqual([identifier for identifier, _ in rows], ['profile'])
                    self.assertFalse(errors)
                    rows, errors = catalogue.list_for_game(home, 'reshade', '/windows/test.wine', 'Psychonauts')
                    expected = {'preset', 'zip:'+pack['id']} if entry is pack else {'preset'}
                    self.assertEqual({identifier for identifier, _ in rows}, expected)
                    self.assertFalse(errors)

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
