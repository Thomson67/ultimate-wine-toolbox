import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from test_reshade import ROOT, pe, r
import test_reshade as fixtures
import reshade_vulkan as vk


class ReShadeVulkanTests(unittest.TestCase):
    def setUp(self):
        fixtures.ReShadeTests.setUp(self)
        self.loader = self.home / 'reshade/runtime/vulkan-loader/1.4.341.0/64/vulkan-1.dll'
        self.loader.parent.mkdir(parents=True)
        self.loader.write_bytes(pe(64) + b'loader')
        self.cfg.update(dll='vulkan', vulkan_loader=str(self.loader),
                        vulkan_loader_hash=r.fingerprint(self.loader)['sha256'])
        r.save_json(self.config, self.cfg)
        self.registry = self.rom / 'system.reg'
        self.registry.write_text('WINE REGISTRY Version 2\n#arch=win64\n\n[Software\\\\Example]\n"Keep"="original"\n')
        self.original_reg = self.registry.read_text()

    def test_install_repeat_and_disable_preserve_presets_env_and_registry_changes(self):
        (self.game / 'vulkan-1.dll').write_bytes(b'original app loader')
        r.event(self.home, self.rom, 'gameStart')
        self.assertEqual((self.game / 'vulkan-1.dll').read_bytes(), self.loader.read_bytes())
        self.assertEqual((self.rom / 'drive_c/windows/system32/vulkan-1.dll').read_bytes(), self.loader.read_bytes())
        self.assertEqual((self.game / 'ReShade64.dll').read_bytes(), self.runtime.read_bytes())
        self.assertFalse((self.game / 'vulkan.dll').exists())
        self.assertFalse((self.game / 'dxgi.dll').exists())
        manifest = json.loads((self.game / 'ReShade64.json').read_text())
        self.assertEqual(manifest['layer']['name'], 'VK_LAYER_reshade')
        self.assertEqual(manifest['layer']['library_path'], '.\\ReShade64.dll')
        name = vk.windows_path(self.game / 'ReShade64.json')
        self.assertTrue(vk.value_line(self.registry.read_text(), vk.LAYER_SECTION, name).endswith('=dword:00000000'))
        first = (self.rom / 'autorun.cmd').read_text()
        self.assertIn('vulkan-1=n;d3dcompiler_47=n,b', first)
        self.assertIn('MANGOHUD=1', first)
        self.registry.write_text(self.registry.read_text() + '\n[Software\\\\LaterGameState]\n"KeepToo"="new save"\n')
        (self.game / 'ReShadePreset.ini').write_text('Techniques=CAS@CAS.fx\n')
        r.event(self.home, self.rom, 'gameStart')
        r.event(self.home, self.rom, 'gameStop')
        self.assertEqual((self.rom / 'autorun.cmd').read_text(), first)
        r.set_enabled(self.home, self.rom, False)
        self.assertEqual((self.game / 'vulkan-1.dll').read_bytes(), b'original app loader')
        self.assertFalse((self.game / 'ReShade64.dll').exists())
        self.assertFalse((self.game / 'ReShade64.json').exists())
        self.assertFalse((self.rom / 'drive_c/windows/system32/vulkan-1.dll').exists())
        self.assertEqual((self.rom / 'autorun.cmd').read_text(), self.original)
        self.assertIn('"KeepToo"="new save"', self.registry.read_text())
        self.assertIn('"Keep"="original"', self.registry.read_text())
        self.assertIsNone(vk.value_line(self.registry.read_text(), vk.LAYER_SECTION, name))
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_text(), 'Techniques=CAS@CAS.fx\n')

    def test_loader_tampering_and_uninitialized_registry_change_no_game_files(self):
        self.loader.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'loader missing or changed'):
            r.event(self.home, self.rom, 'gameStart')
        self.assertEqual(self.registry.read_text(), self.original_reg)
        self.assertEqual((self.rom / 'autorun.cmd').read_text(), self.original)
        self.assertFalse((self.game / 'ReShade64.dll').exists())
        self.loader.write_bytes(pe(64) + b'loader')
        self.registry.unlink()
        with self.assertRaisesRegex(ValueError, 'initialized prefix'):
            r.event(self.home, self.rom, 'gameStart')
        self.assertFalse((self.game / 'ReShade64.dll').exists())

    def test_unrelated_existing_reshade_layer_is_not_disabled(self):
        original = vk.set_value(self.original_reg, vk.LAYER_SECTION, 'C:\\OtherReShade.json',
                                '"C:\\\\OtherReShade.json"=dword:00000000')
        self.registry.write_text(original)
        with self.assertRaisesRegex(ValueError, 'another enabled'):
            r.event(self.home, self.rom, 'gameStart')
        self.assertEqual(self.registry.read_text(), original)
        self.assertFalse((self.game / 'vulkan-1.dll').exists())

    def test_failure_after_registry_write_rolls_back_files_and_registry(self):
        atomic = r.atomic_bytes
        failed = False
        def fail_autorun(path, data):
            nonlocal failed
            if path == self.rom / 'autorun.cmd' and not failed:
                failed = True
                raise OSError('simulated ENV write failure')
            atomic(path, data)
        with patch.object(r, 'atomic_bytes', side_effect=fail_autorun), self.assertRaises(OSError):
            r.event(self.home, self.rom, 'gameStart')
        self.assertFalse((self.game / 'vulkan-1.dll').exists())
        self.assertFalse((self.game / 'ReShade64.dll').exists())
        self.assertEqual((self.rom / 'autorun.cmd').read_text(), self.original)
        self.assertIsNone(vk.value_line(self.registry.read_text(), vk.LAYER_SECTION,
                                       vk.windows_path(self.game / 'ReShade64.json')))

    def test_prepare_and_finish_reuse_backend_and_existing_preset(self):
        workspace = r.prepare(self.home, self.rom, self.exe, 'vulkan', '6.8.0', 'none')
        pending = r.read_json(workspace / 'pending.json')
        self.assertEqual(pending['dll'], 'vulkan')
        self.assertEqual(pending['backend_dll'], 'dxgi')
        (workspace / 'dxgi.dll').symlink_to(self.runtime)
        (workspace / 'd3dcompiler_47.dll').symlink_to(self.compiler)
        (workspace / 'ReShade_shaders').symlink_to(self.shaders)
        backend = self.home / 'reshade/runtime/game-state' / (pending['state_key'] + '.state')
        backend.write_text('selected_repos=\n')
        with patch.object(r, 'COMPILER_HASH', {64: r.fingerprint(self.compiler)['sha256']}), patch.object(vk, 'loader', return_value=self.loader):
            cfg = r.finish(self.home, self.rom)
        self.assertEqual(cfg['dll'], 'vulkan')
        self.assertEqual(cfg['vulkan_loader'], str(self.loader))
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_text(), 'Techniques=\n')

    def test_registry_32bit_views_and_preexisting_managed_value_restore(self):
        name = vk.windows_path(self.game / 'ReShade32.json')
        for win32 in (True, False):
            self.registry.write_text(self.original_reg)
            record, changed = vk.registry_plan(self.rom, self.game / 'ReShade32.json', 32, win32)
            self.assertEqual('Wow6432Node' in record['section'], not win32)
            self.registry.write_text(changed)
            vk.registry_restore(record)
            self.assertIsNone(vk.value_line(self.registry.read_text(), record['section'], name))
        original = json.dumps(name) + '=dword:00000001'
        self.registry.write_text(vk.set_value(self.original_reg, vk.LAYER_SECTION, name, original))
        record, changed = vk.registry_plan(self.rom, self.game / 'ReShade32.json', 32, True)
        self.registry.write_text(changed)
        vk.registry_restore(record)
        self.assertEqual(vk.value_line(self.registry.read_text(), vk.LAYER_SECTION, name), original)

    def test_api_menu_offers_vulkan_and_keeps_stdout_machine_readable(self):
        code = '''source "$WT_ROOT/lib/common.sh"
WT_LANGUAGE=fr; load_i18n
WT_HOME="$TEST_HOME"
source "$WT_ROOT/modules/reshade.sh"
resh_cmd() { printf 'vulkan\\treferences\\tvulkan-1.dll'; }
menu_select() { printf '%s\\n' "$@" > "$TEST_HOME/menu"; printf vulkan; }
msgbox() { printf '%s' "$2" > "$TEST_HOME/help"; }
resh_api_select /games/Azahar.wine drive_c/Azahar/azahar.exe
'''
        result = subprocess.run(['bash', '-c', code], env=dict(os.environ,
            WT_ROOT=str(ROOT / 'toolbox'), TEST_HOME=str(self.home)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'vulkan')
        self.assertIn('expérimental', (self.home / 'menu').read_text())
        self.assertNotIn('missing translation', (self.home / 'help').read_text())


if __name__ == '__main__':
    unittest.main()
