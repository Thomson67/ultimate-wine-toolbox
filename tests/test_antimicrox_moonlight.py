"""Apply the confirmed evdev workaround only to AMX with Sunshine present."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MoonlightInputTests(unittest.TestCase):
    def launch(self, devices, inherited=None):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            sysroot = home/'sys/class/input'; sysroot.mkdir(parents=True)
            for i, name in enumerate(devices):
                node = sysroot/f'event{i}/device/name'; node.parent.mkdir(parents=True)
                node.write_text(name+'\n')
            app = home/'tools/antimicrox/squashfs-root/AppRun'
            app.parent.mkdir(parents=True)
            app.write_text('#!/bin/bash\nprintf "%s\\n" "${SDL_JOYSTICK_HIDAPI-unset}" "$@"\n')
            app.chmod(0o755)
            source = (ROOT/'toolbox/helpers/antimicrox-launch.sh').read_text()
            source = source.replace('/sys/class/input', str(sysroot))
            script = home/'launch.sh'; script.write_text(source)
            env = dict(os.environ, WT_HOME=folder)
            env.pop('SDL_JOYSTICK_HIDAPI', None)
            if inherited is not None: env['SDL_JOYSTICK_HIDAPI'] = inherited
            return subprocess.run(['bash', str(script), '--show', '--eventgen', 'uinput'],
                                  env=env, text=True, capture_output=True, timeout=10)

    def test_virtual_sunshine_controller_uses_confirmed_workaround(self):
        result = self.launch(['Sunshine (libvirtualhid) X-Box Series Controller'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['0', '--show', '--eventgen', 'uinput'])
        self.assertIn('Sunshine controller detected', result.stderr)

    def test_sunshine_presence_overrides_an_inherited_hidapi_default(self):
        result = self.launch(['Sunshine (libvirtualhid) X-Box Series Controller'], '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], '0')

    def test_local_controllers_keep_the_existing_sdl_configuration(self):
        for inherited in (None, '0', '1'):
            with self.subTest(inherited=inherited):
                result = self.launch(['Sony Interactive Entertainment Wireless Controller', '8BitDo Pro 2'], inherited)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines()[0], inherited if inherited is not None else 'unset')
                self.assertNotIn('HIDAPI disabled', result.stderr)

    def test_keyboard_and_mouse_without_sunshine_controller_do_not_trigger_override(self):
        result = self.launch(['libvirtualhid Keyboard', 'libvirtualhid Mouse', 'Logitech USB Receiver'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], 'unset')

    def test_empty_sysfs_does_not_prevent_launch(self):
        result = self.launch([])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], 'unset')

    def test_local_and_virtual_controllers_can_coexist(self):
        result = self.launch(['8BitDo Pro 2', 'Sunshine (libvirtualhid) X-Box Series Controller', 'Wireless Controller'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], '0')


if __name__ == '__main__':
    unittest.main()
