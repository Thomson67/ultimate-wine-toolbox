from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import reshade_manager as m
import reshade_presets as p
import reshade_pack as pack
import test_reshade as fixture
import test_reshade_pack as pack_fixture


class PresetCollectionTests(unittest.TestCase):
    setUp = fixture.ReShadeTests.setUp

    def source(self, name, technique):
        path = self.base / name
        path.write_text('Techniques=' + technique + '\nTechniqueSorting=Disabled@Other.fx\n[Color.fx]\nStrength=1\n')
        return path

    def test_migrate_current_import_switch_and_keep_live_edits(self):
        m.event(self.home, self.rom, 'gameStart')
        current = p.listing(self.home, self.rom)[0]
        a = p.import_file(self.home, self.rom, self.source('A.ini', 'A@A.fx'))
        (self.game / 'ReShadePreset.ini').write_text('Techniques=A@A.fx\n[A.fx]\nAmount=7\n')
        b = p.import_file(self.home, self.rom, self.source('B.ini', 'B@B.fx'))
        self.assertEqual(len(p.listing(self.home, self.rom)), 3)
        self.assertIn('Amount=7', p.path(self.home, self.rom, a).read_text())
        p.activate(self.home, self.rom, a)
        self.assertIn('Amount=7', (self.game / 'ReShadePreset.ini').read_text())
        self.assertEqual(p.index(self.home, self.rom)['active'], a)
        (self.game / 'ReShadePreset.ini').write_text('Techniques=A@A.fx\n[A.fx]\nAmount=8\n')
        m.event(self.home, self.rom, 'gameStop')
        self.assertIn('Amount=8', p.path(self.home, self.rom, a).read_text())
        p.activate(self.home, self.rom, b)
        m.set_enabled(self.home, self.rom, False)
        m.set_enabled(self.home, self.rom, True)
        m.event(self.home, self.rom, 'gameStart')
        self.assertIn('B@B.fx', (self.game / 'ReShadePreset.ini').read_text())
        p.activate(self.home, self.rom, current['id'])
        self.assertEqual((self.game / 'ReShadePreset.ini').read_text(), 'Techniques=\n')

    def test_pack_variants_share_dependencies_and_require_correct_context(self):
        self.cfg.update(version='6.3.3', release_id='6.3.3-addons')
        m.save_json(self.config, self.cfg)
        before = p.listing(self.home, self.rom)[0]['id']
        archive = pack_fixture.LocalReShadePackTests.bundle(self, {'Other.ini': b'Techniques=Other@Other.fx\n'})
        pack.install(self.home, self.rom, archive, 'Ultra.ini')
        rows = p.listing(self.home, self.rom)
        other = next(v['id'] for v in rows if v['name'] == 'Other.ini')
        self.assertTrue(next(v for v in rows if v['name'] == 'Ultra.ini')['active'])
        p.activate(self.home, self.rom, other)
        self.assertTrue((self.game / 'ReShadePreset.ini').read_text().startswith('Techniques=Citra@Citra.fx,Other'))
        with self.assertRaisesRegex(ValueError, 'original shader pack'):
            p.activate(self.home, self.rom, before)
        pack.remove(self.home, self.rom)
        self.assertEqual(p.index(self.home, self.rom)['active'], before)
        self.assertFalse(next(v for v in p.listing(self.home, self.rom) if v['id'] == other)['compatible'])
        with self.assertRaisesRegex(ValueError, 'original shader pack'):
            p.activate(self.home, self.rom, other)

    def test_existing_pack_can_add_variants_without_reinstalling_addon(self):
        self.cfg.update(version='6.3.3', release_id='6.3.3-addons')
        m.save_json(self.config, self.cfg)
        archive = pack_fixture.LocalReShadePackTests.bundle(self, {'Other.ini': b'Techniques=Other@Other.fx\n'})
        pack.install(self.home, self.rom, archive, 'Ultra.ini')
        meta = pack.manifest(self.home, self.rom)
        other = next(v['id'] for v in p.listing(self.home, self.rom) if v['name'] == 'Other.ini')
        p.remove(self.home, self.rom, other)
        files, loaded = pack.archive(archive)
        loaded['archive_sha256'] = meta['archive_sha256']
        p.pack_presets(self.home, self.rom, files, loaded)
        self.assertTrue(any(v['name'] == 'Other.ini' for v in p.listing(self.home, self.rom)))
        self.assertEqual((self.game / 'citra.addon').read_bytes(), fixture.pe(64))

    def test_details_rename_delete_and_duplicate_import(self):
        source = self.source('A.ini', 'A@A.fx,B@B.fx')
        a = p.import_file(self.home, self.rom, source)
        self.assertEqual(p.import_file(self.home, self.rom, source), a)
        p.rename(self.home, self.rom, a, 'Couleurs douces')
        detail = p.details(self.home, self.rom, a)
        self.assertIn('Couleurs douces', detail)
        self.assertIn('A.ini', detail)
        self.assertIn('Effets actifs : 2', detail)
        self.assertNotIn('Other.fx', detail)
        self.assertIn('Strength=1', p.details(self.home, self.rom, a, full=True))
        with self.assertRaisesRegex(ValueError, 'active'):
            p.remove(self.home, self.rom, a)
        b = p.import_file(self.home, self.rom, self.source('B.ini', 'B@B.fx'))
        p.remove(self.home, self.rom, a)
        self.assertFalse(p.path(self.home, self.rom, a).exists())
        self.assertEqual(p.index(self.home, self.rom)['active'], b)
        with self.assertRaises(ValueError):
            p.rename(self.home, self.rom, b, 'bad\nname')

    def test_invalid_ini_and_game_active_do_not_replace_current(self):
        m.event(self.home, self.rom, 'gameStart')
        source = self.base / 'not-a-preset.ini'
        source.write_text('[GENERAL]\nPresetPath=Other.ini\n')
        before = (self.game / 'ReShadePreset.ini').read_bytes()
        with self.assertRaises(ValueError):
            p.import_file(self.home, self.rom, source)
        self.assertEqual((self.game / 'ReShadePreset.ini').read_bytes(), before)
        with patch.object(m, 'ensure_idle', side_effect=ValueError('game active')), self.assertRaisesRegex(ValueError, 'active'):
            p.import_file(self.home, self.rom, self.source('A.ini', 'A@A.fx'))
        self.assertEqual((self.game / 'ReShadePreset.ini').read_bytes(), before)

    def test_failed_switch_restores_working_preset_and_selection(self):
        a = p.import_file(self.home, self.rom, self.source('A.ini', 'A@A.fx'))
        b = p.import_file(self.home, self.rom, self.source('B.ini', 'B@B.fx'))
        original = m.atomic_bytes
        calls = 0
        def fail_once(path, data):
            nonlocal calls
            if Path(path).name == 'index.json':
                calls += 1
                if calls == 1:
                    raise OSError('disk write failed')
            return original(path, data)
        with patch.object(m, 'atomic_bytes', side_effect=fail_once), self.assertRaisesRegex(OSError, 'disk write failed'):
            p.activate(self.home, self.rom, a)
        self.assertEqual(p.index(self.home, self.rom)['active'], b)
        self.assertIn('B@B.fx', (self.profile / 'ReShadePreset.ini').read_text())


class PresetCollectionUiTests(unittest.TestCase):
    def test_list_details_full_parameters_and_activation(self):
        import os
        import subprocess
        import tempfile
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, WT_ROOT=str(root / 'toolbox'), WT_LANGUAGE='fr',
                       STEP=str(Path(tmp) / 'step'), RESULT=str(Path(tmp) / 'result'), OPTIONS=str(Path(tmp) / 'options'),
                       REPORT=str(Path(tmp) / 'report'))
            result = subprocess.run(['bash', '-c', r'''
source "$WT_ROOT/modules/reshade.sh"
community_txt() { printf '%s' "$1"; }
i18n() { printf '%s' "$1"; }
msgbox() { return 0; }
community_report() { printf '%s' "$2" > "$REPORT"; }
resh_cmd() {
 case "$1" in
  presets-list) printf '[{"id":"aaaaaaaaaaaaaaaaaaaaaaaa","name":"Ultra","active":true,"compatible":true}]';;
  presets-info) if [ "${*: -1}" = full ]; then echo 'Amount=7'; else echo 'Effets actifs : 2'; fi;;
  presets-select) printf '%s\n' "$@" > "$RESULT";;
 esac
}
menu_select() {
 local step="$(cat "$STEP" 2>/dev/null || echo 0)"
 printf '%s' "$((step+1))" > "$STEP"
 case "$step" in
  0) printf '%s\n' "$@" > "$OPTIONS"; echo aaaaaaaaaaaaaaaaaaaaaaaa;;
  1) echo full;;
  2) echo select;;
  *) echo back;;
 esac
}
resh_presets_menu '/games/Emulator.wine'
'''], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Ultra — actif', Path(env['OPTIONS']).read_text())
            self.assertEqual(Path(env['REPORT']).read_text(), 'Amount=7')
            self.assertEqual(Path(env['RESULT']).read_text().splitlines(),
                             ['presets-select', '/games/Emulator.wine', 'aaaaaaaaaaaaaaaaaaaaaaaa'])
