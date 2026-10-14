import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
spec = importlib.util.spec_from_file_location('dotnet', ROOT / 'toolbox/helpers/wsquashfs_dotnet.py')
dotnet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dotnet)


def entry(name, version='4.8.0'):
    return '[Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\test]\n"DisplayName"="' + name + '"\n"DisplayVersion"="' + version + '"\n'


class DotnetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.prefix = self.base / 'Game.wine'
        (self.prefix / 'drive_c/windows').mkdir(parents=True)
        (self.prefix / 'drive_c/game').mkdir()
        (self.prefix / 'drive_c/game/game.exe').write_text('game')
        (self.prefix / 'autorun.cmd').write_text('DIR=drive_c/game\nCMD=game.exe\n')
        (self.prefix / 'system.reg').write_text('WINE REGISTRY Version 2\n')
        self.backups = self.base / 'backups'
        self.cache = self.base / 'cache'
        self.env = patch.dict(dotnet.os.environ, UWT_DOTNET_WORK_ROOT=str(self.base / 'local'))
        self.env.start()
        self.addCleanup(self.env.stop)

    def set_registry(self, text):
        (self.prefix / 'system.reg').write_text(text)

    def test_shared_mono_is_availability_not_installed_microsoft(self):
        shared = self.base / 'share/wine'
        (shared / 'wine-mono-10.4.0').mkdir(parents=True)
        (shared / 'mono/wine-mono-11.3.0').mkdir(parents=True)
        data = dotnet.inspect(self.prefix, [shared])
        self.assertEqual(data['status'], 'absent')
        self.assertEqual(len(data['shared']), 2)

    def test_mono_ndp_values_are_not_microsoft_evidence(self):
        self.set_registry(entry('Wine Mono Windows Support', '11.3.0') +
            '[Software\\\\Microsoft\\\\NET Framework Setup\\\\NDP\\\\v4\\\\Full]\n"Release"=dword:00080eb1\n')
        self.assertEqual(dotnet.inspect(self.prefix)['status'], 'mono')

    def test_release_without_identity_is_uncertain(self):
        self.set_registry('[Software\\\\Microsoft\\\\NET Framework Setup\\\\NDP\\\\v4\\\\Full]\n"Release"=dword:00080eb1\n')
        self.assertEqual(dotnet.inspect(self.prefix)['status'], 'uncertain')

    def test_unrelated_release_value_does_not_identify_dotnet(self):
        self.set_registry('[Software\\\\Microsoft\\\\NET Framework Setup\\\\NDP]\n"Version"="x"\n[Unrelated]\n"Release"=dword:1\n')
        self.assertEqual(dotnet.inspect(self.prefix)['status'], 'absent')

    def test_native_and_mixed_states(self):
        native = entry('Microsoft .NET Framework 4.8')
        self.set_registry(native)
        self.assertEqual(dotnet.inspect(self.prefix)['status'], 'microsoft')
        self.set_registry(native + entry('Wine Mono Runtime'))
        self.assertEqual(dotnet.inspect(self.prefix)['status'], 'mixed')

    def test_ambiguous_and_native_states_refuse_before_download_or_backup(self):
        for text in (entry('Microsoft .NET Framework 4.8'),
                     entry('Microsoft .NET Framework 4.8') + entry('Wine Mono Runtime'),
                     '[NET Framework Setup]\n"Release"=dword:1\n'):
            self.set_registry(text)
            for action in ('mono', 'microsoft'):
                with patch.object(dotnet, 'fetch_mono') as fetch, patch.object(dotnet, 'backup') as backup:
                    with self.assertRaises(ValueError):
                        dotnet.change(self.prefix, action, self.backups, self.cache)
                    fetch.assert_not_called()
                    backup.assert_not_called()

    def test_snapshot_excludes_only_game_and_does_not_follow_save_links(self):
        saves = self.base / 'external-save'
        saves.mkdir()
        (saves / 'save.dat').write_text('progress')
        (self.prefix / 'drive_c/users').mkdir()
        (self.prefix / 'drive_c/users/Saved').symlink_to(saves, target_is_directory=True)
        snapshot = dotnet.backup(self.prefix, self.backups)
        self.assertFalse((snapshot / 'prefix/drive_c/game').exists())
        self.assertTrue((snapshot / 'prefix/drive_c/users/Saved').is_symlink())
        self.assertEqual((snapshot / 'prefix/system.reg').read_text(), (self.prefix / 'system.reg').read_text())
        self.assertEqual(json.loads((snapshot / 'backup.json').read_text())['excluded_game'], 'drive_c/game')
        with self.assertRaises(ValueError):
            dotnet.backup(self.prefix, self.prefix / 'bad-backup')

    def test_unidentifiable_game_prevents_snapshot(self):
        (self.prefix / 'drive_c/game').rename(self.prefix / 'drive_c/unknown')
        (self.prefix / 'autorun.cmd').write_text('DIR=drive_c/windows\n')
        with self.assertRaises(ValueError):
            dotnet.backup(self.prefix, self.backups)

    def test_latest_asset_requires_official_stable_url_and_digest(self):
        data = dict(tag_name='wine-mono-11.3.0', prerelease=False, assets=[dict(
            name='wine-mono-11.3.0-x86.msi', digest='sha256:' + 'a' * 64,
            browser_download_url='https://github.com/wine-mono/wine-mono/releases/download/wine-mono-11.3.0/wine-mono-11.3.0-x86.msi')])
        self.assertEqual(dotnet.latest_asset(data)[0], '11.3.0')
        for value in ('', 'sha256:123'):
            data['assets'][0]['digest'] = value
            with self.assertRaises(ValueError):
                dotnet.latest_asset(data)
        data['assets'][0]['digest'] = 'sha256:' + 'a' * 64
        data['assets'][0]['browser_download_url'] = 'https://example.com/payload.msi'
        with self.assertRaises(ValueError):
            dotnet.latest_asset(data)

    def test_microsoft_removes_mono_then_installs_and_checks_postcondition(self):
        self.set_registry(entry('Wine Mono Runtime'))
        def installer(prefix, verbs, native_runner=False, unattended=True, mono_cleanup=False):
            self.assertTrue(native_runner)
            self.assertFalse(unattended)
            self.assertEqual(verbs, ['remove_mono', 'dotnet48'])
            self.assertTrue(mono_cleanup)
            (prefix / 'drive_c/windows/dotnet48.installed.workaround').touch()
            (prefix / 'system.reg').write_text(entry('Microsoft .NET Framework 4.8'))
            return 0
        with patch.object(dotnet.tricks, 'prepare'), patch.object(dotnet.tricks, 'install', side_effect=installer):
            dotnet.change(self.prefix, 'microsoft', self.backups, self.cache)
        self.assertEqual(len(list(self.backups.glob('dotnet-*'))), 1)

    def test_installer_failure_keeps_snapshot(self):
        self.set_registry(entry('Wine Mono Runtime'))
        original = (self.prefix / 'system.reg').read_bytes()
        def fail(staged, verbs, native_runner=False, unattended=True, mono_cleanup=False):
            self.assertTrue(native_runner)
            self.assertNotEqual(staged, self.prefix)
            (staged / 'system.reg').write_text('partial installation')
            return 8
        with patch.object(dotnet.tricks, 'prepare'), patch.object(dotnet.tricks, 'install', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                dotnet.change(self.prefix, 'microsoft', self.backups, self.cache)
        self.assertEqual(len(list(self.backups.glob('dotnet-*'))), 1)
        self.assertEqual((self.prefix / 'system.reg').read_bytes(), original)
        self.assertEqual(len(list((self.base / 'local').glob('install-*'))), 1)

    def test_dotnet40_alone_is_not_reported_as_successful_dotnet48(self):
        self.set_registry(entry('Wine Mono Runtime'))
        original = (self.prefix / 'system.reg').read_bytes()
        def installer(staged, verbs, native_runner=False, unattended=True, mono_cleanup=False):
            (staged / 'system.reg').write_text(entry('Microsoft .NET Framework 4 Client Profile', '4.0.30319'))
            return 0
        with patch.object(dotnet.tricks, 'prepare'), patch.object(dotnet.tricks, 'install', side_effect=installer):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                dotnet.change(self.prefix, 'microsoft', self.backups, self.cache)
        self.assertEqual((self.prefix / 'system.reg').read_bytes(), original)

    def test_restore_snapshot_reverts_failed_attempt_preserving_game(self):
        self.set_registry(entry('Wine Mono Runtime', '9.3.0'))
        snapshot = dotnet.backup(self.prefix, self.backups)
        self.set_registry('partial .NET installation')
        (self.prefix / 'drive_c/windows/partial-file').touch()
        dotnet.restore(self.prefix, snapshot, self.backups)
        self.assertEqual(dotnet.inspect(self.prefix)['status'], 'mono')
        self.assertFalse((self.prefix / 'drive_c/windows/partial-file').exists())
        self.assertEqual((self.prefix / 'drive_c/game/game.exe').read_text(), 'game')
        self.assertEqual(len(list(self.backups.glob('dotnet-*'))), 2)

    def test_snapshot_of_other_game_is_refused(self):
        snapshot = dotnet.backup(self.prefix, self.backups)
        data = json.loads((snapshot / 'backup.json').read_text())
        data['prefix'] = '/other/game.wine'
        (snapshot / 'backup.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            dotnet.restore(self.prefix, snapshot, self.backups)

    def test_mono_checks_real_registry_result_not_only_exit_code(self):
        msi = self.base / 'mono.msi'
        msi.write_text('package')
        self.set_registry(entry('Wine Mono Runtime', '10.4.0'))
        with patch.object(dotnet, 'fetch_mono', return_value=('11.3.0', msi)), patch.object(dotnet.tricks, 'prepare'), patch.object(dotnet.tricks, 'install', return_value=0):
            with self.assertRaisesRegex(ValueError, 'not confirmed'):
                dotnet.change(self.prefix, 'mono', self.backups, self.cache)

    def test_current_mono_no_install_or_backup(self):
        self.set_registry(entry('Wine Mono Runtime', '11.3.0'))
        with patch.object(dotnet, 'fetch_mono', return_value=('11.3.0', self.base / 'mono.msi')), patch.object(dotnet, 'backup') as backup:
            dotnet.change(self.prefix, 'mono', self.backups, self.cache)
            backup.assert_not_called()

    def test_mono_install_passes_unix_namespace_and_accepts_verified_result(self):
        msi = self.base / 'cache with spaces/mono.msi'
        msi.parent.mkdir()
        msi.write_text('verified package')
        def installer(prefix, args, wine_command=False, native_runner=False, unattended=True):
            self.assertTrue(native_runner)
            self.assertFalse(unattended)
            self.assertTrue(wine_command)
            self.assertEqual(args[:4], ['msiexec', '/i', '//?/unix' + str(msi), '/norestart'])
            self.assertEqual(args[4:], ['/l*vx', r'C:\windows\temp\uwt-mono-install.log'])
            (prefix / 'system.reg').write_text(entry('Wine Mono Runtime', '11.3.0'))
            return 0
        with patch.object(dotnet, 'fetch_mono', return_value=('11.3.0', msi)), patch.object(dotnet.tricks, 'prepare'), patch.object(dotnet.tricks, 'install', side_effect=installer):
            dotnet.change(self.prefix, 'mono', self.backups, self.cache)

    def test_external_program_files_refused_before_installer(self):
        (self.prefix / 'drive_c/Program Files').symlink_to(self.base, target_is_directory=True)
        with patch.object(dotnet.tricks, 'install') as installer:
            with self.assertRaisesRegex(ValueError, 'Installer directory'):
                dotnet.change(self.prefix, 'microsoft', self.backups, self.cache)
            installer.assert_not_called()

    def test_running_prefix_blocks_before_backup(self):
        with patch.object(dotnet.tricks, 'prepare', side_effect=ValueError('still in use')), patch.object(dotnet, 'backup') as backup:
            with self.assertRaisesRegex(ValueError, 'still in use'):
                dotnet.change(self.prefix, 'microsoft', self.backups, self.cache)
            backup.assert_not_called()
