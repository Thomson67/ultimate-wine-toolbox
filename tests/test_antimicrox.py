import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AntiMicroXTests(unittest.TestCase):
    def run_bash(self, code, env=None):
        return subprocess.run(['bash', '-c', code], env=env, text=True,
                              capture_output=True, timeout=12)

    def test_asset_selection_excludes_debug(self):
        source = (ROOT/'toolbox/helpers/install-antimicrox.sh').read_text()
        script = source.split("<<'PY'\n", 1)[1].split('\nPY', 1)[0]
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            names = ['AntiMicroX-x86_64.AppImage', 'AntiMicroX-debug-x86_64.AppImage']
            url = 'https://github.com/AntiMicroX/antimicrox/releases/download/3.6.1/'
            (base/'release').write_text(json.dumps({'assets': [
                {'name': n, 'browser_download_url': url+n} for n in names]}))
            result = subprocess.run(['python3', '-c', script, str(base/'release'), str(base/'url')],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((base/'url').read_text(), url+names[0])

    def test_launcher_overrides_host_qt_but_preserves_display_and_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            app = base/'tools/antimicrox/squashfs-root/AppRun'
            app.parent.mkdir(parents=True)
            app.write_text('#!/bin/bash\nprintf "%s\\n" "$QT_QPA_PLATFORM" "$QT_PLUGIN_PATH" "${QT_STYLE_OVERRIDE-unset}" "$DISPLAY" "$@"\n')
            app.chmod(0o755)
            env = dict(os.environ, WT_HOME=folder, QT_QPA_PLATFORM='wayland',
                       QT_PLUGIN_PATH='/batocera/qt5', QT_STYLE_OVERRIDE='bad-style', DISPLAY=':7')
            result = subprocess.run(['bash', str(ROOT/'toolbox/helpers/antimicrox-launch.sh'),
                                     '--profile', '/userdata/My Game.amgp'], env=env,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertEqual(lines, ['xcb', str(base/'tools/antimicrox/squashfs-root/usr/plugins'),
                                     'unset', ':7', '--profile', '/userdata/My Game.amgp'])

    def test_legacy_download_is_extracted_once(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); tools = base/'tools/antimicrox'; tools.mkdir(parents=True)
            image = tools/'AntiMicroX.AppImage'
            image.write_text('''#!/bin/bash
mkdir -p squashfs-root
printf '#!/bin/bash\\necho ready\\n' > squashfs-root/AppRun
chmod +x squashfs-root/AppRun
echo extracted >> "$WT_HOME/count"
''')
            image.chmod(0o755)
            for _ in range(2):
                result = subprocess.run(['bash', str(ROOT/'toolbox/helpers/antimicrox-launch.sh')],
                                        env=dict(os.environ, WT_HOME=folder), text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'ready')
            self.assertEqual((base/'count').read_text(), 'extracted\n')

    def test_editor_surfaces_failure_and_returns_to_menu(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); binary = base/'tools/antimicrox/antimicrox'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/bash\necho "Qt failed to load" >&2\nexit 42\n')
            binary.chmod(0o755)
            env = dict(os.environ, WT_HOME=folder, WT_LANGUAGE='fr', MODULE=str(ROOT/'toolbox/modules/antimicrox.sh'))
            result = self.run_bash('''source "$MODULE"
pgrep() { return 1; }
amx_log_path() { printf '%s/editor.log' "$WT_HOME"; }
msgbox() { printf '%s\\n' "$2"; }
amx_editor
''', env)
            self.assertEqual(result.returncode, 42)
            self.assertIn('code 42', result.stdout)
            self.assertIn('Qt failed to load', result.stdout)

    def test_editor_initializes_tray_menu_needed_by_settings_ok(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); binary = base/'tools/antimicrox/antimicrox'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$WT_HOME/args"\n')
            binary.chmod(0o755)
            env = dict(os.environ, WT_HOME=folder, WT_LANGUAGE='fr', MODULE=str(ROOT/'toolbox/modules/antimicrox.sh'))
            result = self.run_bash('''source "$MODULE"
pgrep() { return 1; }
amx_log_path() { printf '%s/editor.log' "$WT_HOME"; }
msgbox() { return 0; }
amx_editor
''', env)
            self.assertEqual(result.returncode, 0, result.stderr)
            args = (base/'args').read_text().splitlines()
            self.assertIn('--show', args)
            self.assertNotIn('--no-tray', args)
            self.assertEqual(args[args.index('--eventgen')+1], 'uinput')

    def test_associations_handle_spaces_brackets_replacement_and_disable(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, WT_HOME=folder, WT_LANGUAGE='fr', MODULE=str(ROOT/'toolbox/modules/antimicrox.sh'))
            result = self.run_bash('''source "$MODULE"
amx_set_profile '/userdata/Game[GE Proton].wsquashfs' '/userdata/first.amgp'
amx_set_profile '/userdata/Other.wine' '/userdata/other.amgp'
amx_set_profile '/userdata/Game[GE Proton].wsquashfs' '/userdata/new.amgp'
amx_set_profile '/userdata/Other.wine' ''
cat "$AMX_OVERRIDES"
''', env)
            self.assertEqual(result.stdout, '/userdata/Game[GE Proton].wsquashfs\t/userdata/new.amgp\n')

    def hook_fixture(self, base):
        # Redirect only fixed hardware/data locations; execute the actual hook logic.
        source = (ROOT/'toolbox/hooks/antimicrox-game-event.sh').read_text()
        source = source.replace('/userdata/', str(base)+'/').replace('/dev/uinput', str(base/'uinput'))
        source = source.replace('/proc/', str(base/'proc')+'/')
        hook = base/'hook.sh'; hook.write_text(source)
        (base/'uinput').touch()
        (base/'config').mkdir()
        binary = base/'tools/antimicrox/antimicrox'; binary.parent.mkdir(parents=True)
        binary.write_text("#!/usr/bin/env python3\nimport os, signal, time\nfrom pathlib import Path\nbase = Path(os.environ['WT_HOME'])/'proc'/str(os.getpid())\nbase.mkdir(parents=True)\n(base/'stat').write_text(str(os.getpid())+' (AntiMicroX (test)) '+' '.join(['S']+['0']*18+['12345']))\n(base/'cmdline').write_bytes(b'antimicrox-test\\0')\ndef stop(*args):\n    (base/'stat').unlink(missing_ok=True)\n    raise SystemExit(0)\nsignal.signal(signal.SIGTERM, stop)\ntime.sleep(60)\n")
        binary.chmod(0o755)
        profile = base/'My Profile.amgp'; profile.write_text('<joystick/>')
        rom = str(base/'My Game[GE].wine')
        (base/'config/antimicrox-games.tsv').write_text(rom+'\t'+str(profile)+'\n')
        return hook, rom

    def test_hook_start_stop_does_not_hold_lock_or_stop_wrong_game(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); hook, rom = self.hook_fixture(base)
            env = dict(os.environ, WT_HOME=folder)
            session = base/'state/antimicrox/session'
            pid = None
            def event(kind, game):
                return subprocess.run(['bash', str(hook), kind, 'windows', '', '', game],
                                      env=env, text=True, capture_output=True, timeout=8)
            try:
                self.assertEqual(event('gameStart', rom).returncode, 0)
                self.assertTrue(session.exists())
                pid = int(session.read_text().split('\t')[1])
                self.assertEqual(event('gameStop', 'different-game').returncode, 0)
                self.assertTrue(session.exists())
                self.assertEqual(event('gameStop', rom).returncode, 0)
                self.assertFalse(session.exists())
                status = base/'proc'/str(pid)/'stat'
                self.assertTrue(not status.exists() or status.read_text().split(') ')[1].startswith('Z'))
            finally:
                if pid:
                    try: os.kill(pid, 9)
                    except ProcessLookupError: pass

    def test_live_hook_opens_one_visible_instance_without_no_tray(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); hook, rom = self.hook_fixture(base)
            helpers = base/'toolbox/helpers'; helpers.mkdir(parents=True)
            (helpers/'antimicrox_live.py').write_text((ROOT/'toolbox/helpers/antimicrox_live.py').read_text())
            (helpers/'antimicrox_focus.py').write_text('''import os, sys, json
from pathlib import Path
try:
    os.fstat(9)
    raise RuntimeError('hook lock inherited by focus observer')
except OSError:
    pass
(Path(os.environ['WT_HOME'])/'focus-args').write_text(json.dumps(sys.argv[1:]))
''')
            commands = base/'bin'; commands.mkdir()
            popup = commands/'batocera-flash-screen'
            popup.write_text('#!/bin/sh\nexit 0\n'); popup.chmod(0o755)
            state = base/'state'; state.mkdir()
            profile = str(base/'My Profile.amgp')
            (state/'antimicrox-live.json').write_text(json.dumps({'rom': rom, 'profile': profile, 'phase': 'prepared'}))
            binary = base/'tools/antimicrox/antimicrox'
            text = binary.read_text().replace('import os, signal, time', 'import os, signal, time, sys, json')
            text = text.replace("base.mkdir(parents=True)", "base.mkdir(parents=True)\n(base.parent.parent/'args').write_text(json.dumps(sys.argv[1:]))")
            binary.write_text(text)
            env = dict(os.environ, WT_HOME=folder, PATH=str(commands)+os.pathsep+os.environ['PATH'])
            session = state/'antimicrox/session'; pid = None
            try:
                result = subprocess.run(['bash', str(hook), 'gameStart', 'windows', '', '', rom],
                                        env=env, text=True, capture_output=True, timeout=8)
                self.assertEqual(result.returncode, 0, result.stderr)
                pid = int(session.read_text().split('\t')[1])
                args = json.loads((base/'args').read_text())
                self.assertIn('--show', args)
                self.assertNotIn('--hidden', args)
                self.assertNotIn('--no-tray', args)
                self.assertEqual(args[args.index('--profile')+1], profile)
                self.assertEqual(json.loads((state/'antimicrox-live.json').read_text())['phase'], 'running')
                focus_args = json.loads((base/'focus-args').read_text())
                self.assertEqual(focus_args[:4], ['spawn', rom, str(pid), '12345'])
                stop = subprocess.run(['bash', str(hook), 'gameStop', 'windows', '', '', rom],
                                      env=env, capture_output=True, timeout=8)
                self.assertEqual(stop.returncode, 0)
                self.assertFalse(session.exists())
            finally:
                if pid:
                    try: os.kill(pid, 9)
                    except ProcessLookupError: pass

    def test_unconfigured_next_game_cleans_stale_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); hook, rom = self.hook_fixture(base)
            env = dict(os.environ, WT_HOME=folder)
            session = base/'state/antimicrox/session'; pid = None
            try:
                for game in [rom, 'unconfigured-game']:
                    result = subprocess.run(['bash', str(hook), 'gameStart', 'windows', '', '', game],
                                            env=env, capture_output=True, timeout=8)
                    self.assertEqual(result.returncode, 0)
                    if game == rom:
                        pid = int(session.read_text().split('\t')[1])
                self.assertFalse(session.exists())
            finally:
                if pid:
                    try: os.kill(pid, 9)
                    except ProcessLookupError: pass


if __name__ == '__main__':
    unittest.main()
