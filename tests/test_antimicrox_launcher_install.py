import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('launcher_installer', ROOT/'scripts/install-antimicrox-launchers-test.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class LauncherInstallTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.home, self.source = self.root/'installed', self.root/'source'
        self.home.mkdir(); self.source.mkdir()
        (self.home/'VERSION').write_text('0.7.2\n')
        self.hook = self.root/'scripts/global-hook.sh'
        self.hook.parent.mkdir(); self.hook.write_bytes(b'#!/bin/bash\necho oldhook\n')
        self.hook.chmod(0o755)
        self.old = {'toolbox/helpers/antimicrox_live.py': b'# old live helper\n',
                    'toolbox/modules/antimicrox.sh': b'#!/bin/bash\necho oldmodule\n',
                    'toolbox/hooks/antimicrox-game-event.sh': self.hook.read_bytes()}
        for name, data in self.old.items():
            target = self.home/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755)
            source = self.source/name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(data.replace(b'old', b'new'))
        helper = self.source/installer.HELPER
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text('print("new helper")\n')
        hashes = {name: installer.sha(data) for name, data in self.old.items()}
        p = patch.object(installer, 'BASE_HASHES', hashes)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(installer, 'idle')
        p.start(); self.addCleanup(p.stop)

    def install(self):
        return installer.install(self.home, self.hook, 'local', self.source)

    def test_install_updates_both_hook_copies_and_restore_preserves_user_profiles(self):
        backup = self.install()
        self.assertEqual(self.hook.read_bytes(), (self.home/'toolbox/hooks/antimicrox-game-event.sh').read_bytes())
        self.assertIn(b'newhook', self.hook.read_bytes())
        self.assertEqual(self.hook.stat().st_mode & 0o777, 0o755)
        profile = self.home/'config/User.amgp'
        profile.parent.mkdir(); profile.write_text('user profile')
        installer.restore(backup)
        for name, data in self.old.items():
            self.assertEqual((self.home/name).read_bytes(), data)
        self.assertEqual(self.hook.read_bytes(), self.old['toolbox/hooks/antimicrox-game-event.sh'])
        self.assertFalse((self.home/installer.HELPER).exists())
        self.assertEqual(profile.read_text(), 'user profile')

    def test_local_changes_are_refused_before_any_write(self):
        module = self.home/'toolbox/modules/antimicrox.sh'
        module.write_text('user changes')
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(module.read_text(), 'user changes')
        self.assertFalse((self.home/'state/backups').exists())
        self.assertFalse((self.home/installer.HELPER).exists())

    def test_downloaded_syntax_error_is_refused_before_any_write(self):
        (self.source/installer.HELPER).write_text('broken python : :')
        with self.assertRaises(SyntaxError):
            self.install()
        self.assertFalse((self.home/'state/backups').exists())
        self.assertEqual(self.hook.read_bytes(), self.old['toolbox/hooks/antimicrox-game-event.sh'])

    def test_restore_does_not_overwrite_subsequent_updates(self):
        backup = self.install()
        self.hook.write_text('a future release')
        with self.assertRaises(ValueError):
            installer.restore(backup)
        self.assertEqual(self.hook.read_text(), 'a future release')
        self.assertTrue((self.home/installer.HELPER).exists())

    def test_interrupted_install_rolls_back_already_replaced_files(self):
        real_replace = installer.replace
        calls = []
        def failing_replace(*args):
            calls.append(args)
            if len(calls) == 2:
                raise OSError('simulated installation failure')
            real_replace(*args)
        with patch.object(installer, 'replace', side_effect=failing_replace):
            with self.assertRaises(OSError):
                self.install()
        for name, data in self.old.items():
            self.assertEqual((self.home/name).read_bytes(), data)
        self.assertFalse((self.home/installer.HELPER).exists())

    def test_upgrade_from_first_test_keeps_rules_and_restores_previous_test(self):
        self.install()
        paths = [*self.old, installer.HELPER]
        previous = {name: (self.home/name).read_bytes() for name in paths}
        hashes = {name: installer.sha(data) for name, data in previous.items()}
        rules = self.home/'config/antimicrox-launchers/test.json'
        rules.parent.mkdir(parents=True); rules.write_text('{"existing":true}')
        module = self.source/'toolbox/modules/antimicrox.sh'
        module.write_bytes(module.read_bytes()+b'\n# retest action\n')
        with patch.object(installer, 'PREVIOUS_TEST_HASHES', hashes):
            backup = self.install()
        self.assertIn('retest action', (self.home/'toolbox/modules/antimicrox.sh').read_text())
        self.assertEqual(rules.read_text(), '{"existing":true}')
        installer.restore(backup)
        for name, content in previous.items():
            self.assertEqual((self.home/name).read_bytes(), content)

    def test_upgrade_also_accepts_the_retest_version(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/modules/antimicrox.sh'
        module.write_bytes(module.read_bytes()+b'\n# integrated menus\n')
        with patch.object(installer, 'RETEST_TEST_HASHES', hashes):
            self.install()
        self.assertIn('integrated menus', (self.home/'toolbox/modules/antimicrox.sh').read_text())


if __name__ == '__main__':
    unittest.main()
