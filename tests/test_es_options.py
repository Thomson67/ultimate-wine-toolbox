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
        with self.assertRaises(ValueError):
            es.publish(['mouse'], 'en', self.xml)
        self.assertEqual('<features/>', self.xml.read_text())


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
        self.requested = 'next'

    def test_one_shot_preserves_new_marker_and_restores_old_one_on_failure(self):
        def consume(_):
            self.requested = None
        with mock.patch.object(launcher, 'Overrides') as overrides, \
                mock.patch.object(launcher, 'clear_request', side_effect=consume):
            overrides.return_value.get.side_effect = lambda *a, **kw: self.requested
            launcher.event(self.home, self.rom, 'gameStart', self.saves)
            self.assertFalse(self.marker.exists())
            launcher.event(self.home, self.rom, 'gameStop', self.saves)
            self.assertEqual(self.marker.read_bytes(), b'old marker')
            self.requested = 'next'
            launcher.event(self.home, self.rom, 'gameStart', self.saves)
            self.marker.write_bytes(b'new marker')
            launcher.event(self.home, self.rom, 'gameStop', self.saves)
            launcher.event(self.home, self.rom, 'gameStart', self.saves)
            self.assertEqual(self.marker.read_bytes(), b'new marker')
            self.assertEqual(list(self.marker.parent.iterdir()), [self.marker])

    def test_failed_es_write_rolls_back_the_marker(self):
        with mock.patch.object(launcher, 'Overrides') as overrides, \
                mock.patch.object(launcher, 'clear_request', side_effect=OSError('disk full')):
            overrides.return_value.get.return_value = 'next'
            with self.assertRaises(OSError):
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
