import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wtr', ROOT / 'toolbox/helpers/wsquashfs_winetricks.py')
wtr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wtr)


class WinetricksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.prefix = self.base / 'Game with spaces.wine'
        (self.prefix / 'drive_c/windows/system32').mkdir(parents=True)
        self.shared = self.base / 'runner.dll'
        self.shared.write_text('original runner DLL')
        self.dll = self.prefix / 'drive_c/windows/system32/example.dll'
        self.dll.symlink_to(self.shared)
        self.saves = self.base / 'saves'
        self.saves.mkdir()
        (self.prefix / 'drive_c/Saved').symlink_to(self.saves)

    def test_batocera_runner_environment_and_real_installer_exit_code(self):
        launcher = self.base / 'batocera-wine'
        source = '''#!/bin/bash
WINE="$TEST_RUNNER/bin/wine"
WINESERVER="$TEST_RUNNER/bin/wineserver"
waitWineServer() { :; }
cleanAndExit() { return 0; }
trick_wine() {
    local target="$1"; shift
    WINEPREFIX="$target" "$TEST_TRICKS" "$@"
}
l_PREFIX="$3"
shift 3
if [ "$#" -gt 0 ]; then
            trick_wine "${l_PREFIX}" "$@"
fi
unset l_PREFIX
cleanAndExit $?
'''
        launcher.write_text(source)
        tricks = self.base / 'fake-tricks'
        tricks.write_text('''#!/bin/bash
[ "$WINE" = "$TEST_RUNNER/bin/wine" ] || exit 71
[ "$WINESERVER" = "$TEST_RUNNER/bin/wineserver" ] || exit 72
[ "$WINEPREFIX" = "$TEST_PREFIX" ] || exit 73
[ "$1" = -q ] && [ "$2" = vcrun2022 ] || exit 74
printf installed > "$WINEPREFIX/drive_c/windows/system32/example.dll"
exit "${TEST_EXIT:-0}"
''')
        tricks.chmod(0o755)
        with patch.dict(os.environ, TEST_RUNNER=str(self.base / 'Selected-UMU'),
                        TEST_PREFIX=str(self.prefix), TEST_TRICKS=str(tricks)):
            self.assertEqual(wtr.install(self.prefix, ['vcrun2022'], launcher), 0)
            self.assertEqual(wtr.install(self.prefix, ['vcrun2022'], launcher, native_runner=True), 0)
            with patch.dict(os.environ, TEST_EXIT='9'):
                self.assertEqual(wtr.install(self.prefix, ['vcrun2022'], launcher), 9)
        self.assertEqual(launcher.read_text(), source)
        self.assertEqual(self.dll.read_text(), 'installed')
        self.assertFalse(self.dll.is_symlink())
        self.assertEqual(self.shared.read_text(), 'original runner DLL')
        self.assertTrue((self.prefix / 'drive_c/Saved').is_symlink())

    def test_invalid_verbs_and_unrecognized_launcher_leave_prefix_untouched(self):
        launcher = self.base / 'unsupported'
        launcher.write_text('exit 0')
        for verbs in [['--force'], ['vcrun2022;touch'], ['../bad'], []]:
            with self.assertRaises(ValueError):
                wtr.install(self.prefix, verbs, launcher)
        with self.assertRaises(ValueError):
            wtr.install(self.prefix, ['vcrun2022'], launcher)
        self.assertTrue(self.dll.is_symlink())

    def test_dotnet_uses_one_native_engine_for_all_umu_installer_tools(self):
        for separate_wine64 in (True, False):
            with self.subTest(separate_wine64=separate_wine64):
                runner = self.base / ('UMU runner ' + str(separate_wine64))
                (runner / 'bin').mkdir(parents=True)
                (runner / 'files/bin').mkdir(parents=True)
                (runner / 'umu-batocera').mkdir()
                (runner / 'umu-batocera/umu-root-runner.py').touch()
                for name in ('wine', 'wine64', 'wineserver'):
                    wrapper = runner / 'bin' / name
                    wrapper.write_text('#!/bin/bash\nexit 88\n')
                    wrapper.chmod(0o755)
                    if name == 'wine64' and not separate_wine64:
                        continue
                    native = runner / 'files/bin' / name
                    native.write_text('''#!/bin/bash
[ "$WINEPREFIX" = "$TEST_PREFIX" ] || exit 71
[ "$WINELOADER" = "$TEST_RUNNER/files/bin/wine" ] || exit 72
printf '%s|%s\\n' "${0##*/}" "$*" >> "$TEST_CALLS"
''')
                    native.chmod(0o755)
                launcher = self.base / 'native-launcher'
                launcher.write_text('''#!/bin/bash
WINE="$TEST_RUNNER/bin/wine"
WINE64="$TEST_RUNNER/bin/wine64"
WINESERVER="$TEST_RUNNER/bin/wineserver"
waitWineServer() { WINEPREFIX="$TEST_PREFIX" "$WINESERVER" -w; }
cleanAndExit() { return 0; }
trick_wine() { local target="$1"; shift; WINEPREFIX="$target" "$TEST_TRICKS" "$@"; }
l_PREFIX="$3"
shift 3
            trick_wine "${l_PREFIX}" "$@"
''')
                fake = self.base / 'fake-dotnet-tricks'
                fake.write_text('''#!/bin/bash
set -e
"$WINE" regedit.exe /S registry.reg
"$WINE" winecfg -v win7
"$WINE" ndp48-x86-x64-allos-enu.exe /q
"$WINE64" msiexec.exe /i package.msi
"$WINESERVER" -w
exit 9
''')
                fake.chmod(0o755)
                calls = self.base / ('native-calls-' + str(separate_wine64))
                with patch.dict(os.environ, TEST_RUNNER=str(runner), TEST_PREFIX=str(self.prefix),
                                TEST_TRICKS=str(fake), TEST_CALLS=str(calls)):
                    self.assertEqual(wtr.install(self.prefix, ['remove_mono', 'dotnet48'], launcher, native_runner=True), 9)
                lines = calls.read_text().splitlines()
                self.assertIn('wine|regedit.exe /S registry.reg', lines)
                self.assertIn('wine|winecfg -v win7', lines)
                self.assertIn('wine|ndp48-x86-x64-allos-enu.exe /q', lines)
                expected64 = 'wine64' if separate_wine64 else 'wine'
                self.assertIn(expected64 + '|msiexec.exe /i package.msi', lines)
                self.assertEqual(lines.count('wineserver|-w'), 2)

    def test_msi_uses_selected_runner_prefix_and_literal_arguments(self):
        runner = self.base / 'runner with spaces'
        (runner / 'bin').mkdir(parents=True)
        wine = runner / 'bin/wine'
        wine.write_text('''#!/bin/bash
[ "$WINEPREFIX" = "$TEST_PREFIX" ] || exit 71
[ "$1" = msiexec ] && [ "$2" = /i ] && [ "$3" = 'Z:\\cache path\\mono.msi' ] || exit 72
exit 9
''')
        wine.chmod(0o755)
        launcher = self.base / 'batocera-wine'
        source = '''#!/bin/bash
WINE="$TEST_RUNNER/bin/wine"
WINESERVER="$TEST_RUNNER/bin/wineserver"
waitWineServer() { [ "$WINEPOINT" = "$TEST_PREFIX" ] || exit 73; }
cleanAndExit() { return 0; }
l_PREFIX="$3"
shift 3
if [ "$#" -gt 0 ]; then
            trick_wine "${l_PREFIX}" "$@"
fi
'''
        launcher.write_text(source)
        with patch.dict(os.environ, TEST_RUNNER=str(runner), TEST_PREFIX=str(self.prefix)):
            self.assertEqual(wtr.install(self.prefix, ['msiexec', '/i', 'Z:\\cache path\\mono.msi'], launcher, wine_command=True), 9)
        self.assertEqual(launcher.read_text(), source)

    def test_external_windows_directory_is_refused(self):
        (self.prefix / 'drive_c/windows/fonts').symlink_to(self.saves)
        with self.assertRaises(ValueError):
            wtr.prepare(self.prefix)
        self.assertTrue(self.dll.is_symlink())

    def test_running_prefix_is_refused(self):
        fake_env = self.base / 'process-env'
        fake_env.write_bytes(os.fsencode('WINEPREFIX=' + str(self.prefix)) + b'\0')
        with patch.object(wtr.Path, 'glob', return_value=[fake_env]):
            with self.assertRaisesRegex(ValueError, 'still in use'):
                wtr.prepare(self.prefix)
        self.assertTrue(self.dll.is_symlink())

    def test_creation_failure_menu_offers_winetricks_and_retests_after_success(self):
        script = r'''
source toolbox/modules/wsquashfs.sh
i18n() { printf '%s' "$1"; }
wsq_state_value() { printf '%s' "$TEST_MODE"; }
menu_select() {
    printf '%s\n' "$@" > "$TEST_MENU"
    if [ "$TEST_MODE" = create ]; then printf winetricks; else printf cancel; fi
}
wsq_install_extra_winetricks() { echo installed; }
yesno() { return 0; }
wsq_retry_pending() { echo retested; }
wsq_cancel_pending() { :; }
wsq_launch_failure_menu Failed
'''
        menu = self.base / 'menu'
        for mode in ('create', 'update'):
            result = subprocess.run(['bash', '-c', script], cwd=ROOT, capture_output=True,
                text=True, env=dict(os.environ, WT_ROOT=str(ROOT / 'toolbox'),
                                    TEST_MODE=mode, TEST_MENU=str(menu)))
            self.assertEqual(result.returncode, 1)
            if mode == 'create':
                self.assertIn('\nwinetricks\n', menu.read_text())
                self.assertEqual(result.stdout, 'installed\nretested\n')
            else:
                self.assertNotIn('\nwinetricks\n', menu.read_text())
                self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
