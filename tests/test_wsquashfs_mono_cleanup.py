"""Run the private Mono-removal adaptation against simulated Wine commands."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import wsquashfs_mono_cleanup as cleanup
import wsquashfs_winetricks as tricks


FUNCTION = r'''load_remove_mono()
{
    mono_install_found=0
    for mono_installer_desc in 'Wine Mono Windows Support' 'Wine Mono Runtime' 'Wine Mono'; do
        mono_uuid="$(WINEDEBUG=-all "${WINE_ARCH}" uninstaller --list 2>&1 | grep "${mono_installer_desc}" | cut -f1 -d\|)"
        if test "${mono_uuid}"; then
            "${WINE_ARCH}" uninstaller --remove "${mono_uuid}"
            mono_install_found=1
        fi
    done
    if [ "${mono_install_found}" -eq 1 ]; then
        "${WINE_ARCH}" reg delete "HKLM\\Software\\Microsoft\\NET Framework Setup\\NDP\\v3.5" /f || true
        "${WINE_ARCH}" reg delete "HKLM\\Software\\Microsoft\\NET Framework Setup\\NDP\\v4" /f || true
    fi
}
'''


class MonoCleanupTests(unittest.TestCase):
    def run_cleanup(self, mono, private_launcher=False):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wine = base / 'wine'
            wine.write_text('''#!/bin/bash
if [ "$*" = 'uninstaller --list' ]; then
    if [ "$TEST_MONO" = 1 ]; then
        for guid in '{11111111-1111-1111-1111-111111111111}' '{22222222-2222-2222-2222-222222222222}'; do
            grep -qF -- "$guid" "$TEST_CALLS" 2>/dev/null || printf '%s|Wine Mono Windows Support\\n' "$guid"
        done
    fi
else
    printf '%s|%s\\n' "$#" "$*" >> "$TEST_CALLS"
fi
''')
            wine.chmod(0o700)
            calls = base / 'calls'
            script = base / 'cleanup.sh'
            script.write_text(cleanup.patched(FUNCTION) + '\nload_remove_mono\n')
            env = dict(os.environ, WINE_ARCH=str(wine), TEST_MONO=str(int(mono)), TEST_CALLS=str(calls))
            if private_launcher:
                script.write_text('#!/bin/bash\n' + FUNCTION + '\nload_remove_mono\n')
                original = script.read_bytes()
                launcher = base / 'batocera-wine'
                launcher.write_text('''WINETRICKS="$TEST_TRICKS"
trick_wine() {
    WINEPOINT="$1"
    shift
    TRICK=("$@")
    WINEPREFIX=${WINEPOINT} ${CMD_PREFIX} "${WINETRICKS}" "${TRICK[@]}"
}
waitWineServer() { :; }
cleanAndExit() { :; }
l_PREFIX="$3"
shift 3
            trick_wine "${l_PREFIX}" "$@"
''')
                with patch.dict(os.environ, dict(env, TEST_TRICKS=str(script))), \
                     patch.object(tricks, 'prepare'), patch.object(tricks, 'installer_file_limit'):
                    self.assertEqual(tricks.install(base / 'Game.wine', ['remove_mono', 'dotnet48'],
                        launcher, native_runner=True, mono_cleanup=True), 0)
                self.assertEqual(script.read_bytes(), original)
            else:
                result = subprocess.run(['bash', str(script)], capture_output=True, text=True, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
            return calls.read_text().splitlines() if calls.exists() else []

    def test_multiple_support_guids_and_both_registry_views(self):
        calls = self.run_cleanup(True)
        self.assertEqual(len(calls), 6)
        self.assertTrue(calls[0].startswith('3|uninstaller --remove {11111111-'))
        self.assertTrue(calls[1].startswith('3|uninstaller --remove {22222222-'))
        self.assertEqual(sum('/reg:32' in c for c in calls), 2)
        self.assertEqual(sum('/reg:64' in c for c in calls), 2)

    def test_no_mono_does_not_clear_registry(self):
        self.assertEqual(self.run_cleanup(False), [])

    def test_launcher_uses_private_copy_and_keeps_original_winetricks(self):
        self.assertEqual(len(self.run_cleanup(True, private_launcher=True)), 6)

    def test_unknown_source_is_rejected(self):
        for text in ('echo unknown', FUNCTION.replace(' /f || true', ' /f'),
                     FUNCTION.replace('uninstaller --remove', 'unknown --remove')):
            with self.assertRaises(ValueError):
                cleanup.patched(text)


if __name__ == '__main__':
    unittest.main()
