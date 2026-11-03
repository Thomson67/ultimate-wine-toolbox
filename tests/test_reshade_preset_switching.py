from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import reshade_manager as m
import reshade_pack as pack
import reshade_presets as p
import test_reshade as fixture


class NativePresetSwitchingTests(unittest.TestCase):
    setUp = fixture.ReShadeTests.setUp

    def setup_collection(self):
        m.event(self.home, self.rom, 'gameStart')
        a = self.base / 'A.ini'; a.write_text('Techniques=A@A.fx\n[A.fx]\nAmount=1\n')
        b = self.base / 'B.ini'; b.write_text('Techniques=B@B.fx\n[B.fx]\nAmount=2\n')
        first = p.import_file(self.home, self.rom, a)
        second = p.import_file(self.home, self.rom, b)
        p.activate(self.home, self.rom, first)
        m.event(self.home, self.rom, 'gameStart')
        return first, second

    def session(self, root=None):
        root = root or self.rom
        return m.read_json(m.journal_path(self.home, self.rom, root, root))['preset_session']

    def target(self, identity, root=None):
        root = root or self.rom
        session = self.session(root)
        name = next(n for n, i in session['files'].items() if i == identity)
        return root / Path(self.exe).parent / session['directory'] / name

    def select_in_game(self, identity, root=None):
        root = root or self.rom
        config = root / Path(self.exe).parent / 'ReShade.ini'
        data = pack.ini(config.read_bytes())
        data['GENERAL']['PresetPath'] = '.\\' + self.target(identity, root).relative_to(config.parent).as_posix().replace('/', '\\')
        config.write_bytes(pack.encode_ini(data))

    def test_page_keys_native_switch_saves_all_edits_and_last_choice(self):
        a, b = self.setup_collection()
        config = pack.ini((self.game / 'ReShade.ini').read_bytes())
        self.assertEqual(config['INPUT']['KeyPreviousPreset'], '33,0,0,0')
        self.assertEqual(config['INPUT']['KeyNextPreset'], '34,0,0,0')
        self.assertEqual(config['INPUT']['KeyOverlay'], '36,0,0,0')
        self.assertIn('UWT-ReShadePresets', config['GENERAL']['PresetPath'])
        self.target(a).write_text('Techniques=A@A.fx\n[A.fx]\nAmount=7\n')
        self.target(b).write_text('Techniques=B@B.fx\n[B.fx]\nAmount=9\n')
        self.select_in_game(b)
        m.event(self.home, self.rom, 'gameStop')
        self.assertEqual(p.index(self.home, self.rom)['active'], b)
        self.assertIn('Amount=7', p.path(self.home, self.rom, a).read_text())
        self.assertIn('Amount=9', p.path(self.home, self.rom, b).read_text())
        export = self.base / 'export.ini'
        m.export_preset(self.home, self.rom, export)
        self.assertIn('B@B.fx', export.read_text())
        m.event(self.home, self.rom, 'gameStart')
        config = pack.ini((self.game / 'ReShade.ini').read_bytes())
        self.assertIn(b, config['GENERAL']['PresetPath'])
        self.assertIn('Amount=9', self.target(b).read_text())
        p.activate(self.home, self.rom, a)
        m.event(self.home, self.rom, 'gameStart')
        self.assertIn(a, pack.ini((self.game / 'ReShade.ini').read_bytes())['GENERAL']['PresetPath'])
        self.assertIn('Amount=7', self.target(a).read_text())

    def test_deleted_renamed_or_other_pack_presets_are_not_cycled(self):
        a, b = self.setup_collection()
        old_path = self.target(b)
        other = p.add(self.home, self.rom, b'Techniques=Other\n', 'Other pack', pack='a'*64)
        p.remove(self.home, self.rom, b)
        p.rename(self.home, self.rom, a, 'CON / couleurs : douces')
        m.event(self.home, self.rom, 'gameStart')
        session = self.session()
        self.assertNotIn(b, session['files'].values())
        self.assertNotIn(other, session['files'].values())
        self.assertNotEqual(old_path.parent, self.target(a).parent)
        self.assertNotIn(':', self.target(a).name)
        staged = [Path(n) for n in m.read_json(m.journal_path(self.home, self.rom, self.rom, self.rom))['files'] if 'UWT-ReShadePresets' in n]
        m.set_enabled(self.home, self.rom, False)
        self.assertTrue(all(not n.exists() for n in staged))

    def test_unknown_ini_path_is_not_read_or_imported(self):
        a, b = self.setup_collection()
        outside = self.base / 'outside.ini'; outside.write_text('Techniques=PRIVATE\n')
        config = pack.ini((self.game / 'ReShade.ini').read_bytes())
        config['GENERAL']['PresetPath'] = str(outside)
        (self.game / 'ReShade.ini').write_bytes(pack.encode_ini(config))
        before = set(p.index(self.home, self.rom)['items'])
        m.event(self.home, self.rom, 'gameStop')
        self.assertEqual(set(p.index(self.home, self.rom)['items']), before)
        self.assertEqual(p.index(self.home, self.rom)['active'], a)
        self.assertNotIn('PRIVATE', (self.profile / 'ReShadePreset.ini').read_text())

    def test_old_bottle_cannot_override_the_last_running_bottle(self):
        a, b = self.setup_collection()
        other_root = self.base / 'another-bottle.wine'
        other_root.mkdir()
        (other_root / 'autorun.cmd').write_text(self.original)
        m.install_files(self.home, self.rom, other_root, other_root, self.cfg)
        self.select_in_game(b, other_root)
        self.target(b, other_root).write_text('Techniques=B@B.fx\n[B.fx]\nAmount=42\n')
        self.select_in_game(a)
        m.event(self.home, self.rom, 'gameStop')
        self.assertEqual(p.index(self.home, self.rom)['active'], b)
        self.assertIn('Amount=42', p.path(self.home, self.rom, b).read_text())

    def test_manual_shortcuts_are_retained_and_startup_override_cleared(self):
        data = m.profile_ini('[GENERAL]\nStartupPresetPath=Old.ini\n[INPUT]\nKeyPreviousPreset=0,0,0,0\nKeyNextPreset=75,1,0,0\n', self.cfg, './UWT-ReShadePresets/test/A.ini')
        config = pack.ini(data.encode())
        self.assertEqual(config['INPUT']['KeyPreviousPreset'], '33,0,0,0')
        self.assertEqual(config['INPUT']['KeyNextPreset'], '75,1,0,0')
        self.assertEqual(config['GENERAL']['StartupPresetPath'], '')
