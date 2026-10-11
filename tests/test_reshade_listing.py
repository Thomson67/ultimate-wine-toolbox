import importlib.util
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resh_listing', ROOT / 'toolbox/helpers/reshade_manager.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class ReShadeListingTests(unittest.TestCase):
    def test_batch_statuses_preserve_order_filter_formats_and_read_fresh_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / 'home'
            paths = ['/games/Zèbre.wsquashfs', '/games/with spaces.PC',
                     '/games/nested/Test.wine', '/games/Unsupported.wtgz']
            active = home / 'reshade/games' / (r.key(paths[0]) + '.json')
            disabled = home / 'reshade/games' / (r.key(paths[1]) + '.json')
            r.save_json(active, {'enabled': True})
            r.save_json(disabled, {'enabled': False})
            self.assertEqual(r.list_statuses(home, paths),
                             [(paths[0], 'enabled'), (paths[1], 'disabled'), (paths[2], 'missing')])
            # No game files exist: listing only reads local ReShade configuration.
            r.save_json(active, {'enabled': False})
            self.assertEqual(r.list_statuses(home, paths)[0][1], 'disabled')
            active.unlink()
            self.assertEqual(r.list_statuses(home, paths)[0][1], 'missing')

    def test_menu_uses_one_python_process_and_keeps_labels_and_selection_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            games = base / 'games'
            games.mkdir()
            paths = [games / 'Alpha.wsquashfs', games / 'Bêta.PC', games / 'nested/Gamma.wine']
            paths[0].touch()
            paths[1].mkdir()
            paths[2].mkdir(parents=True)
            (games / 'Unsupported.wtgz').touch()
            home = base / 'home'
            r.save_json(home / 'reshade/games' / (r.key(paths[0]) + '.json'), {'enabled': True})
            r.save_json(home / 'reshade/games' / (r.key(paths[1]) + '.json'), {'enabled': False})
            private = base / 'bin'
            private.mkdir()
            wrapper = private / 'python3'
            wrapper.write_text('#!/bin/bash\nprintf "call\\n" >> "$CALLS"\nexec '
                               + shlex.quote(sys.executable) + ' "$@"\n')
            wrapper.chmod(0o755)
            env = dict(os.environ, WT_ROOT=str(ROOT / 'toolbox'), WT_HOME=str(home), TEST_HOME=str(home),
                       PATH=str(private) + ':' + os.environ['PATH'], TEST_ROMS=str(games),
                       CALLS=str(base / 'calls'), ROWS=str(base / 'rows'))
            script = '''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/graphics.sh"
source "$WT_ROOT/modules/reshade.sh"
WINDOWS_ROMS="$TEST_ROMS"
msgbox() { return 0; }
menu_select() { shift 2; printf '%s\\0' "$@" > "$ROWS"; return 1; }
resh_menu
'''
            result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
            self.assertEqual(result.stderr, '')
            self.assertEqual((base / 'calls').read_text(), 'call\n')
            rows = (base / 'rows').read_bytes().decode().split('\0')[:-1]
            self.assertEqual(rows[::2], ['1', '2', '3'])
            self.assertEqual(rows[1::2], ['Alpha.wsquashfs — ' + 'Activé',
                                        'Bêta.PC — ' + 'Installé, désactivé',
                                        'Gamma.wine — ' + 'Non installé'])


if __name__ == '__main__':
    unittest.main()
