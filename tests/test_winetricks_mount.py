"""Exercise real SquashFS/OverlayFS publication in an isolated mount namespace."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ComponentMountTests(unittest.TestCase):
    def test_real_archive_overlay_preserves_game_and_persists_component_changes(self):
        required = os.environ.get('UWT_REQUIRE_MOUNT_TEST') == '1'
        available = (os.geteuid() == 0 and all(shutil.which(tool) for tool in ('mount', 'mksquashfs')))
        if available:
            probe = 'import sys; sys.path.insert(0, sys.argv[1]); from winetricks_target import enter_private_namespace; enter_private_namespace()'
            available = subprocess.run([sys.executable, '-c', probe, str(ROOT / 'toolbox/helpers')],
                                       capture_output=True).returncode == 0
        if not available:
            if required:
                self.fail('Required real mount test needs root, mount namespaces and squashfs-tools')
            self.skipTest('Real mount test needs root, mount namespaces and squashfs-tools')
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'original'
            (source / 'drive_c/game').mkdir(parents=True)
            (source / 'drive_c/windows').mkdir()
            (source / 'system.reg').write_text('old registry')
            (source / 'autorun.cmd').write_text('DIR=drive_c/game\n')
            (source / 'drive_c/game/game.exe').write_text('game must stay')
            (source / 'drive_c/windows/original.dll').write_text('old dll')
            archive = base / 'Game.wsquashfs'
            subprocess.run(['mksquashfs', str(source), str(archive), '-noappend', '-processors', '1'],
                           capture_output=True, check=True)
            original = archive.read_bytes()
            script = r'''
import os, pathlib, shutil, sys
sys.path.insert(0, sys.argv[1])
from winetricks_target import mounted_prefix, enter_private_namespace
from wsquashfs_dotnet_storage import publish
enter_private_namespace()
# Simulate Batocera images that do not provide the external utility.
original_run = __import__('subprocess').run
def run_without_unshare(args, *a, **kw):
    assert pathlib.Path(args[0]).name != 'unshare'
    return original_run(args, *a, **kw)
__import__('subprocess').run = run_without_unshare
base = pathlib.Path(sys.argv[2])
archive = base / 'Game.wsquashfs'
upper = base / 'bottles/Runner/Game.wsquashfs.wine'
runtime = base / 'runtime'
with mounted_prefix(archive, upper, runtime) as prefix:
    staged = base / 'staged.wine'
    game = prefix / 'drive_c/game'
    shutil.copytree(prefix, staged, symlinks=True,
                    ignore=lambda folder, names: ['game'] if pathlib.Path(folder) == game.parent else [])
    (staged / 'system.reg').write_text('new registry')
    (staged / 'drive_c/windows/new.dll').write_text('new component')
    os.environ['UWT_COMPONENT_MOUNTED_PREFIX'] = str(prefix)
    publish(staged, prefix, game)
    assert (game / 'game.exe').read_text() == 'game must stay'
    assert not list(prefix.glob('.uwt-dotnet-commit-*'))
with mounted_prefix(archive, upper, runtime) as prefix:
    assert (prefix / 'system.reg').read_text() == 'new registry'
    assert (prefix / 'drive_c/windows/new.dll').read_text() == 'new component'
    assert (prefix / 'drive_c/game/game.exe').read_text() == 'game must stay'
assert not (upper / 'drive_c/game').exists()
assert not list(upper.parent.glob('.uwt-components-work-*'))
'''
            result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'toolbox/helpers'), str(base)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(archive.read_bytes(), original)
