import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vulkan_installer', ROOT / 'scripts/install-reshade-vulkan-test.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class VulkanInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir()
        (self.home / 'VERSION').write_text('0.8.1\n')
        self.hook = Path(self.temp.name) / 'hook.sh'
        self.hook.write_text('#!/bin/bash\necho original\n')
        path = 'toolbox/helpers/reshade_vulkan.py'
        self.payload = {'files': {installer.HOOK: '#!/bin/bash\necho new\n', path: '# new helper\n'},
                        'base_hashes': {installer.HOOK: [installer.digest(self.hook.read_bytes())], path: [None]}}
        source = self.home / installer.HOOK
        source.parent.mkdir(parents=True)
        source.write_bytes(self.hook.read_bytes())

    def test_embedded_sources_and_baselines_are_complete(self):
        payload = installer.unpack()
        for path, content in payload['files'].items():
            self.assertEqual(content, (ROOT / path).read_text(), path)
            self.assertTrue(payload['base_hashes'][path])

    def test_repeat_and_restore_preserve_mangohud_state_and_disable_vulkan_first(self):
        state = self.home / 'config/mangohud-settings.json'
        state.parent.mkdir()
        state.write_text('{"global":{"vulkan":"mailbox"}}\n')
        with patch.object(installer, 'unpack', return_value=self.payload):
            installer.install(self.home, self.hook)
            installer.install(self.home, self.hook)
        def check_still_new(home):
            self.assertEqual(self.hook.read_text(), self.payload['files'][installer.HOOK])
        with patch.object(installer, 'restore_vulkan_games', side_effect=check_still_new) as disable:
            installer.restore(self.home)
        disable.assert_called_once_with(self.home)
        self.assertEqual(self.hook.read_text(), '#!/bin/bash\necho original\n')
        self.assertFalse((self.home / 'toolbox/helpers/reshade_vulkan.py').exists())
        self.assertEqual(json.loads(state.read_text())['global']['vulkan'], 'mailbox')

    def test_restore_stops_if_game_cleanup_fails(self):
        with patch.object(installer, 'unpack', return_value=self.payload):
            installer.install(self.home, self.hook)
        with patch.object(installer, 'restore_vulkan_games', side_effect=ValueError('game active')):
            with self.assertRaisesRegex(ValueError, 'game active'):
                installer.restore(self.home)
        self.assertEqual(self.hook.read_text(), self.payload['files'][installer.HOOK])
        self.assertTrue((self.home / installer.STATE).exists())

    def test_unknown_files_are_refused_before_mutation(self):
        self.hook.write_text('# unknown user hook\n')
        with patch.object(installer, 'unpack', return_value=self.payload), self.assertRaises(ValueError):
            installer.install(self.home, self.hook)
        self.assertEqual(self.hook.read_text(), '# unknown user hook\n')
        self.assertFalse((self.home / installer.STATE).exists())


if __name__ == '__main__':
    unittest.main()
