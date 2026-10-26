import importlib.util
import http.client
import io
import urllib.parse
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
                    'toolbox/hooks/antimicrox-game-event.sh': self.hook.read_bytes(),
                    'toolbox/modules/community.sh': b'#!/bin/bash\necho oldcommunity\n',
                    'toolbox/helpers/community_profiles.py': b'# old profiles\n',
                    'toolbox/helpers/community_service.py': b'# old service\n',
                    'toolbox/lib/common.sh': b'#!/bin/bash\necho oldcommon\n'}
        for name in installer.BASE_HASHES:
            if name not in self.old:
                self.old[name] = ('#!/bin/bash\n# old '+name+'\n').encode()
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
        self.port = self.root/'ports/Ultimate Wine Toolbox.sh'
        self.port.parent.mkdir()
        self.port.write_bytes(self.old['toolbox/ports/Ultimate Wine Toolbox.sh'])
        hashes = {name: installer.sha(data) for name, data in self.old.items()}
        p = patch.object(installer, 'BASE_HASHES', hashes)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(installer, 'idle')
        p.start(); self.addCleanup(p.stop)

    def install(self):
        return installer.install(self.home, self.hook, 'local', self.source, self.port)

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


    def test_upgrade_accepts_integrated_menus_version(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/modules/antimicrox.sh'
        module.write_bytes(module.read_bytes()+b'\n# direct learning return\n')
        with patch.object(installer, 'INTEGRATED_MENUS_HASHES', hashes):
            self.install()
        self.assertIn('direct learning return', (self.home/'toolbox/modules/antimicrox.sh').read_text())


    def test_upgrade_from_contextual_share_updates_all_community_helpers(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        for name in ['toolbox/helpers/community_profiles.py', 'toolbox/helpers/community_service.py']:
            source = self.source/name
            source.write_bytes(source.read_bytes()+b'\n# portable launcher packages\n')
        with patch.object(installer, 'CONTEXT_SHARE_HASHES', hashes):
            backup = self.install()
        self.assertIn('portable launcher packages', (self.home/'toolbox/helpers/community_profiles.py').read_text())
        self.assertIn('portable launcher packages', (self.home/'toolbox/helpers/community_service.py').read_text())
        installer.restore(backup)
        self.assertNotIn('portable launcher packages', (self.home/'toolbox/helpers/community_profiles.py').read_text())


    def test_upgrade_from_complete_package_test_adds_community_menu_actions(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/modules/community.sh'
        module.write_bytes(module.read_bytes()+b'\n# complete game menu actions\n')
        with patch.object(installer, 'COMPLETE_PACKAGE_HASHES', hashes):
            backup = self.install()
        self.assertIn('complete game menu actions', (self.home/'toolbox/modules/community.sh').read_text())
        installer.restore(backup)
        self.assertNotIn('complete game menu actions', (self.home/'toolbox/modules/community.sh').read_text())


    def test_upgrade_from_community_menu_version(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/modules/community.sh'
        module.write_bytes(module.read_bytes()+b'\n# assigned games selector\n')
        with patch.object(installer, 'COMMUNITY_MENU_HASHES', hashes):
            self.install()
        self.assertIn('assigned games selector', (self.home/'toolbox/modules/community.sh').read_text())


    def test_upgrade_from_assigned_menu_updates_common_menu_and_can_restore_it(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/lib/common.sh'
        module.write_bytes(module.read_bytes()+b'\n# readable menus\n')
        with patch.object(installer, 'ASSIGNED_MENU_HASHES', hashes):
            backup = self.install()
        self.assertIn('readable menus', (self.home/'toolbox/lib/common.sh').read_text())
        installer.restore(backup)
        self.assertNotIn('readable menus', (self.home/'toolbox/lib/common.sh').read_text())


    def test_upgrade_from_readability_version_keeps_menu_settings_restorable(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/lib/common.sh'
        module.write_bytes(module.read_bytes()+b'\n# regular menu font\n')
        with patch.object(installer, 'READABLE_MENU_HASHES', hashes):
            backup = self.install()
        self.assertIn('regular menu font', (self.home/'toolbox/lib/common.sh').read_text())
        installer.restore(backup)
        self.assertNotIn('regular menu font', (self.home/'toolbox/lib/common.sh').read_text())


    def test_reinstalling_same_version_is_a_noop_including_copied_hook(self):
        backup = self.install()
        paths = [self.home/name for name in [*self.old, installer.HELPER]]+[self.hook, self.port]
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
        self.assertIsNone(self.install())
        self.assertEqual(list((self.home/'state/backups').iterdir()), [backup])
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}, before)
        installer.restore(backup)
        self.assertFalse((self.home/installer.HELPER).exists())

    def test_same_version_with_a_changed_hook_is_still_refused(self):
        self.install()
        self.hook.write_text('#!/bin/bash\necho local change\n')
        with self.assertRaisesRegex(ValueError, 'code modifié'):
            self.install()
        self.assertIn('local change', self.hook.read_text())

    def test_upgrade_from_regular_menu_version(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/lib/common.sh'
        module.write_bytes(module.read_bytes()+b'\n# next version\n')
        with patch.object(installer, 'REGULAR_MENU_HASHES', hashes):
            self.install()
        self.assertIn('next version', (self.home/'toolbox/lib/common.sh').read_text())


    def test_upgrade_from_black_menu_version_updates_all_list_modules(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/modules/reshade.sh'
        module.write_bytes(module.read_bytes()+b'\n# data list presentation\n')
        with patch.object(installer, 'BLACK_MENU_HASHES', hashes):
            backup = self.install()
        self.assertIn('data list presentation', (self.home/'toolbox/modules/reshade.sh').read_text())
        installer.restore(backup)
        self.assertNotIn('data list presentation', (self.home/'toolbox/modules/reshade.sh').read_text())


    def test_upgrade_refreshes_both_ports_copies_and_restore_reverts_both(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        source = self.source/'toolbox/ports/Ultimate Wine Toolbox.sh'
        source.write_bytes(source.read_bytes()+b'\n# contrast option +pc\n')
        with patch.object(installer, 'SELECTIVE_MENU_HASHES', hashes):
            backup = self.install()
        self.assertEqual(self.port.read_bytes(), source.read_bytes())
        self.assertEqual((self.home/'toolbox/ports/Ultimate Wine Toolbox.sh').read_bytes(), source.read_bytes())
        installer.restore(backup)
        self.assertNotIn(b'contrast option', self.port.read_bytes())

    def test_custom_ports_launcher_is_not_overwritten(self):
        self.port.write_text('#!/bin/bash\n# custom launcher\n')
        with self.assertRaises(ValueError):
            self.install()
        self.assertIn('custom launcher', self.port.read_text())
        self.assertFalse((self.home/'state/backups').exists())


    def test_remote_install_encodes_spaces_and_downloads_both_launcher_copies(self):
        ref = 'a'*40
        prefix = 'https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/'+ref+'/'
        seen = []
        def download(url, timeout):
            seen.append(url)
            # Exercise the real HTTP request-path validator without opening a socket.
            http.client.HTTPConnection('example.invalid').putrequest('GET', urllib.parse.urlsplit(url).path)
            self.assertTrue(url.startswith(prefix))
            name = urllib.parse.unquote(url[len(prefix):])
            return io.BytesIO((self.source/name).read_bytes())
        with patch.object(installer.urllib.request, 'urlopen', side_effect=download):
            backup = installer.install(self.home, self.hook, ref, port=self.port)
        self.assertIn(prefix+'toolbox/ports/Ultimate%20Wine%20Toolbox.sh', seen)
        self.assertTrue(all(' ' not in url for url in seen))
        expected = (self.source/'toolbox/ports/Ultimate Wine Toolbox.sh').read_bytes()
        self.assertEqual(self.port.read_bytes(), expected)
        self.assertEqual((self.home/'toolbox/ports/Ultimate Wine Toolbox.sh').read_bytes(), expected)
        installer.restore(backup)
        self.assertEqual(self.port.read_bytes(), self.old['toolbox/ports/Ultimate Wine Toolbox.sh'])


    def test_upgrade_from_contrast_version_preserves_existing_profiles(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/helpers/community_profiles.py'
        module.write_bytes(module.read_bytes()+b'\n# bulk configuration export\n')
        with patch.object(installer, 'CONTRAST_MENU_HASHES', hashes):
            backup = self.install()
        self.assertIn('bulk configuration export', (self.home/'toolbox/helpers/community_profiles.py').read_text())
        installer.restore(backup)
        self.assertNotIn('bulk configuration export', (self.home/'toolbox/helpers/community_profiles.py').read_text())


    def test_upgrade_from_bulk_export_version_updates_role_editing_helpers(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/helpers/antimicrox_live.py'
        module.write_bytes(module.read_bytes()+b'\n# edit launcher or game role\n')
        with patch.object(installer, 'BULK_EXPORT_HASHES', hashes):
            backup = self.install()
        self.assertIn('edit launcher or game role', (self.home/'toolbox/helpers/antimicrox_live.py').read_text())
        installer.restore(backup)
        self.assertNotIn('edit launcher or game role', (self.home/'toolbox/helpers/antimicrox_live.py').read_text())


    def test_upgrade_from_grouped_menu_version_updates_deletion_helpers(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/helpers/antimicrox_profiles.py'
        module.write_bytes(module.read_bytes()+b'\n# preserve launcher references\n')
        with patch.object(installer, 'GROUPED_MENU_HASHES', hashes):
            backup = self.install()
        self.assertIn('preserve launcher references', (self.home/'toolbox/helpers/antimicrox_profiles.py').read_text())
        installer.restore(backup)
        self.assertNotIn('preserve launcher references', (self.home/'toolbox/helpers/antimicrox_profiles.py').read_text())


    def test_upgrade_from_explicit_removal_version_updates_unused_profile_filter(self):
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        module = self.source/'toolbox/helpers/antimicrox_profiles.py'
        module.write_bytes(module.read_bytes()+b'\n# unassigned profile filter\n')
        with patch.object(installer, 'EXPLICIT_REMOVAL_HASHES', hashes):
            backup = self.install()
        self.assertIn('unassigned profile filter', (self.home/'toolbox/helpers/antimicrox_profiles.py').read_text())
        installer.restore(backup)
        self.assertNotIn('unassigned profile filter', (self.home/'toolbox/helpers/antimicrox_profiles.py').read_text())


    def test_install_and_restore_update_the_existing_native_wrapper_too(self):
        name = 'toolbox/helpers/antimicrox-launch.sh'
        wrapper = self.home/'tools/antimicrox/antimicrox'
        wrapper.parent.mkdir(parents=True); wrapper.write_bytes(self.old[name]); wrapper.chmod(0o755)
        backup = self.install()
        self.assertEqual(wrapper.read_bytes(), (self.source/name).read_bytes())
        self.assertEqual(wrapper.stat().st_mode & 0o777, 0o755)
        self.assertIsNone(self.install())
        installer.restore(backup)
        self.assertEqual(wrapper.read_bytes(), self.old[name])
        self.assertEqual(wrapper.stat().st_mode & 0o777, 0o755)

    def test_test_install_does_not_create_a_runtime_when_antimicrox_is_absent(self):
        self.install()
        self.assertFalse((self.home/'tools/antimicrox/antimicrox').exists())

    def test_modified_installed_native_wrapper_is_refused_before_any_write(self):
        wrapper = self.home/'tools/antimicrox/antimicrox'
        wrapper.parent.mkdir(parents=True); wrapper.write_text('# local customization\n')
        with self.assertRaises(ValueError): self.install()
        self.assertFalse((self.home/'state/backups').exists())
        self.assertEqual((self.home/'toolbox/modules/antimicrox.sh').read_bytes(), self.old['toolbox/modules/antimicrox.sh'])

    def test_installed_wrapper_symlink_is_refused_before_any_write(self):
        wrapper = self.home/'tools/antimicrox/antimicrox'; wrapper.parent.mkdir(parents=True)
        target = self.root/'custom-wrapper'; target.write_text('# custom\n'); wrapper.symlink_to(target)
        with self.assertRaises(ValueError): self.install()
        self.assertFalse((self.home/'state/backups').exists())
        self.assertEqual(target.read_text(), '# custom\n')

    def test_upgrade_from_unassigned_cleanup_version_updates_both_native_wrappers(self):
        name = 'toolbox/helpers/antimicrox-launch.sh'
        wrapper = self.home/'tools/antimicrox/antimicrox'
        wrapper.parent.mkdir(parents=True); wrapper.write_bytes(self.old[name]); wrapper.chmod(0o755)
        self.install()
        hashes = {name: installer.sha((self.home/name).read_bytes())
                  for name in [*self.old, installer.HELPER]}
        source = self.source/name; source.write_bytes(source.read_bytes()+b'\n# Sunshine SDL workaround\n')
        with patch.object(installer, 'UNASSIGNED_REMOVAL_HASHES', hashes):
            backup = self.install()
        self.assertIn(b'Sunshine SDL workaround', wrapper.read_bytes())
        self.assertEqual(wrapper.read_bytes(), (self.home/name).read_bytes())
        installer.restore(backup)
        self.assertNotIn(b'Sunshine SDL workaround', wrapper.read_bytes())


    def test_offline_guides_install_as_text_without_shell_parsing_or_execution(self):
        name = 'toolbox/docs/fr/antimicrox.txt'
        text = 'Profils (launcher / jeu) : 64 Kio.\n$(touch '+str(self.root/'should-not-exist')+')\n'
        (self.source/name).write_text(text)
        backup = self.install()
        self.assertEqual((self.home/name).read_text(), text)
        self.assertFalse((self.root/'should-not-exist').exists())
        installer.restore(backup)
        self.assertEqual((self.home/name).read_bytes(), self.old[name])

    def test_invalid_utf8_guide_is_rejected_before_any_write(self):
        (self.source/'toolbox/docs/fr/antimicrox.txt').write_bytes(b'\xff')
        with self.assertRaises(ValueError): self.install()
        self.assertFalse((self.home/'state/backups').exists())

    def test_embedded_nul_in_guide_is_rejected_before_any_write(self):
        (self.source/'toolbox/docs/en/creation.txt').write_bytes(b'Guide\0bad')
        with self.assertRaises(ValueError): self.install()
        self.assertFalse((self.home/'state/backups').exists())


class PublishedVersionHashesTests(unittest.TestCase):
    def test_deletion_version_keeps_its_updated_profiles_helper_hash(self):
        # Published in 02edb647: this must not inherit the pre-deletion baseline.
        path = 'toolbox/helpers/antimicrox_profiles.py'
        self.assertEqual(installer.DELETION_MENU_HASHES[path],
                         '0df93eb827267e25aa54a79b0c40fe91fc3e0f02132d11f35b6728ee64ed97ef')
        self.assertEqual(installer.BASE_HASHES[path],
                         'f048a9cb29bea1cccd5ecc5d441f2b0e45fca0ffd73509b541c01a2b6f2843ce')


    def test_explicit_removal_version_keeps_its_published_hashes(self):
        self.assertEqual(installer.EXPLICIT_REMOVAL_HASHES['toolbox/helpers/antimicrox_profiles.py'],
                         installer.DELETION_MENU_HASHES['toolbox/helpers/antimicrox_profiles.py'])
        self.assertEqual(installer.EXPLICIT_REMOVAL_HASHES['toolbox/modules/antimicrox.sh'],
                         '6e5ab5ad92c0924dd329b9da43558bdd22cf64010f231d77e9be0100a552ada4')


    def test_unassigned_cleanup_version_preserves_its_profile_and_wrapper_hashes(self):
        self.assertEqual(installer.UNASSIGNED_REMOVAL_HASHES['toolbox/helpers/antimicrox_profiles.py'],
                         'a48f52d0cb36c737a28d7d189e36e1d684f53e48d54a3c8f0051f0e85ada77ab')
        self.assertEqual(installer.MOONLIGHT_INPUT_HASHES['toolbox/helpers/antimicrox-launch.sh'],
                         '7da8c0c8a1688a93f7b2fa278c48bd8784cf6cf58504d1f1d57ec06843a0731f')
        self.assertEqual(installer.PLAIN_GAME_LIST_HASHES['toolbox/helpers/antimicrox-launch.sh'],
                         installer.MOONLIGHT_INPUT_HASHES['toolbox/helpers/antimicrox-launch.sh'])
        for name, hashes in vars(installer).items():
            if name.endswith('_HASHES') and name not in ('MOONLIGHT_INPUT_HASHES', 'PLAIN_GAME_LIST_HASHES', 'DOCS_REFRESH_HASHES', 'SAVE_BACKUP_CLEANUP_HASHES'):
                self.assertEqual(hashes['toolbox/helpers/antimicrox-launch.sh'], 'a5266a0e16eb3aba60beb27dae1810eff4b2c2d239ce8383f75f9bd422aa438b', name)


if __name__ == '__main__':
    unittest.main()
