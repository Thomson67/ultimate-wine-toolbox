"""Read real integrated presets, including a genuine squashfs archive."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'toolbox/helpers'))
import community_reshade as c
import community_profiles as community


def dll():
    data = bytearray(200)
    data[:2] = b'MZ'; data[60:64] = (64).to_bytes(4, 'little')
    data[64:68] = b'PE\0\0'; data[68:70] = (0x8664).to_bytes(2, 'little')
    data.extend("crosire's ReShade post-processing injector for 64-bit".encode('utf-16le'))
    return bytes(data)


class IntegratedPresets(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.home = self.base/'home'
        self.game = self.base/'Integrated.wine'; self.folder = self.game/'drive_c/game'
        (self.folder/'presets').mkdir(parents=True)
        (self.folder/'dxgi.dll').write_bytes(dll())
        (self.folder/'ReShade.ini').write_text('[GENERAL]\nPresetPath=.\\presets\\Current.ini\n')
        self.original = b'Techniques=CRT\n[CRT.fx]\nAmount=0.5\n'
        (self.folder/'presets/Current.ini').write_bytes(self.original)
        (self.folder/'Alternative.ini').write_text('Techniques=Bloom\n')
        self.bottles = self.base/'bottles'
        self.patch = patch.object(c, 'BOTTLES', self.bottles); self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_directory_active_preset_and_non_destructive_export(self):
        before = {p.relative_to(self.game):p.read_bytes() for p in self.game.rglob('*') if p.is_file()}
        values = c.presets(self.home, self.game)
        self.assertEqual(len(values), 2)
        self.assertEqual(values[0]['path'], 'drive_c/game/presets/Current.ini')
        self.assertTrue(values[0]['active'])
        destination = self.base/'shared.ini'
        c.export(self.home, self.game, values[0]['id'], destination)
        self.assertEqual(destination.read_bytes(), self.original)
        self.assertEqual(before, {p.relative_to(self.game):p.read_bytes() for p in self.game.rglob('*') if p.is_file()})
        self.assertIn((str(self.game), 'external-enabled'), c.games(self.home))
        self.assertEqual(c.games(self.home, managed_only=True), [])
        with patch.object(community, 'game_title', return_value='Integrated'):
            self.assertEqual(community.reshade_games(self.home), [(str(self.game),'Integrated','external-enabled')])
        with self.assertRaises(ValueError):
            c.export(self.home, self.game, values[0]['id'], self.folder/'overwrite.ini')

    def test_external_config_paths_and_symlinks_are_not_read(self):
        outside = self.base/'Outside.ini'; outside.write_text('Techniques=Private\n')
        (self.folder/'Linked.ini').symlink_to(outside)
        (self.folder/'ReShade.ini').write_text('[GENERAL]\nPresetPath=../../../Outside.ini\n')
        values = c.presets(self.home, self.game)
        self.assertEqual(len(values), 2)
        self.assertFalse(any(v['active'] for v in values))
        for path in ('Z:/Outside.ini', '/tmp/Outside.ini', '$HOME/Outside.ini', '../../../Outside.ini'):
            self.assertIsNone(c.preset_target(('PresetPath='+path).encode(), 'drive_c/game/ReShade.ini'))
        self.assertEqual(c.preset_target(b'PresetPath=C:\\game\\presets\\Current.ini', 'drive_c/game/ReShade.ini'),
                         'drive_c/game/presets/Current.ini')

    def test_read_budget_limits_discovery(self):
        with patch.object(c, 'SCAN_LIMIT', 1):
            with self.assertRaisesRegex(RuntimeError, 'choose a preset file manually'):
                c.presets(self.home, self.game)

    @unittest.skipUnless(shutil.which('mksquashfs') and shutil.which('unsquashfs'), 'squashfs-tools required')
    def test_real_archive_and_saved_runner_presets_are_distinct_and_unchanged(self):
        archive = self.base/'Integrated.wsquashfs'
        subprocess.run(['mksquashfs', str(self.game), str(archive), '-noappend', '-processors', '1', '-quiet'],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        runtime = self.bottles/'Wine Runner'/(archive.name+'.wine')
        saved = runtime/'drive_c/game/presets/Current.ini'; saved.parent.mkdir(parents=True)
        updated = b'Techniques=CRT\n[CRT.fx]\nAmount=0.9\n'; saved.write_bytes(updated)
        (saved.parent.parent/'ReShade.ini').write_text('PresetPath=.\\presets\\Current.ini\n')
        before = {p.relative_to(runtime):p.read_bytes() for p in runtime.rglob('*') if p.is_file()}
        values = c.presets(self.home, archive)
        self.assertEqual(len(values), 3)
        original = next(v for v in values if v['archive'] and v['active'])
        changed = next(v for v in values if not v['archive'])
        self.assertNotEqual(original['id'], changed['id'])
        self.assertIn('Archive du jeu', original['label'])
        self.assertIn('Réglages enregistrés', changed['label'])
        self.assertTrue(changed['active'])
        c.export(self.home, archive, original['id'], self.base/'archive.ini')
        c.export(self.home, archive, changed['id'], self.base/'saved.ini')
        self.assertEqual((self.base/'archive.ini').read_bytes(), self.original)
        self.assertEqual((self.base/'saved.ini').read_bytes(), updated)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), digest)
        self.assertEqual(before, {p.relative_to(runtime):p.read_bytes() for p in runtime.rglob('*') if p.is_file()})
        self.assertFalse((self.base/'squashfs-root').exists())
        self.assertIn((str(archive),'external-enabled'), c.games(self.home))
        self.assertEqual(c.games(self.home, managed_only=True), [])
        with self.assertRaises(ValueError):
            c.export(self.home, archive, changed['id'], saved)
        self.assertEqual(saved.read_bytes(), updated)


if __name__ == '__main__': unittest.main()
