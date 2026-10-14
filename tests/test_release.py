"""Regression checks for the v0.2 workflows; never touch Batocera paths."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
import runner_names as names
import wsquashfs_builder as builder
import wsquashfs_options as options
import wsquashfs_integrity as integrity


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def bash(self, script):
        return subprocess.run(['bash', '-c', script], cwd=ROOT,
                              env=dict(os.environ, TEST_ROOT=str(self.base)),
                              capture_output=True, text=True, check=True)

    def test_shell_and_python_sources(self):
        import re
        for path in ROOT.rglob('*.sh'):
            subprocess.run(['bash', '-n', str(path)], check=True)
            for block in re.finditer(r"python3[^\n]*<<\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\1(?:\n|$)", path.read_text(), re.S):
                compile(block[2], str(path) + ' inline Python', 'exec')
        for path in (ROOT / 'toolbox').rglob('*.py'):
            compile(path.read_bytes(), str(path), 'exec')

    def test_translation_keys_and_placeholders(self):
        def load(language):
            result = self.bash('source toolbox/lang/' + language + '.sh\n'
                               'for key in "${!I18N[@]}"; do printf "%s\\0%s\\0" "$key" "${I18N[$key]}"; done')
            fields = result.stdout.split('\0')[:-1]
            return dict(zip(fields[::2], fields[1::2]))
        import re
        fr, en = load('fr'), load('en')
        self.assertEqual(set(fr), set(en))
        for key in fr:
            self.assertEqual(re.findall(r'%(?:[0-9.]*[sd]|%)', fr[key]),
                             re.findall(r'%(?:[0-9.]*[sd]|%)', en[key]), key)

    def test_save_validation(self):
        prefix = self.base / 'Game.wine'
        save = prefix / 'drive_c/users/root/AppData/Local/Game/Saved'
        save.mkdir(parents=True)
        exe = prefix / 'drive_c/game/Game.exe'
        exe.parent.mkdir(parents=True)
        exe.touch()
        rel = save.relative_to(prefix).as_posix()
        self.assertEqual(builder.safe_save_dir(prefix, rel, 'drive_c/game/Game.exe'), rel)
        for bad in ('.', '..', 'drive_c', 'drive_c/users/root',
                    'drive_c/users/root/AppData/Local', 'drive_c/game'):
            with self.assertRaises(ValueError, msg=bad):
                builder.safe_save_dir(prefix, bad, 'drive_c/game/Game.exe')
        external = self.base / 'saves/Game'
        external.mkdir(parents=True)
        save.rmdir()
        save.symlink_to(external)
        self.assertEqual(builder.safe_save_dir(prefix, rel, save_root=external.parent), rel)
        save.unlink()
        save.symlink_to(self.base)
        with self.assertRaises(ValueError):
            builder.safe_save_dir(prefix, rel, save_root=external.parent)

    def test_save_detection_and_launcher_exclusions(self):
        prefix = self.base / 'Game.wine'
        game = prefix / 'drive_c/game'
        game.mkdir(parents=True)
        (game / 'Play.cmd').touch()
        (game / 'autorun.cmd').touch()
        launcher_dir = game / 'launchers'
        launcher_dir.mkdir()
        (launcher_dir / 'AUTORUN.CMD').touch()
        (game / 'uninstall.exe').touch()
        nested = game / 'Other.wine'
        nested.mkdir()
        (nested / 'Game.exe').touch()
        self.assertEqual([row[1] for row in builder.find_exes(prefix)], ['drive_c/game/Play.cmd'])
        before = builder.snapshot(prefix)
        save = prefix / 'drive_c/users/root/AppData/Local/Game/Saved'
        save.mkdir(parents=True)
        (save / 'slot.sav').write_text('progress')
        rows = builder.diff_snapshots(prefix, before, builder.snapshot(prefix))
        self.assertEqual(rows[0][1], save.relative_to(prefix).as_posix())

    def test_existing_prefix_game_outside_default_game_directory(self):
        prefix = self.base / 'CastleStorm.wine'
        for relative in ('CastleStorm/CastleStorm.exe',
                         'CastleStorm/_CommonRedist/DirectX/dxwebsetup.exe',
                         'CastleStorm/unins000.exe', 'windows/regedit.exe',
                         'Program Files/Internet Explorer/iexplore.exe',
                         'users/root/AppData/Helper.exe', '.hidden/Other.exe'):
            path = prefix / 'drive_c' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (prefix / 'autorun.cmd').write_text('#DIR=drive_c/Program Files/myprogram\n#CMD=start.exe\n')
        outside = self.base / 'outside.exe'; outside.touch()
        (prefix / 'drive_c/CastleStorm/external.exe').symlink_to(outside)
        self.assertEqual([row[1] for row in builder.find_exes(prefix, 'drive_c')],
                         ['drive_c/CastleStorm/CastleStorm.exe'])
        self.assertEqual(builder.find_exes(prefix), [])

    def test_runner_names(self):
        cases = {'wine-11.5-amd64-wow64': 'Vanilla-11.5',
                 'wine-9.17-staging-tkg-amd64': 'TKG-9.17',
                 'wine-proton-9.0-4-amd64': 'Vanilla-Proton-9.0-4',
                 'GE-Proton10-25': 'GE-Proton-10-25',
                 'GE-Proton10-25-UMU': 'GE-Proton10-25-UMU',
                 'wine-tkg-v41': 'TKG-v41', 'ge-custom-v40': 'GE-Custom-v40'}
        for old, new in cases.items():
            self.assertEqual(names.canonical(old), new)

    def test_release_menu_preserves_original_asset(self):
        (self.base / 'Vanilla-11.5').mkdir()
        (self.base / 'wine-9.17-staging-tkg-amd64').mkdir()
        result = self.bash('''
WT_HOME="$TEST_ROOT"; WT_ROOT="$PWD/toolbox"; BATOCERA_CUSTOM_WINE="$TEST_ROOT"
source toolbox/modules/runners.sh
i18n() { printf '%s' "$1"; }
msgbox() { return 99; }
runner_release_rows_kron4ek() {
    printf 'v1\twine-11.5-amd64.tar.xz\turl1\t1024\t\nv2\twine-9.17-staging-tkg-amd64.tar.xz\turl2\t1536\tchecksum\n'
}
menu_select() {
    [ "$3" = 1 ] && [ "$4" = 'Vanilla-11.5 | 1.0 KiB | installed' ] || return 10
    [ "$5" = 2 ] && [ "$6" = 'TKG-9.17 | 1.5 KiB | installed' ] || return 11
    printf 2
}
runner_choose_release kron4ek-vanilla Test
''')
        self.assertEqual(result.stdout, 'v2\twine-9.17-staging-tkg-amd64.tar.xz\turl2\t1536\tchecksum\n')

    def test_umu_batch_is_noninteractive_and_preserves_failure(self):
        main = self.base / 'umu-toolbox.sh'
        original = '#!/bin/bash\nmsg() {\n echo INTERACTIVE\n}\nmsg Title Body\nexit "${MOCK_EXIT:-0}"\n'
        main.write_text(original)
        main.chmod(0o755)
        result = self.bash('''
source toolbox/modules/umu.sh
UMU_TOOLBOX_ROOT="$TEST_ROOT"; UMU_TOOLBOX_MAIN="$TEST_ROOT/umu-toolbox.sh"
ensure_umu_toolbox() { return 0; }; i18n() { printf '%s' "$1"; }
install_umu_runner Runner batch || exit 10
export MOCK_EXIT=9
install_umu_runner Runner batch; rc=$?
[ "$rc" = 9 ] || exit 11
''')
        self.assertNotIn('INTERACTIVE', result.stdout)
        self.assertEqual(main.read_text(), original)
        self.assertEqual(list(self.base.glob('.starter-batch.*')), [])

    def test_migration_backup_and_rollback(self):
        root, bottles = self.base / 'runners', self.base / 'bottles'
        old = 'wine-11.5-amd64'
        (root / old).mkdir(parents=True)
        (bottles / old).mkdir(parents=True)
        conf, state, backups = self.base / 'batocera.conf', self.base / 'state.json', self.base / 'backups'
        original = '# retained\nwindows.wine-runner=' + old + '\nwindows.dxvk=1\n'
        conf.write_text(original)
        state.write_text(json.dumps({'runner': old}))
        real_atomic = names.atomic
        calls = 0
        def fail_second(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated write failure')
            real_atomic(path, data)
        with patch.object(names, 'atomic', fail_second), self.assertRaises(OSError):
            names.migrate(root, conf, bottles, state, backups)
        self.assertEqual(conf.read_text(), original)
        self.assertTrue((root / old).is_dir())
        self.assertTrue((bottles / old).is_dir())
        with contextlib.redirect_stdout(io.StringIO()):
            names.migrate(root, conf, bottles, state, backups)
        self.assertTrue((root / 'Vanilla-11.5').is_dir())
        self.assertIn('windows.wine-runner=Vanilla-11.5', conf.read_text())
        self.assertEqual(json.loads(state.read_text())['runner'], 'Vanilla-11.5')
        self.assertTrue(any(p.read_text() == original for p in backups.glob('*/batocera.conf')))

    def test_options_preserve_unrelated_settings(self):
        conf = self.base / 'batocera.conf'
        original = 'windows.dxvk=1\nwindows["Other.wine"].enable_hidraw=0\n'
        conf.write_text(original)
        options.write_values(conf, original.splitlines(keepends=True), 'Game.wine', {'enable_hidraw': '1'})
        self.assertTrue(conf.read_text().startswith(original))
        options.write_values(conf, conf.read_text().splitlines(keepends=True), 'Game.wine', {'enable_hidraw': 'inherit'})
        self.assertEqual(conf.read_text(), original)

    def test_external_save_copy_and_portable_directory(self):
        self.bash('''
WT_HOME="$TEST_ROOT"; WT_ROOT="$PWD/toolbox"
source toolbox/modules/wsquashfs.sh
WSQ_SAVE_ROOT="$TEST_ROOT/saves"
wt_log() { :; }
mkdir -p "$TEST_ROOT/prefix/drive_c/game" "$WSQ_SAVE_ROOT/Old"
printf progress > "$WSQ_SAVE_ROOT/Old/.slot"
ln -s "$WSQ_SAVE_ROOT/Old" "$TEST_ROOT/prefix/drive_c/game/Saved"
wsq_move_save_data "$TEST_ROOT/prefix" drive_c/game/Saved New || exit 10
cmp "$WSQ_SAVE_ROOT/Old/.slot" "$WSQ_SAVE_ROOT/New/.slot" || exit 11
wsq_cleanup_internal_savedir "$TEST_ROOT/prefix" drive_c/game/Saved || exit 12
test -d "$TEST_ROOT/prefix/drive_c/game/Saved" && test ! -L "$TEST_ROOT/prefix/drive_c/game/Saved" || exit 13
test -f "$WSQ_SAVE_ROOT/Old/.slot" || exit 14
''')

    def test_version_upgrade(self):
        self.bash('source toolbox/modules/update.sh\nwt_version_is_newer v0.2.0 0.1.3 || exit 10\n'
                  'if wt_version_is_newer v0.1.3 0.2.0; then exit 11; fi\n'
                  'if wt_version_is_newer invalid 0.1.3; then exit 12; fi')

    def test_integrity_log_retention(self):
        for index in range(26):
            path = self.base / f'wsquashfs-integrity-{index:02}.log'
            path.touch()
            os.utime(path, (index, index))
        (self.base / 'session.log').touch()
        self.bash('WT_HOME="$TEST_ROOT"; WT_ROOT="$PWD/toolbox"\n'
                  'source toolbox/modules/wsquashfs.sh\nWT_LOG_DIR="$TEST_ROOT"\n'
                  'wsq_integrity_rotate_logs "$TEST_ROOT/wsquashfs-integrity-25.log"')
        self.assertEqual(len(list(self.base.glob('wsquashfs-integrity-*.log'))), 20)
        self.assertTrue((self.base / 'session.log').exists())

    def test_clean_install_and_upgrade_preserve_user_data(self):
        import shutil
        package = self.base / 'package'
        package.mkdir()
        shutil.copytree(ROOT / 'toolbox', package / 'toolbox')
        for name in ('VERSION', 'uninstall.sh'):
            shutil.copy(ROOT / name, package / name)
        # Redirect every Batocera path and disable the external runtime download.
        installer = (ROOT / 'package-install.sh').read_text().replace('/userdata', str(self.base / 'userdata'))
        (package / 'package-install.sh').write_text(installer)
        (package / 'toolbox/helpers/install-mangohud-runtime.sh').write_text('#!/bin/bash\nexit 0\n')
        commands = self.base / 'commands'
        commands.mkdir()
        (commands / 'id').write_text('#!/bin/sh\nprintf "0\\n"\n')
        (commands / 'id').chmod(0o755)
        env = dict(os.environ, LANG='C', PATH=str(commands) + ':' + os.environ['PATH'])
        subprocess.run(['bash', str(package / 'package-install.sh')], env=env, check=True, capture_output=True)
        dest = self.base / 'userdata/system/ultimate-wine-toolbox'
        self.assertTrue((dest / 'toolbox/helpers/wsquashfs_builder.py').is_file())
        self.assertTrue((self.base / 'userdata/roms/ports/Ultimate Wine Toolbox.sh.keys').is_file())
        for directory in ('config', 'templates', 'dxvk/bundles', 'state', 'runtime'):
            folder = dest / directory
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'retained').write_text('user data')
        conf = self.base / 'userdata/system/batocera.conf'
        conf.write_text('windows.wine-runner=wine-11.5-amd64\n')
        (dest / 'toolbox/obsolete').touch()
        subprocess.run(['bash', str(package / 'package-install.sh')], env=env, check=True, capture_output=True)
        for directory in ('config', 'templates', 'dxvk/bundles', 'state', 'runtime'):
            self.assertEqual((dest / directory / 'retained').read_text(), 'user data')
        self.assertFalse((dest / 'toolbox/obsolete').exists())
        self.assertEqual(conf.read_text(), 'windows.wine-runner=wine-11.5-amd64\n')

    def test_integrity_exit_codes(self):
        archive, log, cancel = self.base / 'game.wsquashfs', self.base / 'check.log', self.base / 'cancel'
        archive.touch()
        fake = self.base / 'unsquashfs'
        fake.write_text('#!/bin/sh\nif [ "$1" = -help ]; then echo "-pf FILE"; fi\nexit 0\n')
        fake.chmod(0o755)
        self.assertEqual(integrity.check(archive, 'full', log, cancel, str(fake)), 0)
        fake.write_text('#!/bin/sh\nexit 2\n')
        self.assertEqual(integrity.check(archive, 'quick', log, cancel, str(fake)), 1)
        self.assertEqual(integrity.check(archive, 'full', log, cancel, str(fake)), 3)
        cancel.touch()
        self.assertEqual(integrity.check(archive, 'quick', log, cancel, str(fake)), 130)


if __name__ == '__main__':
    unittest.main()
