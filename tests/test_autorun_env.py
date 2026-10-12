import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'toolbox/helpers/autorun_env.py'
spec = importlib.util.spec_from_file_location('autorun_env', HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class AutorunEnvTests(unittest.TestCase):
    def test_enable_disable_preserve_other_settings(self):
        source = 'DIR=game\nCMD="game.exe"\nENV=MANGOHUD=1\nENV=UMU_DIRECT_GAME=0 FOO="two words"\n'
        result = module.rewrite(source, True)
        self.assertEqual(result.count('ENV='), 1)
        self.assertEqual(module.env_tokens(result), ['MANGOHUD=1', 'FOO=two words', 'UMU_DIRECT_GAME=1'])
        self.assertEqual(module.rewrite(result, True), result)
        disabled = module.rewrite(result, False)
        self.assertFalse(module.enabled(disabled))
        self.assertIn('CMD="game.exe"', disabled)
        self.assertEqual(module.env_tokens(disabled), ['MANGOHUD=1', 'FOO=two words'])
    def test_final_autorun_rewrite_keeps_env(self):
        script = (ROOT / 'toolbox/modules/wsquashfs.sh').read_text()
        block = script[script.index('wsq_write_autorun() {'):script.index('\nwsq_runner_candidates()')]
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            (p/'autorun.cmd').write_text('DIR=old\nCMD=old.exe\nENV=MANGOHUD=1 UMU_DIRECT_GAME=1\n')
            subprocess.run(['bash','-c', block + '\nwsq_write_autorun "$1" "game/new.exe" "." "user.reg"', '_', folder], env={'WT_ROOT':str(ROOT/'toolbox'), 'PATH':'/usr/bin:/bin'}, check=True)
            text = (p/'autorun.cmd').read_text()
            self.assertIn('CMD="new.exe"', text)
            self.assertIn('SAVEFILES=user.reg', text)
            self.assertTrue(module.enabled(text))
            self.assertEqual(text.count('ENV='),1)

    def test_sony_xinput_states_and_env_preservation(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'autorun.cmd'
            p.write_text('DIR=game\nCMD=game.exe\nENV=MANGOHUD=1 UMU_DIRECT_GAME=1\nENV=PROTON_SONY_HIDRAW_XINPUT=0\n')
            for value in ('1', '0', 'inherit'):
                subprocess.run(['python3', str(HELPER), 'set', str(p), value, '--key', 'PROTON_SONY_HIDRAW_XINPUT'], check=True)
                actual = subprocess.check_output(['python3', str(HELPER), 'get', str(p), '--key', 'PROTON_SONY_HIDRAW_XINPUT'], text=True).strip()
                self.assertEqual(actual, value)
                text = p.read_text()
                self.assertEqual(text.count('ENV='), 1)
                self.assertTrue(module.enabled(text))
                self.assertIn('MANGOHUD=1', text)
                self.assertEqual(text.count('PROTON_SONY_HIDRAW_XINPUT='), int(value != 'inherit'))
