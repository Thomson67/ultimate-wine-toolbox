import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest import TestCase, mock, skipUnless
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import es_launcher as launcher
import es_options as es


class OptionsTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.xml = self.root/'es_features_uwt.cfg'
        self.conf = self.root/'batocera.conf'
        self.rom = Path('/userdata/roms/windows/A game [UMU].wsquashfs')

    def test_selected_sections_are_scoped_to_wine_windows_and_can_be_removed(self):
        es.publish(['mangohud', 'mouse'], 'fr', self.xml)
        xml = ET.parse(self.xml)
        options = xml.findall("./emulator[@name='wine']/system[@name='windows']/feature")
        self.assertEqual({'uwt_mangohud', 'uwt_mouse', 'uwt_mangohud_display',
                          'uwt_mangohud_fps', 'uwt_mangohud_vulkan'},
                         {option.get('value') for option in options})
        self.assertIn('Souris virtuelle', self.xml.read_text())
        es.publish([], 'en', self.xml)
        self.assertFalse(self.xml.exists())

    def test_override_priority_and_hidden_options(self):
        es.publish(['mouse', 'launcher'], 'en', self.xml)
        self.conf.write_text(
            f'{es.game_key(self.rom, "mouse")}=off\n'
            'windows.uwt_mouse=on\nwindows.uwt_launcher=next\n'
            'windows.uwt_keyboard=on\n'
        )
        overrides = es.Overrides(self.rom, self.xml, self.conf)
        other = es.Overrides('/roms/Other.wine', self.xml, self.conf)
        self.assertEqual(overrides.get('mouse', toolbox_game='on'), 'off')
        self.assertEqual(other.get('mouse', toolbox_game='off'), 'off')
        self.assertEqual(other.get('mouse'), 'on')
        self.assertIsNone(other.get('launcher', game_only=True))
        self.assertIsNone(other.get('keyboard'))
        es.publish([], 'en', self.xml)
        self.assertIsNone(es.Overrides(self.rom, self.xml, self.conf).get('mouse'))

    def test_does_not_overwrite_a_foreign_fragment(self):
        self.xml.write_text('<features/>')
        es.refresh(self.xml)
        with self.assertRaises(ValueError):
            es.publish(['mouse'], 'en', self.xml)
        self.assertEqual('<features/>', self.xml.read_text())

    def test_upgrade_refreshes_labels_without_changing_selected_sections(self):
        es.publish(['mouse', 'launcher', 'reshade'], 'fr', self.xml)
        legacy = self.xml.read_text().replace('Afficher le launcher (par jeu)', 'Réafficher le launcher (par jeu)')
        legacy = legacy.replace('name="Oui"', 'name="Au prochain démarrage"')
        legacy = legacy.replace('ReShade (par jeu)', 'ReShade configuré (par jeu)')
        self.xml.write_text(legacy)
        es.refresh(self.xml)
        root = ET.parse(self.xml)
        feature = root.find('./emulator/system/feature[@value="uwt_launcher"]')
        self.assertEqual(feature.get('name'), 'Afficher le launcher (par jeu)')
        self.assertEqual({c.get('value'): c.get('name') for c in feature}, {'normal': 'Non', 'next': 'Oui'})
        self.assertEqual(root.find('./emulator/system/feature[@value="uwt_reshade"]').get('name'), 'ReShade (par jeu)')
        self.assertEqual(es.exposed(self.xml), {'mouse', 'launcher', 'reshade'})

    def add_bundle(self, name):
        for arch in ('x32', 'x64'):
            (self.root/'dxvk/bundles'/name/arch).mkdir(parents=True)

    def test_dxvk_catalog_refreshes_only_installed_bundles(self):
        bundles = self.root/'dxvk/bundles'
        self.add_bundle('DXVK-2.7__VKD3D-3.0')
        (bundles/'Incomplete/x32').mkdir(parents=True)
        (bundles/'Link').symlink_to(bundles/'DXVK-2.7__VKD3D-3.0')
        es.publish(['dxvk', 'mouse'], 'fr', self.xml, bundles)
        self.assertEqual(es.dxvk_choices(bundles).keys(), {'batocera', 'DXVK-2.7__VKD3D-3.0'})
        shutil.rmtree(bundles/'DXVK-2.7__VKD3D-3.0')
        self.add_bundle('DXVK-3.0__VKD3D-3.1')
        es.refresh(self.xml, bundles)
        options = ET.parse(self.xml).findall('./emulator/system/feature[@value="uwt_dxvk"]/choice')
        self.assertEqual([(choice.get('value'), choice.get('name')) for choice in options],
                         [('batocera', 'Versions natives de Batocera'),
                          ('DXVK-3.0__VKD3D-3.1', 'DXVK-3.0__VKD3D-3.1')])
        self.assertEqual(es.exposed(self.xml), {'dxvk', 'mouse'})

    def test_dxvk_hook_applies_scope_priority_and_restores_the_global_bundle(self):
        bundles = self.root/'dxvk/bundles'
        for bundle in ('Global', 'System', 'Game', 'Test', 'Toolbox'):
            self.add_bundle(bundle)
        es.publish(['dxvk'], 'en', self.xml, bundles)
        self.conf.write_text(f'{es.game_key(self.rom, "dxvk")}=Game\nwindows.uwt_dxvk=System\n')
        override = es.Overrides(self.rom, self.xml, self.conf, bundles)
        self.assertEqual(override.assigned_dxvk_bundles(), {'Game', 'System'})
        repo = Path(__file__).resolve().parents[1]
        helpers = self.root/'toolbox/helpers'
        helpers.mkdir(parents=True)
        shutil.copy(repo/'toolbox/helpers/antimicrox_live.py', helpers)
        code = (repo/'toolbox/helpers/es_options.py').read_text()
        (helpers/'es_options.py').write_text(code.replace(str(es.FEATURES), str(self.xml)).replace(str(es.CONF), str(self.conf)))
        path = self.root/'active'
        path.symlink_to(bundles/'Global')
        hook = self.root/'hook.sh'
        code = (repo/'toolbox/hooks/dxvk-game-event.sh').read_text()
        hook.write_text(code.replace('/userdata/system/ultimate-wine-toolbox', str(self.root))
                        .replace('/userdata/system/wine/dxvk', str(path))
                        .replace('/userdata/system/logs/ultimate-wine-toolbox', str(self.root/'logs'))
                        .replace(str(es.FEATURES), str(self.xml)))
        config = self.root/'config'
        config.mkdir()
        (config/'dxvk-games.tsv').write_text(f'Toolbox\t{self.rom}\n')

        def launch(action):
            subprocess.run(['bash', str(hook), action, 'windows', '', '', str(self.rom)],
                           check=True, capture_output=True)
            return path.resolve().name if path.is_symlink() else None

        self.assertEqual(launch('gameStart'), 'Game')
        self.assertEqual(launch('gameStop'), 'Global')
        shutil.rmtree(bundles/'Game')
        self.assertEqual(launch('gameStart'), 'Toolbox')
        (config/'dxvk-games.tsv').unlink()
        self.assertEqual(launch('gameStart'), 'System')
        self.conf.write_text(f'{es.game_key(self.rom, "dxvk")}=batocera\n')
        self.assertIsNone(launch('gameStart'))
        self.assertEqual(launch('gameStop'), 'Global')
        state = self.root/'state'
        state.mkdir()
        (state/f'wsq-dxvk-test.{os.getpid()}').write_text(f'{self.rom}\nTest\n')
        self.assertEqual(launch('gameStart'), 'Test')
        self.assertEqual(launch('gameStop'), 'Global')


BATCH = r'''
@echo off
IF EXIST "z:\userdata\saves\windows\Different Save Folder\conf-ok.txt" GOTO game_exe
mkdir "z:\userdata\saves\windows\Unused Folder"
start /wait "" ".\Launcher.exe"
copy /y NUL "z:\userdata\saves\windows\Different Save Folder\conf-ok.txt" >NUL
:game_exe
'''


class LauncherTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.rom = self.home/'Renamed Game.wine'
        script = self.rom/'drive_c/Game Files/start.bat'
        script.parent.mkdir(parents=True)
        script.write_bytes(BATCH.replace('\n', '\r\n').encode())
        (self.rom/'autorun.cmd').write_text('DIR=drive_c/Game Files\nCMD="start.bat"\n')
        self.saves = self.home/'saves'
        self.marker = self.saves/'Different Save Folder/conf-ok.txt'
        self.marker.parent.mkdir(parents=True)
        self.marker.write_bytes(b'old marker')
        self.features = self.home/'features.cfg'
        self.conf = self.home/'batocera.conf'
        es.publish(['launcher'], 'fr', self.features)
        self.setting = es.game_key(self.rom, 'launcher')

    def test_launcher_runs_on_consecutive_starts_until_disabled(self):
        enabled = f'{self.setting}=next\n'
        self.conf.write_text(enabled)
        with mock.patch.object(launcher, 'Overrides',
                               side_effect=lambda rom: es.Overrides(rom, self.features, self.conf)):
            launcher.event(self.home, self.rom, 'gameStart', self.saves)
            self.assertFalse(self.marker.exists())
            launcher.event(self.home, self.rom, 'gameStop', self.saves)
            self.assertEqual(self.marker.read_bytes(), b'old marker')
            launcher.event(self.home, self.rom, 'gameStart', self.saves)
            self.assertFalse(self.marker.exists())
            self.marker.write_bytes(b'new marker')
            launcher.event(self.home, self.rom, 'gameStop', self.saves)
            self.assertEqual(self.conf.read_text(), enabled)
            self.conf.write_text(f'{self.setting}=normal\n')
            launcher.event(self.home, self.rom, 'gameStart', self.saves)
            self.assertEqual(self.marker.read_bytes(), b'new marker')
            self.assertEqual(list(self.marker.parent.iterdir()), [self.marker])

    def test_disabling_after_an_interrupted_launch_restores_original(self):
        self.conf.write_text(f'{self.setting}=next\n')
        with mock.patch.object(launcher, 'Overrides',
                               side_effect=lambda rom: es.Overrides(rom, self.features, self.conf)):
            launcher.event(self.home, self.rom, 'gameStart', self.saves)
            self.assertFalse(self.marker.exists())
            self.conf.write_text(f'{self.setting}=normal\n')
            launcher.event(self.home, self.rom, 'gameStart', self.saves)
        self.assertEqual(self.marker.read_bytes(), b'old marker')

    def test_rejects_ambiguous_marker_and_symlink_escape(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            launcher.marker_spec(BATCH.replace('IF EXIST "z:', 'IF EXIST "c:'))
        outside = self.home/'outside'
        outside.mkdir()
        (self.saves/'alias').symlink_to(outside)
        with self.assertRaises(ValueError):
            launcher.safe_marker('alias/conf-ok.txt', self.saves)

    def test_archive_is_read_with_cat_without_extracting(self):
        archive = self.home/'Game.wsquashfs'
        with mock.patch.object(launcher.subprocess, 'Popen') as popen:
            child = popen.return_value.__enter__.return_value
            child.stdout.read.return_value = BATCH.encode()
            child.wait.return_value = 0
            self.assertEqual(launcher.script(archive, 'drive_c/game/start.bat'), BATCH)
            self.assertEqual(popen.call_args.args[0],
                             ['unsquashfs', '-cat', '-no-wildcards', str(archive), 'drive_c/game/start.bat'])

    @skipUnless(shutil.which('mksquashfs') and shutil.which('unsquashfs'), 'requires squashfs-tools')
    def test_real_archive_uses_the_batch_selected_in_autorun(self):
        archive = self.home/'Game [UMU].wsquashfs'
        subprocess.run(['mksquashfs', str(self.rom), str(archive), '-noappend', '-processors', '1'],
                       check=True, capture_output=True)
        batch = launcher.script(archive, launcher.batch_path(launcher.script(archive, 'autorun.cmd')))
        self.assertEqual(launcher.marker_spec(batch), 'Different Save Folder/conf-ok.txt')
