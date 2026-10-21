"""Persistent component targets: mount ownership, runner identity and idle checks."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
import winetricks_target as target
import wsquashfs_dotnet as dotnet


class ComponentTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rom = self.root / 'Game.wsquashfs'; self.rom.write_bytes(b'original archive')
        self.bottle = self.root / 'bottles/Runner/Game.wsquashfs.wine'
        self.runtime = self.root / 'runtime'

    def test_overlay_uses_persistent_upper_and_readonly_archive_without_game_copy(self):
        calls = []
        with patch.object(target, 'checked', side_effect=lambda args: calls.append(args)):
            with target.mounted_prefix(self.rom, self.bottle, self.runtime) as prefix:
                self.assertEqual(prefix.suffix, '.wine')
                self.assertTrue(self.bottle.is_dir())
                options = calls[1][4]
                self.assertIn(f'upperdir={self.bottle}', options)
                self.assertIn('redirect_dir=on', options)
                work = Path(options.split('workdir=')[1].split(',')[0])
                self.assertTrue(work.is_dir())
                self.assertEqual(work.parent, self.bottle.parent)
        self.assertFalse(work.exists())
        self.assertEqual(calls[0], ['mount', '-o', 'loop,ro,nosuid,nodev', str(self.rom), str(self.runtime / 'lower')])
        self.assertEqual(calls[-2:], [['umount', str(self.runtime / 'prefix.wine')],
                                     ['umount', str(self.runtime / 'lower')]])
        self.assertEqual(self.rom.read_bytes(), b'original archive')
        self.assertTrue(self.bottle.exists())

    def test_failed_overlay_mount_releases_only_our_lower_mount(self):
        calls = []
        def command(args):
            calls.append(args)
            if args[:3] == ['mount', '-t', 'overlay']:
                raise ValueError('unsupported overlay')
        with patch.object(target, 'checked', side_effect=command):
            with self.assertRaisesRegex(ValueError, 'unsupported overlay'):
                with target.mounted_prefix(self.rom, self.bottle, self.runtime):
                    self.fail('installer must not run')
        self.assertEqual(calls[-1], ['umount', str(self.runtime / 'lower')])
        self.assertFalse(list(self.bottle.parent.glob('.uwt-components-work-*')))
        self.assertTrue(self.rom.exists())

    def test_busy_mount_keeps_work_and_never_force_unmounts_or_deletes_bottle(self):
        calls = []
        def command(args):
            calls.append(args)
            if args[0] == 'umount':
                raise ValueError('busy')
        with patch.object(target, 'checked', side_effect=command):
            with target.mounted_prefix(self.rom, self.bottle, self.runtime):
                pass
        self.assertTrue(list(self.bottle.parent.glob('.uwt-components-work-*')))
        self.assertTrue(self.bottle.is_dir())
        self.assertTrue(all(len(args) == 2 for args in calls if args[0] == 'umount'))

    def test_pc_requires_initialized_bottle_and_binds_it_without_copying_game(self):
        pc = self.root / 'Game.pc'; pc.mkdir()
        calls = []
        with patch.object(target, 'checked', side_effect=lambda args: calls.append(args)):
            with self.assertRaisesRegex(ValueError, 'Launch this .pc game once'):
                with target.mounted_prefix(pc, self.bottle, self.runtime):
                    self.fail('uninitialized bottle')
            (self.bottle / 'drive_c/windows').mkdir(parents=True)
            (self.bottle / 'system.reg').write_text('registry')
            with target.mounted_prefix(pc, self.bottle, self.runtime):
                pass
        self.assertEqual(calls, [['mount', '--bind', str(self.bottle), str(self.runtime / 'prefix.wine')],
                                 ['umount', str(self.runtime / 'prefix.wine')]])

    def test_runner_specific_and_legacy_bottle_locations(self):
        launcher = self.root / 'batocera-wine'
        launcher.write_text('WINE_BOTTLE_DIR}/${WINE_VERSION}/${ROMGAMENAME}.wine')
        self.assertEqual(target.bottle_for(self.rom, 'Runner', launcher, self.root / 'bottles'), self.bottle)
        launcher.write_text('old launcher')
        self.assertEqual(target.bottle_for(self.rom, 'Runner', launcher, self.root / 'bottles'),
                         self.root / 'bottles/Game.wsquashfs')

    def test_idle_check_refuses_running_prefix_and_overlay_in_another_namespace(self):
        proc = self.root / 'proc'; entry = proc / '87654321'; entry.mkdir(parents=True)
        (entry / 'environ').write_bytes(b'WINEPREFIX=' + os.fsencode(self.bottle) + b'\0')
        with patch.object(target, 'targets', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'active'):
                target.ensure_idle(self.rom, self.bottle, proc)
            (entry / 'environ').write_bytes(b'')
            (entry / 'mountinfo').write_text(f'1 2 3 / / rw - overlay overlay rw,upperdir={self.bottle},workdir=/other\n')
            with self.assertRaisesRegex(ValueError, 'already mounted'):
                target.ensure_idle(self.rom, self.bottle, proc)
            (entry / 'mountinfo').write_text('')
            target.ensure_idle(self.rom, self.bottle, proc)

    def test_pc_dotnet_excludes_external_game_and_preserves_environment(self):
        pc = self.root / 'Game.pc'; pc.mkdir()
        prefix = self.root / 'prefix.wine'
        seen = []
        def run(args):
            seen.append((args, os.environ['UWT_COMPONENT_ROM_NAME'], dotnet.game_directory(prefix)))
            return subprocess.CompletedProcess(args, 0)
        with patch.dict(os.environ, UWT_COMPONENT_ROM_NAME='original', UWT_COMPONENT_PC_BOTTLE='original'):
            with patch.object(target.subprocess, 'run', side_effect=run):
                self.assertEqual(target.invoke(prefix, 'dotnet', ['inspect'], pc, Path('/unused')), 0)
            self.assertEqual(os.environ['UWT_COMPONENT_ROM_NAME'], 'original')
            self.assertEqual(os.environ['UWT_COMPONENT_PC_BOTTLE'], 'original')
        self.assertEqual(seen[0][1], 'Game.pc')
        self.assertEqual(seen[0][2], prefix / 'drive_c/.uwt-external-pc-game')

    def test_private_launcher_keeps_original_rom_settings_during_staging(self):
        launcher = self.root / 'batocera-wine'
        source = 'ROMGAMENAME=$(basename "${GAMENAME}")\n            trick_wine "${l_PREFIX}" "$@"\n'
        launcher.write_text(source)
        def run(args, env):
            wrapper = Path(args[1]).read_text()
            self.assertIn('ROMGAMENAME="${UWT_COMPONENT_ROM_NAME}"', wrapper)
            self.assertEqual(env['UWT_COMPONENT_ROM_NAME'], 'Game.wsquashfs')
            return subprocess.CompletedProcess(args, 0)
        with patch.dict(os.environ, UWT_COMPONENT_ROM_NAME='Game.wsquashfs'):
            with patch.object(target.tricks, 'prepare'), patch.object(target.tricks.subprocess, 'run', side_effect=run):
                self.assertEqual(target.tricks.install(self.root / 'prefix.wine', ['corefonts'], launcher), 0)
        self.assertEqual(launcher.read_text(), source)
